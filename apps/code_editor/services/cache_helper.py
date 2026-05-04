"""Cache invalidation utilities for the code editor.

This module centralises logic for invalidating various caches used across
the system.  Caches help reduce expensive calls to remote services or
heavy computations but must be invalidated when underlying data changes.
Each helper method attempts to clear a named cache or delete keys by
pattern.  If a cache is not configured it quietly does nothing.

Example usage::

    from code_editor.services.cache_helper import CacheHelper
    CacheHelper.invalidate_model_registry_cache()

When adding new caches to the project, define an explicit invalidation
method here and call it from the appropriate service or signal.
"""

from django.core.cache import caches
from django.core.cache.backends.base import BaseCache
from typing import Optional


def _get_cache(alias: str) -> Optional[BaseCache]:
    """Safely get a cache backend by alias.

    Returns ``None`` if the cache alias is not configured.  Catching
    ``InvalidCacheBackendError`` avoids raising when caches are not
    available in certain environments (e.g. tests).
    """
    try:
        return caches[alias]
    except Exception:
        return None


class CacheHelper:
    """High-level cache invalidation methods."""

    @staticmethod
    def _clear(alias: str) -> None:
        cache = _get_cache(alias)
        if cache:
            try:
                cache.clear()
            except Exception:
                # Ignore errors to avoid cascading failures
                pass

    @staticmethod
    def invalidate_model_registry_cache() -> None:
        """Invalidate any caches storing model metadata or registry information."""
        CacheHelper._clear('model_registry')

    @staticmethod
    def invalidate_provider_health_cache() -> None:
        """Invalidate provider health status caches."""
        CacheHelper._clear('provider_health')

    @staticmethod
    def invalidate_repository_stats_cache() -> None:
        """Invalidate caches tracking repository statistics (file counts, chunks, etc.)."""
        CacheHelper._clear('repository_stats')

    @staticmethod
    def invalidate_code_map_cache() -> None:
        """Invalidate caches storing code map or structure information."""
        CacheHelper._clear('code_map')

    @staticmethod
    def invalidate_context_pack_cache() -> None:
        """Invalidate caches for context packs used during retrieval."""
        CacheHelper._clear('context_pack')

    @staticmethod
    def invalidate_retrieval_result_cache() -> None:
        """Invalidate caches storing retrieval results.  Use with caution to avoid heavy
        recomputation when not needed."""
        CacheHelper._clear('retrieval_results')

    @staticmethod
    def invalidate_all() -> None:
        """Invalidate all known caches.  Should be used sparingly."""
        CacheHelper.invalidate_model_registry_cache()
        CacheHelper.invalidate_provider_health_cache()
        CacheHelper.invalidate_repository_stats_cache()
        CacheHelper.invalidate_code_map_cache()
        CacheHelper.invalidate_context_pack_cache()
        CacheHelper.invalidate_retrieval_result_cache()