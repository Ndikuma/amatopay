"""Template context processors."""

from django.conf import settings


def site_settings(request):
    """Add site-wide settings to template context."""
    return {
        'SITE_NAME': getattr(settings, 'SITE_NAME', 'AmatoPay'),
        'SITE_URL': getattr(settings, 'SITE_URL', ''),
        'SUPPORT_EMAIL': getattr(settings, 'SUPPORT_EMAIL', 'support@amatopay.com'),
        'ENABLE_REGISTRATION': getattr(settings, 'ENABLE_REGISTRATION', True),
    }


def feature_flags(request):
    """Add feature flags to template context."""
    return {
        'FEATURES': getattr(settings, 'FEATURE_FLAGS', {}),
    }


def user_context(request):
    """Add user-specific context."""
    context = {}
    
    if request.user.is_authenticated:
        context['user_display_name'] = request.user.get_full_name() or request.user.username
        context['user_initials'] = ''.join([
            name[0].upper() for name in request.user.get_full_name().split()[:2]
        ]) if request.user.get_full_name() else request.user.username[:2].upper()
    
    return context
