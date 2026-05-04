from typing import Dict, Any, Optional
from django.utils import timezone
from ..models import CodeEditorApiKey
from .config import ConfigService
from ..exceptions import InvalidRequestException


class ApiKeyService:
    """Service for managing API keys"""
    
    @staticmethod
    def create_api_key(
        name: str,
        daily_quota: Optional[int] = None,
        rpm_limit: Optional[int] = None,
        created_by: Optional[Any] = None
    ) -> Dict[str, Any]:
        """Create a new API key"""
        if not name or not name.strip():
            raise InvalidRequestException("API key name cannot be empty")
        
        # Get defaults if not provided
        quota_defaults = ConfigService.get_quota_defaults()
        daily_quota = daily_quota or quota_defaults['daily_quota']
        rpm_limit = rpm_limit or quota_defaults['rpm']
        
        # Generate the key
        raw_key, key_hash, prefix = CodeEditorApiKey.generate_key()
        
        # Create the API key record
        api_key = CodeEditorApiKey.objects.create(
            name=name.strip(),
            key_hash=key_hash,
            prefix=prefix,
            daily_quota=daily_quota,
            rpm_limit=rpm_limit,
            created_by=created_by
        )
        
        return {
            'id': api_key.id,
            'name': api_key.name,
            'key': raw_key,  # Only returned once on creation
            'prefix': api_key.prefix,
            'daily_quota': api_key.daily_quota,
            'rpm_limit': api_key.rpm_limit,
            'is_active': api_key.is_active,
            'created_at': api_key.created_at,
            'last_used_at': api_key.last_used_at,
        }
    
    @staticmethod
    def list_api_keys(user: Optional[Any] = None) -> list:
        """List API keys (filtered by user if provided)"""
        queryset = CodeEditorApiKey.objects.all()
        
        if user and not user.is_staff:
            # Non-staff users can only see their own keys
            queryset = queryset.filter(created_by=user)
        
        keys = []
        for api_key in queryset.order_by('-created_at'):
            keys.append({
                'id': api_key.id,
                'name': api_key.name,
                'prefix': api_key.prefix,
                'daily_quota': api_key.daily_quota,
                'rpm_limit': api_key.rpm_limit,
                'is_active': api_key.is_active,
                'created_at': api_key.created_at,
                'last_used_at': api_key.last_used_at,
                'revoked_at': api_key.revoked_at,
            })
        
        return keys
    
    @staticmethod
    def revoke_api_key(key_id: int, user: Optional[Any] = None) -> Dict[str, Any]:
        """Revoke an API key"""
        try:
            api_key = CodeEditorApiKey.objects.get(id=key_id)
        except CodeEditorApiKey.DoesNotExist:
            raise InvalidRequestException("API key not found")
        
        # Check permissions
        if user and not user.is_staff and api_key.created_by != user:
            raise InvalidRequestException("Permission denied")
        
        if not api_key.is_active:
            raise InvalidRequestException("API key is already revoked")
        
        api_key.revoke()
        
        return {
            'id': api_key.id,
            'name': api_key.name,
            'prefix': api_key.prefix,
            'is_active': api_key.is_active,
            'revoked_at': api_key.revoked_at,
        }
    
    @staticmethod
    def get_api_key_info(key_id: int, user: Optional[Any] = None) -> Dict[str, Any]:
        """Get API key information"""
        try:
            api_key = CodeEditorApiKey.objects.get(id=key_id)
        except CodeEditorApiKey.DoesNotExist:
            raise InvalidRequestException("API key not found")
        
        # Check permissions
        if user and not user.is_staff and api_key.created_by != user:
            raise InvalidRequestException("Permission denied")
        
        return {
            'id': api_key.id,
            'name': api_key.name,
            'prefix': api_key.prefix,
            'daily_quota': api_key.daily_quota,
            'rpm_limit': api_key.rpm_limit,
            'is_active': api_key.is_active,
            'created_at': api_key.created_at,
            'last_used_at': api_key.last_used_at,
            'revoked_at': api_key.revoked_at,
        }
    
    @staticmethod
    def update_api_key(
        key_id: int,
        name: Optional[str] = None,
        daily_quota: Optional[int] = None,
        rpm_limit: Optional[int] = None,
        user: Optional[Any] = None
    ) -> Dict[str, Any]:
        """Update API key settings"""
        try:
            api_key = CodeEditorApiKey.objects.get(id=key_id)
        except CodeEditorApiKey.DoesNotExist:
            raise InvalidRequestException("API key not found")
        
        # Check permissions
        if user and not user.is_staff and api_key.created_by != user:
            raise InvalidRequestException("Permission denied")
        
        # Update fields if provided
        update_fields = []
        if name is not None:
            if not name.strip():
                raise InvalidRequestException("API key name cannot be empty")
            api_key.name = name.strip()
            update_fields.append('name')
        
        if daily_quota is not None:
            if daily_quota < 0:
                raise InvalidRequestException("Daily quota must be non-negative")
            api_key.daily_quota = daily_quota
            update_fields.append('daily_quota')
        
        if rpm_limit is not None:
            if rpm_limit < 1 or rpm_limit > 1000:
                raise InvalidRequestException("RPM limit must be between 1 and 1000")
            api_key.rpm_limit = rpm_limit
            update_fields.append('rpm_limit')
        
        if update_fields:
            api_key.save(update_fields=update_fields)
        
        return {
            'id': api_key.id,
            'name': api_key.name,
            'prefix': api_key.prefix,
            'daily_quota': api_key.daily_quota,
            'rpm_limit': api_key.rpm_limit,
            'is_active': api_key.is_active,
            'created_at': api_key.created_at,
            'last_used_at': api_key.last_used_at,
            'revoked_at': api_key.revoked_at,
        }
