"""URL patterns for bulk operation views.

These patterns expose endpoints for performing bulk actions on tasks and
candidate patches.  Clients should POST the appropriate IDs to these
endpoints to cancel tasks or approve patches en masse.
"""

from django.urls import path

from . import bulk_views

app_name = 'bulk'

urlpatterns = [
    path('cancel-tasks/', bulk_views.bulk_cancel_tasks, name='bulk_cancel_tasks'),
    path('approve-patches/', bulk_views.bulk_approve_patches, name='bulk_approve_patches'),
]