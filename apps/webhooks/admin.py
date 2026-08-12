from django.contrib import admin, messages
from django.utils.html import format_html
from unfold.admin import ModelAdmin

from apps.core.admin_base import ReadOnlyAmatoModelAdmin
from .models import WebhookAttempt, WebhookDelivery, WebhookEvent
from .services import retry_now


admin.site.register(WebhookEvent, ReadOnlyAmatoModelAdmin)


@admin.register(WebhookDelivery)
class WebhookDeliveryAdmin(ModelAdmin):
    list_display = ("event", "endpoint", "status_badge", "attempts", "last_status_code", "next_retry_at", "updated_at")
    list_filter = ("status", "last_status_code", "event__type")
    search_fields = ("event__event_id", "event__type", "endpoint__url", "last_error")
    readonly_fields = ("event", "endpoint", "status", "attempts", "last_status_code", "last_error", "next_retry_at", "delivered_at", "created_at", "updated_at")
    actions = ("retry_selected",)

    @admin.display(description="Status")
    def status_badge(self, obj):
        colors = {"delivered": "#0d897f", "failed": "#dc2626", "retrying": "#d97706", "pending": "#64748b"}
        return format_html('<strong style="color:{}">{}</strong>', colors.get(obj.status, "#64748b"), obj.get_status_display())

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
class WebhookAttemptAdmin(ReadOnlyAmatoModelAdmin):
    list_display = ("created_at", "delivery", "attempt_number", "succeeded", "response_status", "duration_ms")
    list_filter = ("succeeded", "response_status", "created_at")
    search_fields = ("delivery__event__event_id", "request_url", "error")
