from rest_framework import serializers

from .models import BankAccount, LedgerEntry, Merchant, Payout


class BankAccountSerializer(serializers.ModelSerializer):
    class Meta:
        model = BankAccount
        fields = [
            "id",
            "label",
            "bank_name",
            "account_holder_name",
            "account_number_last4",
            "routing_code",
        ]


class PayoutSerializer(serializers.ModelSerializer):
    bank_account = BankAccountSerializer(read_only=True)
    bank_account_id = serializers.IntegerField(read_only=True)

    class Meta:
        model = Payout
        fields = [
            "id",
            "external_reference",
            "merchant_id",
            "bank_account_id",
            "bank_account",
            "amount_paise",
            "status",
            "attempts",
            "failure_reason",
            "created_at",
            "updated_at",
            "processing_started_at",
            "next_retry_at",
            "completed_at",
        ]


class LedgerEntrySerializer(serializers.ModelSerializer):
    class Meta:
        model = LedgerEntry
        fields = [
            "id",
            "merchant_id",
            "payout_id",
            "direction",
            "category",
            "amount_paise",
            "reference",
            "metadata",
            "created_at",
        ]


class MerchantSummarySerializer(serializers.ModelSerializer):
    bank_accounts = BankAccountSerializer(many=True, read_only=True)
    balance_paise = serializers.IntegerField(read_only=True)
    available_balance_paise = serializers.IntegerField(read_only=True)
    held_balance_paise = serializers.IntegerField(read_only=True)
    credit_total_paise = serializers.IntegerField(read_only=True)
    debit_total_paise = serializers.IntegerField(read_only=True)

    class Meta:
        model = Merchant
        fields = [
            "id",
            "name",
            "reference",
            "balance_paise",
            "available_balance_paise",
            "held_balance_paise",
            "credit_total_paise",
            "debit_total_paise",
            "bank_accounts",
        ]


class MerchantDashboardSerializer(serializers.Serializer):
    merchant = MerchantSummarySerializer()
    payouts = PayoutSerializer(many=True)
    transactions = LedgerEntrySerializer(many=True)


class PayoutCreateSerializer(serializers.Serializer):
    amount_paise = serializers.IntegerField(min_value=1)
    bank_account_id = serializers.IntegerField(min_value=1)
