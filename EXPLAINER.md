# Explainer

## The Ledger

Balances are not stored as floats or denormalized cash columns. The source of truth is `LedgerEntry`, where every row is either a credit or a debit in paise.

- `seed_credit` creates opening balances
- `payout_hold` debits the merchant immediately when a payout is requested
- `payout_refund` credits the merchant back if the payout fails

The balance calculation query lives in [backend/payouts/services.py](/C:/Users/subra/Downloads/Playto/backend/payouts/services.py):

```python
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
balance = totals["credit_total_paise"] - totals["debit_total_paise"]
```

I modeled credits and debits this way because it gives one append-only ledger source of truth for money movement, makes refunds explicit, and keeps the invariant simple:

`merchant balance = sum(credits) - sum(debits)`

For the dashboard list, I also annotate `held_balance_paise` from payouts in `pending` or `processing` so the UI can separate spendable balance from in-flight withdrawals.

## The Lock

The exact code that prevents two concurrent payouts from overdrawing a merchant balance is:

```python
@transaction.atomic
def _create_payout_for_merchant_once(...):
    merchant = Merchant.objects.select_for_update().get(pk=merchant_id)
    ...
    balance_paise = get_merchant_balance_paise(merchant.id)
    if balance_paise < amount_paise:
        raise InsufficientFundsError(...)
    ...
    LedgerEntry.objects.create(
        merchant=merchant,
        payout=payout,
        direction=LedgerEntry.Direction.DEBIT,
        category=LedgerEntry.Category.PAYOUT_HOLD,
        amount_paise=amount_paise,
        ...
    )
```

This relies on the database primitive `SELECT ... FOR UPDATE`, exposed through Django as `select_for_update()`.

Why it works:

- request A locks the merchant row
- request B waits on that row lock instead of reading stale balance
- request A inserts the hold debit and commits
- request B resumes, recomputes balance from the database, and fails if funds are no longer sufficient

That is the important difference between Python-level locking and real database locking.

## The Idempotency

Idempotency is tracked by `MerchantIdempotencyKey`.

- keys are scoped per merchant
- each key stores a request hash, response status code, response body, and expiry
- active keys are unique per `(merchant, key)`
- expiry is `24 hours`

Creation flow:

1. lock the merchant row
2. look for an active idempotency row for that merchant and key
3. if the row exists and is unexpired, compare request hashes
4. if the hash matches, return the stored response snapshot
5. otherwise create one payout, one hold ledger entry, and one idempotency record

If the first request is still in flight when the second arrives, the second request blocks on the same merchant row lock. After the first request commits, the second request wakes up, sees the stored idempotency row, and replays the exact same response. That avoids duplicate payouts without relying on timing luck.

## The State Machine

The state machine lives in [backend/payouts/models.py](/C:/Users/subra/Downloads/Playto/backend/payouts/models.py):

```python
VALID_TRANSITIONS = {
    Status.PENDING: {Status.PROCESSING},
    Status.PROCESSING: {Status.COMPLETED, Status.FAILED},
    Status.COMPLETED: set(),
    Status.FAILED: set(),
}
```

The specific check that blocks `failed -> completed` is:

```python
def assert_transition(self, target_status: str) -> None:
    if target_status not in self.VALID_TRANSITIONS.get(self.status, set()):
        raise InvalidStateTransitionError(...)
```

`mark_completed()` calls `assert_transition(self.Status.COMPLETED)`, so a payout already in `failed` state cannot move to `completed` because `Status.FAILED` maps to an empty set.

Refunds are atomic because failure and refund creation happen in one transaction:

```python
with transaction.atomic():
    payout = Payout.objects.select_for_update().get(pk=payout_id)
    payout.mark_failed(reason=reason)
    payout.save(...)
    LedgerEntry.objects.create(
        merchant=payout.merchant,
        payout=payout,
        direction=LedgerEntry.Direction.CREDIT,
        category=LedgerEntry.Category.PAYOUT_REFUND,
        amount_paise=payout.amount_paise,
        ...
    )
```

## Retry Logic

When processing begins, the payout records `next_retry_at` using exponential backoff:

- attempt 1: `30s`
- attempt 2: `60s`
- attempt 3: `120s`

If the simulated bank processor picks the stuck path, the payout stays in `processing`. Each processing attempt schedules a one-off Django-Q check exactly at `next_retry_at`.

- if attempts are still below `3`, that check re-enqueues processing asynchronously
- if attempts are already `3`, it marks the payout failed and refunds the hold

## The AI Audit

One specific place AI gave subtly wrong code was the dashboard balance annotation. A naive version tried to add credit totals, debit totals, and held payouts in one ORM query using joins across both `ledger_entries` and `payouts`.

Wrong shape:

```python
queryset.annotate(
    credit_total_paise=Sum("ledger_entries__amount_paise", ...),
    debit_total_paise=Sum("ledger_entries__amount_paise", ...),
    held_balance_paise=Sum("payouts__amount_paise", ...),
)
```

Why it was wrong:

- joining both `ledger_entries` and `payouts` in one aggregate query can multiply rows
- that inflates sums when a merchant has multiple ledger rows and multiple payouts
- the result looks correct in small happy paths, then silently breaks balances later

What I replaced it with:

```python
credit_totals = (
    LedgerEntry.objects.filter(
        merchant_id=OuterRef("pk"),
        direction=LedgerEntry.Direction.CREDIT,
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
```

Then I used `Subquery(...)` plus `Coalesce(...)` for each total independently. That keeps each aggregate isolated and avoids accidental row multiplication.
