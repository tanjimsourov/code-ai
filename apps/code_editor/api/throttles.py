"""Custom throttling classes for the Code Editor API.

These throttles extend Django REST framework's ``SimpleRateThrottle`` to
provide per‑scope rate limiting for different categories of requests.
The default rates are conservative and can be overridden via the
``CODE_EDITOR_RATE_LIMITS`` setting or environment variables at a later
date.  API keys are used for cache keys when available to provide
per‑tenant isolation.
"""

from __future__ import annotations

from typing import Optional

from rest_framework.throttling import SimpleRateThrottle


class _BaseKeyThrottle(SimpleRateThrottle):
    """Base throttle that uses API key or client IP as the cache key."""

    def get_cache_key(self, request, view) -> Optional[str]:  # type: ignore[override]
        # Use the authenticated API key id when available to scope rate limits
        api_key = getattr(request, 'auth', None)
        if api_key and hasattr(api_key, 'id'):
            return f'{self.scope}:{api_key.id}'
        # Fallback to IP address
        ident = self.get_ident(request)
        return f'{self.scope}:{ident}' if ident else None


class AIThrottle(_BaseKeyThrottle):
    """Rate limit for AI requests such as completions and chat."""
    scope = 'ai'
    rate = '60/min'  # Default: 60 requests per minute


class PublicReadThrottle(_BaseKeyThrottle):
    """Rate limit for unauthenticated read‑only endpoints (e.g. health)."""
    scope = 'public_read'
    rate = '120/min'  # Higher since reads are inexpensive


class RepoMutationThrottle(_BaseKeyThrottle):
    """Rate limit for repository mutation operations (create/update/delete)."""
    scope = 'repo_mutation'
    rate = '30/min'


class TaskMutationThrottle(_BaseKeyThrottle):
    """Rate limit for task creation and mutation (e.g. cancellations)."""
    scope = 'task_mutation'
    rate = '60/min'


class ProviderHealthThrottle(_BaseKeyThrottle):
    """Rate limit for provider health status requests."""
    scope = 'provider_health'
    rate = '10/min'


class UpstreamSyncThrottle(_BaseKeyThrottle):
    """Rate limit for upstream repository synchronisation tasks."""
    scope = 'upstream_sync'
    rate = '5/min'