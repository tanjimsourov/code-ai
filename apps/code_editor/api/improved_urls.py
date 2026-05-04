"""Improved URL patterns for the enhanced code_editor API."""

from django.urls import path
from . import improved_task_views as views

urlpatterns = [
    # System endpoints
    path('health/', views.health_check, name='health_check'),
    path('info/', views.api_info, name='api_info'),
    
    # Task endpoints
    path('tasks/', views.task_list, name='task_list'),
    path('tasks/create/', views.create_task, name='create_task'),
    path('tasks/<uuid:task_id>/', views.task_detail, name='task_detail'),
    path('tasks/<uuid:task_id>/steps/', views.task_steps, name='task_steps'),
    path('tasks/<uuid:task_id>/artifacts/', views.task_artifacts, name='task_artifacts'),
    path('tasks/<uuid:task_id>/result/', views.task_result, name='task_result'),
    path('tasks/<uuid:task_id>/cancel/', views.cancel_task, name='cancel_task'),
    
    # Artifact endpoints
    path('tasks/<uuid:task_id>/artifacts/<uuid:artifact_id>/', views.artifact_detail, name='artifact_detail'),
    path('tasks/<uuid:task_id>/artifacts/<uuid:artifact_id>/content/', views.artifact_content, name='artifact_content'),
    
    # Repository endpoints
    path('repositories/', views.repository_list, name='repository_list'),
    path('repositories/<int:repository_id>/', views.repository_detail, name='repository_detail'),
    
    # Project endpoints
    path('projects/', views.project_list, name='project_list'),
    path('projects/<int:project_id>/', views.project_detail, name='project_detail'),
]
