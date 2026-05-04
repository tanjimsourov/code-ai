from typing import Dict, Any, List, Optional
from django.utils import timezone
from django.db.models import Count, Q, Avg, Sum
from datetime import datetime, timedelta
from ..models import CodeEditorRequestLog, CodeEditorApiKey
from ..exceptions import InvalidRequestException


class UsageService:
    """Service for providing usage statistics and analytics"""
    
    @staticmethod
    def get_usage_stats(
        api_key_id: Optional[int] = None,
        user_id: Optional[int] = None,
        days: int = 30,
        user: Optional[Any] = None
    ) -> Dict[str, Any]:
        """Get usage statistics"""
        # Validate days parameter
        if days < 1 or days > 365:
            raise InvalidRequestException("Days must be between 1 and 365")
        
        # Calculate date range
        end_date = timezone.now()
        start_date = end_date - timedelta(days=days)
        
        # Build base queryset
        queryset = CodeEditorRequestLog.objects.filter(
            created_at__gte=start_date,
            created_at__lte=end_date
        )
        
        # Apply filters
        if api_key_id:
            queryset = queryset.filter(api_key_id=api_key_id)
        
        if user_id:
            queryset = queryset.filter(user_id=user_id)
        
        # Check permissions
        if user and not user.is_staff:
            # Non-staff users can only see their own usage
            queryset = queryset.filter(user=user)
        
        # Get overall stats
        total_requests = queryset.count()
        successful_requests = queryset.filter(status='success').count()
        error_requests = queryset.filter(status='error').count()
        
        # Calculate success rate
        success_rate = (successful_requests / total_requests * 100) if total_requests > 0 else 0
        
        # Get latency stats
        latency_stats = queryset.filter(
            status='success',
            latency_ms__isnull=False
        ).aggregate(
            avg_latency=Avg('latency_ms'),
            min_latency=Avg('latency_ms'),
            max_latency=Avg('latency_ms')
        )
        
        # Get request kind breakdown
        kind_stats = queryset.values('request_kind').annotate(
            count=Count('id')
        ).order_by('-count')
        
        # Get provider breakdown
        provider_stats = queryset.values('provider').annotate(
            count=Count('id')
        ).order_by('-count')
        
        # Get daily usage
        daily_usage = queryset.extra(
            {'date': 'date(created_at)'}
        ).values('date').annotate(
            requests=Count('id'),
            successful=Count('id', filter=Q(status='success')),
            errors=Count('id', filter=Q(status='error'))
        ).order_by('date')
        
        return {
            'period': {
                'start_date': start_date,
                'end_date': end_date,
                'days': days
            },
            'summary': {
                'total_requests': total_requests,
                'successful_requests': successful_requests,
                'error_requests': error_requests,
                'success_rate': round(success_rate, 2),
                'avg_latency_ms': round(latency_stats['avg_latency'] or 0, 2),
                'min_latency_ms': latency_stats['min_latency'] or 0,
                'max_latency_ms': latency_stats['max_latency'] or 0,
            },
            'breakdown': {
                'by_request_kind': list(kind_stats),
                'by_provider': list(provider_stats),
            },
            'daily_usage': list(daily_usage),
        }
    
    @staticmethod
    def get_api_key_usage(
        api_key_id: int,
        days: int = 30,
        user: Optional[Any] = None
    ) -> Dict[str, Any]:
        """Get usage for a specific API key"""
        try:
            api_key = CodeEditorApiKey.objects.get(id=api_key_id)
        except CodeEditorApiKey.DoesNotExist:
            raise InvalidRequestException("API key not found")
        
        # Check permissions
        if user and not user.is_staff and api_key.created_by != user:
            raise InvalidRequestException("Permission denied")
        
        # Get usage stats for this API key
        stats = UsageService.get_usage_stats(
            api_key_id=api_key_id,
            days=days,
            user=user
        )
        
        # Add API key specific info
        stats['api_key'] = {
            'id': api_key.id,
            'name': api_key.name,
            'prefix': api_key.prefix,
            'daily_quota': api_key.daily_quota,
            'rpm_limit': api_key.rpm_limit,
            'is_active': api_key.is_active,
        }
        
        return stats
    
    @staticmethod
    def get_top_models(
        days: int = 30,
        limit: int = 10,
        user: Optional[Any] = None
    ) -> List[Dict[str, Any]]:
        """Get most used models"""
        # Validate parameters
        if days < 1 or days > 365:
            raise InvalidRequestException("Days must be between 1 and 365")
        if limit < 1 or limit > 100:
            raise InvalidRequestException("Limit must be between 1 and 100")
        
        # Calculate date range
        end_date = timezone.now()
        start_date = end_date - timedelta(days=days)
        
        # Build queryset
        queryset = CodeEditorRequestLog.objects.filter(
            created_at__gte=start_date,
            created_at__lte=end_date,
            status='success'
        )
        
        # Check permissions
        if user and not user.is_staff:
            queryset = queryset.filter(user=user)
        
        # Get model usage
        model_stats = queryset.values('model_name', 'provider').annotate(
            requests=Count('id'),
            avg_latency=Avg('latency_ms'),
            total_input_chars=Sum('input_chars'),
            total_output_chars=Sum('output_chars')
        ).order_by('-requests')[:limit]
        
        return list(model_stats)
    
    @staticmethod
    def get_error_summary(
        days: int = 30,
        user: Optional[Any] = None
    ) -> List[Dict[str, Any]]:
        """Get error summary"""
        # Validate days
        if days < 1 or days > 365:
            raise InvalidRequestException("Days must be between 1 and 365")
        
        # Calculate date range
        end_date = timezone.now()
        start_date = end_date - timedelta(days=days)
        
        # Build queryset
        queryset = CodeEditorRequestLog.objects.filter(
            created_at__gte=start_date,
            created_at__lte=end_date,
            status='error'
        )
        
        # Check permissions
        if user and not user.is_staff:
            queryset = queryset.filter(user=user)
        
        # Get error breakdown
        error_stats = queryset.values(
            'request_kind',
            'provider',
            'error_message'
        ).annotate(
            count=Count('id')
        ).order_by('-count')
        
        return list(error_stats)
