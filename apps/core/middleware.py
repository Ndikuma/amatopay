"""Custom middleware for request/response processing."""

import time
import logging
from django.utils.deprecation import MiddlewareMixin
from django.http import JsonResponse
from django.conf import settings

logger = logging.getLogger(__name__)


class RequestLoggingMiddleware(MiddlewareMixin):
    """Log request details and timing."""
    
    def process_request(self, request):
        """Mark request start time."""
        request._start_time = time.time()
        
    def process_response(self, request, response):
        """Log request completion."""
        if hasattr(request, '_start_time'):
            duration = (time.time() - request._start_time) * 1000
            
            logger.info(
                f"{request.method} {request.path} - {response.status_code}",
                extra={
                    'method': request.method,
                    'path': request.path,
                    'status': response.status_code,
                    'duration_ms': round(duration, 2),
                    'user': str(request.user) if hasattr(request, 'user') else 'Anonymous'
                }
            )
        
        return response


class SecurityHeadersMiddleware(MiddlewareMixin):
    """Add security headers to responses."""
    
    def process_response(self, request, response):
        """Add security headers."""
        if not settings.DEBUG:
            response['X-Content-Type-Options'] = 'nosniff'
            response['X-Frame-Options'] = 'DENY'
            response['X-XSS-Protection'] = '1; mode=block'
            response['Strict-Transport-Security'] = 'max-age=31536000; includeSubDomains'
        
        return response


class APIVersionMiddleware(MiddlewareMixin):
    """Handle API versioning."""
    
    def process_request(self, request):
        """Extract and validate API version."""
        if request.path.startswith('/api/'):
            # Get version from URL or header
            api_version = request.headers.get('API-Version', 'v1')
            request.api_version = api_version


class RateLimitMiddleware(MiddlewareMixin):
    """Basic rate limiting (use django-ratelimit for production)."""
    
    def process_request(self, request):
        """Check rate limits."""
        # Placeholder - implement with django-ratelimit or Redis
        pass


class ExceptionHandlingMiddleware(MiddlewareMixin):
    """Global exception handler for API requests."""
    
    def process_exception(self, request, exception):
        """Handle unhandled exceptions for API."""
        if request.path.startswith('/api/'):
            logger.error(
                f"Unhandled exception in API: {exception}",
                exc_info=True,
                extra={
                    'path': request.path,
                    'method': request.method,
                    'user': str(request.user) if hasattr(request, 'user') else 'Anonymous'
                }
            )
            
            if settings.DEBUG:
                return JsonResponse({
                    'error': 'Internal server error',
                    'detail': str(exception),
                    'type': type(exception).__name__
                }, status=500)
            
            return JsonResponse({
                'error': 'Internal server error',
                'message': 'An unexpected error occurred'
            }, status=500)
        
        return None


class CORSMiddleware(MiddlewareMixin):
    """Handle CORS for API requests."""
    
    def process_response(self, request, response):
        """Add CORS headers."""
        if request.path.startswith('/api/'):
            allowed_origins = getattr(settings, 'CORS_ALLOWED_ORIGINS', [])
            
            if allowed_origins:
                origin = request.headers.get('Origin')
                if origin in allowed_origins:
                    response['Access-Control-Allow-Origin'] = origin
                    response['Access-Control-Allow-Methods'] = 'GET, POST, PUT, PATCH, DELETE, OPTIONS'
                    response['Access-Control-Allow-Headers'] = 'Content-Type, Authorization'
                    response['Access-Control-Max-Age'] = '3600'
        
        return response
