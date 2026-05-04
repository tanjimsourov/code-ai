"""Structured logging utilities for the Code Editor backend.

This module provides a helper function to emit JSON‑formatted log
entries enriched with contextual information.  It ensures that
sensitive fields (such as API keys, tokens or secrets) are filtered
out before logging.  Structured logging makes it easier to ingest
application logs into centralised logging systems and query them by
specific fields.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict

# Keywords that identify potentially sensitive fields.  If any of these
# substrings appear in a context key, the key is omitted from logs.
SENSITIVE_FIELD_KEYWORDS = {'token', 'key', 'secret', 'password', 'authorization'}


def log_event(event: str, **context: Any) -> None:
    """Log a structured event with optional context.

    :param event: Short event name describing the action (e.g. ``provider_call``)
    :param context: Additional key‑value pairs providing context for the event
    """
    logger = logging.getLogger('code_editor')
    # Filter out sensitive fields and ensure values are serialisable
    safe_context: Dict[str, Any] = {}
    for key, value in context.items():
        # Skip keys containing sensitive substrings
        if any(keyword in key.lower() for keyword in SENSITIVE_FIELD_KEYWORDS):
            continue
        # Convert non‑serialisable values to string
        try:
            json.dumps(value)
            safe_context[key] = value
        except TypeError:
            safe_context[key] = str(value)
    # Include the event name in the logged structure
    log_record = {'event': event, **safe_context}
    # Emit as a JSON string to ease ingestion by log aggregators
    try:
        logger.info(json.dumps(log_record, ensure_ascii=False))
    except Exception:
        # Fall back to logging a simple repr on any error
        logger.info(repr(log_record))