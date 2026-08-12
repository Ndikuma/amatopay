from django.core.exceptions import ValidationError
from django.db import models, transaction
from apps.core.models import UUIDModel, TimeStampedModel


class GatewayConfig(UUIDModel, TimeStampedModel):
    """Admin-managed username/password connection to MobileCash/CECF."""

    name = models.CharField(max_length=100, default="Primary CECF gateway")
    base_url = models.URLField(help_text="CECF/MobileCash API base URL")
    username = models.CharField(max_length=150, blank=True)
    password = models.CharField(max_length=255, blank=True)
    creditor_alias = models.CharField(max_length=80, blank=True)
    timeout_seconds = models.PositiveSmallIntegerField(default=15)
    verify_tls = models.BooleanField(default=True)
    is_active = models.BooleanField(default=False)

    class Meta:
        ordering = ["-is_active", "name"]
        constraints = [
            models.UniqueConstraint(
                fields=["is_active"],
                condition=models.Q(is_active=True),
                name="uq_active_cecf_gateway",
            )
        ]

    def __str__(self):
        suffix = " (active)" if self.is_active else ""
        return f"{self.name}{suffix}"

    def clean(self):
        missing = [
            label
            for label, value in (
                ("username", self.username),
                ("password", self.password),
                ("AmatoPay fiduciary alias", self.creditor_alias),
            )
            if not value
        ]
        if missing:
            raise ValidationError(
                f"Missing required gateway fields: {', '.join(missing)}"
            )

    def save(self, *args, **kwargs):
        self.base_url = self.base_url.rstrip("/")
        with transaction.atomic():
            if self.is_active:
                type(self).objects.filter(is_active=True).exclude(pk=self.pk).update(
                    is_active=False
                )
            return super().save(*args, **kwargs)

    @classmethod
    def active(cls):
        return cls.objects.filter(is_active=True).first()


class AliasVerification(UUIDModel, TimeStampedModel):
    request_id = models.CharField(max_length=100, unique=True)
    session = models.ForeignKey(
        "checkout.PaymentSession",
        on_delete=models.PROTECT,
        related_name="alias_verifications",
        null=True,
        blank=True,
    )
    merchant = models.ForeignKey(
        "merchants.Merchant",
        on_delete=models.PROTECT,
        related_name="payer_alias_verifications",
        null=True,
        blank=True,
    )
    alias_type = models.CharField(max_length=20)
    alias_value = models.CharField(max_length=160)
    found = models.BooleanField(default=False)
    status = models.CharField(max_length=30, blank=True)
    display_name = models.CharField(max_length=180, blank=True)
    provider_customer_ref = models.CharField(max_length=120, blank=True)
    account_type = models.CharField(max_length=30, blank=True)
    currency = models.CharField(max_length=3, default="BIF")
    raw_response = models.JSONField(default=dict, blank=True)


class RTPRequest(UUIDModel, TimeStampedModel):
    request_id = models.CharField(max_length=100, unique=True)
    payment = models.OneToOneField(
        "payments.Payment", on_delete=models.PROTECT, related_name="rtp",
        null=True, blank=True,
    )
    extension_order = models.OneToOneField(
        "billing.PlanExtensionOrder", on_delete=models.PROTECT,
        related_name="rtp", null=True, blank=True,
    )
    plan_request = models.OneToOneField(
        "billing.PlanRequest", on_delete=models.PROTECT,
        related_name="rtp", null=True, blank=True,
    )
    provider_reference = models.CharField(
        max_length=120,
        blank=True,
        db_index=True,
        help_text="Gateway trxRef used by TRANSACTION_BY_REFERENCE monitoring.",
    )
    status = models.CharField(max_length=30, default="pending")
    last_callback_at = models.DateTimeField(null=True, blank=True)
    raw_request = models.JSONField(default=dict, blank=True)
    raw_response = models.JSONField(default=dict, blank=True)
    release_code_ciphertext = models.TextField(blank=True, editable=False)
    last_polled_at = models.DateTimeField(null=True, blank=True)
    next_poll_at = models.DateTimeField(null=True, blank=True, db_index=True)
    poll_attempts = models.PositiveIntegerField(default=0)
    consecutive_poll_failures = models.PositiveSmallIntegerField(default=0)
    last_poll_error = models.TextField(blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["provider_reference"],
                condition=~models.Q(provider_reference=""),
                name="uq_rtp_gateway_trx_ref",
            )
        ]

    @property
    def trx_ref(self):
        return self.provider_reference


class RTPCallback(UUIDModel, TimeStampedModel):
    event_id = models.CharField(max_length=120, unique=True)
    rtp = models.ForeignKey(
        RTPRequest, on_delete=models.PROTECT, related_name="callbacks"
    )
    status = models.CharField(max_length=30)
    reason_code = models.CharField(max_length=80, blank=True)
    payload = models.JSONField(default=dict, blank=True)


class P2PRequest(UUIDModel, TimeStampedModel):
    request_id = models.CharField(max_length=100, unique=True)
    settlement = models.OneToOneField(
        "settlements.Settlement", on_delete=models.PROTECT, related_name="p2p"
    )
    provider_reference = models.CharField(
        max_length=120,
        blank=True,
        db_index=True,
        help_text="Gateway trxRef used by TRANSACTION_BY_REFERENCE monitoring.",
    )
    status = models.CharField(max_length=30, default="processing")
    last_callback_at = models.DateTimeField(null=True, blank=True)
    raw_request = models.JSONField(default=dict, blank=True)
    raw_response = models.JSONField(default=dict, blank=True)
    last_polled_at = models.DateTimeField(null=True, blank=True)
    next_poll_at = models.DateTimeField(null=True, blank=True, db_index=True)
    poll_attempts = models.PositiveIntegerField(default=0)
    consecutive_poll_failures = models.PositiveSmallIntegerField(default=0)
    last_poll_error = models.TextField(blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["provider_reference"],
                condition=~models.Q(provider_reference=""),
                name="uq_p2p_gateway_trx_ref",
            )
        ]

    @property
    def trx_ref(self):
        return self.provider_reference


class P2PCallback(UUIDModel, TimeStampedModel):
    event_id = models.CharField(max_length=120, unique=True)
    p2p = models.ForeignKey(
        P2PRequest, on_delete=models.PROTECT, related_name="callbacks"
    )
    status = models.CharField(max_length=30)
    reason_code = models.CharField(max_length=80, blank=True)
    payload = models.JSONField(default=dict, blank=True)


class GatewayTransactionPoll(UUIDModel, TimeStampedModel):
    class Rail(models.TextChoices):
        RTP = "RTP", "RTP collection"
        P2P = "P2P", "P2P payout"

    rail = models.CharField(max_length=3, choices=Rail.choices, db_index=True)
    request_id = models.CharField(max_length=100, db_index=True)
    trx_ref = models.CharField(max_length=120, db_index=True)
    status = models.CharField(max_length=30, blank=True)
    succeeded = models.BooleanField(default=False, db_index=True)
    response = models.JSONField(default=dict, blank=True)
    error = models.TextField(blank=True)
    duration_ms = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["rail", "trx_ref", "-created_at"], name="idx_gateway_poll_trx"),
        ]
