from django.urls import path

from .views import MerchantFeeQuoteView

app_name = "billing"

urlpatterns = [
    path("quote/", MerchantFeeQuoteView.as_view(), name="fee-quote"),
]
