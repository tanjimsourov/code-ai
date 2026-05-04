"""URL patterns for repository views."""

from django.urls import path
from . import repository_views

app_name = 'repository'

urlpatterns = [
    # Projects
    path('projects/', repository_views.projects_list, name='projects_list'),
    path('projects/<int:project_id>/', repository_views.project_detail, name='project_detail'),
    path('projects/<int:project_id>/stats/', repository_views.project_stats, name='project_stats'),
    
    # Repositories (nested under projects)
    path('projects/<int:project_id>/repositories/', repository_views.repositories_list, name='repositories_list'),
    path('projects/<int:project_id>/repositories/<int:repository_id>/jobs/', repository_views.ingestion_jobs_list, name='ingestion_jobs_list'),
    path('projects/<int:project_id>/repositories/<int:repository_id>/jobs/<str:job_id>/', repository_views.ingestion_job_detail, name='ingestion_job_detail'),
    path('projects/<int:project_id>/repositories/<int:repository_id>/stats/', repository_views.ingestion_stats, name='repository_stats'),

    # Backward-compatible aliases
    path('repositories/<int:repository_id>/ingest/', repository_views.ingestion_jobs_list, name='create_ingestion_job'),
    path('repositories/<int:repository_id>/ingest/<str:job_id>/', repository_views.ingestion_job_detail, name='legacy_ingestion_job_detail'),
    path('repositories/<int:repository_id>/stats/', repository_views.ingestion_stats, name='legacy_repository_stats'),
]
