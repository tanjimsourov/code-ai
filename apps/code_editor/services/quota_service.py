import time
from typing import Dict, Any, Optional
from django.core.cache import cache
from django.utils import timezone
from django.db import transaction
from django.core.exceptions import ObjectDoesNotExist
from ..models import CodeEditorApiKey, CodeEditorRequestLog
from ..exceptions import QuotaExceededException, RateLimitExceededException, InvalidRequestException


class QuotaService:
    """Service for managing quotas and rate limits with Redis atomicity"""
    
    @staticmethod
    def check_rate_limit_atomic(api_key: CodeEditorApiKey) -> bool:
        """Check if API key is within rate limit using atomic Redis operations"""
        cache_key = f"code_editor_rate_limit:{api_key.id}"
        current_time = int(time.time())
        window_start = current_time - 60  # 1 minute window
        
        # Use Redis Lua script for atomic increment and check
        lua_script = """
        local current = redis.call('get', KEYS[1])
        local timestamp = redis.call('get', KEYS[2])
        local window_start = tonumber(ARGV[1])
        
        if current and timestamp and tonumber(timestamp) >= window_start then
            -- Same window, check current count
            if tonumber(current) >= tonumber(ARGV[2]) then
                return {0, tonumber(current)}
            else
                -- Increment count
                local new_count = tonumber(current) + 1
                redis.call('setex', KEYS[1], 60, tostring(new_count))
                redis.call('setex', KEYS[2], 60, tostring(ARGV[3]))
                return {1, new_count}
            end
        else
            -- New window or expired, reset counters
            redis.call('setex', KEYS[1], 60, '1')
            redis.call('setex', KEYS[2], 60, tostring(ARGV[3]))
            return {1, 1}
        end
        """
        
        try:
            # Try to use Redis pipeline for atomicity
            with cache.client.pipeline() as pipe:
                results = pipe.eval(
                    lua_script,
                    2,
                    [cache_key, f"{cache_key}:timestamp"],
                    [str(window_start), str(api_key.rpm_limit), str(current_time)]
                )
                pipe.execute()
            
            can_proceed, current_count = results[0] if results else (True, 0)
            return can_proceed
            
        except Exception:
            # Fallback to non-atomic check
            return QuotaService._check_rate_limit_fallback(api_key)
    
    @staticmethod
    def _check_rate_limit_fallback(api_key: CodeEditorApiKey) -> bool:
        """Fallback non-atomic rate limit check"""
        cache_key = f"code_editor_rate_limit:{api_key.id}"
        current_count = cache.get(cache_key, 0)
        return current_count < api_key.rpm_limit
    
    @staticmethod
    def increment_rate_limit_atomic(api_key: CodeEditorApiKey) -> int:
        """Atomically increment rate limit counter"""
        cache_key = f"code_editor_rate_limit:{api_key.id}"
        timestamp_key = f"{cache_key}:timestamp"
        current_time = int(time.time())
        
        try:
            with cache.client.pipeline() as pipe:
                # Increment counter atomically
                pipe.incr(cache_key)
                # Set expiration if not exists
                pipe.expire(cache_key, 60)
                # Update timestamp
                pipe.setex(timestamp_key, 60, str(current_time))
                results = pipe.execute()
                
                return results[0] if results else 1
                
        except Exception:
            # Fallback
            new_count = cache.incr(cache_key)
            cache.set(cache_key, new_count, 60)
            cache.set(timestamp_key, str(current_time), 60)
            return new_count
    
    @staticmethod
    def check_daily_quota_atomic(api_key: CodeEditorApiKey) -> bool:
        """Check if API key is within daily quota using atomic operations"""
        today = timezone.now().strftime("%Y-%m-%d")
        cache_key = f"code_editor_quota:{api_key.id}:{today}"
        
        try:
            with cache.client.pipeline() as pipe:
                # Get current count
                current_count = pipe.get(cache_key)
                # Set with expiration if not exists
                pipe.expire(cache_key, 86400)  # 24 hours
                results = pipe.execute()
                
                current_count = int(results[0] or 0)
                return current_count < api_key.daily_quota
                
        except Exception:
            # Fallback
            current_count = cache.get(cache_key, 0)
            return current_count < api_key.daily_quota
    
    @staticmethod
    def increment_daily_quota_atomic(api_key: CodeEditorApiKey) -> int:
        """Atomically increment daily quota counter"""
        today = timezone.now().strftime("%Y-%m-%d")
        cache_key = f"code_editor_quota:{api_key.id}:{today}"
        
        try:
            with cache.client.pipeline() as pipe:
                # Increment atomically
                new_count = pipe.incr(cache_key)
                # Set expiration
                pipe.expire(cache_key, 86400)  # 24 hours
                results = pipe.execute()
                
                return results[0] if results else 1
                
        except Exception:
            # Fallback
            new_count = cache.incr(cache_key)
            cache.set(cache_key, new_count, 86400)
            return new_count
    
    @staticmethod
    def enforce_limits_atomic(api_key: CodeEditorApiKey) -> None:
        """Enforce rate limit and quota atomically, raise exceptions if exceeded"""
        # Check rate limit first (more likely to be exceeded)
        if not QuotaService.check_rate_limit_atomic(api_key):
            raise RateLimitExceededException()
        
        # Check daily quota
        if not QuotaService.check_daily_quota_atomic(api_key):
            raise QuotaExceededException()
        
        # Increment both counters atomically
        QuotaService.increment_rate_limit_atomic(api_key)
        QuotaService.increment_daily_quota_atomic(api_key)
    
    @staticmethod
    def get_current_usage_atomic(api_key: CodeEditorApiKey) -> Dict[str, Any]:
        """Get current usage statistics atomically"""
        today = timezone.now().strftime("%Y-%m-%d")
        
        # Get rate limit info
        rate_limit_key = f"code_editor_rate_limit:{api_key.id}"
        rate_limit_timestamp = f"{rate_limit_key}:timestamp"
        current_rpm = cache.get(rate_limit_key, 0)
        rpm_timestamp = cache.get(rate_limit_timestamp, 0)
        
        # Calculate RPM remaining with time window consideration
        current_time = int(time.time())
        if rpm_timestamp and (current_time - int(rpm_timestamp)) < 60:
            # Still within the same 1-minute window
            rpm_remaining = max(0, api_key.rpm_limit - current_rpm)
            rpm_reset_in = 60 - (current_time - int(rpm_timestamp))
        else:
            # New window or expired
            rpm_remaining = api_key.rpm_limit
            rpm_reset_in = 60
        
        # Get daily quota info
        quota_key = f"code_editor_quota:{api_key.id}:{today}"
        daily_used = cache.get(quota_key, 0)
        daily_remaining = max(0, api_key.daily_quota - daily_used)
        
        # Get actual usage from database for accuracy
        today_start = timezone.now().replace(hour=0, minute=0, second=0, microsecond=0)
        actual_requests = CodeEditorRequestLog.objects.filter(
            api_key=api_key,
            created_at__gte=today_start
        ).count()
        
        return {
            'api_key': {
                'id': api_key.id,
                'name': api_key.name,
                'prefix': api_key.prefix,
            },
            'rate_limit': {
                'limit': api_key.rpm_limit,
                'used': current_rpm,
                'remaining': rpm_remaining,
                'reset_in_seconds': rpm_reset_in,
                'window_start': int(rpm_timestamp) if rpm_timestamp else current_time,
            },
            'daily_quota': {
                'limit': api_key.daily_quota,
                'used': daily_used,
                'remaining': daily_remaining,
                'reset_in_seconds': QuotaService._get_seconds_until_midnight(),
            },
            'actual_usage': {
                'requests_today': actual_requests,
            }
        }
    
    @staticmethod
    def _get_seconds_until_midnight() -> int:
        """Get seconds until next midnight UTC"""
        now = timezone.now()
        tomorrow = now.replace(hour=0, minute=0, second=0, microsecond=0) + timezone.timedelta(days=1)
        return int((tomorrow - now).total_seconds())
    
    @staticmethod
    def get_quota_status(api_key_id: int, user: Optional[Any] = None) -> Dict[str, Any]:
        """Get quota status for API key"""
        try:
            api_key = CodeEditorApiKey.objects.get(id=api_key_id)
        except CodeEditorApiKey.DoesNotExist:
            raise InvalidRequestException("API key not found")
        
        # Check permissions
        if user and not user.is_staff and api_key.created_by != user:
            raise InvalidRequestException("Permission denied")
        
        return QuotaService.get_current_usage_atomic(api_key)
    
    @staticmethod
    def reset_rate_limit(api_key: CodeEditorApiKey) -> bool:
        """Reset rate limit for API key (admin only)"""
        cache_key = f"code_editor_rate_limit:{api_key.id}"
        timestamp_key = f"{cache_key}:timestamp"
        
        try:
            with cache.client.pipeline() as pipe:
                pipe.delete(cache_key)
                pipe.delete(timestamp_key)
                pipe.execute()
            return True
        except Exception:
            cache.delete(cache_key)
            cache.delete(timestamp_key)
            return True
    
    @staticmethod
    def reset_daily_quota(api_key: CodeEditorApiKey) -> bool:
        """Reset daily quota for API key (admin only)"""
        today = timezone.now().strftime("%Y-%m-%d")
        cache_key = f"code_editor_quota:{api_key.id}:{today}"
        
        try:
            cache.delete(cache_key)
            return True
        except Exception:
            return False
    
    @staticmethod
    def get_system_quota_stats() -> Dict[str, Any]:
        """Get system-wide quota statistics (admin only)"""
        # Get total active API keys
        total_keys = CodeEditorApiKey.objects.filter(is_active=True).count()
        
        # Get today's request count
        today_start = timezone.now().replace(hour=0, minute=0, second=0, microsecond=0)
        today_requests = CodeEditorRequestLog.objects.filter(
            created_at__gte=today_start
        ).count()
        
        # Get error rate
        today_errors = CodeEditorRequestLog.objects.filter(
            created_at__gte=today_start,
            status='error'
        ).count()
        
        error_rate = (today_errors / today_requests * 100) if today_requests > 0 else 0
        
        return {
            'system_stats': {
                'active_api_keys': total_keys,
                'requests_today': today_requests,
                'errors_today': today_errors,
                'error_rate_percent': round(error_rate, 2),
                'timestamp': timezone.now(),
            }
        }
