from django.urls import path
from .views import MerchantFeeQuoteView

urlpatterns = [path("fees/quote/", MerchantFeeQuoteView.as_view(), name="fee-quote")]
