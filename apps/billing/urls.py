from django.urls import path
from .views import MerchantFeeQuoteView
from . import public_views

app_name = 'billing'

urlpatterns = [path("fees/quote/", MerchantFeeQuoteView.as_view(), name="fee-quote")]

