from django.urls import path

from .views import MerchantDashboardView, MerchantListView, PayoutCreateView


urlpatterns = [
    path("merchants", MerchantListView.as_view(), name="merchant-list"),
    path("merchants/<int:merchant_id>/dashboard", MerchantDashboardView.as_view(), name="merchant-dashboard"),
    path("payouts", PayoutCreateView.as_view(), name="payout-create"),
]
