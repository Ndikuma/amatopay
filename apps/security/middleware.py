"""
SecurityTrackingMiddleware — logs every HTTP request and runs detection rules.

Placed AFTER SessionMiddleware and AuthenticationMiddleware so we have access
to request.user and session data for enrichment.
"""
import logging
import random
import time
from datetime import timedelta
from pathlib import Path

from django.conf import settings
from django.core.cache import cache
from django.http import JsonResponse
from django.shortcuts import render
from django.utils import timezone
import yaml

logger = logging.getLogger('amatopay.security')

_DEFAULT_CONFIG = {
    'skip': (
        '/static/',
        '/media/',
        '/favicon.',
        '/robots.txt',
        '/security/dashboard/',
        '/security/live-stats/',
        '/admin/jsi18n/',
    ),
    'circuit': (
        '/api/v1/checkout/',
        '/api/v1/payments/',
        '/api/v1/settlements/',
        '/pay/',
    ),
    'circuit_options': {
        'failure_threshold': 10,
        'failure_window_seconds': 60,
        'open_seconds': 60,
        'half_open_seconds': 30,
    },
    'rate': {
        'default': 120,
        '/security/login/': 10,
        '/account/sign-in/': 10,
        '/dashboard/': 120,
        '/api/v1/checkout/': 60,
        '/api/v1/payments/': 80,
        '/pay/': 80,
    },
    'block': {
        'default': 300,
        'auth': 600,
        'payment': 900,
    },
}


class SecurityTrackingMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response
        self.config = _load_endpoint_config()

    def __call__(self, request):
        # Fast-path: skip uninteresting paths
        if _matches_prefix(request.path, self.config['skip']):
            return self.get_response(request)

        ip = _get_ip(request)

        # ── Block check (before processing) ───────────────────────────────────
        blocked_ip = _get_blocked_ip(ip)
        if blocked_ip:
            from django.shortcuts import render
            _record_blocked_attempt(ip, request.path)
            return render(
                request,
                'security/blocked_ip.html',
                {
                    'ip_address': ip,
                    'path': request.path,
                    'blocked_ip': blocked_ip,
                },
                status=403,
            )

        # ── Process the request ────────────────────────────────────────────────
        start = time.monotonic()
        response = self.get_response(request)
        elapsed_ms = int((time.monotonic() - start) * 1000)

        # ── Log & detect (after response — never delays the client) ───────────
        try:
            log = _log_request(request, response, ip, elapsed_ms)
            if log is not None:
                from .detectors import run_detectors
                run_detectors(request, response, log)
        except Exception as exc:
            # Never let logging/detection break the actual response
            logger.error("SecurityTrackingMiddleware error (non-fatal): %s", exc)

        return response


class CircuitBreakerMiddleware:
    """Temporarily closes noisy payment endpoints when repeated 5xx responses appear."""

    def __init__(self, get_response):
        self.get_response = get_response
        self.config = _load_endpoint_config()
        options = self.config['circuit_options']
        self.failure_threshold = options['failure_threshold']
        self.failure_window_seconds = options['failure_window_seconds']
        self.open_seconds = options['open_seconds']
        self.half_open_seconds = options['half_open_seconds']

    def __call__(self, request):
        endpoint = self._endpoint_for(request.path)
        if endpoint:
            circuit_key = f"security:circuit:{endpoint}"
            state = cache.get(circuit_key, 'closed')
            if state == 'open':
                opened_at = float(cache.get(f"{circuit_key}:opened_at", time.time()))
                retry_after = max(0, int(self.open_seconds - (time.time() - opened_at)))
                if retry_after > 0:
                    return _security_error_response(
                        request,
                        status=503,
                        template='503.html',
                        payload={
                            'error': 'service_temporarily_unavailable',
                            'message': 'This payment endpoint is temporarily protected by the AmatoPay circuit breaker.',
                            'retry_after': retry_after,
                        },
                        headers={'Retry-After': str(retry_after)},
                    )
                cache.set(circuit_key, 'half-open', timeout=self.half_open_seconds)

        response = self.get_response(request)

        if endpoint:
            self._record_result(endpoint, response.status_code)
        return response

    def _endpoint_for(self, path):
        for endpoint in self.config['circuit']:
            if path.startswith(endpoint):
                return endpoint.strip('/').replace('/', ':')
        return ''

    def _record_result(self, endpoint, status_code):
        circuit_key = f"security:circuit:{endpoint}"
        state = cache.get(circuit_key, 'closed')
        if status_code >= 500:
            failure_key = f"{circuit_key}:failures"
            failures = _cache_incr(failure_key, timeout=self.failure_window_seconds)
            if failures >= self.failure_threshold:
                cache.set(circuit_key, 'open', timeout=self.open_seconds)
                cache.set(f"{circuit_key}:opened_at", time.time(), timeout=self.open_seconds)
            return

        if state == 'half-open':
            cache.set(circuit_key, 'closed', timeout=self.open_seconds)
        cache.delete(f"{circuit_key}:failures")


