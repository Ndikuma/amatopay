from django.contrib import admin
from django.db import models
from django.utils import timezone
from unfold.admin import ModelAdmin


class ExportActionsMixin:
    """Adds "Export selected → CSV / PDF" actions to any ModelAdmin.

    Rows are built from ``list_display`` (callables resolved), so the export
    matches exactly what the operator sees in the changelist.
    """

    export_actions = ("export_selected_csv", "export_selected_pdf")

    def get_actions(self, request):
        actions = super().get_actions(request)
        for name in self.export_actions:
            method = getattr(self, name)
            actions[name] = (method, name, method.short_description)
        return actions

    def _export_columns(self, request):
        display = [c for c in self.get_list_display(request) if c not in ("action_checkbox",)]
        headers = []
        for col in display:
            if col == "__str__":
                headers.append(self.model._meta.verbose_name.title())
            else:
                headers.append(
                    getattr(getattr(self, col, None), "short_description", None)
                    or col.replace("_", " ").title()
                )
        return display, headers

    def _export_rows(self, request, queryset):
        display, headers = self._export_columns(request)
        rows = []
        for obj in queryset:
            row = []
            for col in display:
                attr = getattr(self, col, None)
                if callable(attr):
                    value = attr(obj)
                elif col == "__str__":
                    value = str(obj)
                else:
                    getter = getattr(obj, f"get_{col}_display", None)
                    value = getter() if getter else getattr(obj, col, "")
                    if callable(value):
                        value = value()
                row.append("" if value is None else str(value))
            rows.append(row)
        return headers, rows

    def _export(self, request, queryset, fmt):
        from apps.compliance.exports import as_response
        from apps.compliance.reports import ReportData

        headers, rows = self._export_rows(request, queryset)
        report = ReportData(columns=headers, rows=rows, summary={"selected": len(rows)})
        meta = {
            "title": f"{self.model._meta.verbose_name_plural.title()} export",
            "type_label": "Changelist selection",
            "period_start": "—",
            "period_end": "—",
            "generated_at": timezone.now().strftime("%Y-%m-%d %H:%M"),
            "generated_by": request.user.get_username(),
            "slug": f"{self.model._meta.model_name}-export",
        }
        return as_response(report, meta, fmt)

    @admin.action(description="Export selected → CSV")
    def export_selected_csv(self, request, queryset):
        return self._export(request, queryset, "csv")

    @admin.action(description="Export selected → PDF")
    def export_selected_pdf(self, request, queryset):
        return self._export(request, queryset, "pdf")


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
