import json

from django.contrib import admin, messages
from django.utils.html import format_html
from unfold.admin import ModelAdmin, TabularInline

from apps.core.admin_base import ReadOnlyAmatoModelAdmin
from .models import WebhookAttempt, WebhookDelivery, WebhookEvent
from .services import retry_now


admin.site.register(WebhookEvent, ReadOnlyAmatoModelAdmin)


def _pretty(value):
    """Render a JSON value / string as a readable monospace block."""
    if value in (None, "", {}, []):
        return format_html('<span style="opacity:.5">—</span>')
    text = value
    if isinstance(value, (dict, list)):
        text = json.dumps(value, indent=2, ensure_ascii=False, sort_keys=True)
    else:
        try:
            text = json.dumps(json.loads(value), indent=2, ensure_ascii=False, sort_keys=True)
        except (ValueError, TypeError):
            text = str(value)
    return format_html(
        '<pre style="max-height:420px;overflow:auto;margin:0;padding:12px;'
        'border-radius:8px;background:#0b2934;color:#cfe6e4;font-size:12px;'
        'line-height:1.6;white-space:pre-wrap;word-break:break-word">{}</pre>',
        text,
    )


def _short(text, length=90):
    text = " ".join(str(text or "").split())
    if not text:
        return format_html('<span style="opacity:.5">—</span>')
    return format_html("<code>{}</code>", text[:length] + ("…" if len(text) > length else ""))


class WebhookAttemptInline(TabularInline):
    model = WebhookAttempt
    extra = 0
    can_delete = False
    ordering = ("-attempt_number",)
    fields = ("attempt_number", "created_at", "response_status", "succeeded",
              "duration_ms", "response_preview", "error")
    readonly_fields = fields

    def has_add_permission(self, request, obj=None):
        return False

    @admin.display(description="Merchant response")
    def response_preview(self, obj):
        return _short(obj.response_body)


@admin.register(WebhookDelivery)
class WebhookDeliveryAdmin(ModelAdmin):
    list_display = ("event", "endpoint", "status_badge", "attempts",
                    "last_status_code", "response_preview", "next_retry_at", "updated_at")
    list_filter = ("status", "last_status_code", "event__type")
    search_fields = ("event__event_id", "event__type", "endpoint__url",
                     "last_error", "last_response_body")
    inlines = (WebhookAttemptInline,)
    actions = ("retry_selected",)
    readonly_fields = (
        "event", "endpoint", "status", "attempts", "last_status_code", "last_error",
        "last_response", "last_response_headers_pretty", "next_retry_at",
        "delivered_at", "created_at", "updated_at",
    )
    fieldsets = (
        (None, {"fields": ("event", "endpoint", "status", "attempts",
                           "delivered_at", "next_retry_at", "created_at", "updated_at")}),
        ("Last merchant response", {
            "fields": ("last_status_code", "last_error",
                       "last_response_headers_pretty", "last_response"),
            "description": "What the merchant's endpoint returned on the most recent "
                           "attempt. Full per-attempt history is below.",
        }),
    )

    @admin.display(description="Status")
    def status_badge(self, obj):
        colors = {"delivered": "#0d897f", "failed": "#dc2626", "retrying": "#d97706", "pending": "#64748b"}
        return format_html('<strong style="color:{}">{}</strong>',
                           colors.get(obj.status, "#64748b"), obj.get_status_display())

    @admin.display(description="Merchant response")
    def response_preview(self, obj):
        return _short(obj.last_response_body, 60)

    @admin.display(description="Response body")
    def last_response(self, obj):
        return _pretty(obj.last_response_body)

    @admin.display(description="Response headers")
    def last_response_headers_pretty(self, obj):
        return _pretty(obj.last_response_headers)

    @admin.action(description="Retry selected failed or pending deliveries now")
    def retry_selected(self, request, queryset):
        succeeded = 0
        for delivery in queryset.exclude(status=WebhookDelivery.Status.DELIVERED):
            if retry_now(delivery).status == WebhookDelivery.Status.DELIVERED:
                succeeded += 1
        self.message_user(request, f"Webhook replay completed; {succeeded} delivered successfully.", messages.INFO)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return True

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(WebhookAttempt)
class WebhookAttemptAdmin(ModelAdmin):
    list_display = ("created_at", "delivery", "attempt_number", "succeeded",
                    "response_status", "duration_ms", "response_preview")
    list_filter = ("succeeded", "response_status", "created_at")
    search_fields = ("delivery__event__event_id", "request_url", "error", "response_body")
    readonly_fields = (
        "delivery", "attempt_number", "succeeded", "response_status", "duration_ms",
        "request_url", "error", "created_at",
        "request_headers_pretty", "request_body_pretty",
        "response_headers_pretty", "response_body_pretty",
    )
    fieldsets = (
        (None, {"fields": ("delivery", "attempt_number", "succeeded", "response_status",
                           "duration_ms", "request_url", "error", "created_at")}),
        ("Request sent to the merchant", {"fields": ("request_headers_pretty", "request_body_pretty")}),
        ("Response from the merchant", {"fields": ("response_headers_pretty", "response_body_pretty")}),
    )

    @admin.display(description="Merchant response")
    def response_preview(self, obj):
        return _short(obj.response_body)

    @admin.display(description="Request headers")
    def request_headers_pretty(self, obj):
        return _pretty(obj.request_headers)

    @admin.display(description="Request body")
    def request_body_pretty(self, obj):
        return _pretty(obj.request_body)

    @admin.display(description="Response headers")
    def response_headers_pretty(self, obj):
        return _pretty(obj.response_headers)

    @admin.display(description="Response body")
    def response_body_pretty(self, obj):
        return _pretty(obj.response_body)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return True

    def has_delete_permission(self, request, obj=None):
        return False
