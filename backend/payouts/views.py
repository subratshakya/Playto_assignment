import uuid

from django.core.exceptions import ObjectDoesNotExist
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from .exceptions import IdempotencyConflictError, InsufficientFundsError
from .models import Merchant
from .serializers import MerchantDashboardSerializer, MerchantSummarySerializer, PayoutCreateSerializer
from .services import annotate_merchants_with_balance, create_payout_for_merchant


class MerchantListView(APIView):
    def get(self, request):
        merchants = annotate_merchants_with_balance(
            Merchant.objects.prefetch_related("bank_accounts").all()
        )
        serializer = MerchantSummarySerializer(merchants, many=True)
        return Response(serializer.data)


class MerchantDashboardView(APIView):
    def get(self, request, merchant_id: int):
        merchant = annotate_merchants_with_balance(
            Merchant.objects.prefetch_related("bank_accounts").filter(pk=merchant_id)
        ).first()
        if not merchant:
            return Response({"detail": "Merchant not found."}, status=status.HTTP_404_NOT_FOUND)

        payouts = merchant.payouts.select_related("bank_account").all()[:20]
        transactions = merchant.ledger_entries.all()[:20]
        serializer = MerchantDashboardSerializer(
            {
                "merchant": merchant,
                "payouts": payouts,
                "transactions": transactions,
            }
        )
        return Response(serializer.data)


class PayoutCreateView(APIView):
    def post(self, request):
        serializer = PayoutCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        merchant_header = request.headers.get("X-Merchant-Id")
        idempotency_key = request.headers.get("Idempotency-Key")

        if not merchant_header:
            return Response({"detail": "X-Merchant-Id header is required."}, status=status.HTTP_400_BAD_REQUEST)
        if not idempotency_key:
            return Response({"detail": "Idempotency-Key header is required."}, status=status.HTTP_400_BAD_REQUEST)
        try:
            uuid.UUID(idempotency_key)
        except ValueError:
            return Response(
                {"detail": "Idempotency-Key must be a valid UUID."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            merchant_id = int(merchant_header)
        except ValueError:
            return Response({"detail": "X-Merchant-Id must be an integer."}, status=status.HTTP_400_BAD_REQUEST)

        try:
            result = create_payout_for_merchant(
                merchant_id=merchant_id,
                amount_paise=serializer.validated_data["amount_paise"],
                bank_account_id=serializer.validated_data["bank_account_id"],
                idempotency_key=idempotency_key,
            )
        except Merchant.DoesNotExist:
            return Response({"detail": "Merchant not found."}, status=status.HTTP_404_NOT_FOUND)
        except ObjectDoesNotExist:
            return Response({"detail": "Bank account not found for merchant."}, status=status.HTTP_404_NOT_FOUND)
        except InsufficientFundsError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_409_CONFLICT)
        except IdempotencyConflictError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_409_CONFLICT)

        response_headers = {}
        if result.replayed:
            response_headers["Idempotent-Replay"] = "true"
        return Response(result.body, status=result.status_code, headers=response_headers)
