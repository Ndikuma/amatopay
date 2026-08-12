import json
from datetime import timedelta

from django.contrib.auth import authenticate, login, logout
from django.db.models import Avg, Count, Q
from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from .models import BlockedIP, RequestLog, SecurityAlert

# ── Auth guard ──────────────────────────────────────────────────────────────────

def _require_security_access(view_fn):
    """Decorator: requires Django staff session."""
    def wrapper(request, *args, **kwargs):
        if not (request.user.is_authenticated and request.user.is_staff):
            return redirect(f'/security/login/?next={request.path}')
        return view_fn(request, *args, **kwargs)
    wrapper.__name__ = view_fn.__name__
    return wrapper


# ── Login / logout ─────────────────────────────────────────────────────────────

def security_login(request):
    error = ''
    if request.method == 'POST':
        user = authenticate(
            request,
            username=request.POST.get('username', ''),
            password=request.POST.get('password', ''),
        )
        if user and user.is_staff:
            login(request, user)
            return redirect(request.GET.get('next', '/security/dashboard/'))
        error = 'Invalid credentials or insufficient permissions.'
    return render(request, 'security/login.html', {'error': error})


def security_logout(request):
    logout(request)
    return redirect('/security/login/')


@_require_security_access
def security_overview(request):
    return render(request, 'security/overview.html')


# ── Dashboard ──────────────────────────────────────────────────────────────────

@_require_security_access
def dashboard(request):
    now   = timezone.now()
    today = now - timedelta(hours=24)
    week  = now - timedelta(days=7)

    # ── Top-line stats ─────────────────────────────────────────────────────────
    total_requests   = RequestLog.objects.filter(timestamp__gte=today).count()
    total_alerts     = SecurityAlert.objects.filter(resolved=False).count()
    blocked_ips      = BlockedIP.objects.filter(is_active=True).count()
    critical_alerts  = SecurityAlert.objects.filter(
        resolved=False, severity__in=['critical', 'high']
    ).count()

    api_requests     = RequestLog.objects.filter(timestamp__gte=today, is_api=True).count()
    blocked_requests = RequestLog.objects.filter(
        timestamp__gte=today,
        status_code__in=[403, 429],
    ).count()
    unique_ips       = RequestLog.objects.filter(
        timestamp__gte=today,
    ).values('ip_address').distinct().count()
    errors_4xx       = RequestLog.objects.filter(
        timestamp__gte=today, status_code__gte=400, status_code__lt=500
    ).count()
    errors_5xx       = RequestLog.objects.filter(
        timestamp__gte=today, status_code__gte=500
    ).count()
    avg_response_ms  = (
        RequestLog.objects.filter(timestamp__gte=today)
        .aggregate(avg=Avg('response_ms'))['avg'] or 0
    )
    slow_requests = RequestLog.objects.filter(timestamp__gte=today, response_ms__gt=2000).count()
    rate_limited_ips = BlockedIP.objects.filter(
        is_active=True,
        expires_at__gt=now,
    ).count()
    if critical_alerts:
        risk_level = 'Critical'
        risk_class = 'danger'
        security_score = 62
    elif total_alerts:
        risk_level = 'Watch'
        risk_class = 'warn'
        security_score = 82
    elif errors_5xx:
        risk_level = 'Stable'
        risk_class = 'info'
        security_score = 88
    else:
        risk_level = 'Protected'
        risk_class = 'ok'
        security_score = 96

    # ── Active alerts (unresolved, newest first, limit 50) ─────────────────────
    active_alerts = SecurityAlert.objects.filter(resolved=False).select_related('request_log')[:50]

    # ── Recent requests (last 100) ─────────────────────────────────────────────
    recent_requests = RequestLog.objects.filter(timestamp__gte=today)[:100]

    # ── Top IPs by request count (last 24h) ────────────────────────────────────
    top_ips = (
        RequestLog.objects
        .filter(timestamp__gte=today)
        .values('ip_address')
        .annotate(count=Count('id'))
        .order_by('-count')[:10]
    )
    top_attackers = (
        RequestLog.objects
        .filter(timestamp__gte=today, status_code__in=[403, 429])
        .values('ip_address')
        .annotate(count=Count('id'))
        .order_by('-count')[:10]
    )

    # ── Alert type breakdown ────────────────────────────────────────────────────
    alert_breakdown = (
        SecurityAlert.objects
        .filter(timestamp__gte=week)
        .values('alert_type')
        .annotate(count=Count('id'))
        .order_by('-count')
    )
    alerts_by_severity = (
        SecurityAlert.objects
        .filter(timestamp__gte=today)
        .values('severity')
        .annotate(count=Count('id'))
        .order_by('severity')
    )

    # ── Blocked IPs ────────────────────────────────────────────────────────────
    blocked_list = BlockedIP.objects.filter(is_active=True).order_by('-blocked_at')[:20]

    # ── Hourly request sparkline (last 24h, grouped by hour) ──────────────────
    from django.db.models.functions import TruncHour
    hourly = (
        RequestLog.objects
        .filter(timestamp__gte=today)
        .annotate(hour=TruncHour('timestamp'))
        .values('hour')
        .annotate(count=Count('id'))
        .order_by('hour')
    )
    hourly_data = [{'hour': str(h['hour']), 'count': h['count']} for h in hourly]

    return render(request, 'security/dashboard.html', {
        'now': now,
        'total_requests':  total_requests,
        'total_alerts':    total_alerts,
        'blocked_ips':     blocked_ips,
        'critical_alerts': critical_alerts,
        'api_requests':    api_requests,
        'blocked_requests': blocked_requests,
        'unique_ips':      unique_ips,
        'errors_4xx':      errors_4xx,
        'errors_5xx':      errors_5xx,
        'avg_response_ms': int(avg_response_ms),
        'slow_requests':   slow_requests,
        'rate_limited_ips': rate_limited_ips,
        'risk_level':      risk_level,
        'risk_class':      risk_class,
        'security_score':  security_score,
        'active_alerts':   active_alerts,
        'recent_requests': recent_requests,
        'top_ips':         top_ips,
        'top_attackers':   top_attackers,
        'alert_breakdown': alert_breakdown,
        'alerts_by_severity': alerts_by_severity,
        'blocked_list':    blocked_list,
        'hourly_json':     json.dumps(hourly_data),
    })


