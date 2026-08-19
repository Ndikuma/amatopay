"""Core background tasks."""

import logging
from datetime import timedelta
from django.utils import timezone
from django.contrib.sessions.models import Session
from celery import shared_task

logger = logging.getLogger(__name__)


@shared_task(
    bind=True,
    max_retries=3,
    default_retry_delay=60
)
def cleanup_expired_sessions(self):
    """Remove expired sessions from database."""
    try:
        expired_count = Session.objects.filter(
            expire_date__lt=timezone.now()
        ).delete()[0]
        
        logger.info(f"Cleaned up {expired_count} expired sessions")
        return {'deleted_count': expired_count}
        
    except Exception as exc:
        logger.error(f"Session cleanup failed: {exc}")
        raise self.retry(exc=exc)


@shared_task(
    bind=True,
    max_retries=3
)
def send_batch_notifications(self, notification_ids):
    """Send notifications in batch."""
    from apps.notifications.models import Notification
    
    try:
        notifications = Notification.objects.filter(
            id__in=notification_ids,
            status='pending'
        )
        
        sent_count = 0
        for notification in notifications:
            try:
                notification.send()
                sent_count += 1
            except Exception as e:
                logger.error(f"Failed to send notification {notification.id}: {e}")
        
        logger.info(f"Sent {sent_count}/{len(notification_ids)} notifications")
        return {'sent': sent_count, 'total': len(notification_ids)}
        
    except Exception as exc:
        logger.error(f"Batch notification send failed: {exc}")
        raise self.retry(exc=exc)


@shared_task
def log_task_execution(task_name, status, duration_ms, metadata=None):
    """Log task execution metrics."""
    logger.info(
        f"Task '{task_name}' {status} in {duration_ms}ms",
        extra={
            'task_name': task_name,
            'status': status,
            'duration_ms': duration_ms,
            'metadata': metadata or {}
        }
    )
