import json

from django.shortcuts import get_object_or_404
from django.views.generic import TemplateView
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import Payment
from .processor_client import ProcessorError
from .serializers import (
    CreatePaymentSerializer,
    WebhookEventSerializer,
    mask_reference,
    payment_detail_to_dict,
)
from .services import IdempotencyConflict, UnknownPayment, apply_processor_event, create_payment
from .webhook_security import signature_is_valid


class PaymentListCreateView(APIView):
    # Authentication is out of scope for this exercise (see README).
    authentication_classes = []
    permission_classes = [AllowAny]

    def get(self, request):
        payments = Payment.objects.order_by("-created_at")[:50]
        return Response(
            [
                {
                    "id": str(p.id),
                    "amount": p.amount,
                    "currency": p.currency,
                    "status": p.current_status(),
                    "processor_reference_masked": mask_reference(p.processor_reference),
                    "created_at": p.created_at.isoformat(),
                }
                for p in payments
            ]
        )

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


class PaymentDetailView(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]

    def get(self, request, payment_id):
        payment = get_object_or_404(Payment, id=payment_id)
        return Response(payment_detail_to_dict(payment))


class ProcessorWebhookView(APIView):
    # The processor proves who it is with the signature, not with a login.
    authentication_classes = []
    permission_classes = [AllowAny]

    def post(self, request):
        # Read the raw bytes first: the signature is computed over them exactly.
        raw_body = request.body
        if not signature_is_valid(raw_body, request.headers.get("X-Processor-Signature", "")):
            return Response({"error": "invalid_signature"}, status=status.HTTP_401_UNAUTHORIZED)

        try:
            payload = json.loads(raw_body)
        except ValueError:
            return Response({"error": "invalid_json"}, status=status.HTTP_400_BAD_REQUEST)

        serializer = WebhookEventSerializer(data=payload)
        if not serializer.is_valid():
            return Response(
                {"error": "invalid_event", "details": serializer.errors},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            outcome = apply_processor_event(serializer.validated_data)
        except UnknownPayment:
            return Response({"error": "unknown_payment"}, status=status.HTTP_404_NOT_FOUND)

        # 200 for every accepted event, including ignored ones, so the
        # processor does not keep retrying an event we have already handled.
        return Response({"received": True, "outcome": outcome})


class DemoPageView(TemplateView):
    template_name = "payments/demo.html"
