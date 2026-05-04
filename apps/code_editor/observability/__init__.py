"""Observability utilities for the Code Editor backend.

This package contains helpers for metrics collection and structured logging.
It is separate from the ``utils`` module to avoid import name conflicts and
to support optional dependencies such as Prometheus.  Do not import
application code from here to avoid circular dependencies.
"""