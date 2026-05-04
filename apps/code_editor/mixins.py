"""Reusable mixins for scoped querysets and permissions.

These mixins provide hooks for restricting querysets based on the current
request context.  They are intentionally simple and should be extended or
overridden by views or viewsets that need tenant isolation or per‑owner
filtering.  By default they filter by the authenticated user or API key if
available, while allowing staff users to bypass these restrictions.
"""

from typing import Any
from django.db.models.query import QuerySet
from django.views.generic import View


class WorkspaceScopedQuerysetMixin:
    """Filter querysets by workspace membership for authenticated users.

    This mixin expects the view to define a ``get_queryset`` method returning
    a base QuerySet.  It will then attempt to filter that queryset based on
    a ``workspace`` relationship on the model.  If the request user is not a
    staff member, only objects where the user is a member of the workspace
    will be returned.  If no ``workspace`` attribute exists, the base
    queryset is returned unchanged.
    """

    def get_queryset(self) -> QuerySet:
        # Call the parent's get_queryset if available
        if hasattr(super(), "get_queryset"):
            qs: QuerySet = super().get_queryset()  # type: ignore[misc]
        else:
            raise NotImplementedError("WorkspaceScopedQuerysetMixin requires a get_queryset method")
        user = getattr(getattr(self, "request", None), "user", None)
        if not user or getattr(user, "is_staff", False):
            return qs
        # Only filter if the model has a workspace attribute
        model = qs.model
        if hasattr(model, "workspace"):
            return qs.filter(workspace__members=user)
        return qs


class RepositoryScopedQuerysetMixin:
    """Filter querysets by repository membership for authenticated users.

    Similar to WorkspaceScopedQuerysetMixin, this mixin attempts to filter
    querysets on a related ``repository`` or ``project`` relationship.
    Only objects within repositories belonging to projects the user has
    access to will be returned for non‑staff users.  Models without a
    ``repository`` or ``project`` attribute are returned unfiltered.
    """

    def get_queryset(self) -> QuerySet:
        if hasattr(super(), "get_queryset"):
            qs: QuerySet = super().get_queryset()  # type: ignore[misc]
        else:
            raise NotImplementedError("RepositoryScopedQuerysetMixin requires a get_queryset method")
        user = getattr(getattr(self, "request", None), "user", None)
        if not user or getattr(user, "is_staff", False):
            return qs
        model = qs.model
        if hasattr(model, "repository"):
            return qs.filter(repository__project__members=user)
        if hasattr(model, "project"):
            return qs.filter(project__members=user)
        return qs


class APIKeyOwnedQuerysetMixin:
    """Filter querysets by the API key used to authenticate the request.

    This mixin restricts results to objects related to the authenticated
    API key.  It expects the model to have an ``api_key`` foreign key.
    If no API key is present on the request, or the user is staff, the
    queryset is returned unfiltered.
    """

    def get_queryset(self) -> QuerySet:
        if hasattr(super(), "get_queryset"):
            qs: QuerySet = super().get_queryset()  # type: ignore[misc]
        else:
            raise NotImplementedError("APIKeyOwnedQuerysetMixin requires a get_queryset method")
        api_key = getattr(getattr(self, "request", None), "auth", None)
        user = getattr(getattr(self, "request", None), "user", None)
        if not api_key or (user and getattr(user, "is_staff", False)):
            return qs
        model = qs.model
        if hasattr(model, "api_key"):
            return qs.filter(api_key=api_key)
        return qs


class CodeEditorPermissionMixin(View):
    """Mixin providing a default permission class for API views.

    Views mixing this in will use the CodeEditorApiKeyPermission by default
    unless they override the ``permission_classes`` attribute or are marked
    as staff‑only.  This encourages explicit permission declarations and
    reduces the risk of accidentally leaving an endpoint public.
    """

    permission_classes = ()  # type: ignore[var‑annotated]

    def get_permissions(self) -> Any:
        # If view defines custom permissions, respect them
        if getattr(self, "permission_classes", None):
            return [permission() for permission in self.permission_classes]  # type: ignore[operator]
        # Fallback to API key permission
        from .permissions import CodeEditorApiKeyPermission
        return [CodeEditorApiKeyPermission()]