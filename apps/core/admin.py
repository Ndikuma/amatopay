"""Core admin site customization."""

from django.contrib import admin
from django.contrib.admin import AdminSite
from django.utils.html import format_html
from django.urls import reverse
from django.utils.safestring import mark_safe


class AmatoPayAdminSite(AdminSite):
    """Custom admin site for AmatoPay."""
    
    site_header = 'AmatoPay Admin'
    site_title = 'AmatoPay Admin Portal'
    index_title = 'Payment System Administration'
    
    def each_context(self, request):
        """Add custom context to all admin pages."""
        context = super().each_context(request)
        context.update({
            'show_dashboard_link': True,
            'support_email': 'support@amatopay.com',
        })
        return context


# Custom admin site instance
admin_site = AmatoPayAdminSite(name='amatopay_admin')


class BaseModelAdmin(admin.ModelAdmin):
    """Base admin class with common functionality."""
    
    readonly_fields = ('created_at', 'updated_at', 'id')
    list_per_page = 25
    date_hierarchy = 'created_at'
    
    def get_readonly_fields(self, request, obj=None):
        """Make fields readonly after creation."""
        readonly = list(self.readonly_fields)
        if obj:  # Editing existing object
            readonly.extend(getattr(self, 'readonly_on_edit', []))
        return readonly
    
    def has_delete_permission(self, request, obj=None):
        """Restrict delete based on permissions."""
        if not request.user.is_superuser:
            return False
        return super().has_delete_permission(request, obj)


class ReadOnlyAdmin(admin.ModelAdmin):
    """Admin for read-only models."""
    
    def has_add_permission(self, request):
        return False
    
    def has_change_permission(self, request, obj=None):
        return False
    
    def has_delete_permission(self, request, obj=None):
        return False


def admin_link(obj, field_name, label=None):
    """Generate admin link for related object."""
    if not obj:
        return '-'
    
    app_label = obj._meta.app_label
    model_name = obj._meta.model_name
    url = reverse(f'admin:{app_label}_{model_name}_change', args=[obj.pk])
    
    display_label = label or str(obj)
    return format_html('<a href="{}">{}</a>', url, display_label)


def status_badge(status, label=None):
    """Generate colored status badge."""
    colors = {
        'pending': '#FFA500',
        'processing': '#007BFF',
        'completed': '#28A745',
        'success': '#28A745',
        'failed': '#DC3545',
        'cancelled': '#6C757D',
        'refunded': '#17A2B8',
    }
    
    color = colors.get(status.lower(), '#6C757D')
    display_label = label or status.upper()
    
    return format_html(
        '<span style="background-color: {}; color: white; '
        'padding: 3px 8px; border-radius: 3px; font-size: 11px;">{}</span>',
        color, display_label
    )
