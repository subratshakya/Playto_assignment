from concurrent.futures import ThreadPoolExecutor
import threading
from unittest.mock import patch

from django.db import close_old_connections
from django.test import TestCase, TransactionTestCase
from rest_framework.test import APIClient

from .exceptions import InsufficientFundsError
from .models import BankAccount, LedgerEntry, Merchant, Payout
from .services import create_payout_for_merchant, get_merchant_balance_paise


class IdempotencyApiTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.merchant = Merchant.objects.create(name="Idempotent Mart", reference="idempotent-mart")
        self.bank_account = BankAccount.objects.create(
            merchant=self.merchant,
            label="Primary",
            bank_name="Axis Bank",
            account_holder_name="Idempotent Mart Pvt Ltd",
            account_number_last4="1234",
            routing_code="UTIB0004",
        )
        LedgerEntry.objects.create(
            merchant=self.merchant,
            direction=LedgerEntry.Direction.CREDIT,
            category=LedgerEntry.Category.SEED_CREDIT,
            amount_paise=100000,
            reference="seed:idempotent-mart",
            metadata={"source": "test"},
        )

    @patch("payouts.services.enqueue_payout_processing")
    def test_same_idempotency_key_returns_original_response(self, _mock_enqueue_payout_processing):
        payload = {"amount_paise": 25000, "bank_account_id": self.bank_account.id}

        first_response = self.client.post(
            "/api/v1/payouts",
            payload,
            format="json",
            HTTP_X_MERCHANT_ID=str(self.merchant.id),
            HTTP_IDEMPOTENCY_KEY="merchant-key-1",
        )
        second_response = self.client.post(
            "/api/v1/payouts",
            payload,
            format="json",
            HTTP_X_MERCHANT_ID=str(self.merchant.id),
            HTTP_IDEMPOTENCY_KEY="merchant-key-1",
        )

        self.assertEqual(first_response.status_code, 201)
        self.assertEqual(second_response.status_code, 201)
        self.assertEqual(first_response.json(), second_response.json())
        self.assertEqual(second_response["Idempotent-Replay"], "true")
        self.assertEqual(Payout.objects.count(), 1)
        self.assertEqual(
            LedgerEntry.objects.filter(category=LedgerEntry.Category.PAYOUT_HOLD).count(),
            1,
        )


class ConcurrencyPayoutTests(TransactionTestCase):
    reset_sequences = True

    def setUp(self):
        self.merchant = Merchant.objects.create(name="Concurrent Mart", reference="concurrent-mart")
        self.bank_account = BankAccount.objects.create(
            merchant=self.merchant,
            label="Treasury",
            bank_name="ICICI Bank",
            account_holder_name="Concurrent Mart LLP",
            account_number_last4="9876",
            routing_code="ICIC0005",
        )
        LedgerEntry.objects.create(
            merchant=self.merchant,
            direction=LedgerEntry.Direction.CREDIT,
            category=LedgerEntry.Category.SEED_CREDIT,
            amount_paise=100000,
            reference="seed:concurrent-mart",
            metadata={"source": "test"},
        )

    def _attempt_payout(self, barrier: threading.Barrier, key: str):
        close_old_connections()
        barrier.wait()
        try:
            create_payout_for_merchant(
                merchant_id=self.merchant.id,
                amount_paise=80000,
                bank_account_id=self.bank_account.id,
                idempotency_key=key,
            )
            return "ok"
        except Exception as exc:
            return exc
        finally:
            close_old_connections()

    @patch("payouts.services.enqueue_payout_processing")
    def test_only_one_payout_succeeds_when_funds_are_insufficient(self, _mock_enqueue_payout_processing):
        barrier = threading.Barrier(2)
        with ThreadPoolExecutor(max_workers=2) as executor:
            future_one = executor.submit(self._attempt_payout, barrier, "concurrency-1")
            future_two = executor.submit(self._attempt_payout, barrier, "concurrency-2")
            results = [future_one.result(), future_two.result()]

        successes = [result for result in results if result == "ok"]
        failures = [result for result in results if isinstance(result, Exception)]

        self.assertEqual(len(successes), 1)
        self.assertEqual(len(failures), 1)
        self.assertIsInstance(failures[0], InsufficientFundsError)
        self.assertEqual(Payout.objects.count(), 1)
        self.assertEqual(get_merchant_balance_paise(self.merchant.id), 20000)
