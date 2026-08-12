"""
Security detection rules.

Detectors run after the response is generated, so they should stay small,
query-light, and non-fatal. Any detector failure is logged and never breaks
the user request.
"""
import json
import logging
import re
from datetime import timedelta

from django.utils import timezone

logger = logging.getLogger('amatopay.security')


_INJECTION = re.compile(
    r"(union[\s+]+select|drop[\s+]+table|insert[\s+]+into|delete[\s+]+from|"
    r"exec[\s]*\(|xp_cmdshell|sleep\s*\(\d|benchmark\s*\(|"
    r"<script[\s>]|javascript\s*:|on\w+\s*=|"
    r"(\.\./){2,}|%2e%2e%2f|%00)",
    re.IGNORECASE,
)

_PATH_TRAVERSAL = re.compile(r"(\.\./|\.\.\\|%2e%2e[%/\\])", re.IGNORECASE)

_SUSPICIOUS_UA = re.compile(
    r"(sqlmap|nikto|masscan|nmap|burp\s*suite|zgrab|nuclei|"
    r"dirsearch|gobuster|ffuf|wfuzz|hydra|medusa|metasploit|"
    r"python-requests/[0-9]|curl/[0-9]|wget/[0-9]|scrapy/|go-http-client/1)",
    re.IGNORECASE,
)

_ADMIN_PROBE_PATHS = re.compile(
    r"/(wp-admin|phpmyadmin|\.env|\.git|config\.php|"
    r"backup|dump\.sql|debug|console|actuator|api/v[0-9])",
    re.IGNORECASE,
)

_JSON_INJECTION = re.compile(
    r'("\s*:\s*"|\{|\}|\[|\])\s*(union|select|insert|drop|delete)',
    re.IGNORECASE,
)

_PARAM_POLLUTION = re.compile(r'(^|&)([^=&]+)=[^&]*&.*\2=', re.IGNORECASE)

_HEADER_INJECTION = re.compile(
    r'(\r|\n|\x0d|\x0a).*?(content-type|content-length|host|location)',
    re.IGNORECASE,
)


def run_detectors(request, response, log):
    """Run all detection rules. Exceptions are swallowed so they never affect responses."""
    detectors = (
        _detect_injection,
        _detect_path_traversal,
        _detect_suspicious_ua,
        _detect_admin_probe,
        _detect_scanning,
        _detect_brute_force,
        _detect_rate_limit,
        _detect_json_injection,
        _detect_param_pollution,
        _detect_header_injection,
        _detect_large_payload,
        _detect_suspicious_method,
    )
    for detector in detectors:
        try:
            detector(request, response, log)
        except TypeError:
            detector(response, log)
        except Exception as exc:
            logger.exception("Detector %s failed (non-fatal): %s", detector.__name__, exc)


def _detect_injection(request, response, log):
    probe = request.path + '?' + (request.META.get('QUERY_STRING', '') or '')
    if _INJECTION.search(probe):
        return _alert(
            'critical', 'injection',
            log.ip_address, request.path,
            f"Injection pattern in request: {probe[:400]}",
            log,
        )
    return None


def _detect_path_traversal(request, response, log):
    if _PATH_TRAVERSAL.search(request.path):
        return _alert(
            'high', 'path_traversal',
            log.ip_address, request.path,
            f"Path traversal attempt: {request.path[:400]}",
            log,
        )
    return None


def _detect_suspicious_ua(request, response, log):
    ua = request.META.get('HTTP_USER_AGENT', '') or ''
    if _SUSPICIOUS_UA.search(ua):
        return _alert(
            'high', 'suspicious_ua',
            log.ip_address, request.path,
            f"Scanner/tool user-agent: {ua[:300]}",
            log,
        )
    return None


def _detect_admin_probe(request, response, log):
    if response.status_code == 404 and _ADMIN_PROBE_PATHS.search(request.path):
        return _alert(
            'medium', 'admin_probe',
            log.ip_address, request.path,
            f"Admin/config path probe: {request.path}",
            log,
        )
    return None


