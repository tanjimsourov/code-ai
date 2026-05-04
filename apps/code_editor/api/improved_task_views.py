"""Improved task API endpoints for local development use."""

from __future__ import annotations
import uuid
from django.utils import timezone
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from ..permissions import CodeEditorApiKeyPermission
from rest_framework.response import Response
from rest_framework.pagination import PageNumberPagination

from ..models import Artifact, Repository, TaskRun, TaskStep, Project
from ..services.task_artifact_service import TaskArtifactService
from ..tasks import launch_task_run
from . import improved_serializers
from .improved_serializers import (
    ArtifactSerializer,
    CancelTaskSerializer,
    CreateTaskSerializer,
    TaskRunSerializer,
    TaskStepSerializer,
    TaskSummarySerializer,
    RepositorySerializer,
    ProjectSerializer,
)


class TaskPagination(PageNumberPagination):
    """Pagination for task lists."""
    page_size = 20
    page_size_query_param = 'page_size'
    max_page_size = 100


@api_view(['GET'])
@permission_classes([CodeEditorApiKeyPermission])
def health_check(request):
    """Health check endpoint for API availability."""
    return Response({
        'status': 'healthy',
        'timestamp': timezone.now().isoformat(),
        'version': '1.0.0',
        'endpoints': {
            'tasks': '/api/code-editor/tasks/',
            'repositories': '/api/code-editor/repositories/',
            'projects': '/api/code-editor/projects/',
            'artifacts': '/api/code-editor/artifacts/'
        }
    })


