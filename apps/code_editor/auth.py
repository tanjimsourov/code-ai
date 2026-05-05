"""Authentication helpers for the code editor API.

This module defines an authentication class that optionally enforces
API‑key based authentication. When the ``CODE_EDITOR_REQUIRE_API_KEY``
environment variable is set to a truthy value, requests to
mutating/generative endpoints must include a valid API key.  Keys are
looked up by prefix and SHA‑256 hash for security.  When API key
authentication is disabled, this authentication class is effectively a
no‑op.

The class returns the resolved ``CodeEditorApiKey`` instance as the
``request.auth`` attribute.  User information is not derived from the
API key; therefore the ``user`` component of the returned tuple is
``None``.  Downstream services can access the API key via
``request.auth`` for logging and quota enforcement.

If authentication fails and API keys are required, a
``InvalidAPIKeyException`` is raised, resulting in an HTTP 401
response.  Inactive or revoked keys also trigger this exception.
"""

import hashlib
from typing import Optional, Tuple

from django.utils import timezone
from rest_framework.authentication import BaseAuthentication

from .exceptions import InvalidAPIKeyException
from .models import CodeEditorApiKey
from .services.config import ConfigService


class CodeEditorApiKeyAuthentication(BaseAuthentication):
    """Authenticate requests using a bearer API key.

    The expected header format is one of the following:

    - ``Authorization: Bearer <raw_key>``
    - ``Authorization: ApiKey <raw_key>``
    - ``X-API-Key: <raw_key>``

    Only the ``Authorization`` or ``X-API-Key`` headers are inspected.
    If API keys are not required (``CODE_EDITOR_REQUIRE_API_KEY`` is
    false), the authenticate method returns ``None`` allowing all
    requests through.  When keys are required and the header is
    missing or invalid, an ``InvalidAPIKeyException`` is raised.
    """

    def authenticate(self, request) -> Optional[Tuple[None, CodeEditorApiKey]]:
        """Attempt to authenticate the request.

        Returns a two‑tuple of ``(user, auth)`` where ``user`` is
        ``None`` and ``auth`` is the ``CodeEditorApiKey`` instance if
        authentication succeeds.  If API keys are disabled or no key
        is provided, ``None`` is returned.  If the key is invalid or
        inactive, an ``InvalidAPIKeyException`` is raised.
        """
        # Retrieve the raw key from supported headers
        auth_header = request.headers.get('Authorization') or ''
        api_key_header = request.headers.get('X-API-Key') or request.headers.get('Api-Key') or ''
        raw_key: Optional[str] = None
        if auth_header:
            try:
                scheme, value = auth_header.split(' ', 1)
                scheme_lower = scheme.lower()
                if scheme_lower in {'bearer', 'apikey', 'api-key'}:
                    raw_key = value.strip()
            except ValueError:
                # Header does not contain a space; treat the whole header as the key
                raw_key = auth_header.strip()
        elif api_key_header:
            raw_key = api_key_header.strip()
        if not raw_key:
            return None
        # Keys must start with a known prefix to reduce lookup scope
        prefix = raw_key[:8]
        key_hash = hashlib.sha256(raw_key.encode('utf-8')).hexdigest()
        # Look up candidate keys by prefix
        try:
            candidates = CodeEditorApiKey.objects.filter(prefix=prefix, is_active=True)
        except Exception:
            candidates = CodeEditorApiKey.objects.none()
        for candidate in candidates:
            # Constant‑time compare to avoid timing attacks
            if candidate.key_hash == key_hash:
                # Update last used timestamp
                candidate.last_used_at = timezone.now()
                candidate.save(update_fields=['last_used_at'])
                return (None, candidate)
        if not ConfigService.require_api_key():
            return None
        raise InvalidAPIKeyException("Invalid API key")

    def authenticate_header(self, request) -> str:
        """Return a description of the authentication scheme for 401 responses."""
        return 'Bearer'


# Backward‑compatible alias for any stale imports.  Use the new class
# name instead of the old, but support both references.
LocalCodeEditorAuthentication = CodeEditorApiKeyAuthentication
CodeEditorAPIKeyAuthentication = CodeEditorApiKeyAuthentication