class RateLimitMiddleware:
    """IP-based request limit before the view runs."""

    def __init__(self, get_response):
        self.get_response = get_response
        self.config = _load_endpoint_config()

    def __call__(self, request):
        if _matches_prefix(request.path, self.config['skip']):
            return self.get_response(request)

        ip = _get_ip(request)
        blocked_ttl = self._blocked_ttl(ip)
        if blocked_ttl > 0:
            return self._rate_limit_response(request, blocked_ttl)

        limit = self._limit_for(request.path)
        endpoint = self._endpoint_key(request.path)
        count = _cache_incr(f"security:rate:{ip}:{endpoint}", timeout=60)
        if count > limit:
            duration = self._block_seconds(request.path)
            self._block_ip(ip, duration, request.path, limit)
            return self._rate_limit_response(request, duration, limit=limit)

        return self.get_response(request)

    def _limit_for(self, path):
        for prefix, limit in self.config['rate'].items():
            if prefix != 'default' and path.startswith(prefix):
                return limit
        return self.config['rate']['default']

    def _endpoint_key(self, path):
        for prefix in self.config['rate']:
            if prefix != 'default' and path.startswith(prefix):
                return prefix.strip('/').replace('/', ':') or 'root'
        return 'default'

    def _block_seconds(self, path):
        if path.startswith('/security/login/') or '/auth/' in path:
            return self.config['block']['auth']
        if path.startswith('/api/v1/') or '/payment' in path or '/sessions' in path:
            return self.config['block']['payment']
        return self.config['block']['default']

    def _blocked_ttl(self, ip):
        blocked_until = cache.get(f"security:rate:block:{ip}")
        if not blocked_until:
            return 0
        return max(0, int(float(blocked_until) - time.time()))

    def _block_ip(self, ip, duration, path, limit):
        cache.set(f"security:rate:block:{ip}", time.time() + duration, timeout=duration)
        try:
            from .models import BlockedIP, SecurityAlert
            expires_at = timezone.now() + timedelta(seconds=duration)
            BlockedIP.objects.update_or_create(
                ip_address=ip,
                defaults={
                    'reason': f"Rate limit exceeded on {path} ({limit}/min)",
                    'blocked_by': 'rate-limit',
                    'expires_at': expires_at,
                    'is_active': True,
                },
            )
            SecurityAlert.objects.create(
                severity='medium',
                alert_type='rate_limit',
                ip_address=ip,
                path=path[:2000],
                detail=f"IP {ip} exceeded {limit} requests/min on {path}; temporary block for {duration}s.",
            )
        except Exception as exc:
            logger.error("Rate limit block recording failed: %s", exc)

    def _rate_limit_response(self, request, retry_after, limit=None):
        payload = {
            'error': 'rate_limit_exceeded',
            'message': 'Too many requests. Please try again later.',
            'retry_after': retry_after,
        }
        if limit:
            payload['limit_per_minute'] = limit
        return _security_error_response(
            request,
            status=429,
            template='429.html',
            payload=payload,
            headers={'Retry-After': str(retry_after)},
        )


