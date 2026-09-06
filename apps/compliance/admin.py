from django import forms
from django.contrib import admin, messages
from django.shortcuts import get_object_or_404
from django.urls import path, reverse
from django.utils import timezone
from django.utils.html import format_html
from unfold.admin import ModelAdmin

from apps.core.admin_base import AmatoModelAdmin, ExportActionsMixin, ReadOnlyAmatoModelAdmin

from . import reports
from .exports import as_response
from .models import DataRetentionRecord, RegulatoryReport, SuspiciousTransaction


@admin.register(SuspiciousTransaction)
class SuspiciousTransactionAdmin(ExportActionsMixin, AmatoModelAdmin):
    list_display = (
        "created_at",
        "payment",
        "merchant",
        "status",
        "reported_to_brb",
        "reported_to_cnrf",
        "reported_at",
    )
    list_filter = ("status", "reported_to_brb", "reported_to_cnrf", "created_at")
    search_fields = ("payment__reference", "payment__merchant__display_name", "reason")
    autocomplete_fields = ("payment",)
    actions = ("mark_reported_to_brb", "mark_reported_to_cnrf")

    @admin.display(description="Merchant")
    def merchant(self, obj):
        return obj.payment.merchant.display_name

    @admin.action(description="Mark selected as reported to BRB")
    def mark_reported_to_brb(self, request, queryset):
        updated = queryset.update(reported_to_brb=True, reported_at=timezone.now())
        self.message_user(request, f"{updated} report(s) marked as filed with BRB.")

    @admin.action(description="Mark selected as reported to CNRF")
    def mark_reported_to_cnrf(self, request, queryset):
        updated = queryset.update(reported_to_cnrf=True, reported_at=timezone.now())
        self.message_user(request, f"{updated} report(s) marked as filed with CNRF.")


@admin.register(DataRetentionRecord)
class DataRetentionRecordAdmin(ExportActionsMixin, AmatoModelAdmin):
    list_display = ("object_type", "object_id", "retain_until", "legal_basis", "archived", "deleted_at")
    list_filter = ("archived", "legal_basis", "retain_until")
    search_fields = ("object_type", "object_id", "legal_basis")


class RegulatoryReportForm(forms.ModelForm):
    report_type = forms.ChoiceField(choices=[])

    class Meta:
        model = RegulatoryReport
        fields = ("report_type", "period_start", "period_end", "notes")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        field = self.fields.get("report_type")
        if field is not None:
            field.choices = reports.report_choices()
            field.help_text = "  •  ".join(
                f"{m['label']}: {m['description']}"
                for m in reports.REPORTS.values()
                if m["description"]
            )

    def clean(self):
        cleaned = super().clean()
        start, end = cleaned.get("period_start"), cleaned.get("period_end")
        if start and end and end < start:
            self.add_error("period_end", "The end date must be on or after the start date.")
        return cleaned


@admin.register(RegulatoryReport)
class RegulatoryReportAdmin(ModelAdmin):
    form = RegulatoryReportForm
    list_display = (
        "title_display",
        "report_type",
        "period",
        "row_count",
        "status",
        "generated_by",
        "created_at",
        "downloads",
    )
    list_filter = ("report_type", "status", "created_at")
    search_fields = ("title", "report_type", "notes")
    ordering = ("-created_at",)
    actions = ("mark_submitted",)

    @admin.display(description="Report")
    def title_display(self, obj):
        return obj.title or obj.report_type

    @admin.display(description="Period")
    def period(self, obj):
        return f"{obj.period_start} → {obj.period_end}"

    @admin.display(description="Download")
    def downloads(self, obj):
        if not obj.pk:
            return "—"
        base = reverse("admin:compliance_regulatoryreport_download", args=[obj.pk])
        return format_html(
            '<a href="{}?format=csv">CSV</a> · <a href="{}?format=pdf">PDF</a>', base, base
        )

    def get_readonly_fields(self, request, obj=None):
        if obj is None:
            return ("status",)
        return (
            "report_type", "title", "period", "period_start", "period_end",
            "row_count", "generated_by", "created_at", "updated_at",
            "payload_preview", "downloads",
        )

    def get_fieldsets(self, request, obj=None):
        if obj is None:
            return (
                (None, {
                    "description": "Pick a report and a date range. The data is captured "
                                   "as a frozen snapshot you can export to CSV or PDF.",
                    "fields": ("report_type", "period_start", "period_end", "notes"),
                }),
            )
        return (
            ("Report", {"fields": ("title", "report_type", "period", "row_count", "status", "downloads")}),
            ("Provenance", {"fields": ("generated_by", "created_at", "updated_at", "submitted_at")}),
            ("Notes", {"fields": ("notes",)}),
            ("Snapshot", {"classes": ("collapse",), "fields": ("payload_preview",)}),
        )

    @admin.display(description="Snapshot summary")
    def payload_preview(self, obj):
        summary = (obj.payload or {}).get("summary", {})
        if not summary:
            return "—"
        return format_html(
            "<ul style='margin:0;padding-left:1rem'>{}</ul>",
            format_html("".join(f"<li>{k}: {v}</li>" for k, v in summary.items())),
        )

    def save_model(self, request, obj, form, change):
        if not change:
            data = reports.generate(obj.report_type, obj.period_start, obj.period_end)
            meta = dict(reports.REPORTS[obj.report_type])
            obj.title = f"{meta['label']} · {obj.period_start:%d %b %Y}–{obj.period_end:%d %b %Y}"
            obj.row_count = len(data.rows)
            obj.generated_by = request.user
            obj.payload = {
                "columns": data.columns,
                "rows": data.rows,
                "summary": data.summary,
                "generated_at": timezone.now().isoformat(),
            }
            obj.status = RegulatoryReport.Status.GENERATED
        super().save_model(request, obj, form, change)
        if not change:
            self.message_user(
                request,
                f"Generated “{obj.title}” — {obj.row_count} row(s). Use the CSV / PDF links to export.",
                messages.SUCCESS,
            )

    @admin.action(description="Mark selected as submitted to the regulator")
    def mark_submitted(self, request, queryset):
        updated = queryset.update(
            status=RegulatoryReport.Status.SUBMITTED, submitted_at=timezone.now()
        )
        self.message_user(request, f"{updated} report(s) marked as submitted.")

    def get_urls(self):
        return [
            path(
                "<uuid:pk>/download/",
                self.admin_site.admin_view(self.download_view),
                name="compliance_regulatoryreport_download",
            ),
            *super().get_urls(),
        ]

    def download_view(self, request, pk):
        report_obj = get_object_or_404(RegulatoryReport, pk=pk)
        payload = report_obj.payload or {}
        data = reports.ReportData(
            columns=payload.get("columns", []),
            rows=payload.get("rows", []),
            summary=payload.get("summary", {}),
        )
        meta = {
            "title": report_obj.title,
            "type_label": reports.REPORTS.get(report_obj.report_type, {}).get("label", report_obj.report_type),
            "period_start": report_obj.period_start,
            "period_end": report_obj.period_end,
            "generated_at": payload.get("generated_at", ""),
            "generated_by": report_obj.generated_by.get_username() if report_obj.generated_by_id else "",
            "slug": report_obj.title or report_obj.report_type,
        }
        fmt = "pdf" if request.GET.get("format") == "pdf" else "csv"
        return as_response(data, meta, fmt)
