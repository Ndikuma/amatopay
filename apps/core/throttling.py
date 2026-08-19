"""Advanced rate limiting and throttling for API endpoints."""

import time
import hashlib
from typing import Optional, Tuple
from django.core.cache import cache
from django.conf import settings
from rest_framework.throttling import BaseThrottle
from rest_framework.request import Request
from rest_framework.views import APIView


class AdaptiveRateLimiter:
    """
    Token bucket algorithm with adaptive rate limiting.
    Automatically reduces limits under high load or suspicious patterns.
    """
    
    def __init__(
        self,
        rate: int,
        period: int,
        burst: Optional[int] = None,
        adaptive: bool = True
    ):
        """
        Args:
            rate: Number of requests allowed per period
            period: Time period in seconds
            burst: Maximum burst size (defaults to rate * 2)
            adaptive: Enable adaptive rate limiting
        """
        self.rate = rate
        self.period = period
        self.burst = burst or (rate * 2)
        self.adaptive = adaptive
        
    def get_cache_key(self, identifier: str, scope: str = 'global') -> str:
        """Generate cache key for rate limit tracking."""
        key_hash = hashlib.sha256(f"{scope}:{identifier}".encode()).hexdigest()[:16]
        return f"ratelimit:{key_hash}"
    
    def is_allowed(
        self,
        identifier: str,
        scope: str = 'global',
        cost: int = 1
    ) -> Tuple[bool, dict]:
        """
        Check if request is allowed under rate limit.
        
        Returns:
            (allowed, info_dict) where info_dict contains:
                - remaining: tokens remaining
                - reset_at: timestamp when limit resets
                - retry_after: seconds to wait if blocked
        """
        cache_key = self.get_cache_key(identifier, scope)
        now = time.time()
        
        # Get current bucket state
        bucket = cache.get(cache_key)
        
        if bucket is None:
            # Initialize new bucket
            bucket = {
                'tokens': self.burst,
                'last_update': now,
                'request_count': 0,
                'blocked_count': 0
            }
        
        # Calculate tokens to add based on time elapsed
        elapsed = now - bucket['last_update']
        tokens_to_add = elapsed * (self.rate / self.period)
        
        bucket['tokens'] = min(
            self.burst,
            bucket['tokens'] + tokens_to_add
        )
        bucket['last_update'] = now
        bucket['request_count'] += 1
        
        # Apply adaptive throttling if enabled
        if self.adaptive and bucket['blocked_count'] > 10:
            # Reduce rate by 50% if frequently blocked
            effective_cost = cost * 2
        else:
            effective_cost = cost
        
        # Check if request can be allowed
        if bucket['tokens'] >= effective_cost:
            bucket['tokens'] -= effective_cost
            allowed = True
            bucket['blocked_count'] = max(0, bucket['blocked_count'] - 1)
        else:
            allowed = False
            bucket['blocked_count'] += 1
        
        # Save bucket state
        cache.set(cache_key, bucket, self.period * 2)
        
        # Calculate metadata
        reset_at = now + (self.period - (elapsed % self.period))
        retry_after = max(
            0,
            (effective_cost - bucket['tokens']) / (self.rate / self.period)
        )
        
        return allowed, {
            'remaining': int(bucket['tokens']),
            'limit': self.burst,
            'reset_at': int(reset_at),
            'retry_after': int(retry_after) if not allowed else 0,
            'request_count': bucket['request_count']
        }


class MerchantAPIThrottle(BaseThrottle):
    """Per-merchant API throttling with tiered limits."""
    
    TIER_LIMITS = {
        'free': (100, 3600),      # 100 req/hour
        'basic': (1000, 3600),    # 1k req/hour
        'premium': (10000, 3600), # 10k req/hour
        'enterprise': (100000, 3600) # 100k req/hour
    }
    
    def allow_request(self, request: Request, view: APIView) -> bool:
        """Check if request is allowed for merchant."""
        merchant = getattr(request, 'merchant', None)
        if not merchant:
            return True  # No merchant = internal call
        
        # Get merchant tier
        tier = getattr(merchant, 'api_tier', 'free')
        rate, period = self.TIER_LIMITS.get(tier, self.TIER_LIMITS['free'])
        
        # Create rate limiter
        limiter = AdaptiveRateLimiter(rate=rate, period=period)
        
        # Check limit
        allowed, info = limiter.is_allowed(
            identifier=str(merchant.id),
            scope='merchant_api'
        )
        
        # Add rate limit headers to response
        request.rate_limit_info = info
        
        if not allowed:
            self.wait = info['retry_after']
            
        return allowed


class IPBasedThrottle(BaseThrottle):
    """IP-based throttling to prevent abuse."""
    
    def allow_request(self, request: Request, view: APIView) -> bool:
        """Check if request from IP is allowed."""
        ip = self.get_ident(request)
        
        # Stricter limits for anonymous IPs
        limiter = AdaptiveRateLimiter(
            rate=1000,    # 1000 requests
            period=3600,  # per hour
            burst=100     # max burst of 100
        )
        
        allowed, info = limiter.is_allowed(
            identifier=ip,
            scope='ip_global'
        )
        
        if not allowed:
            self.wait = info['retry_after']
            
        return allowed


class CECFGatewayThrottle:
    """
    Specialized throttling for CECF gateway calls.
    Prevents overwhelming the external payment gateway.
    """
    
    def __init__(self):
        # Conservative limits for external gateway
        self.limiter = AdaptiveRateLimiter(
            rate=50,      # 50 requests
            period=60,    # per minute
            burst=10,     # max burst of 10
            adaptive=True
        )
    
    def acquire(self, operation: str, cost: int = 1) -> Tuple[bool, int]:
        """
        Acquire permission to call CECF gateway.
        
        Args:
            operation: Operation type (e.g., 'payment', 'verify', 'status')
            cost: Request cost (complex operations cost more)
            
        Returns:
            (allowed, retry_after_seconds)
        """
        allowed, info = self.limiter.is_allowed(
            identifier='cecf_gateway',
            scope=f'gateway_{operation}',
            cost=cost
        )
        
        return allowed, info['retry_after']
    
    def backoff_on_error(self, error_type: str):
        """Implement exponential backoff on gateway errors."""
        cache_key = f"gateway_backoff:{error_type}"
        failures = cache.get(cache_key, 0)
        
        # Exponential backoff: 2^failures seconds (max 300s = 5 min)
        backoff = min(300, 2 ** failures)
        
        cache.set(cache_key, failures + 1, timeout=backoff * 2)
        return backoff
    
    def reset_backoff(self, error_type: str):
        """Reset backoff counter on successful request."""
        cache.delete(f"gateway_backoff:{error_type}")


# Global instances
cecf_throttle = CECFGatewayThrottle()