def _detect_scanning(request, response, log):
    if response.status_code != 404:
        return None
    from .models import RequestLog
    window = timezone.now() - timedelta(minutes=5)
    count = RequestLog.objects.filter(
        ip_address=log.ip_address,
        status_code=404,
        timestamp__gte=window,
    ).count()
    if count in (10, 25, 50, 100):
        return _alert(
            'medium', 'scanning',
            log.ip_address, log.path,
            f"{count} x 404 from {log.ip_address} in last 5 min - possible directory scan.",
            log,
        )
    return None


def _detect_brute_force(request, response, log):
    if response.status_code not in (401, 403) or not log.path.startswith('/api/v1/'):
        return None
    from .models import RequestLog
    window = timezone.now() - timedelta(minutes=10)
    count = RequestLog.objects.filter(
        ip_address=log.ip_address,
        status_code__in=(401, 403),
        is_api=True,
        timestamp__gte=window,
    ).count()
    if count in (5, 15, 30):
        return _alert(
            'critical' if count >= 30 else 'high',
            'brute_force',
            log.ip_address,
            log.path,
            f"{count} auth failures from {log.ip_address} on API in last 10 min.",
            log,
        )
    return None


def _detect_rate_limit(request, response, log):
    from .models import RequestLog
    window = timezone.now() - timedelta(seconds=60)
    count = RequestLog.objects.filter(ip_address=log.ip_address, timestamp__gte=window).count()
    if count in (120, 300, 600):
        return _alert(
            'critical' if count >= 300 else 'medium',
            'rate_limit',
            log.ip_address,
            log.path,
            f"{count} requests/min from {log.ip_address} - possible flood/DoS.",
            log,
        )
    return None


def _detect_json_injection(request, response, log):
    if not (request.content_type or '').startswith('application/json'):
        return None
    try:
        body = json.loads(request.body or b'{}')
    except (TypeError, ValueError, json.JSONDecodeError):
        return None
    body_str = json.dumps(body, ensure_ascii=True)
    if _JSON_INJECTION.search(body_str):
        return _alert(
            'critical', 'injection',
            log.ip_address, request.path,
            f"JSON injection detected: {body_str[:300]}",
            log,
        )
    return None


def _detect_param_pollution(request, response, log):
    query = request.META.get('QUERY_STRING', '') or ''
    if _PARAM_POLLUTION.search(query):
        return _alert(
            'medium', 'param_pollution',
            log.ip_address, request.path,
            f"Parameter pollution attempt: {query[:300]}",
            log,
        )
    return None


def _detect_header_injection(request, response, log):
    header_values = '\n'.join(
        str(value) for key, value in request.META.items()
        if key.startswith('HTTP_') or key in {'CONTENT_TYPE', 'CONTENT_LENGTH'}
    )
    if _HEADER_INJECTION.search(header_values):
        return _alert(
            'high', 'header_injection',
            log.ip_address, request.path,
            "Header injection attempt detected",
            log,
        )
    return None


def _detect_large_payload(request, response, log):
    try:
        size = int(request.META.get('CONTENT_LENGTH') or 0)
    except (TypeError, ValueError):
        return None
    if size > 1024 * 1024:
        return _alert(
            'medium', 'large_payload',
            log.ip_address, request.path,
            f"Large payload: {size} bytes",
            log,
        )
    return None


def _detect_suspicious_method(request, response, log):
    method = request.method.upper()
    if method in {'TRACE', 'TRACK', 'OPTIONS', 'CONNECT'}:
        return _alert(
            'high', 'suspicious_method',
            log.ip_address, request.path,
            f"Suspicious HTTP method: {method}",
            log,
        )
    return None


def _alert(severity, alert_type, ip, path, detail, log=None):
    from .models import SecurityAlert
    alert = SecurityAlert.objects.create(
        severity=severity,
        alert_type=alert_type,
        ip_address=ip,
        path=path[:2000],
        detail=detail,
        request_log=log,
    )
    logger.warning(
        "[SECURITY] [%s] %s from %s - %s",
        severity.upper(), alert_type, ip, detail[:120],
    )
    return alert
