from datetime import timedelta
import uuid

from django.core.validators import MinValueValidator
from django.db import models
from django.db.models import Q
from django.utils import timezone

from .exceptions import InvalidStateTransitionError


class TimeStampedModel(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class Merchant(TimeStampedModel):
    name = models.CharField(max_length=255)
    reference = models.SlugField(max_length=64, unique=True)

    class Meta:
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name


class BankAccount(TimeStampedModel):
    merchant = models.ForeignKey(Merchant, related_name="bank_accounts", on_delete=models.CASCADE)
    label = models.CharField(max_length=120)
    bank_name = models.CharField(max_length=120)
    account_holder_name = models.CharField(max_length=255)
    account_number_last4 = models.CharField(max_length=4)
    routing_code = models.CharField(max_length=20)

    class Meta:
        ordering = ["merchant__name", "label"]

    def __str__(self) -> str:
        return f"{self.merchant.reference}:{self.label}"


class Payout(TimeStampedModel):
    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        PROCESSING = "processing", "Processing"
        COMPLETED = "completed", "Completed"
        FAILED = "failed", "Failed"

    VALID_TRANSITIONS = {
        Status.PENDING: {Status.PROCESSING},
        Status.PROCESSING: {Status.COMPLETED, Status.FAILED},
        Status.COMPLETED: set(),
        Status.FAILED: set(),
    }
    MAX_ATTEMPTS = 3

    merchant = models.ForeignKey(Merchant, related_name="payouts", on_delete=models.CASCADE)
    bank_account = models.ForeignKey(BankAccount, related_name="payouts", on_delete=models.PROTECT)
    amount_paise = models.BigIntegerField(validators=[MinValueValidator(1)])
    status = models.CharField(max_length=32, choices=Status.choices, default=Status.PENDING, db_index=True)
    attempts = models.PositiveSmallIntegerField(default=0)
    external_reference = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)
    processing_started_at = models.DateTimeField(null=True, blank=True)
    next_retry_at = models.DateTimeField(null=True, blank=True, db_index=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    failure_reason = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.CheckConstraint(check=Q(amount_paise__gt=0), name="payout_amount_positive"),
        ]

    def __str__(self) -> str:
        return f"{self.external_reference} ({self.status})"

    @classmethod
    def retry_delay_for_attempt(cls, attempt_number: int) -> timedelta:
        multiplier = 2 ** max(attempt_number - 1, 0)
        return timedelta(seconds=30 * multiplier)

    def assert_transition(self, target_status: str) -> None:
        if target_status not in self.VALID_TRANSITIONS.get(self.status, set()):
            raise InvalidStateTransitionError(f"Cannot move payout {self.pk} from {self.status} to {target_status}.")

    def start_processing(self, *, retry: bool = False, at=None) -> None:
        started_at = at or timezone.now()
        if retry:
            if self.status != self.Status.PROCESSING:
                raise InvalidStateTransitionError(f"Retry is only allowed while processing, not {self.status}.")
        else:
            self.assert_transition(self.Status.PROCESSING)
            self.status = self.Status.PROCESSING
        self.attempts += 1
        self.processing_started_at = started_at
        self.next_retry_at = started_at + self.retry_delay_for_attempt(self.attempts)

    def mark_retry_scheduled(self, *, at=None) -> None:
        scheduled_at = at or timezone.now()
        next_attempt = min(self.attempts + 1, self.MAX_ATTEMPTS)
        self.next_retry_at = scheduled_at + self.retry_delay_for_attempt(next_attempt)

    def mark_completed(self, *, at=None) -> None:
        finished_at = at or timezone.now()
        self.assert_transition(self.Status.COMPLETED)
        self.status = self.Status.COMPLETED
        self.completed_at = finished_at
        self.failure_reason = ""
        self.next_retry_at = None

    def mark_failed(self, *, reason: str, at=None) -> None:
        failed_at = at or timezone.now()
        self.assert_transition(self.Status.FAILED)
        self.status = self.Status.FAILED
        self.failure_reason = reason
        self.completed_at = failed_at
        self.next_retry_at = None


class MerchantIdempotencyKey(TimeStampedModel):
    merchant = models.ForeignKey(Merchant, related_name="idempotency_keys", on_delete=models.CASCADE)
    payout = models.OneToOneField("Payout", related_name="idempotency_record", on_delete=models.SET_NULL, null=True, blank=True)
    key = models.CharField(max_length=255)
    request_hash = models.CharField(max_length=64)
    response_status_code = models.PositiveSmallIntegerField()
    response_body = models.JSONField(default=dict)
    expires_at = models.DateTimeField(db_index=True)
    is_active = models.BooleanField(default=True, db_index=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["merchant", "key"],
                condition=Q(is_active=True),
                name="uq_active_idempotency_key_per_merchant",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.merchant.reference}:{self.key}"

    def has_expired(self, *, at=None) -> bool:
        reference = at or timezone.now()
        return self.expires_at <= reference


class LedgerEntry(TimeStampedModel):
    class Direction(models.TextChoices):
        CREDIT = "credit", "Credit"
        DEBIT = "debit", "Debit"

    class Category(models.TextChoices):
        SEED_CREDIT = "seed_credit", "Seed Credit"
        PAYOUT_HOLD = "payout_hold", "Payout Hold"
        PAYOUT_REFUND = "payout_refund", "Payout Refund"

    merchant = models.ForeignKey(Merchant, related_name="ledger_entries", on_delete=models.CASCADE)
    payout = models.ForeignKey(Payout, related_name="ledger_entries", on_delete=models.CASCADE, null=True, blank=True)
    direction = models.CharField(max_length=16, choices=Direction.choices)
    category = models.CharField(max_length=32, choices=Category.choices)
    amount_paise = models.BigIntegerField(validators=[MinValueValidator(1)])
    reference = models.CharField(max_length=255)
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        constraints = [
            models.CheckConstraint(check=Q(amount_paise__gt=0), name="ledger_amount_positive"),
            models.UniqueConstraint(
                fields=["payout", "category"],
                condition=Q(payout__isnull=False),
                name="uq_payout_category_once",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.merchant.reference}:{self.direction}:{self.amount_paise}"
