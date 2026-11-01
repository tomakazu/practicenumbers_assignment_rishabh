from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from .services import tokenize
from .validators import TokenizationError
from .webhooks import UnknownCharge, deliver_with_mode_in_background


class TokenizeView(APIView):
    # Stands in for an external processor called directly by the client.
    authentication_classes = []
    permission_classes = [AllowAny]

    def post(self, request):
        try:
            payment_method = tokenize(request.data)
        except TokenizationError as error:
            return Response(
                {"error": error.code, "message": error.message},
                status=status.HTTP_400_BAD_REQUEST,
            )

        return Response(
            {
                "token": payment_method.token,
                "method": payment_method.method,
                "last4": payment_method.last4,
                "brand_or_bank_type": payment_method.brand_or_bank_type,
            },
            status=status.HTTP_201_CREATED,
        )


class SimulateWebhooksView(APIView):
    """Test helper: the same as the simulate_webhooks command, for the demo page."""

    authentication_classes = []
    permission_classes = [AllowAny]

    def post(self, request):
        reference = request.data.get("reference", "")
        mode = request.data.get("mode", "")
        try:
            deliver_with_mode_in_background(reference, mode)
        except UnknownCharge:
            return Response({"error": "unknown_reference"}, status=status.HTTP_404_NOT_FOUND)
        except ValueError as error:
            return Response({"error": "invalid_mode", "message": str(error)}, status=status.HTTP_400_BAD_REQUEST)

        return Response({"scheduled": mode, "reference": reference}, status=status.HTTP_202_ACCEPTED)
