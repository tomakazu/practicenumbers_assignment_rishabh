from rest_framework import serializers


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


def payment_to_dict(payment):
    return {
        "id": str(payment.id),
        "amount": payment.amount,
        "currency": payment.currency,
        "status": payment.current_status(),
        "processor_reference": payment.processor_reference,
        "created_at": payment.created_at.isoformat(),
    }
