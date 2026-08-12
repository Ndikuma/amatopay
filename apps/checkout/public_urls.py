from django.urls import path

from .payment_views import checkout_status

urlpatterns = [
    path(
        "sessions/<uuid:session_id>/status/",
        checkout_status,
        name="checkout_status",
    ),
]
