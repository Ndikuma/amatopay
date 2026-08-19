"""Comprehensive health check system for production monitoring."""

import time
import psutil
import logging
from typing import Dict, List, Callable, Optional
from dataclasses import dataclass
from datetime import datetime
from django.core.cache import cache
from django.db import connection
from django.conf import settings
import redis

logger = logging.getLogger(__name__)


@dataclass
class HealthCheckResult:
    """Result of a health check."""
    name: str
    status: str  # 'healthy', 'degraded', 'unhealthy'
    latency_ms: float
    message: Optional[str] = None
    metadata: Optional[dict] = None
    timestamp: Optional[datetime] = None
    
    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = datetime.utcnow()
    
    def to_dict(self) -> dict:
        return {
            'name': self.name,
            'status': self.status,
            'latency_ms': round(self.latency_ms, 2),
            'message': self.message,
            'metadata': self.metadata,
            'timestamp': self.timestamp.isoformat()
        }


class HealthChecker:
    """Orchestrates health checks across system components."""
    
    def __init__(self):
        self.checks: Dict[str, Callable] = {}
        self._register_default_checks()
    
    def _register_default_checks(self):
        """Register built-in health checks."""
        self.register('database', self._check_database)
        self.register('cache', self._check_cache)
        self.register('redis', self._check_redis)
        self.register('disk', self._check_disk_space)
        self.register('memory', self._check_memory)
        self.register('cpu', self._check_cpu)
    
    def register(self, name: str, check_func: Callable):
        """Register a new health check."""
        self.checks[name] = check_func
    
    def run_check(self, name: str) -> HealthCheckResult:
        """Run a specific health check."""
        if name not in self.checks:
            return HealthCheckResult(
                name=name,
                status='unhealthy',
                latency_ms=0,
                message=f"Unknown health check: {name}"
            )
        
        start = time.time()
        try:
            result = self.checks[name]()
            latency_ms = (time.time() - start) * 1000
            
            if isinstance(result, HealthCheckResult):
                result.latency_ms = latency_ms
                return result
            
            return HealthCheckResult(
                name=name,
                status='healthy',
                latency_ms=latency_ms,
                metadata=result if isinstance(result, dict) else None
            )
            
        except Exception as e:
            logger.error(f"Health check '{name}' failed: {e}", exc_info=True)
            return HealthCheckResult(
                name=name,
                status='unhealthy',
                latency_ms=(time.time() - start) * 1000,
                message=str(e)
            )
    
    def run_all(self) -> Dict[str, HealthCheckResult]:
        """Run all registered health checks."""
        results = {}
        for name in self.checks:
            results[name] = self.run_check(name)
        return results
    
    def get_overall_status(self, results: Dict[str, HealthCheckResult]) -> str:
        """Determine overall system health."""
        statuses = [r.status for r in results.values()]
        
        if any(s == 'unhealthy' for s in statuses):
            return 'unhealthy'
        elif any(s == 'degraded' for s in statuses):
            return 'degraded'
        else:
            return 'healthy'
    
    # Built-in health checks
    
    def _check_database(self) -> HealthCheckResult:
        """Check database connectivity and performance."""
        try:
            with connection.cursor() as cursor:
                cursor.execute("SELECT 1")
                cursor.fetchone()
            
            # Check connection pool
            db_settings = settings.DATABASES['default']
            max_conns = db_settings.get('CONN_MAX_AGE', 0)
            
            return HealthCheckResult(
                name='database',
                status='healthy',
                latency_ms=0,  # Will be set by run_check
                metadata={
                    'engine': db_settings['ENGINE'],
                    'conn_max_age': max_conns
                }
            )
            
        except Exception as e:
            return HealthCheckResult(
                name='database',
                status='unhealthy',
                latency_ms=0,
                message=f"Database connection failed: {e}"
            )
    
    def _check_cache(self) -> HealthCheckResult:
        """Check cache system health."""
        try:
            test_key = '__health_check__'
            test_value = str(time.time())
            
            cache.set(test_key, test_value, 10)
            retrieved = cache.get(test_key)
            cache.delete(test_key)
            
            if retrieved != test_value:
                raise ValueError("Cache read/write mismatch")
            
            return HealthCheckResult(
                name='cache',
                status='healthy',
                latency_ms=0,
                metadata={'backend': settings.CACHES['default']['BACKEND']}
            )
            
        except Exception as e:
            return HealthCheckResult(
                name='cache',
                status='unhealthy',
                latency_ms=0,
                message=f"Cache check failed: {e}"
            )
    
    def _check_redis(self) -> HealthCheckResult:
        """Check Redis connectivity."""
        try:
            import redis
            r = redis.from_url(settings.CELERY_BROKER_URL)
            r.ping()
            
            info = r.info('stats')
            
            return HealthCheckResult(
                name='redis',
                status='healthy',
                latency_ms=0,
                metadata={
                    'total_connections': info.get('total_connections_received'),
                    'connected_clients': info.get('connected_clients')
                }
            )
            
        except Exception as e:
            return HealthCheckResult(
                name='redis',
                status='degraded',  # Not critical if Celery is down
                latency_ms=0,
                message=f"Redis check failed: {e}"
            )
    
    def _check_disk_space(self) -> HealthCheckResult:
        """Check available disk space."""
        try:
            usage = psutil.disk_usage('/')
            percent_used = usage.percent
            
            if percent_used > 90:
                status = 'unhealthy'
                message = f"Disk usage critical: {percent_used}%"
            elif percent_used > 80:
                status = 'degraded'
                message = f"Disk usage high: {percent_used}%"
            else:
                status = 'healthy'
                message = None
            
            return HealthCheckResult(
                name='disk',
                status=status,
                latency_ms=0,
                message=message,
                metadata={
                    'total_gb': round(usage.total / (1024**3), 2),
                    'used_gb': round(usage.used / (1024**3), 2),
                    'free_gb': round(usage.free / (1024**3), 2),
                    'percent': percent_used
                }
            )
            
        except Exception as e:
            return HealthCheckResult(
                name='disk',
                status='unhealthy',
                latency_ms=0,
                message=f"Disk check failed: {e}"
            )
    
    def _check_memory(self) -> HealthCheckResult:
        """Check memory usage."""
        try:
            mem = psutil.virtual_memory()
            percent_used = mem.percent
            
            if percent_used > 90:
                status = 'unhealthy'
                message = f"Memory usage critical: {percent_used}%"
            elif percent_used > 80:
                status = 'degraded'
                message = f"Memory usage high: {percent_used}%"
            else:
                status = 'healthy'
                message = None
            
            return HealthCheckResult(
                name='memory',
                status=status,
                latency_ms=0,
                message=message,
                metadata={
                    'total_gb': round(mem.total / (1024**3), 2),
                    'available_gb': round(mem.available / (1024**3), 2),
                    'percent': percent_used
                }
            )
            
        except Exception as e:
            return HealthCheckResult(
                name='memory',
                status='unhealthy',
                latency_ms=0,
                message=f"Memory check failed: {e}"
            )
    
    def _check_cpu(self) -> HealthCheckResult:
        """Check CPU usage."""
        try:
            cpu_percent = psutil.cpu_percent(interval=1)
            
            if cpu_percent > 90:
                status = 'degraded'
                message = f"CPU usage high: {cpu_percent}%"
            else:
                status = 'healthy'
                message = None
            
            return HealthCheckResult(
                name='cpu',
                status=status,
                latency_ms=0,
                message=message,
                metadata={
                    'percent': cpu_percent,
                    'cores': psutil.cpu_count()
                }
            )
            
        except Exception as e:
            return HealthCheckResult(
                name='cpu',
                status='unhealthy',
                latency_ms=0,
                message=f"CPU check failed: {e}"
            )


# Global health checker instance
health_checker = HealthChecker()
