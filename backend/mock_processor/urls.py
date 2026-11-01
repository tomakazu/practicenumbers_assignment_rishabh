from django.urls import path

from .views import SimulateWebhooksView, TokenizeView

urlpatterns = [
    path("tokenize", TokenizeView.as_view(), name="processor-tokenize"),
    path("simulate", SimulateWebhooksView.as_view(), name="processor-simulate"),
]
