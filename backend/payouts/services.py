from dataclasses import dataclass
from datetime import timedelta
import hashlib
import json
import random
import time

from django.core.exceptions import ObjectDoesNotExist
from django.db import IntegrityError, OperationalError, transaction
from django.db.models import BigIntegerField, F, OuterRef, Q, Subquery, Sum, Value
from django.db.models.functions import Coalesce
from django.utils import timezone
from django_q.models import Schedule
from django_q.tasks import async_task, schedule
from rest_framework import status

from .exceptions import IdempotencyConflictError, InsufficientFundsError
from .models import BankAccount, LedgerEntry, Merchant, MerchantIdempotencyKey, Payout
from .serializers import PayoutSerializer


@dataclass(frozen=True)
class CreatePayoutResult:
    body: dict
    status_code: int
    replayed: bool = False


def merchant_balance_annotations():
    zero_value = Value(0, output_field=BigIntegerField())
    credit_totals = (
        LedgerEntry.objects.filter(
            merchant_id=OuterRef("pk"),
            direction=LedgerEntry.Direction.CREDIT,
        )
        .values("merchant_id")
        .annotate(total=Sum("amount_paise"))
        .values("total")
    )
    debit_totals = (
        LedgerEntry.objects.filter(
            merchant_id=OuterRef("pk"),
            direction=LedgerEntry.Direction.DEBIT,
        )
        .values("merchant_id")
        .annotate(total=Sum("amount_paise"))
        .values("total")
    )
    held_totals = (
        Payout.objects.filter(
            merchant_id=OuterRef("pk"),
            status__in=[Payout.Status.PENDING, Payout.Status.PROCESSING],
        )
        .values("merchant_id")
        .annotate(total=Sum("amount_paise"))
        .values("total")
    )

    return {
        "credit_total_paise": Coalesce(Subquery(credit_totals, output_field=BigIntegerField()), zero_value),
        "debit_total_paise": Coalesce(Subquery(debit_totals, output_field=BigIntegerField()), zero_value),
        "held_balance_paise": Coalesce(Subquery(held_totals, output_field=BigIntegerField()), zero_value),
    }


def annotate_merchants_with_balance(queryset):
    annotations = merchant_balance_annotations()
    return queryset.annotate(**annotations).annotate(
        balance_paise=F("credit_total_paise") - F("debit_total_paise"),
        available_balance_paise=F("credit_total_paise") - F("debit_total_paise"),
    )


def get_merchant_balance_paise(merchant_id: int) -> int:
    zero_value = Value(0, output_field=BigIntegerField())
    totals = LedgerEntry.objects.filter(merchant_id=merchant_id).aggregate(
        credit_total_paise=Coalesce(
            Sum("amount_paise", filter=Q(direction=LedgerEntry.Direction.CREDIT)),
            zero_value,
        ),
        debit_total_paise=Coalesce(
            Sum("amount_paise", filter=Q(direction=LedgerEntry.Direction.DEBIT)),
            zero_value,
        ),
    )
    return int(totals["credit_total_paise"] - totals["debit_total_paise"])


def hash_payout_request(*, amount_paise: int, bank_account_id: int) -> str:
    payload = {"amount_paise": amount_paise, "bank_account_id": bank_account_id}
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()


def enqueue_payout_processing(payout_id: int, *, retry: bool = False) -> None:
    async_task("payouts.tasks.process_payout_task", payout_id, retry=retry)


def schedule_payout_retry_check(payout_id: int, retry_at, attempt_number: int) -> None:
    schedule(
        "payouts.tasks.retry_payout_if_stuck_task",
        payout_id,
        scheduled_attempt=attempt_number,
        schedule_type=Schedule.ONCE,
        next_run=retry_at,
    )


def serialize_payout_snapshot(payout: Payout) -> dict:
    return PayoutSerializer(payout).data


def create_payout_for_merchant(
    *,
    merchant_id: int,
    amount_paise: int,
    bank_account_id: int,
    idempotency_key: str,
) -> CreatePayoutResult:
    attempts_remaining = 3
    while attempts_remaining > 0:
        try:
            return _create_payout_for_merchant_once(
                merchant_id=merchant_id,
                amount_paise=amount_paise,
                bank_account_id=bank_account_id,
                idempotency_key=idempotency_key,
            )
        except OperationalError as exc:
            attempts_remaining -= 1
            if attempts_remaining == 0 or "locked" not in str(exc).lower():
                raise
            time.sleep(0.05)


