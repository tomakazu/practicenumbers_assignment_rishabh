from django.urls import path

from .views import TokenizeView

urlpatterns = [
    path("tokenize", TokenizeView.as_view(), name="processor-tokenize"),
]
