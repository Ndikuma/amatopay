"""Core application views."""

from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from django.conf import settings

from .health import health_checker
from apps.gateway.circuit_breaker import (
    cecf_payment_breaker,
    cecf_verification_breaker
)


@api_view(['GET'])
@permission_classes([AllowAny])
def health_check(request):
    """
    Comprehensive health check endpoint.
    Returns overall system health and component status.
    """
    # Run all health checks
    results = health_checker.run_all()
    overall_status = health_checker.get_overall_status(results)
    
    # Get circuit breaker stats
    circuit_stats = {
        'payment': cecf_payment_breaker.get_stats(),
        'verification': cecf_verification_breaker.get_stats()
    }
    
    response_data = {
        'status': overall_status,
        'timestamp': results[list(results.keys())[0]].timestamp.isoformat(),
        'checks': {name: result.to_dict() for name, result in results.items()},
        'circuit_breakers': circuit_stats,
        'version': getattr(settings, 'APP_VERSION', '1.0.0')
    }
    
    # Return appropriate HTTP status
    if overall_status == 'healthy':
        http_status = status.HTTP_200_OK
    elif overall_status == 'degraded':
        http_status = status.HTTP_200_OK  # Still operational
    else:
        http_status = status.HTTP_503_SERVICE_UNAVAILABLE
    
    return Response(response_data, status=http_status)


@api_view(['GET'])
@permission_classes([AllowAny])
def liveness(request):
    """
    Kubernetes liveness probe endpoint.
    Returns 200 if application is running.
    """
    return Response({'status': 'alive'}, status=status.HTTP_200_OK)


@api_view(['GET'])
@permission_classes([AllowAny])
def readiness(request):
    """
    Kubernetes readiness probe endpoint.
    Returns 200 if application can serve traffic.
    """
    # Quick checks for readiness
    db_check = health_checker.run_check('database')
    cache_check = health_checker.run_check('cache')
    
    if db_check.status == 'healthy' and cache_check.status == 'healthy':
        return Response({'status': 'ready'}, status=status.HTTP_200_OK)
    else:
        return Response(
            {
                'status': 'not_ready',
                'database': db_check.status,
                'cache': cache_check.status
            },
            status=status.HTTP_503_SERVICE_UNAVAILABLE
        )
