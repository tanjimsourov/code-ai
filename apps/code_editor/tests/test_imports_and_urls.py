"""Minimal smoke tests to verify import stability of core modules.

These tests ensure that the package's top‑level modules and URL patterns
can be imported without raising exceptions.  They do not exercise any
functional behaviour but serve as a guard against breaking changes in
module paths or missing dependencies.
"""

import importlib


def test_imports() -> None:
    """Verify that key modules import successfully."""
    importlib.import_module('code_editor.views')
    importlib.import_module('code_editor.api.urls')
    importlib.import_module('code_editor.api.health_views')
    importlib.import_module('code_editor.api.throttles')
    importlib.import_module('code_editor.observability.metrics')


def test_urlpatterns_iterable() -> None:
    """Ensure that urlpatterns is defined and iterable."""
    urls = importlib.import_module('code_editor.api.urls')
    assert hasattr(urls, 'urlpatterns')
    # iterate through patterns to ensure they are valid
    for pattern in urls.urlpatterns:
        # The pattern should have a callback or include
        assert getattr(pattern, 'callback', None) or getattr(pattern, 'url_patterns', None)