@api_view(['POST'])
@permission_classes([CodeEditorApiKeyPermission])
def create_task(request):
    """Create a task resource and launch execution asynchronously."""
    serializer = CreateTaskSerializer(data=request.data)
    if not serializer.is_valid():
        return Response({
            'error': {
                'message': 'Invalid request data',
                'type': 'ValidationError',
                'details': serializer.errors
            }
        }, status=status.HTTP_400_BAD_REQUEST)

    repository_id = serializer.validated_data['repository_id']
    
    try:
        repository = Repository.objects.get(id=repository_id)
    except Repository.DoesNotExist:
        return Response({
            'error': {
                'message': f'Repository {repository_id} does not exist',
                'type': 'NotFound',
                'suggestion': 'Check available repositories via /api/code-editor/repositories/'
            }
        }, status=status.HTTP_404_NOT_FOUND)

    # Create task
    task = TaskRun.objects.create(
        repository=repository,
        task_type=serializer.validated_data['task_type'],
        instruction=serializer.validated_data['instruction'].strip(),
        request_payload=serializer.validated_data.get('request_payload', {}),
        config=serializer.validated_data.get('config', {}),
        status='queued',
        current_stage='queued',
        summary='Task queued for execution',
    )

    # Launch task execution
    try:
        launch_info = launch_task_run(task)
        task.refresh_from_db()
    except Exception as exc:
        # If launch fails, update task status
        task.status = 'failed'
        task.error_message = f'Failed to launch task: {str(exc)}'
        task.save(update_fields=['status', 'error_message', 'updated_at'])
        
        return Response({
            'error': {
                'message': 'Failed to launch task execution',
                'type': 'LaunchError',
                'details': str(exc)
            }
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    # Return response
    response_serializer = TaskRunSerializer(task)
    return Response({
        'success': True,
        'data': response_serializer.data,
        'links': {
            'self': f'/api/code-editor/tasks/{task.id}/',
            'steps': f'/api/code-editor/tasks/{task.id}/steps/',
            'artifacts': f'/api/code-editor/tasks/{task.id}/artifacts/',
            'result': f'/api/code-editor/tasks/{task.id}/result/',
            'cancel': f'/api/code-editor/tasks/{task.id}/cancel/',
        },
        'launch_info': launch_info
    }, status=status.HTTP_201_CREATED)


@api_view(['GET'])
@permission_classes([CodeEditorApiKeyPermission])
def task_detail(request, task_id):
    """Get detailed information about a specific task."""
    try:
        task_uuid = uuid.UUID(task_id)
        task = TaskRun.objects.get(id=task_uuid)
    except (ValueError, TaskRun.DoesNotExist):
        return Response({
            'error': {
                'message': f'Task {task_id} not found',
                'type': 'NotFound'
            }
        }, status=status.HTTP_404_NOT_FOUND)

    serializer = TaskRunSerializer(task)
    return Response({
        'success': True,
        'data': serializer.data
    })


@api_view(['GET'])
@permission_classes([CodeEditorApiKeyPermission])
def task_list(request):
    """List all tasks with optional filtering and pagination."""
    queryset = TaskRun.objects.all().order_by('-created_at')
    
    # Apply filters
    status_filter = request.query_params.get('status')
    if status_filter:
        queryset = queryset.filter(status=status_filter)
    
    task_type_filter = request.query_params.get('task_type')
    if task_type_filter:
        queryset = queryset.filter(task_type=task_type_filter)
    
    repository_filter = request.query_params.get('repository')
    if repository_filter:
        try:
            queryset = queryset.filter(repository_id=int(repository_filter))
        except (TypeError, ValueError):
            pass
    
    # Paginate
    paginator = TaskPagination()
    page = paginator.paginate_queryset(queryset, request)
    
    serializer = TaskRunSerializer(page, many=True)
    return paginator.get_paginated_response({
        'success': True,
        'data': serializer.data
    })


@api_view(['GET'])
@permission_classes([CodeEditorApiKeyPermission])
def task_steps(request, task_id):
    """Get execution steps for a specific task."""
    try:
        task_uuid = uuid.UUID(task_id)
        task = TaskRun.objects.get(id=task_uuid)
    except (ValueError, TaskRun.DoesNotExist):
        return Response({
            'error': {
                'message': f'Task {task_id} not found',
                'type': 'NotFound'
            }
        }, status=status.HTTP_404_NOT_FOUND)

    steps = task.steps.all().order_by('order')
    serializer = TaskStepSerializer(steps, many=True)
    
    return Response({
        'success': True,
        'data': serializer.data,
        'summary': {
            'total_steps': steps.count(),
            'completed_steps': steps.filter(status='completed').count(),
            'failed_steps': steps.filter(status='failed').count(),
            'current_step': task.current_stage
        }
    })


@api_view(['GET'])
@permission_classes([CodeEditorApiKeyPermission])
def task_artifacts(request, task_id):
    """Get artifacts generated during task execution."""
    try:
        task_uuid = uuid.UUID(task_id)
        task = TaskRun.objects.get(id=task_uuid)
    except (ValueError, TaskRun.DoesNotExist):
        return Response({
            'error': {
                'message': f'Task {task_id} not found',
                'type': 'NotFound'
            }
        }, status=status.HTTP_404_NOT_FOUND)

    artifacts = task.artifacts.all().order_by('-created_at')
    
    # Filter by artifact type
    artifact_type = request.query_params.get('type')
    if artifact_type:
        artifacts = artifacts.filter(artifact_type=artifact_type)
    
    serializer = ArtifactSerializer(artifacts, many=True)
    
    return Response({
        'success': True,
        'data': serializer.data,
        'summary': {
            'total_artifacts': artifacts.count(),
            'types': list(artifacts.values_list('artifact_type', flat=True).distinct())
        }
    })


@api_view(['GET'])
@permission_classes([CodeEditorApiKeyPermission])
def artifact_detail(request, task_id, artifact_id):
    """Get detailed information about a specific artifact."""
    try:
        task_uuid = uuid.UUID(task_id)
        task = TaskRun.objects.get(id=task_uuid)
    except (ValueError, TaskRun.DoesNotExist):
        return Response({
            'error': {
                'message': f'Task {task_id} not found',
                'type': 'NotFound'
            }
        }, status=status.HTTP_404_NOT_FOUND)

    try:
        artifact_uuid = uuid.UUID(artifact_id)
        artifact = Artifact.objects.get(id=artifact_uuid, task=task)
    except (ValueError, Artifact.DoesNotExist):
        return Response({
            'error': {
                'message': f'Artifact {artifact_id} not found',
                'type': 'NotFound'
            }
        }, status=status.HTTP_404_NOT_FOUND)

    serializer = ArtifactSerializer(artifact)
    return Response({
        'success': True,
        'data': serializer.data
    })


@api_view(['GET'])
@permission_classes([CodeEditorApiKeyPermission])
def artifact_content(request, task_id, artifact_id):
    """Get the content of a specific artifact."""
    try:
        task_uuid = uuid.UUID(task_id)
        task = TaskRun.objects.get(id=task_uuid)
    except (ValueError, TaskRun.DoesNotExist):
        return Response({
            'error': {
                'message': f'Task {task_id} not found',
                'type': 'NotFound'
            }
        }, status=status.HTTP_404_NOT_FOUND)

    try:
        artifact_uuid = uuid.UUID(artifact_id)
        artifact = Artifact.objects.get(id=artifact_uuid, task=task)
    except (ValueError, Artifact.DoesNotExist):
        return Response({
            'error': {
                'message': f'Artifact {artifact_id} not found',
                'type': 'NotFound'
            }
        }, status=status.HTTP_404_NOT_FOUND)

    try:
        content = TaskArtifactService.read_content(artifact)
        
        return Response({
            'success': True,
            'data': {
                'content': content,
                'content_type': artifact.content_type,
                'size_bytes': len(content.encode('utf-8')) if isinstance(content, str) else len(content)
            }
        })
    except Exception as exc:
        return Response({
            'error': {
                'message': f'Failed to read artifact content: {str(exc)}',
                'type': 'ReadError'
            }
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['GET'])
@permission_classes([CodeEditorApiKeyPermission])
def task_result(request, task_id):
    """Get the final result of a completed task."""
    try:
        task_uuid = uuid.UUID(task_id)
        task = TaskRun.objects.get(id=task_uuid)
    except (ValueError, TaskRun.DoesNotExist):
        return Response({
            'error': {
                'message': f'Task {task_id} not found',
                'type': 'NotFound'
            }
        }, status=status.HTTP_404_NOT_FOUND)

    if task.status not in ['completed', 'failed', 'cancelled']:
        return Response({
            'error': {
                'message': f'Task {task_id} is not yet completed',
                'type': 'InvalidState',
                'current_status': task.status
            }
        }, status=status.HTTP_400_BAD_REQUEST)

    # Get best candidate if available
    best_candidate = None
    if task.status == 'completed':
        try:
            from ..models import CandidateScore
            best_score = CandidateScore.objects.filter(task=task).order_by('-final_score').first()
            if best_score:
                best_candidate = {
                    'candidate_key': best_score.candidate_patch.candidate_key,
                    'final_score': best_score.final_score,
                    'rank': best_score.rank,
                    'component_scores': {
                        'syntax': best_score.syntax_score,
                        'validation': best_score.validation_score,
                        'relevance': best_score.relevance_score,
                        'risk': best_score.risk_score,
                        'quality': best_score.quality_score
                    }
                }
        except Exception:
            pass

    return Response({
        'success': True,
        'data': {
            'task_id': str(task.id),
            'status': task.status,
            'result_summary': task.result_summary,
            'result_payload': task.result_payload,
            'summary': task.summary,
            'error_message': task.error_message,
            'completed_at': task.completed_at.isoformat() if task.completed_at else None,
            'duration_seconds': (
                (task.completed_at - task.started_at).total_seconds()
                if task.completed_at and task.started_at else None
            ),
            'best_candidate': best_candidate
        }
    })


@api_view(['POST'])
@permission_classes([CodeEditorApiKeyPermission])
def cancel_task(request, task_id):
    """Cancel a running task."""
    try:
        task_uuid = uuid.UUID(task_id)
        task = TaskRun.objects.get(id=task_uuid)
    except (ValueError, TaskRun.DoesNotExist):
        return Response({
            'error': {
                'message': f'Task {task_id} not found',
                'type': 'NotFound'
            }
        }, status=status.HTTP_404_NOT_FOUND)

    if task.status in ['completed', 'failed', 'cancelled', 'rolled_back']:
        return Response({
            'error': {
                'message': f'Task {task_id} cannot be cancelled (status: {task.status})',
                'type': 'InvalidState'
            }
        }, status=status.HTTP_400_BAD_REQUEST)

    # Get cancellation reason
    serializer = CancelTaskSerializer(data=request.data)
    reason = ''
    if serializer.is_valid():
        reason = serializer.validated_data.get('reason', '')

    # Cancel the task
    task.cancellation_requested = True
    task.cancellation_reason = reason or 'User requested cancellation'
    task.cancellation_requested_at = timezone.now()
    task.save(update_fields=[
        'cancellation_requested', 'cancellation_reason', 
        'cancellation_requested_at', 'updated_at'
    ])

    return Response({
        'success': True,
        'data': {
            'task_id': str(task.id),
            'status': 'cancel_requested',
            'message': 'Task cancellation requested'
        }
    })


@api_view(['GET'])
@permission_classes([CodeEditorApiKeyPermission])
def repository_list(request):
    """List all available repositories."""
    repositories = Repository.objects.all().order_by('name')
    serializer = RepositorySerializer(repositories, many=True)
    
    return Response({
        'success': True,
        'data': serializer.data,
        'summary': {
            'total_repositories': repositories.count()
        }
    })


@api_view(['GET'])
@permission_classes([CodeEditorApiKeyPermission])
def repository_detail(request, repository_id):
    """Get detailed information about a repository."""
    try:
        repository = Repository.objects.get(id=repository_id)
    except Repository.DoesNotExist:
        return Response({
            'error': {
                'message': f'Repository {repository_id} not found',
                'type': 'NotFound'
            }
        }, status=status.HTTP_404_NOT_FOUND)

    serializer = RepositorySerializer(repository)
    
    # Add additional stats
    stats = {
        'indexed_files': repository.indexed_files.count(),
        'total_chunks': sum(f.chunks.count() for f in repository.indexed_files.all()),
        'task_runs': repository.task_runs.count(),
        'last_indexed': repository.last_indexed_at.isoformat() if repository.last_indexed_at else None
    }
    
    return Response({
        'success': True,
        'data': {
            **serializer.data,
            'stats': stats
        }
    })


@api_view(['GET'])
@permission_classes([CodeEditorApiKeyPermission])
def project_list(request):
    """List all available projects."""
    projects = Project.objects.all().order_by('name')
    serializer = ProjectSerializer(projects, many=True)
    
    return Response({
        'success': True,
        'data': serializer.data,
        'summary': {
            'total_projects': projects.count()
        }
    })


@api_view(['GET'])
@permission_classes([CodeEditorApiKeyPermission])
def project_detail(request, project_id):
    """Get detailed information about a project."""
    try:
        project = Project.objects.get(id=project_id)
    except Project.DoesNotExist:
        return Response({
            'error': {
                'message': f'Project {project_id} not found',
                'type': 'NotFound'
            }
        }, status=status.HTTP_404_NOT_FOUND)

    serializer = ProjectSerializer(project)
    
    # Add additional stats
    stats = {
        'repository_count': project.repositories.count(),
        'task_runs': sum(repo.task_runs.count() for repo in project.repositories.all()),
        'is_active': project.is_active
    }
    
    return Response({
        'success': True,
        'data': {
            **serializer.data,
            'stats': stats
        }
    })


@api_view(['GET'])
@permission_classes([AllowAny])
def api_info(request):
    """Get API information and available endpoints."""
    return Response({
        'name': 'Code Editor API',
        'version': '1.0.0',
        'description': 'Local AI coding backend with task orchestration',
        'endpoints': {
            'tasks': {
                'list': 'GET /api/code-editor/tasks/',
                'create': 'POST /api/code-editor/tasks/',
                'detail': 'GET /api/code-editor/tasks/{id}/',
                'steps': 'GET /api/code-editor/tasks/{id}/steps/',
                'artifacts': 'GET /api/code-editor/tasks/{id}/artifacts/',
                'result': 'GET /api/code-editor/tasks/{id}/result/',
                'cancel': 'POST /api/code-editor/tasks/{id}/cancel/'
            },
            'repositories': {
                'list': 'GET /api/code-editor/repositories/',
                'detail': 'GET /api/code-editor/repositories/{id}/'
            },
            'projects': {
                'list': 'GET /api/code-editor/projects/',
                'detail': 'GET /api/code-editor/projects/{id}/'
            },
            'artifacts': {
                'detail': 'GET /api/code-editor/tasks/{task_id}/artifacts/{artifact_id}/',
                'content': 'GET /api/code-editor/tasks/{task_id}/artifacts/{artifact_id}/content/'
            },
            'system': {
                'health': 'GET /api/code-editor/health/',
                'info': 'GET /api/code-editor/info/'
            }
        },
        'features': [
            'Task orchestration with multiple candidates',
            'Intelligent file selection with symbol analysis',
            'Multi-strategy patch generation',
            'Comprehensive validation pipeline',
            'Candidate scoring and ranking',
            'Failing-test-first bug repair'
        ],
        'task_types': TaskRun.TASK_TYPES,
        'task_status_choices': TaskRun.STATUS_CHOICES
    })
