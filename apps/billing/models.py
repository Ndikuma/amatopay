import uuid
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from decimal import Decimal
from apps.core.models import TimeStampedModel, UUIDModel


class PricingPlan(UUIDModel, TimeStampedModel):
    code = models.SlugField(max_length=40, unique=True)
    name = models.CharField(max_length=100)
    description = models.TextField(blank=True)
    features = models.JSONField(
        default=list, blank=True, help_text="A list of plan features."
    )
    included_transactions_per_month = models.PositiveIntegerField(
        null=True,
        blank=True,
        help_text="Included successful payments per calendar month; blank means unlimited.",
    )
    monthly_price = models.DecimalField(
        max_digits=20,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Published monthly plan price; blank means contract pricing.",
    )
    transaction_fee_percentage = models.DecimalField(
        max_digits=7,
        decimal_places=4,
        null=True,
        blank=True,
        help_text="Percentage fee per transaction for pay-as-you-go plans.",
    )

    currency = models.CharField(max_length=3, default="BIF")
    active = models.BooleanField(default=True)

    class Meta:
        ordering = ["name"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(monthly_price__isnull=True)
                | models.Q(monthly_price__gte=0),
                name="ck_plan_monthly_price_nonnegative",
            )
        ]

    def clean(self):
        self.currency = self.currency.upper()

    def __str__(self):
        return self.name


class MerchantPlanAssignment(UUIDModel, TimeStampedModel):
    merchant = models.ForeignKey(
        "merchants.Merchant", on_delete=models.PROTECT, related_name="plan_assignments"
    )
    plan = models.ForeignKey(
        PricingPlan, on_delete=models.PROTECT, related_name="merchant_assignments"
    )
    effective_from = models.DateTimeField(db_index=True)
    effective_until = models.DateTimeField(null=True, blank=True, db_index=True)
    active = models.BooleanField(default=True)
    reason = models.CharField(max_length=255)
    contracted_transactions_per_month = models.PositiveIntegerField(
        null=True,
        blank=True,
        help_text=(
            "Contract-specific monthly allowance. Leave blank to use the plan allowance."
        ),
    )
    contracted_monthly_price = models.DecimalField(
        max_digits=20,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Signed monthly price. Leave blank to use the plan price.",
    )
    assigned_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="assigned_merchant_plans",
    )

    class Meta:
        ordering = ["merchant", "-effective_from"]
        constraints = [
            models.UniqueConstraint(
                fields=["merchant", "effective_from"],
                name="uq_merchant_plan_effective",
            ),
            models.CheckConstraint(
                condition=models.Q(contracted_monthly_price__isnull=True)
                | models.Q(contracted_monthly_price__gte=0),
                name="ck_contract_monthly_price_nonnegative",
            ),
        ]
        indexes = [models.Index(fields=["merchant", "active", "effective_from"])]

    def clean(self):
        if self.effective_until and self.effective_until <= self.effective_from:
            raise ValidationError(
                {"effective_until": "End time must be after the effective start."}
            )
        if not self.reason.strip():
            raise ValidationError({"reason": "An assignment reason is required."})
        if not self.plan.active:
            raise ValidationError({"plan": "Only an active plan can be assigned."})

    def __str__(self):
        return f"{self.merchant} — {self.plan}"

    @property
    def monthly_transaction_limit(self):
        if self.contracted_transactions_per_month is not None:
            return self.contracted_transactions_per_month
        return self.plan.included_transactions_per_month

    @property
    def effective_monthly_price(self):
        if self.contracted_monthly_price is not None:
            return self.contracted_monthly_price
        return self.plan.monthly_price


class PlanRequest(UUIDModel, TimeStampedModel):
    """Records a merchant's request to be assigned a pricing plan, paid via RTP."""

    class Status(models.TextChoices):
        PENDING_PAYMENT = "pending_payment", "Pending payment"
        PAID = "paid", "Paid"
        ACTIVE = "active", "Active — plan assigned"
        FAILED = "failed", "Failed"
        CANCELLED = "cancelled", "Cancelled"

    reference = models.CharField(max_length=64, unique=True, editable=False)
    merchant = models.ForeignKey(
        "merchants.Merchant", on_delete=models.PROTECT, related_name="plan_requests"
    )
    plan = models.ForeignKey(
        PricingPlan, on_delete=models.PROTECT, related_name="plan_requests"
    )
    amount = models.DecimalField(max_digits=20, decimal_places=2)
    currency = models.CharField(max_length=3, default="BIF")
    payer_alias = models.CharField(max_length=60)
    note = models.TextField(blank=True)
    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.PENDING_PAYMENT
    )
    provider_reference = models.CharField(max_length=120, blank=True, db_index=True)
    paid_at = models.DateTimeField(null=True, blank=True)
    initiated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True, blank=True,
        related_name="billing_plan_requests",
    )

    class Meta:
        ordering = ["-created_at"]

    def save(self, *args, **kwargs):
        if not self.reference:
            self.reference = "AMP-PLR-" + uuid.uuid4().hex[:16].upper()
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.reference} — {self.plan} ({self.status})"
