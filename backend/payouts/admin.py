from django.contrib import admin

from .models import BankAccount, LedgerEntry, Merchant, MerchantIdempotencyKey, Payout


@admin.register(Merchant)
class MerchantAdmin(admin.ModelAdmin):
    list_display = ("id", "name", "reference", "created_at")
    search_fields = ("name", "reference")


@admin.register(BankAccount)
class BankAccountAdmin(admin.ModelAdmin):
    list_display = ("id", "merchant", "label", "bank_name", "account_number_last4")
    list_select_related = ("merchant",)


@admin.register(Payout)
class PayoutAdmin(admin.ModelAdmin):
    list_display = ("id", "merchant", "amount_paise", "status", "attempts", "created_at")
    list_filter = ("status",)
    list_select_related = ("merchant", "bank_account")


@admin.register(LedgerEntry)
class LedgerEntryAdmin(admin.ModelAdmin):
    list_display = ("id", "merchant", "direction", "category", "amount_paise", "created_at")
    list_filter = ("direction", "category")
    list_select_related = ("merchant", "payout")


@admin.register(MerchantIdempotencyKey)
class MerchantIdempotencyKeyAdmin(admin.ModelAdmin):
    list_display = ("id", "merchant", "key", "expires_at", "is_active")
    list_filter = ("is_active",)
    list_select_related = ("merchant", "payout")
