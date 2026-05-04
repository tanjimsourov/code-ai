"""URL patterns for task views."""

from django.urls import path
from . import task_views

app_name = 'tasks'

urlpatterns = [
    # Task management
    path('', task_views.create_task, name='create_task'),
    path('<uuid:task_id>/', task_views.task_detail, name='task_detail'),
    path('<uuid:task_id>/steps/', task_views.task_steps, name='task_steps'),
    path('<uuid:task_id>/artifacts/', task_views.task_artifacts, name='task_artifacts'),
    path('<uuid:task_id>/patches/', task_views.task_patches, name='task_patches'),
    path('<uuid:task_id>/review/', task_views.task_artifacts_and_patches, name='task_artifacts_and_patches'),
    path('<uuid:task_id>/patches/<uuid:candidate_id>/approve/', task_views.approve_patch, name='approve_patch'),
    path('<uuid:task_id>/patches/<uuid:candidate_id>/reject/', task_views.reject_patch, name='reject_patch'),
    path('<uuid:task_id>/artifacts/<uuid:artifact_id>/', task_views.artifact_detail, name='artifact_detail'),
    path('<uuid:task_id>/artifacts/<uuid:artifact_id>/content/', task_views.artifact_content, name='artifact_content'),
    path('<uuid:task_id>/result/', task_views.task_result, name='task_result'),
    path('<uuid:task_id>/cancel/', task_views.cancel_task, name='cancel_task'),
]