@transaction.atomic
def _create_payout_for_merchant_once(
    *,
    merchant_id: int,
    amount_paise: int,
    bank_account_id: int,
    idempotency_key: str,
) -> CreatePayoutResult:
    request_hash = hash_payout_request(amount_paise=amount_paise, bank_account_id=bank_account_id)
    now = timezone.now()

    merchant = Merchant.objects.select_for_update().get(pk=merchant_id)

    existing_record = (
        MerchantIdempotencyKey.objects.select_for_update()
        .filter(merchant=merchant, key=idempotency_key, is_active=True)
        .first()
    )
    if existing_record:
        if existing_record.has_expired(at=now):
            existing_record.is_active = False
            existing_record.save(update_fields=["is_active", "updated_at"])
        else:
            if existing_record.request_hash != request_hash:
                raise IdempotencyConflictError("Idempotency-Key was already used with a different request payload.")
            return CreatePayoutResult(
                body=existing_record.response_body,
                status_code=existing_record.response_status_code,
                replayed=True,
            )

    try:
        bank_account = BankAccount.objects.get(pk=bank_account_id, merchant=merchant)
    except ObjectDoesNotExist as exc:
        raise BankAccount.DoesNotExist("Merchant bank account was not found.") from exc

    balance_paise = get_merchant_balance_paise(merchant.id)
    if balance_paise < amount_paise:
        raise InsufficientFundsError(
            f"Merchant balance is {balance_paise} paise but payout amount is {amount_paise} paise."
        )

    payout = Payout.objects.create(
        merchant=merchant,
        bank_account=bank_account,
        amount_paise=amount_paise,
    )
    LedgerEntry.objects.create(
        merchant=merchant,
        payout=payout,
        direction=LedgerEntry.Direction.DEBIT,
        category=LedgerEntry.Category.PAYOUT_HOLD,
        amount_paise=amount_paise,
        reference=f"hold:{payout.external_reference}",
        metadata={"status": Payout.Status.PENDING},
    )

    payload = serialize_payout_snapshot(payout)
    MerchantIdempotencyKey.objects.create(
        merchant=merchant,
        payout=payout,
        key=idempotency_key,
        request_hash=request_hash,
        response_status_code=status.HTTP_201_CREATED,
        response_body=payload,
        expires_at=now + timedelta(hours=24),
    )

    transaction.on_commit(lambda: enqueue_payout_processing(payout.id))
    return CreatePayoutResult(body=payload, status_code=status.HTTP_201_CREATED)


def process_payout(payout_id: int, *, retry: bool = False, random_fn=None) -> None:
    draw = random_fn or random.random
    now = timezone.now()

    with transaction.atomic():
        payout = (
            Payout.objects.select_for_update()
            .select_related("merchant", "bank_account")
            .get(pk=payout_id)
        )

        if retry:
            if payout.status != Payout.Status.PROCESSING:
                return
            if payout.attempts >= Payout.MAX_ATTEMPTS:
                fail_payout_with_refund(payout_id, reason="max retry attempts exhausted")
                return
            payout.start_processing(retry=True, at=now)
        else:
            if payout.status != Payout.Status.PENDING:
                return
            payout.start_processing(retry=False, at=now)

        payout.save(update_fields=["status", "attempts", "processing_started_at", "next_retry_at", "updated_at"])
        transaction.on_commit(
            lambda payout_id=payout.id, retry_at=payout.next_retry_at, attempt_number=payout.attempts: (
                schedule_payout_retry_check(payout_id, retry_at, attempt_number)
            )
        )

    outcome = draw()
    if outcome < 0.7:
        complete_payout(payout_id)
    elif outcome < 0.9:
        fail_payout_with_refund(payout_id, reason="processor_rejected")


def complete_payout(payout_id: int) -> None:
    with transaction.atomic():
        payout = Payout.objects.select_for_update().get(pk=payout_id)
        if payout.status != Payout.Status.PROCESSING:
            return
        payout.mark_completed()
        payout.save(update_fields=["status", "completed_at", "failure_reason", "next_retry_at", "updated_at"])


def fail_payout_with_refund(payout_id: int, *, reason: str) -> None:
    with transaction.atomic():
        payout = (
            Payout.objects.select_for_update()
            .select_related("merchant")
            .get(pk=payout_id)
        )
        if payout.status == Payout.Status.FAILED:
            return
        if payout.status != Payout.Status.PROCESSING:
            return

        payout.mark_failed(reason=reason)
        payout.save(update_fields=["status", "failure_reason", "completed_at", "next_retry_at", "updated_at"])

        try:
            LedgerEntry.objects.create(
                merchant=payout.merchant,
                payout=payout,
                direction=LedgerEntry.Direction.CREDIT,
                category=LedgerEntry.Category.PAYOUT_REFUND,
                amount_paise=payout.amount_paise,
                reference=f"refund:{payout.external_reference}",
                metadata={"reason": reason},
            )
        except IntegrityError:
            pass


def retry_payout_if_stuck(payout_id: int, *, scheduled_attempt: int) -> bool:
    now = timezone.now()
    should_retry = False

    with transaction.atomic():
        payout = Payout.objects.select_for_update().get(pk=payout_id)
        if payout.status != Payout.Status.PROCESSING:
            return False
        if payout.attempts != scheduled_attempt:
            return False
        if payout.next_retry_at is None or payout.next_retry_at > now:
            return False

        if payout.attempts >= Payout.MAX_ATTEMPTS:
            payout.mark_failed(reason="max retry attempts exhausted", at=now)
            payout.save(update_fields=["status", "failure_reason", "completed_at", "next_retry_at", "updated_at"])
            LedgerEntry.objects.get_or_create(
                merchant=payout.merchant,
                payout=payout,
                category=LedgerEntry.Category.PAYOUT_REFUND,
                defaults={
                    "direction": LedgerEntry.Direction.CREDIT,
                    "amount_paise": payout.amount_paise,
                    "reference": f"refund:{payout.external_reference}",
                    "metadata": {"reason": "max retry attempts exhausted"},
                },
            )
            return False

        should_retry = True
        transaction.on_commit(lambda payout_id=payout.id: enqueue_payout_processing(payout_id, retry=True))

    return should_retry