class AuthenticatedRateLimitMiddleware:
    """Higher per-user limits after Django authentication has populated request.user."""

    USER_TIER_LIMITS = {
        'free': 120,
        'premium': 600,
        'enterprise': 2400,
        'internal': 10000,
    }

    def __init__(self, get_response):
        self.get_response = get_response
        self.config = _load_endpoint_config()

    def __call__(self, request):
        user = getattr(request, 'user', None)
        if not getattr(user, 'is_authenticated', False):
            return self.get_response(request)
        if _matches_prefix(request.path, self.config['skip']):
            return self.get_response(request)

        tier = getattr(user, 'tier', 'free') or 'free'
        limit = self.USER_TIER_LIMITS.get(tier, self.USER_TIER_LIMITS['free'])
        count = _cache_incr(f"security:user-rate:{user.pk}", timeout=60)
        if count > limit:
            return _security_error_response(
                request,
                status=429,
                template='429.html',
                payload={
                    'error': 'user_rate_limit_exceeded',
                    'message': 'Your authenticated request limit has been exceeded.',
                    'limit_per_minute': limit,
                    'tier': tier,
                    'retry_after': 60,
                },
                headers={'Retry-After': '60'},
            )
        return self.get_response(request)


class RequestThrottlingMiddleware:
    """Adds a small delay for clients that recently received 403/429 responses."""

    MAX_DELAY_SECONDS = 1.5

    def __init__(self, get_response):
        self.get_response = get_response
        self.config = _load_endpoint_config()

    def __call__(self, request):
        if not _matches_prefix(request.path, self.config['skip']):
            level = int(cache.get(f"security:throttle:{_get_ip(request)}", 0) or 0)
            if level > 0:
                time.sleep(self._delay_for(level))

        response = self.get_response(request)
        self._record_response(request, response)
        return response

    def _record_response(self, request, response):
        if _matches_prefix(request.path, self.config['skip']):
            return
        key = f"security:throttle:{_get_ip(request)}"
        level = int(cache.get(key, 0) or 0)
        if response.status_code in (403, 429):
            cache.set(key, min(level + 1, 8), timeout=300)
        elif response.status_code < 300 and level > 0:
            if level == 1:
                cache.delete(key)
            else:
                cache.set(key, level - 1, timeout=300)

    def _delay_for(self, level):
        delay = min(0.08 * (2 ** level), self.MAX_DELAY_SECONDS)
        return delay * random.uniform(0.8, 1.2)


# ── Helpers ────────────────────────────────────────────────────────────────────

def _get_ip(request) -> str:
    x_fwd = request.META.get('HTTP_X_FORWARDED_FOR', '')
    if x_fwd:
        return x_fwd.split(',')[0].strip()
    return request.META.get('REMOTE_ADDR', '0.0.0.0')


def _get_blocked_ip(ip: str):
    from django.utils import timezone
    from .models import BlockedIP
    return BlockedIP.objects.filter(
        ip_address=ip,
        is_active=True,
    ).filter(
        # Not expired (expires_at is null → permanent, or future)
        expires_at__isnull=True,
    ).first() or BlockedIP.objects.filter(
        ip_address=ip,
        is_active=True,
        expires_at__gt=timezone.now(),
    ).first()


def _log_request(request, response, ip: str, elapsed_ms: int):
    from .models import RequestLog
    merchant_id = ''
    try:
        if hasattr(request, 'user') and hasattr(request.user, 'merchant_id'):
            merchant_id = str(request.user.merchant_id)
    except Exception:
        pass

    return RequestLog.objects.create(
        ip_address=ip,
        method=request.method,
        path=request.path[:2000],
        query_string=(request.META.get('QUERY_STRING', '') or '')[:2000],
        status_code=response.status_code,
        response_ms=elapsed_ms,
        user_agent=(request.META.get('HTTP_USER_AGENT', '') or '')[:500],
        referer=(request.META.get('HTTP_REFERER', '') or '')[:500],
        is_api=request.path.startswith('/api/v1/'),
        merchant_id=merchant_id[:100],
    )


def _record_blocked_attempt(ip: str, path: str):
    try:
        from .models import SecurityAlert
        SecurityAlert.objects.create(
            severity='high',
            alert_type='blocked_attempt',
            ip_address=ip,
            path=path[:2000],
            detail=f"Request from blocked IP {ip} was denied at {path}",
        )
    except Exception:
        pass


