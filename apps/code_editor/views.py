"""Legacy API views wrapper for backwards compatibility.

This module re‑exports selected callables from ``code_editor.api.views`` so
that code written against older versions of the package continues to work.
Only stable public endpoints are exposed.  New functionality should be
imported from ``code_editor.api`` instead.
"""

from __future__ import annotations

# Import public API view functions from the modern API module.  If a view is
# removed from ``code_editor.api.views``, remove it from the exports below.
from .api.views import (  # noqa: F401  
    health_check,
    models_list,
    providers_list,
    chat_completion,
    text_completion,
    edit_code,
    generate_embeddings,
    rerank_documents,
    infill_code,
    apply_patch,
    revert_patch,
)

__all__ = [
    'health_check',
    'models_list',
    'providers_list',
    'chat_completion',
    'text_completion',
    'edit_code',
    'generate_embeddings',
    'rerank_documents',
    'infill_code',
    'apply_patch',
    'revert_patch',
]