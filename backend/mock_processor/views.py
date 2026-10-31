from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from .services import tokenize
from .validators import TokenizationError


class TokenizeView(APIView):
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
