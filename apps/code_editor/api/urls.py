"""URL configuration for the code_editor API."""

from django.urls import path, include
from . import views, task_views, repository_views, retrieval_views, template_views
from .health_views import live_health, ready_health
from ..observability.metrics import metrics_view

urlpatterns = [
    # Core API endpoints
    path('health/', views.health_check, name='health_check'),
    path('models/', views.models_list, name='models_list'),
    path('providers/', views.providers_list, name='providers_list'),
    path('chat/', views.chat_completion, name='chat_completion'),
    path('completion/', views.text_completion, name='text_completion'),
    path('infill/', views.infill_code, name='infill_code'),
    path('edit/', views.edit_code, name='edit_code'),
    path('embed/', views.generate_embeddings, name='generate_embeddings'),
    path('rerank/', views.rerank_documents, name='rerank_documents'),
    path('template-command/', template_views.template_command, name='template_command'),
    
    # Repository and project management
    path('', include('code_editor.api.repository_urls')),
    path(
        'repositories/',
        include(('code_editor.api.repository_urls', 'legacy_repository'), namespace='legacy_repository'),
    ),
    
    # Retrieval and search
    path('retrieval/', include('code_editor.api.retrieval_urls')),
    path('search/', retrieval_views.search_chunks, name='search_chunks'),
    path('context/', retrieval_views.get_chunk_context, name='get_chunk_context'),
    path('files/', retrieval_views.search_files, name='search_files'),

    # Patch management
    path('patch/apply/', views.apply_patch, name='apply_patch'),
    path('patch/revert/', views.revert_patch, name='revert_patch'),
    
    # Task orchestration
    path('tasks/', include('code_editor.api.task_urls')),

    # Bulk operations for tasks and candidate patches
    path('bulk/', include('code_editor.api.bulk_urls')),
    
    # Improved task orchestration API (v2)
    path('v2/', include('code_editor.api.improved_urls')),
]

# Observability endpoints
urlpatterns += [
    path('health/live', live_health, name='health_live'),
    path('health/ready', ready_health, name='health_ready'),
    path('metrics/', metrics_view, name='metrics'),
]