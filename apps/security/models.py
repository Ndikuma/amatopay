from django.db import models
from django.utils import timezone


class RequestLog(models.Model):
    timestamp      = models.DateTimeField(auto_now_add=True, db_index=True)
    ip_address     = models.GenericIPAddressField(db_index=True)
    method         = models.CharField(max_length=10)
    path           = models.CharField(max_length=2000)
    query_string   = models.CharField(max_length=2000, blank=True)
    status_code    = models.SmallIntegerField(db_index=True)
    response_ms    = models.PositiveIntegerField(default=0)
    user_agent     = models.CharField(max_length=500, blank=True)
    referer        = models.CharField(max_length=500, blank=True)
    is_api         = models.BooleanField(default=False, db_index=True)
    merchant_id    = models.CharField(max_length=100, blank=True)
    country_code   = models.CharField(max_length=2, blank=True)

    class Meta:
        db_table = 'sec_request_log'
        ordering = ['-timestamp']
        indexes = [
            models.Index(fields=['ip_address', 'timestamp']),
            models.Index(fields=['status_code', 'timestamp']),
        ]

    def __str__(self):
        return f"{self.method} {self.path} [{self.status_code}] {self.ip_address}"

    @property
    def status_class(self):
        if self.status_code < 300:
            return 'ok'
        if self.status_code < 400:
            return 'redirect'
        if self.status_code < 500:
            return 'client_err'
        return 'server_err'

    @property
    def is_slow(self):
        return self.response_ms > 2000


class SecurityAlert(models.Model):
    SEV_INFO     = 'info'
    SEV_LOW      = 'low'
    SEV_MEDIUM   = 'medium'
    SEV_HIGH     = 'high'
    SEV_CRITICAL = 'critical'
    SEV_CHOICES = [
        (SEV_INFO,     'Info'),
        (SEV_LOW,      'Low'),
        (SEV_MEDIUM,   'Medium'),
        (SEV_HIGH,     'High'),
        (SEV_CRITICAL, 'Critical'),
    ]
    SEV_ORDER = {SEV_INFO: 0, SEV_LOW: 1, SEV_MEDIUM: 2, SEV_HIGH: 3, SEV_CRITICAL: 4}

    TYPE_BRUTE_FORCE    = 'brute_force'
    TYPE_RATE_LIMIT     = 'rate_limit'
    TYPE_SCANNING       = 'scanning'
    TYPE_INJECTION      = 'injection'
    TYPE_PARAM_POLLUTION = 'param_pollution'
    TYPE_HEADER_INJECTION = 'header_injection'
    TYPE_LARGE_PAYLOAD  = 'large_payload'
    TYPE_SUSPICIOUS_METHOD = 'suspicious_method'
    TYPE_PATH_TRAVERSAL = 'path_traversal'
    TYPE_SUSPICIOUS_UA  = 'suspicious_ua'
    TYPE_BLOCKED_ATTEMPT = 'blocked_attempt'
    TYPE_ADMIN_PROBE    = 'admin_probe'
    TYPE_CHOICES = [
        (TYPE_BRUTE_FORCE,     'Brute Force'),
        (TYPE_RATE_LIMIT,      'Rate Limit'),
        (TYPE_SCANNING,        'Scanning'),
        (TYPE_INJECTION,       'Injection Attempt'),
        (TYPE_PARAM_POLLUTION, 'Parameter Pollution'),
        (TYPE_HEADER_INJECTION, 'Header Injection'),
        (TYPE_LARGE_PAYLOAD,   'Large Payload'),
        (TYPE_SUSPICIOUS_METHOD, 'Suspicious Method'),
        (TYPE_PATH_TRAVERSAL,  'Path Traversal'),
        (TYPE_SUSPICIOUS_UA,   'Suspicious User-Agent'),
        (TYPE_BLOCKED_ATTEMPT, 'Blocked IP Attempt'),
        (TYPE_ADMIN_PROBE,     'Admin Probe'),
    ]

    timestamp   = models.DateTimeField(auto_now_add=True, db_index=True)
    severity    = models.CharField(max_length=10, choices=SEV_CHOICES, db_index=True)
    alert_type  = models.CharField(max_length=30, choices=TYPE_CHOICES, db_index=True)
    ip_address  = models.GenericIPAddressField(db_index=True)
    path        = models.CharField(max_length=2000)
    detail      = models.TextField()
    resolved    = models.BooleanField(default=False, db_index=True)
    resolved_at = models.DateTimeField(null=True, blank=True)
    resolved_by = models.CharField(max_length=100, blank=True)
    request_log = models.ForeignKey(
        RequestLog, null=True, blank=True, on_delete=models.SET_NULL, related_name='alerts'
    )

    class Meta:
        db_table = 'sec_alert'
        ordering = ['-timestamp']
        indexes = [
            models.Index(fields=['resolved', 'severity']),
            models.Index(fields=['ip_address', 'timestamp']),
        ]

    def __str__(self):
        return f"[{self.severity.upper()}] {self.alert_type} from {self.ip_address}"

    def resolve(self, by='admin'):
        self.resolved    = True
        self.resolved_at = timezone.now()
        self.resolved_by = by
        self.save(update_fields=['resolved', 'resolved_at', 'resolved_by'])


class BlockedIP(models.Model):
    ip_address = models.GenericIPAddressField(unique=True, db_index=True)
    reason     = models.CharField(max_length=500)
    blocked_at = models.DateTimeField(auto_now_add=True)
    blocked_by = models.CharField(max_length=100, default='system')
    expires_at = models.DateTimeField(null=True, blank=True)
    is_active  = models.BooleanField(default=True, db_index=True)

    class Meta:
        db_table = 'sec_blocked_ip'
        ordering = ['-blocked_at']

    def __str__(self):
        return f"{self.ip_address} ({'active' if self.is_active else 'inactive'})"

    @property
    def is_expired(self):
        if not self.expires_at:
            return False
        return timezone.now() > self.expires_at
