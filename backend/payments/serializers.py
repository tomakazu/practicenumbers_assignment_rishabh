from django.utils.dateparse import parse_datetime
from rest_framework import serializers

from .models import PaymentStatus

class CreatePaymentSerializer(serializers.Serializer):
    amount = serializers.IntegerField(min_value=1)
    currency = serializers.ChoiceField(choices=["USD"])
    payment_token = serializers.CharField(max_length=64)

    def validate(self, attrs):
        unexpected = sorted(set(self.initial_data) - set(self.fields))
        if unexpected:
            raise serializers.ValidationError(
                f"Unexpected fields: {', '.join(unexpected)}. Send only amount, currency and payment_token."
            )
        return attrs


class WebhookEventSerializer(serializers.Serializer):
    """The processor's webhook contract from the brief."""

    event_id = serializers.CharField(max_length=64)
    processor_reference = serializers.CharField(max_length=64)
    status = serializers.ChoiceField(choices=PaymentStatus.values)
    failure_code = serializers.ChoiceField(
        choices=["card_declined", "insufficient_funds", "processor_error"],
        allow_null=True,
        required=False,
    )
    occurred_at = serializers.CharField()

    def validate_occurred_at(self, value):
        moment = parse_datetime(value)
        if moment is None:
            raise serializers.ValidationError("Must be an ISO 8601 timestamp.")
        return moment


def mask_reference(reference):
    if not reference:
        return None
    return f"{reference[:3]}••••{reference[-4:]}"


def payment_to_dict(payment):
    return {
        "id": str(payment.id),
        "amount": payment.amount,
        "currency": payment.currency,
        "status": payment.current_status(),
        "processor_reference": payment.processor_reference,
        "created_at": payment.created_at.isoformat(),
    }


def payment_detail_to_dict(payment):
    data = payment_to_dict(payment)
    data["processor_reference_masked"] = mask_reference(payment.processor_reference)
    data["ledger"] = [
        {
            "status": entry.status,
            "failure_code": entry.failure_code,
            "event_id": entry.event_id,
            "occurred_at": entry.occurred_at.isoformat() if entry.occurred_at else None,
            "recorded_at": entry.created_at.isoformat(),
        }
        for entry in payment.ledger_entries.all()
    ]
    data["webhook_events"] = [
        {
            "event_id": event.event_id,
            "status": event.status,
            "outcome": event.outcome,
            "received_at": event.received_at.isoformat(),
        }
        for event in payment.webhook_events.all()
    ]
    return data
