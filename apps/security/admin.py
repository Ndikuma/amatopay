from django.contrib import admin
from django.utils.html import format_html
from unfold.admin import ModelAdmin

from .models import BlockedIP, RequestLog, SecurityAlert

_SEV_STYLE = {
    'info':     ('rgba(99,102,241,.12)',  '#6366f1'),
    'low':      ('rgba(34,197,94,.12)',   '#22c55e'),
    'medium':   ('rgba(245,158,11,.12)',  '#f59e0b'),
    'high':     ('rgba(239,68,68,.12)',   '#ef4444'),
    'critical': ('rgba(220,38,38,.2)',    '#dc2626'),
}

_SVG_CHECK = '<svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" style="vertical-align:middle;margin-right:2px"><path d="M20 6 9 17l-5-5"/></svg>'
_SVG_X     = '<svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" style="vertical-align:middle;margin-right:2px"><path d="M18 6 6 18M6 6l12 12"/></svg>'


@admin.register(SecurityAlert)
class SecurityAlertAdmin(ModelAdmin):
    list_display  = ['timestamp', 'sev_badge', 'alert_type', 'ip_address', 'path_short', 'resolved_badge']
    list_filter   = ['severity', 'alert_type', 'resolved']
    search_fields = ['ip_address', 'path', 'detail']
    readonly_fields = ['timestamp', 'severity', 'alert_type', 'ip_address', 'path',
                       'detail', 'resolved_at', 'resolved_by', 'request_log']
    ordering      = ['-timestamp']
    list_per_page = 50

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return request.user.is_superuser

    @admin.display(description='Severity')
    def sev_badge(self, obj):
        bg, fg = _SEV_STYLE.get(obj.severity, ('rgba(107,114,128,.12)', '#6b7280'))
        return format_html(
            '<span style="padding:2px 8px;border-radius:9999px;font-size:11px;font-weight:700;'
            'background:{};color:{};text-transform:uppercase;letter-spacing:.05em">{}</span>',
            bg, fg, obj.severity,
        )

    @admin.display(description='Path')
    def path_short(self, obj):
        p = obj.path[:60] + ('…' if len(obj.path) > 60 else '')
        return format_html('<code style="font-size:11px">{}</code>', p)

    @admin.display(description='Resolved')
    def resolved_badge(self, obj):
        if obj.resolved:
            return format_html(
                '<span style="display:inline-flex;align-items:center;color:#10b981;font-size:12px">{} yes</span>',
                format_html(_SVG_CHECK),
            )
        return format_html(
            '<span style="display:inline-flex;align-items:center;color:#ef4444;font-size:12px">{} open</span>',
            format_html(_SVG_X),
        )


@admin.register(RequestLog)
class RequestLogAdmin(ModelAdmin):
    list_display  = ['timestamp', 'method', 'path_short', 'status_badge', 'ip_address',
                     'response_ms', 'is_api']
    list_filter   = ['method', 'status_code', 'is_api']
    search_fields = ['ip_address', 'path', 'user_agent']
    readonly_fields = [f.name for f in RequestLog._meta.get_fields() if hasattr(f, 'name') and not f.is_relation]
    ordering      = ['-timestamp']
    list_per_page = 100
    date_hierarchy = 'timestamp'

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return request.user.is_superuser

    @admin.display(description='Path')
    def path_short(self, obj):
        p = obj.path[:55] + ('…' if len(obj.path) > 55 else '')
        return format_html('<code style="font-size:11px">{}</code>', p)

    @admin.display(description='Status')
    def status_badge(self, obj):
        code = obj.status_code
        if code < 300:
            bg, fg = 'rgba(16,185,129,.12)', '#10b981'
        elif code < 400:
            bg, fg = 'rgba(59,130,246,.12)', '#3b82f6'
        elif code < 500:
            bg, fg = 'rgba(245,158,11,.12)', '#f59e0b'
        else:
            bg, fg = 'rgba(239,68,68,.12)', '#ef4444'
        return format_html(
            '<span style="padding:2px 8px;border-radius:9999px;font-size:11px;font-weight:600;'
            'background:{};color:{}">{}</span>',
            bg, fg, code,
        )


@admin.register(BlockedIP)
class BlockedIPAdmin(ModelAdmin):
    list_display  = ['ip_address', 'reason_short', 'blocked_by', 'blocked_at', 'expires_at', 'status_badge']
    list_filter   = ['is_active', 'blocked_by']
    search_fields = ['ip_address', 'reason']
    ordering      = ['-blocked_at']
    list_per_page = 50

    @admin.display(description='Reason')
    def reason_short(self, obj):
        r = obj.reason[:60] + ('…' if len(obj.reason) > 60 else '')
        return r

    @admin.display(description='Status')
    def status_badge(self, obj):
        if obj.is_active and not obj.is_expired:
            return format_html(
                '<span style="padding:2px 8px;border-radius:9999px;font-size:11px;font-weight:600;'
                'background:rgba(239,68,68,.12);color:#ef4444">Blocked</span>'
            )
        return format_html(
            '<span style="padding:2px 8px;border-radius:9999px;font-size:11px;font-weight:600;'
            'background:rgba(107,114,128,.12);color:#6b7280">Inactive</span>'
        )
