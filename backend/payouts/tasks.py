from .services import process_payout, retry_payout_if_stuck


def process_payout_task(payout_id: int, retry: bool = False) -> None:
    process_payout(payout_id, retry=retry)


def retry_payout_if_stuck_task(payout_id: int, scheduled_attempt: int) -> bool:
    return retry_payout_if_stuck(payout_id, scheduled_attempt=scheduled_attempt)
