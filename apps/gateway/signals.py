from django.dispatch import Signal


billing_object_created = Signal()
billing_rtp_paid = Signal()
rtp_created_with_release_code = Signal()