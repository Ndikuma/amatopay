import uuid, secrets
from django.db import models
from apps.core.models import UUIDModel, TimeStampedModel


class PaymentSession(UUIDModel, TimeStampedModel):
    class Status(models.TextChoices):
        CREATED = "created", "Created"
        AWAITING_ALIAS = "awaiting_alias", "Awaiting alias"
        ALIAS_VERIFIED = "alias_verified", "Alias verified"
        AWAITING_PAYMENT = "awaiting_payment", "Awaiting payment"
        PROCESSING = "processing", "Processing"
        COMPLETED = "completed", "Completed"
        EXPIRED = "expired", "Expired"
        CANCELLED = "cancelled", "Cancelled"
        FAILED = "failed", "Failed"

    session_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    client_secret = models.CharField(max_length=120, unique=True, editable=False)
    merchant = models.ForeignKey(
        "merchants.Merchant", on_delete=models.PROTECT, related_name="payment_sessions"
    )
    order_number = models.CharField(max_length=100)
    description = models.CharField(max_length=255)
    amount = models.DecimalField(max_digits=20, decimal_places=2)
    fee_amount = models.DecimalField(max_digits=20, decimal_places=2, default=0)
    fee_percentage = models.DecimalField(max_digits=7, decimal_places=4, default=0)
    fee_source = models.CharField(max_length=30, blank=True)
    pricing_plan = models.ForeignKey(
        "billing.PricingPlan",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="checkout_sessions",
    )
    plan_assignment = models.ForeignKey(
        "billing.MerchantPlanAssignment",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="checkout_sessions",
    )
    fee_calculated_at = models.DateTimeField(null=True, blank=True)
    currency = models.CharField(max_length=3, default="BIF")
    payer_alias = models.CharField(max_length=160, blank=True)
    payer_display_name = models.CharField(max_length=180, blank=True)
    return_url = models.URLField(blank=True)
    require_delivery_confirmation = models.BooleanField(
        default=True,
        help_text=(
            "When false, the payment settles to the merchant immediately on "
            "collection with no delivery-confirmation hold. Only permitted for "
            "merchants with instant_settlement_enabled."
        ),
    )
    expires_at = models.DateTimeField()
    status = models.CharField(
        max_length=30, choices=Status.choices, default=Status.CREATED
    )
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=models.Q(amount__gt=0), name="ck_session_amount_positive"
            ),
            models.CheckConstraint(
                condition=models.Q(fee_amount__gte=0)
                & models.Q(fee_amount__lt=models.F("amount")),
                name="ck_session_fee_valid",
            ),
        ]

    @property
    def total_amount(self):
        return self.amount

    @property
    def net_amount(self):
        return self.amount - self.fee_amount

    def save(self, *a, **kw):
        if not self.client_secret:
            self.client_secret = "cs_" + secrets.token_urlsafe(28)
        super().save(*a, **kw)
