from django.db import models
from apps.core.models import UUIDModel, TimeStampedModel


class FiduciaryAccount(UUIDModel, TimeStampedModel):
    singleton_key = models.CharField(
        max_length=20, default="AMATOPAY", unique=True, editable=False
    )
    alias_type = models.CharField(max_length=20, default="MOBILE", editable=False)
    creditor_alias = models.CharField(
        max_length=160, unique=True, editable=False, default=""
    )
    account_number = models.CharField(
        max_length=120, unique=True, editable=False, default=""
    )
    account_name = models.CharField(max_length=180, blank=True)
    currency = models.CharField(max_length=3, default="BIF")
    active = models.BooleanField(default=True)
    verified_at = models.DateTimeField(null=True, blank=True, editable=False)
    raw_verification = models.JSONField(default=dict, blank=True, editable=False)

    class Meta:
        verbose_name = "AmatoPay fiduciary account"
        verbose_name_plural = "AmatoPay fiduciary account"

    @property
    def is_verified(self):
        return self.verified_at is not None

    def __str__(self):
        return f"{self.account_name or 'AmatoPay fiduciary'} · {self.creditor_alias}"


class FundHold(UUIDModel, TimeStampedModel):
    class Status(models.TextChoices):
        HELD = "held", "Held"
        DELIVERY_PENDING = "delivery_pending", "Delivery pending"
        DELIVERY_CONFIRMED = "delivery_confirmed", "Delivery confirmed"
        DISPUTED = "disputed", "Disputed"
        RELEASE_PENDING = "release_pending", "Release pending"
        RELEASED = "released", "Released"
        REFUND_PENDING = "refund_pending", "Refund pending"
        REFUNDED = "refunded", "Refunded"
        FROZEN = "frozen", "Frozen"

    payment = models.OneToOneField(
        "payments.Payment", on_delete=models.PROTECT, related_name="fund_hold"
    )
    fiduciary_account = models.ForeignKey(
        FiduciaryAccount, on_delete=models.PROTECT, related_name="holds"
    )
    amount = models.DecimalField(max_digits=20, decimal_places=2)
    status = models.CharField(
        max_length=30, choices=Status.choices, default=Status.HELD
    )
    held_at = models.DateTimeField(auto_now_add=True)
    release_eligible_at = models.DateTimeField(null=True, blank=True)
    released_at = models.DateTimeField(null=True, blank=True)
    international = models.BooleanField(default=False)
    freeze_reason = models.CharField(max_length=255, blank=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=models.Q(amount__gt=0), name="ck_fund_hold_amount_positive"
            )
        ]


class FiduciaryEntry(UUIDModel):
    class Direction(models.TextChoices):
        CREDIT = "credit", "Credit"
        DEBIT = "debit", "Debit"

    class Kind(models.TextChoices):
        CUSTOMER_FUNDS = "customer_funds", "Customer funds"
        RELEASE = "release", "Release"
        REFUND = "refund", "Refund"
        FEE = "fee", "Fee"
        TAX = "tax", "Tax"
        ADJUSTMENT = "adjustment", "Adjustment"

    account = models.ForeignKey(
        FiduciaryAccount, on_delete=models.PROTECT, related_name="entries"
    )
    payment = models.ForeignKey(
        "payments.Payment", on_delete=models.PROTECT, related_name="fiduciary_entries"
    )
    direction = models.CharField(max_length=10, choices=Direction.choices)
    kind = models.CharField(
        max_length=30, choices=Kind.choices, default=Kind.CUSTOMER_FUNDS
    )
    amount = models.DecimalField(max_digits=20, decimal_places=2)
    reference = models.CharField(max_length=120)
    narrative = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=models.Q(amount__gt=0), name="ck_fiduciary_entry_positive"
            ),
            models.UniqueConstraint(
                fields=["payment", "kind", "reference"],
                name="uq_fiduciary_payment_kind_reference",
            ),
        ]
