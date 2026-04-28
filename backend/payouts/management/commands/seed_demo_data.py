from django.core.management.base import BaseCommand

from payouts.models import BankAccount, LedgerEntry, Merchant


MERCHANT_SEEDS = [
    {
        "name": "Blue Shop",
        "reference": "blue-shop",
        "seed_amount_paise": 450000,
        "bank_accounts": [
            {
                "label": "Primary HDFC",
                "bank_name": "HDFC Bank",
                "account_holder_name": "Blue Shop Pvt Ltd",
                "account_number_last4": "1101",
                "routing_code": "HDFC0001",
            }
        ],
    },
    {
        "name": "Northwind Foods",
        "reference": "northwind-foods",
        "seed_amount_paise": 820000,
        "bank_accounts": [
            {
                "label": "ICICI Ops",
                "bank_name": "ICICI Bank",
                "account_holder_name": "Northwind Foods LLP",
                "account_number_last4": "2244",
                "routing_code": "ICIC0002",
            }
        ],
    },
    {
        "name": "Orbit Electronics",
        "reference": "orbit-electronics",
        "seed_amount_paise": 1250000,
        "bank_accounts": [
            {
                "label": "Axis Treasury",
                "bank_name": "Axis Bank",
                "account_holder_name": "Orbit Electronics Ltd",
                "account_number_last4": "7788",
                "routing_code": "UTIB0003",
            }
        ],
    },
]


class Command(BaseCommand):
    help = "Seed demo merchants, bank accounts, and ledger credits."

    def handle(self, *args, **options):
        created_merchants = 0
        created_entries = 0

        for merchant_seed in MERCHANT_SEEDS:
            merchant, merchant_created = Merchant.objects.get_or_create(
                reference=merchant_seed["reference"],
                defaults={"name": merchant_seed["name"]},
            )
            if merchant_created:
                created_merchants += 1

            for bank_account_seed in merchant_seed["bank_accounts"]:
                BankAccount.objects.get_or_create(
                    merchant=merchant,
                    label=bank_account_seed["label"],
                    defaults=bank_account_seed,
                )

            ledger_entry, entry_created = LedgerEntry.objects.get_or_create(
                merchant=merchant,
                payout=None,
                category=LedgerEntry.Category.SEED_CREDIT,
                reference=f"seed:{merchant.reference}",
                defaults={
                    "direction": LedgerEntry.Direction.CREDIT,
                    "amount_paise": merchant_seed["seed_amount_paise"],
                    "metadata": {"source": "seed_demo_data"},
                },
            )
            if entry_created:
                created_entries += 1

        self.stdout.write(
            self.style.SUCCESS(
                f"Seed complete. Merchants created: {created_merchants}, ledger credits created: {created_entries}."
            )
        )
