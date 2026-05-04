"""Health check endpoints for the Code Editor backend.

These endpoints provide basic liveness and readiness information.
The ``live_health`` endpoint returns a minimal response indicating
that the application process is running.  The ``ready_health``
endpoint performs a series of non‑destructive checks to ensure that
critical dependencies (database, cache, providers, storage) are
available.  Health endpoints do not require authentication and
should not leak sensitive information.
"""

from __future__ import annotations

import os
from typing import Any, Dict

from django.conf import settings
from django.core.cache import cache
from django.db import connections
from django.db.migrations.executor import MigrationExecutor
from django.http import JsonResponse

try:
    from ..services.router import RouterService
except Exception:
    RouterService = None  # type: ignore[misc]


def live_health(request: Any) -> JsonResponse:
    """Return a simple liveness response.

    This endpoint indicates that the application process is running and able
    to handle HTTP requests.  It does not perform any dependency checks.
    """
    return JsonResponse({'status': 'ok'})


def ready_health(request: Any) -> JsonResponse:
    """Return readiness status by performing dependency checks.

    The readiness check verifies database connectivity, migration
    status, cache availability, provider registry initialisation and
    storage path accessibility.  Each check is reported as a boolean
    flag.  If any of the checks fail the overall ``status`` is set to
    ``degraded``.  No sensitive information is returned.
    """
    checks: Dict[str, Any] = {}
    status_overall = 'ok'
    # Check database connectivity
    try:
        connections['default'].ensure_connection()
        checks['database'] = True
    except Exception:
        checks['database'] = False
        status_overall = 'degraded'
    # Check pending migrations
    try:
        executor = MigrationExecutor(connections['default'])
        pending = bool(executor.migration_plan(executor.loader.graph.leaf_nodes()))
        checks['migrations_pending'] = pending
        # Pending migrations do not degrade readiness but are reported
    except Exception:
        checks['migrations_pending'] = None
        status_overall = 'degraded'
    # Check cache
    try:
        cache_key = 'code_editor_health_check'
        cache.set(cache_key, '1', 1)
        checks['cache'] = True
    except Exception:
        checks['cache'] = False
        status_overall = 'degraded'
    # Check provider registry
    try:
        if RouterService is not None:
            router = RouterService()
            # Only attempt to list providers; do not call external APIs
            providers = router.get_available_providers()
            checks['providers_configured'] = bool(providers)
        else:
            checks['providers_configured'] = False
            status_overall = 'degraded'
    except Exception:
        checks['providers_configured'] = False
        status_overall = 'degraded'
    # Check storage path if configured
    try:
        storage_path = getattr(settings, 'CODE_EDITOR_TASK_STORAGE_ROOT', None)
        if storage_path:
            checks['storage_writable'] = bool(
                os.path.isdir(storage_path) and os.access(storage_path, os.W_OK)
            )
            if not checks['storage_writable']:
                status_overall = 'degraded'
        else:
            # If not configured treat as ok
            checks['storage_writable'] = True
    except Exception:
        checks['storage_writable'] = False
        status_overall = 'degraded'
    # Compose response
    response: Dict[str, Any] = {
        'status': status_overall,
        'checks': checks,
    }
    return JsonResponse(response)