# ── API actions ────────────────────────────────────────────────────────────────

@_require_security_access
@require_POST
def block_ip(request):
    ip     = request.POST.get('ip_address', '').strip()
    reason = request.POST.get('reason', 'Manual block from dashboard').strip()
    if not ip:
        return JsonResponse({'error': 'IP address required.'}, status=400)

    obj, created = BlockedIP.objects.update_or_create(
        ip_address=ip,
        defaults={
            'reason':     reason[:500],
            'blocked_by': str(request.user.username),
            'is_active':  True,
            'expires_at': None,
        },
    )
    return JsonResponse({'ok': True, 'ip': ip, 'created': created})


@_require_security_access
@require_POST
def unblock_ip(request, ip):
    updated = BlockedIP.objects.filter(ip_address=ip).update(is_active=False)
    return JsonResponse({'ok': True, 'updated': updated})


@_require_security_access
@require_POST
def resolve_alert(request, alert_id):
    try:
        alert = SecurityAlert.objects.get(pk=alert_id)
    except SecurityAlert.DoesNotExist:
        return JsonResponse({'error': 'Alert not found.'}, status=404)
    alert.resolve(by=str(request.user.username))
    return JsonResponse({'ok': True})


@_require_security_access
@require_POST
def resolve_all_alerts(request):
    now = timezone.now()
    count = SecurityAlert.objects.filter(resolved=False).update(
        resolved=True,
        resolved_at=now,
        resolved_by=str(request.user.username),
    )
    return JsonResponse({'ok': True, 'resolved': count})


# ── Live stats endpoint (for dashboard auto-refresh) ──────────────────────────

@_require_security_access
def live_stats(request):
    now   = timezone.now()
    today = now - timedelta(hours=24)
    return JsonResponse({
        'total_requests':  RequestLog.objects.filter(timestamp__gte=today).count(),
        'total_alerts':    SecurityAlert.objects.filter(resolved=False).count(),
        'blocked_ips':     BlockedIP.objects.filter(is_active=True).count(),
        'critical_alerts': SecurityAlert.objects.filter(
            resolved=False, severity__in=['critical', 'high']
        ).count(),
        'errors_5xx': RequestLog.objects.filter(
            timestamp__gte=today, status_code__gte=500
        ).count(),
        'timestamp': now.isoformat(),
    })
