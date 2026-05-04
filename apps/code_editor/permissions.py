"""Permission helpers for the code editor API.

This module defines permission classes used to enforce API‑key
authentication and quota limits on mutating/generative endpoints.
When API key enforcement is disabled via configuration,
``LocalCodeEditorPermission`` simply allows all requests.  When
enforced, ``CodeEditorApiKeyPermission`` ensures that a valid API
key has been authenticated and that its quota and rate limits are
within allowed thresholds.  Quota enforcement is delegated to
``QuotaService.enforce_limits_atomic``, which raises exceptions if
limits are exceeded.  These exceptions propagate through the view
layer as HTTP errors.
"""

from rest_framework import permissions

from .exceptions import InvalidAPIKeyException
from .services.config import ConfigService
from .services.quota_service import QuotaService


class LocalCodeEditorPermission(permissions.BasePermission):
    """Allow all requests when API keys are not required.

    This permission class simply returns ``True`` for all requests,
    maintaining backward compatibility for local development and
    tooling when API key enforcement is disabled.
    """

    def has_permission(self, request, view) -> bool:
        return True


class CodeEditorApiKeyPermission(permissions.BasePermission):
    """Require a valid API key and enforce quotas.

    This permission checks whether API keys are required.  If not,
    all requests are allowed.  If API keys are required, the
    authenticated API key is retrieved from ``request.auth``.  If
    absent, an ``InvalidAPIKeyException`` is raised.  The
    ``QuotaService.enforce_limits_atomic`` method is called to
    check rate and daily quota limits.  Any exceptions thrown
    propagate up to the caller and are handled by the view or DRF.
    """

    def has_permission(self, request, view) -> bool:
        # If API keys are not required, allow all requests
        if not ConfigService.require_api_key():
            return True
        api_key = getattr(request, 'auth', None)
        # If user is authenticated via Django's auth and API keys are not
        # enforced for authenticated users, allow.  However, in this
        # implementation we still require an API key when the flag is set.
        if api_key is None:
            # No API key found on the request
            raise InvalidAPIKeyException("API key required")
        # Inactive or revoked keys should be treated as invalid
        if not getattr(api_key, 'is_active', False):
            raise InvalidAPIKeyException("API key is inactive")
        # Enforce rate and quota limits.  Exceptions propagate as 429s.
        QuotaService.enforce_limits_atomic(api_key)
        return True


# ---------------------------------------------------------------------------
# Extended permission classes
#
# These classes build upon the base API key permission to support optional
# public surfaces and role‑based access.  Public surfaces are only exposed
# when explicitly enabled via environment variables.  Otherwise, the
# underlying ``CodeEditorApiKeyPermission`` is used to enforce API key
# authentication and quota restrictions.


class PublicModelListingPermission(permissions.BasePermission):
    """Allow anonymous access to model listings when enabled.

    By default the list of available models is protected and requires an API
    key.  Set the ``CODE_EDITOR_PUBLIC_MODEL_LISTING`` environment variable
    to a truthy value to enable anonymous listing.  When disabled, this
    permission falls back to the normal API key enforcement.
    """

    def has_permission(self, request, view) -> bool:
        from .services.config import ConfigService  # Local import to avoid cycles
        if ConfigService.public_model_listing_enabled():
            return True
        # Defer to API key permission
        return CodeEditorApiKeyPermission().has_permission(request, view)


class PublicProviderListingPermission(permissions.BasePermission):
    """Allow anonymous access to provider listings when enabled.

    This mirrors ``PublicModelListingPermission`` but controls access to the
    provider metadata endpoint.  Enable via the
    ``CODE_EDITOR_PUBLIC_PROVIDER_LISTING`` environment variable.
    """

    def has_permission(self, request, view) -> bool:
        from .services.config import ConfigService
        if ConfigService.public_provider_listing_enabled():
            return True
        return CodeEditorApiKeyPermission().has_permission(request, view)


class PublicOpenAIModelListingPermission(permissions.BasePermission):
    """Allow anonymous access to the OpenAI‑compatible models endpoint.

    Controlled by ``CODE_EDITOR_PUBLIC_OPENAI_MODEL_LISTING``.  When disabled
    (default), callers must present a valid API key.
    """

    def has_permission(self, request, view) -> bool:
        from .services.config import ConfigService
        if ConfigService.public_openai_model_listing_enabled():
            return True
        return CodeEditorApiKeyPermission().has_permission(request, view)


class AdminOrInternalPermission(permissions.BasePermission):
    """Allow access only to admin/staff users or internal service calls.

    This permission is useful for sensitive endpoints such as metrics or
    operational controls.  The internal logic simply checks whether the
    request.user is authenticated and has the ``is_staff`` or ``is_superuser``
    flag set.  Additional internal checks (e.g. trusted IP ranges) can be
    added here in the future.
    """

    def has_permission(self, request, view) -> bool:
        user = getattr(request, 'user', None)
        if user and (getattr(user, 'is_staff', False) or getattr(user, 'is_superuser', False)):
            return True
        # Deny by default
        return False


class CanRunAIRequest(permissions.BasePermission):
    """Placeholder for per‑user AI request authorization.

    In a multi‑tenant deployment you may wish to restrict which API keys or
    authenticated users can access AI generation endpoints.  This class
    currently delegates to ``CodeEditorApiKeyPermission`` but can be
    extended to enforce additional policy (e.g. subscription tier, group
    membership).  To avoid breaking existing behaviour, this permission
    always calls through to the API key permission.
    """

    def has_permission(self, request, view) -> bool:
        return CodeEditorApiKeyPermission().has_permission(request, view)


class CanMutateRepository(permissions.BasePermission):
    """Placeholder permission for repository mutations.

    This class can be extended to verify that the authenticated user or API
    key has write privileges on the targeted project or repository.  At
    present it simply defers to ``CodeEditorApiKeyPermission``.  Future
    implementations should consult role information stored on the API key or
    related user models.
    """

    def has_permission(self, request, view) -> bool:
        return CodeEditorApiKeyPermission().has_permission(request, view)


class CanApprovePatch(permissions.BasePermission):
    """Permission for approving candidate patches.

    Patch approval alters the state of a task and may trigger code
    application.  This class exists as an extension point for future
    policy controls (e.g. requiring specific roles).  For now it defers
    entirely to the API key permission.
    """

    def has_permission(self, request, view) -> bool:
        return CodeEditorApiKeyPermission().has_permission(request, view)


# Backward‑compatible aliases for any stale imports.
CodeEditorAPIKeyPermission = CodeEditorApiKeyPermission
