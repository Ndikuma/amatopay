from django.db import models
from unfold.admin import ModelAdmin


class AmatoModelAdmin(ModelAdmin):
    """Useful Unfold defaults for operational models without a custom admin."""

    list_per_page = 50
    list_max_show_all = 200
    show_full_result_count = False
    save_on_top = True

    def get_list_display(self, request):
        configured = super().get_list_display(request)
        if configured != ("__str__",):
            return configured
        preferred = (
            "reference",
            "request_id",
            "event_id",
            "merchant",
            "payment",
            "session",
            "name",
            "code",
            "status",
            "amount",
            "fee_amount",
            "net_amount",
            "active",
            "created_at",
            "updated_at",
        )
        field_names = {field.name for field in self.model._meta.fields}
        selected = [name for name in preferred if name in field_names][:7]
        return tuple(selected or ["__str__"])

    def get_search_fields(self, request):
        configured = super().get_search_fields(request)
        if configured:
            return configured
        preferred = (
            "reference",
            "request_id",
            "event_id",
            "name",
            "code",
            "description",
            "reason",
        )
        field_names = {field.name for field in self.model._meta.fields}
        return tuple(name for name in preferred if name in field_names)[:4]

    def get_list_filter(self, request):
        configured = super().get_list_filter(request)
        if configured:
            return configured
        filters = []
        for field in self.model._meta.fields:
            if isinstance(field, models.BooleanField) or field.choices:
                filters.append(field.name)
        return tuple(filters[:4])


class ReadOnlyAmatoModelAdmin(AmatoModelAdmin):
    """Unfold presentation for immutable operational and financial records."""

    def get_readonly_fields(self, request, obj=None):
        return tuple(field.name for field in self.model._meta.fields)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return True

    def has_delete_permission(self, request, obj=None):
        return False
