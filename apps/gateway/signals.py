from django.dispatch import Signal


billing_object_created = Signal()
billing_collection_paid = Signal()
collection_created_with_release_code = Signal()