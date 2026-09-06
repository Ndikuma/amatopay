from django import forms
from django.contrib import admin, messages
from django.utils.html import format_html
from unfold.admin import ModelAdmin

from apps.core.admin_base import ReadOnlyAmatoModelAdmin
from . import client

from .provider import MobileCashGateway
from .release_codes import decrypt_release_code
from .models import (
    AliasVerification,
    GatewayCallback,
    GatewayConfig,
    GatewayRequest,
    GatewayTransactionPoll,
)


class GatewayConfigForm(forms.ModelForm):
    password = forms.CharField(
        required=False,
        widget=forms.PasswordInput(render_value=False),
        help_text="Leave blank while editing to keep the saved password.",
    )

    class Meta:
        model = GatewayConfig
        fields = "__all__"

    def clean_password(self):
        value = self.cleaned_data.get("password")
        return value or (self.instance.password if self.instance.pk else "")


@admin.register(GatewayConfig)
class GatewayConfigAdmin(ModelAdmin):
    form = GatewayConfigForm
    list_display = ("name", "base_url", "is_active", "verify_tls", "updated_at")
    list_filter = ("is_active", "verify_tls")
    readonly_fields = ("created_at", "updated_at")
    fieldsets = (
        ("Gateway", {"fields": ("name", "base_url", "is_active")}),
        (
            "BurundiPay authentication",
            {"fields": ("username", "password", "creditor_alias")},
        ),
        ("Connection", {"fields": ("timeout_seconds", "verify_tls")}),
        ("Audit", {"fields": ("created_at", "updated_at"), "classes": ("collapse",)}),
    )
    actions = ("test_connection", "activate")

    @admin.action(description="Test selected gateway connections")
    def test_connection(self, request, queryset):
        for config in queryset:
            try:
                gateway = MobileCashGateway(
                    base_url=config.base_url,
                    username=config.username,
                    password=config.password,
                    creditor_alias=config.creditor_alias,
                    timeout=config.timeout_seconds,
                    verify_tls=config.verify_tls,
                )
                gateway.authenticate()
                self.message_user(request, f"{config.name}: connection successful.")
            except Exception as exc:
                self.message_user(
                    request,
                    f"{config.name}: {exc}",
                    level=messages.ERROR,
                )

    @admin.action(description="Activate selected gateway")
    def activate(self, request, queryset):
        if queryset.count() != 1:
            self.message_user(
                request, "Select exactly one gateway.", level=messages.ERROR
            )
            return
        config = queryset.first()
        config.is_active = True
        config.save()
        self.message_user(request, f"{config.name} is now active.")


@admin.register(GatewayRequest)
class GatewayRequestAdmin(ReadOnlyAmatoModelAdmin):
    """Internal collection/payout view; the encrypted release code is never rendered."""

    list_display = (
        "request_id",
        "rail",
        "status",
        "provider_reference",
        "created_at",
    )
    list_filter = ("rail", "status")
    search_fields = ("request_id", "provider_reference")

    def get_readonly_fields(self, request, obj=None):
        fields = tuple(
            field.name
            for field in GatewayRequest._meta.fields
            if field.name != "release_code_ciphertext"
        )
        return (*fields, "secure_delivery_code")

    @admin.display(description="Secure delivery code")
    def secure_delivery_code(self, obj):
        if not obj or not obj.release_code_ciphertext:
            return "Unavailable (already confirmed or not generated)"
        try:
            code = decrypt_release_code(obj.release_code_ciphertext)
        except ValueError:
            return "Unavailable (decryption failed)"
        return format_html(
            '<span style="display:flex;gap:.5rem;align-items:center">'
            '<input type="text" value="{}" readonly aria-label="Secure delivery code" '
            'style="font-family:monospace;font-size:1.1rem;letter-spacing:.15em;'
            'max-width:10rem;padding:.4rem .6rem">'
            '<button type="button" class="button" '
            'data-collection-id="{}" data-action="resend-sms" '
            'onclick="navigator.clipboard.writeText(this.previousElementSibling.value);'
            'this.textContent=&quot;Copied&quot;">Copy</button></span>',
            code,
            obj.request_id,
        )


    actions = ("resend_delivery_code_sms",)

    @admin.action(description="Resend secure delivery code via SMS")
    def resend_delivery_code_sms(self, request, queryset):
        sent_count = 0
        for collection in queryset:
            if not collection.release_code_ciphertext or not collection.payment:
                continue
            try:
                code = decrypt_release_code(collection.release_code_ciphertext)
                phone_number = collection.payment.payer_alias
                message = f"Your AmatoPay secure delivery code is: {code}"
                client.send_sms(phone_number, message)
                sent_count += 1
            except Exception as exc:
                self.message_user(
                    request,
                    f"Could not resend code for {collection.request_id}: {exc}",
                    level=messages.ERROR,
                )
        if sent_count:
            self.message_user(
                request, f"Successfully resent {sent_count} delivery code(s) via SMS."
            )


admin.site.register(
    [AliasVerification, GatewayCallback],
    ReadOnlyAmatoModelAdmin,
)


@admin.register(GatewayTransactionPoll)
class GatewayTransactionPollAdmin(ReadOnlyAmatoModelAdmin):
    list_display = (
        "rail",
        "trx_ref",
        "request_id",
        "status",
        "succeeded",
        "duration_ms",
        "created_at",
    )
    list_filter = ("rail", "succeeded", "status")
    search_fields = ("trx_ref", "request_id", "error")
    readonly_fields = [field.name for field in GatewayTransactionPoll._meta.fields]