def _cache_incr(key, timeout=60):
    try:
        return cache.incr(key)
    except ValueError:
        cache.set(key, 1, timeout=timeout)
        return 1


def _matches_prefix(path, prefixes):
    return any(path.startswith(prefix) for prefix in prefixes)


def _load_endpoint_config():
    config = {
        'skip': list(_DEFAULT_CONFIG['skip']),
        'circuit': list(_DEFAULT_CONFIG['circuit']),
        'circuit_options': dict(_DEFAULT_CONFIG['circuit_options']),
        'rate': dict(_DEFAULT_CONFIG['rate']),
        'block': dict(_DEFAULT_CONFIG['block']),
    }
    path = getattr(settings, 'SECURITY_ENDPOINTS_FILE', None)
    if path is None:
        path = Path(__file__).resolve().parent / 'endpoints.yaml'
    else:
        path = Path(path)

    try:
        data = yaml.safe_load(path.read_text(encoding='utf-8')) or {}
    except OSError as exc:
        logger.warning("Security endpoint config not loaded from %s: %s", path, exc)
        return config
    except yaml.YAMLError as exc:
        logger.warning("Security endpoint YAML is invalid in %s: %s", path, exc)
        return config

    skip = data.get('skip')
    if isinstance(skip, list):
        config['skip'] = _clean_prefix_list(skip) or config['skip']

    circuit = data.get('circuit') or {}
    if isinstance(circuit, dict):
        endpoints = circuit.get('endpoints')
        if isinstance(endpoints, list):
            config['circuit'] = _clean_prefix_list(endpoints) or config['circuit']
        for key in ('failure_threshold', 'failure_window_seconds', 'open_seconds', 'half_open_seconds'):
            value = _positive_int(circuit.get(key))
            if value:
                config['circuit_options'][key] = value
    elif isinstance(circuit, list):
        config['circuit'] = _clean_prefix_list(circuit) or config['circuit']

    rate_limits = data.get('rate_limits') or {}
    if isinstance(rate_limits, dict):
        default_limit = _positive_int(rate_limits.get('default'))
        if default_limit:
            config['rate']['default'] = default_limit
        endpoints = rate_limits.get('endpoints') or {}
        if isinstance(endpoints, dict):
            for prefix, limit in endpoints.items():
                limit = _positive_int(limit)
                prefix = str(prefix).strip()
                if prefix and limit:
                    config['rate'][prefix] = limit

    block_durations = data.get('block_durations') or {}
    if isinstance(block_durations, dict):
        for name, seconds in block_durations.items():
            seconds = _positive_int(seconds)
            name = str(name).strip()
            if name and seconds:
                config['block'][name] = seconds

    if 'default' not in config['rate']:
        config['rate']['default'] = _DEFAULT_CONFIG['rate']['default']
    for key, value in _DEFAULT_CONFIG['block'].items():
        config['block'].setdefault(key, value)
    for key, value in _DEFAULT_CONFIG['circuit_options'].items():
        config['circuit_options'].setdefault(key, value)
    return config


def _clean_prefix_list(values):
    prefixes = []
    for value in values:
        prefix = str(value).strip()
        if prefix:
            prefixes.append(prefix)
    return prefixes


def _positive_int(value):
    try:
        value = int(value)
    except (TypeError, ValueError):
        return None
    return value if value > 0 else None


def _security_error_response(request, status, template, payload, headers=None):
    headers = headers or {}
    if _wants_json(request):
        response = JsonResponse(payload, status=status)
    else:
        context = {
            'retry_after': payload.get('retry_after'),
            'limit_per_minute': payload.get('limit_per_minute'),
        }
        response = render(request, template, context=context, status=status)
    for key, value in headers.items():
        response[key] = value
    return response


def _wants_json(request):
    if request is None:
        return True
    if request.path.startswith('/api/'):
        return True
    accept = request.META.get('HTTP_ACCEPT', '')
    content_type = request.META.get('CONTENT_TYPE', '')
    return 'application/json' in accept or content_type.startswith('application/json')
