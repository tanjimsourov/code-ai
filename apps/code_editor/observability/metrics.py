"""Prometheus metrics instrumentation for the Code Editor backend.

This module defines counters and histograms for tracking request counts,
latencies and other operational statistics.  If the ``prometheus_client``
library is not installed, all metrics objects are set to ``None`` and
the ``metrics_view`` will respond with a 503 status.  When Prometheus
is available the ``metrics_view`` returns a standard ``text/plain``
exposition format.
"""

from __future__ import annotations

from typing import Any, Optional

try:
    # Import Prometheus client library if available
    from prometheus_client import Counter, Histogram, generate_latest, CONTENT_TYPE_LATEST
except ImportError:  # pragma: no cover
    # Prometheus is optional; fall back to stubs when missing
    Counter = None  # type: ignore[assignment]
    Histogram = None  # type: ignore[assignment]
    generate_latest = None  # type: ignore[assignment]
    CONTENT_TYPE_LATEST = 'text/plain; charset=utf-8'  # type: ignore[assignment]

from django.http import HttpResponse
import os

__all__ = [
    'REQUEST_COUNT', 'REQUEST_LATENCY', 'PROVIDER_LATENCY', 'INPUT_TOKENS',
    'OUTPUT_TOKENS', 'TASK_STATUS', 'INDEXING_DURATION', 'VALIDATION_DURATION',
    'metrics_view',
]

def _create_counter(name: str, documentation: str, labelnames: tuple[str, ...] = ()):
    """Helper to create a Prometheus Counter or return None when unavailable."""
    if Counter is None:
        return None
    return Counter(name, documentation, labelnames=labelnames)  # type: ignore[no-untyped-call]


def _create_histogram(name: str, documentation: str, labelnames: tuple[str, ...] = (), buckets: Optional[list[float]] = None):
    """Helper to create a Prometheus Histogram or return None when unavailable."""
    if Histogram is None:
        return None
    if buckets is None:
        # Default buckets approximate deciles from 1ms up to 5m
        buckets = [0.001, 0.01, 0.1, 1.0, 10.0, 30.0, 60.0, 120.0, 300.0]
    return Histogram(name, documentation, labelnames=labelnames, buckets=buckets)  # type: ignore[no-untyped-call]


# Request level metrics
REQUEST_COUNT = _create_counter(
    'code_editor_requests_total',
    'Total number of API requests',
    labelnames=('endpoint', 'method', 'status'),
)

REQUEST_LATENCY = _create_histogram(
    'code_editor_request_latency_seconds',
    'Latency of API requests in seconds',
    labelnames=('endpoint', 'method'),
)

# Provider call metrics
PROVIDER_LATENCY = _create_histogram(
    'code_editor_provider_latency_seconds',
    'Latency of calls to AI providers in seconds',
    labelnames=('provider', 'request_type'),
)

# Token/character usage estimates
INPUT_TOKENS = _create_counter(
    'code_editor_input_tokens_total',
    'Estimated number of input tokens/chars processed',
    labelnames=('provider', 'request_type'),
)

OUTPUT_TOKENS = _create_counter(
    'code_editor_output_tokens_total',
    'Estimated number of output tokens/chars generated',
    labelnames=('provider', 'request_type'),
)

# Task status counts
TASK_STATUS = _create_counter(
    'code_editor_task_status_total',
    'Count of tasks by final status',
    labelnames=('status',),
)

# Indexing and validation durations
INDEXING_DURATION = _create_histogram(
    'code_editor_indexing_duration_seconds',
    'Time taken to index repositories',
    labelnames=('repository',),
)

VALIDATION_DURATION = _create_histogram(
    'code_editor_validation_duration_seconds',
    'Duration of validation runs',
    labelnames=('task',),
)


def metrics_view(request: Any) -> HttpResponse:
    """
    Return a Prometheus exposition response subject to security configuration.

    The metrics endpoint is disabled when the ``prometheus_client`` library is
    unavailable.  When enabled, access is controlled by two environment
    variables:

    - ``CODE_EDITOR_PUBLIC_METRICS``: if set to ``true`` (case insensitive),
      metrics are returned to any caller.
    - ``CODE_EDITOR_METRICS_TOKEN``: a shared secret token.  When public
      metrics are disabled, callers must provide this token either via
      ``Authorization: Bearer <token>`` or ``X-Code-Editor-Metrics-Token``
      header.  If no token is configured, the endpoint returns ``404`` to
      avoid exposing internals.

    A missing or incorrect token results in ``403 Forbidden`` without
    revealing configuration details.  When the Prometheus client is not
    installed, ``503 Service Unavailable`` is returned regardless of
    configuration.  On success, the response uses the content type from
    ``CONTENT_TYPE_LATEST``.
    """
    # Metrics unavailable when client is missing
    if generate_latest is None:
        return HttpResponse('metrics unavailable', status=503, content_type='text/plain')
    # Determine if public metrics are allowed
    public_flag = os.getenv('CODE_EDITOR_PUBLIC_METRICS', 'false').lower() == 'true'
    if public_flag:
        output = generate_latest()  # type: ignore[no-untyped-call]
        return HttpResponse(output, content_type=CONTENT_TYPE_LATEST)
    # Check for configured token
    token = os.getenv('CODE_EDITOR_METRICS_TOKEN')
    if not token:
        # Hide existence of metrics endpoint when not public and no token
        return HttpResponse(status=404)
    # Extract provided token from headers (Authorization Bearer or X-Code-Editor-Metrics-Token)
    provided: Optional[str] = None
    auth_header: Optional[str] = request.headers.get('Authorization')  # type: ignore[assignment]
    if auth_header and auth_header.lower().startswith('bearer '):
        provided = auth_header.split(' ', 1)[1].strip()
    if not provided:
        provided = request.headers.get('X-Code-Editor-Metrics-Token')  # type: ignore[assignment]
    if provided != token:
        # Incorrect or missing token
        return HttpResponse(status=403)
    output = generate_latest()  # type: ignore[no-untyped-call]
    return HttpResponse(output, content_type=CONTENT_TYPE_LATEST)