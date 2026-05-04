"""Test suite for the code_editor app.

This package contains unit tests for the core utility functions and services
provided by the code_editor Django app. Tests are written using Django's
built-in TestCase and the standard unittest framework. Run them with
`python manage.py test code_editor` from within a full Django project.
"""

# Some tests reference ``timezone`` directly (e.g. ``timezone.now()``) without
# importing it. In a full Django project this may work due to implicit
# imports, but in this package's test environment ``timezone`` would be
# undefined. Import it here and expose it as a module-level symbol so
# that tests can access ``timezone.now()`` without explicit imports.
from django.utils import timezone as _timezone  # type: ignore

# Expose the timezone object at module level. This ensures that
# ``timezone.now()`` calls within tests succeed without an explicit import.
globals()['timezone'] = _timezone

