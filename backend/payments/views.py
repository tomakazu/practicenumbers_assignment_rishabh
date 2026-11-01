from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from .processor_client import ProcessorError
from .serializers import CreatePaymentSerializer
from .services import IdempotencyConflict, create_payment


class PaymentCreateView(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]

    def post(self, request):
        key = request.headers.get("Idempotency-Key", "").strip()
        if not key or len(key) > 255:
            return Response(
                {"error": "invalid_idempotency_key", "message": "Send an Idempotency-Key header (1-255 characters)."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        serializer = CreatePaymentSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(
                {"error": "invalid_request", "details": serializer.errors},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            result = create_payment(key, serializer.validated_data)
        except IdempotencyConflict:
            return Response(
                {"error": "idempotency_key_reused", "message": "This Idempotency-Key was already used with a different request body."},
                status=status.HTTP_422_UNPROCESSABLE_ENTITY,
            )
        except ProcessorError as error:
            return Response(
                {"error": error.code, "message": error.message},
                status=status.HTTP_400_BAD_REQUEST,
            )

        response = Response(result.body, status=result.status_code)
        if result.replayed:
            response["Idempotent-Replayed"] = "true"
        return response
