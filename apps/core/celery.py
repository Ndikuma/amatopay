"""Celery configuration for asynchronous task processing."""

import os
from celery import Celery
from celery.schedules import crontab
from django.conf import settings

# Set default Django settings
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')

app = Celery('amatopay')

# Load configuration from Django settings
app.config_from_object('django.conf:settings', namespace='CELERY')

# Auto-discover tasks from all installed apps
app.autodiscover_tasks(lambda: settings.INSTALLED_APPS)


# Task routing configuration
app.conf.task_routes = {
    'apps.payments.tasks.*': {'queue': 'payments'},
    'apps.gateway.tasks.*': {'queue': 'gateway'},
    'apps.notifications.tasks.*': {'queue': 'notifications'},
    'apps.compliance.tasks.*': {'queue': 'compliance'},
}

# Task execution time limits
app.conf.task_time_limit = 300  # 5 minutes hard limit
app.conf.task_soft_time_limit = 240  # 4 minutes soft limit

# Task retry configuration
app.conf.task_acks_late = True  # Acknowledge after execution
app.conf.task_reject_on_worker_lost = True  # Requeue on worker crash

# Result backend settings
app.conf.result_expires = 3600  # Results expire after 1 hour
app.conf.result_backend_transport_options = {
    'master_name': 'mymaster',
    'visibility_timeout': 3600,
}

# Periodic task schedule
app.conf.beat_schedule = {
    'check-pending-payments': {
        'task': 'apps.payments.tasks.check_pending_payments',
        'schedule': crontab(minute='*/5'),  # Every 5 minutes
    },
    'cleanup-expired-sessions': {
        'task': 'apps.core.tasks.cleanup_expired_sessions',
        'schedule': crontab(hour='*/4', minute=0),  # Every 4 hours
    },
    'sync-cecf-status': {
        'task': 'apps.gateway.tasks.sync_cecf_transaction_status',
        'schedule': crontab(minute='*/10'),  # Every 10 minutes
    },
    'generate-daily-reports': {
        'task': 'apps.reports.tasks.generate_daily_settlement_report',
        'schedule': crontab(hour=1, minute=0),  # 1 AM daily
    },
    'health-check-external-services': {
        'task': 'apps.gateway.tasks.health_check_cecf',
        'schedule': crontab(minute='*/2'),  # Every 2 minutes
    },
}


@app.task(bind=True, ignore_result=True)
def debug_task(self):
    """Debug task for testing Celery configuration."""
    print(f'Request: {self.request!r}')
