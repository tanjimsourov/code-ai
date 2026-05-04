import time
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from ..permissions import CodeEditorApiKeyPermission
# Local single-user mode keeps these endpoints open without API-key auth.
from rest_framework.response import Response
from rest_framework.pagination import PageNumberPagination

class DefaultPagination(PageNumberPagination):
    page_size = 20
    page_size_query_param = "page_size"
    max_page_size = 100
from rest_framework.views import APIView
from django.utils import timezone
from ..services import RepositoryService, IngestionService
from ..exceptions import CodeEditorException, InvalidRequestException
from .repository_serializers import (
    ProjectSerializer, RepositorySerializer, CreateRepositorySerializer,
    IngestionJobSerializer, ProjectStatsSerializer, IngestionStatsSerializer
)


@api_view(['GET', 'POST'])
@permission_classes([CodeEditorApiKeyPermission])
def projects_list(request):
    """List or create projects"""
    if request.method == 'GET':
        # Apply pagination for project list
        projects = RepositoryService.list_projects(include_inactive=False)
        paginator = DefaultPagination()
        page = paginator.paginate_queryset(projects, request)
        serializer = ProjectSerializer(page, many=True)
        return paginator.get_paginated_response({
            'object': 'list',
            'data': serializer.data
        })
    elif request.method == 'POST':
        try:
            serializer = ProjectSerializer(data=request.data)
            serializer.is_valid(raise_exception=True)
            
            project = RepositoryService.create_project(
                name=serializer.validated_data['name'],
                description=serializer.validated_data.get('description', '')
            )
            
            response_serializer = ProjectSerializer(project)
            return Response({
                'object': 'project',
                'data': response_serializer.data
            }, status=status.HTTP_201_CREATED)
            
        except Exception as e:
            return Response({
                'error': {
                    'message': str(e),
                    'type': e.__class__.__name__
                }
            }, status=status.HTTP_400_BAD_REQUEST)


@api_view(['GET', 'PUT', 'DELETE'])
@permission_classes([CodeEditorApiKeyPermission])
def project_detail(request, project_id):
    """Get, update, or delete a project"""
    try:
        from ..models import Project
        project = Project.objects.get(id=project_id)
        
        if request.method == 'GET':
            serializer = ProjectSerializer(project)
            return Response({
                'object': 'project',
                'data': serializer.data
            })
        
        elif request.method == 'PUT':
            serializer = ProjectSerializer(project, data=request.data, partial=True)
            serializer.is_valid(raise_exception=True)
            
            serializer.save()
            
            return Response({
                'object': 'project',
                'data': serializer.data
            })
        
        elif request.method == 'DELETE':
            project.delete()
            return Response(status=status.HTTP_204_NO_CONTENT)
            
    except Project.DoesNotExist:
        return Response({
            'error': {
                'message': 'Project not found',
                'type': 'NotFound'
            }
        }, status=status.HTTP_404_NOT_FOUND)
    except Exception as e:
        return Response({
            'error': {
                'message': str(e),
                'type': e.__class__.__name__
            }
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['GET', 'POST'])
@permission_classes([CodeEditorApiKeyPermission])
def repositories_list(request, project_id):
    """List or create repositories for a project"""
    try:
        from ..models import Project
        project = Project.objects.get(id=project_id)
        
        if request.method == 'GET':
            # Use select_related to avoid N+1 queries and paginate results
            repositories = project.repositories.select_related("project").all()
            paginator = DefaultPagination()
            page = paginator.paginate_queryset(repositories, request)
            serializer = RepositorySerializer(page, many=True)
            return paginator.get_paginated_response({
                'object': 'list',
                'data': serializer.data
            })
        elif request.method == 'POST':
            serializer = CreateRepositorySerializer(data=request.data)
            serializer.is_valid(raise_exception=True)
            
            repository = RepositoryService.add_repository(
                project=project,
                **serializer.validated_data
            )
            
            response_serializer = RepositorySerializer(repository)
            return Response({
                'object': 'repository',
                'data': response_serializer.data
            }, status=status.HTTP_201_CREATED)
            
    except Project.DoesNotExist:
        return Response({
            'error': {
                'message': 'Project not found',
                'type': 'NotFound'
            }
        }, status=status.HTTP_404_NOT_FOUND)
    except Exception as e:
        return Response({
            'error': {
                'message': str(e),
                'type': e.__class__.__name__
            }
        }, status=status.HTTP_400_BAD_REQUEST)


@api_view(['GET', 'POST'])
@permission_classes([CodeEditorApiKeyPermission])
def ingestion_jobs_list(request, repository_id, project_id=None):
    """List or start ingestion jobs for a repository"""
    try:
        from ..models import Repository
        repository = Repository.objects.get(id=repository_id)
        if project_id is not None and repository.project_id != project_id:
            raise Repository.DoesNotExist
        
        if request.method == 'GET':
            # Paginate ingestion jobs and avoid N+1 queries
            jobs = repository.ingestion_jobs.select_related("repository").all().order_by('-created_at')
            paginator = DefaultPagination()
            page = paginator.paginate_queryset(jobs, request)
            serializer = IngestionJobSerializer(page, many=True)
            return paginator.get_paginated_response({
                'object': 'list',
                'data': serializer.data
            })
        elif request.method == 'POST':
            job = RepositoryService.start_ingestion_job(repository)
            serializer = IngestionJobSerializer(job)
            return Response({
                'object': 'ingestion_job',
                'data': serializer.data
            }, status=status.HTTP_201_CREATED)
            
    except Repository.DoesNotExist:
        return Response({
            'error': {
                'message': 'Repository not found',
                'type': 'NotFound'
            }
        }, status=status.HTTP_404_NOT_FOUND)
    except Exception as e:
        return Response({
            'error': {
                'message': str(e),
                'type': e.__class__.__name__
            }
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['GET'])
@permission_classes([CodeEditorApiKeyPermission])
def ingestion_job_detail(request, job_id, repository_id=None, project_id=None):
    """Get details of an ingestion job"""
    try:
        job = RepositoryService.get_ingestion_status(job_id)
        
        if not job:
            return Response({
                'error': {
                    'message': 'Job not found',
                    'type': 'NotFound'
                }
            }, status=status.HTTP_404_NOT_FOUND)

        if repository_id is not None and job.repository_id != repository_id:
            return Response({
                'error': {
                    'message': 'Job not found',
                    'type': 'NotFound'
                }
            }, status=status.HTTP_404_NOT_FOUND)

        if project_id is not None and job.repository.project_id != project_id:
            return Response({
                'error': {
                    'message': 'Job not found',
                    'type': 'NotFound'
                }
            }, status=status.HTTP_404_NOT_FOUND)
        
        serializer = IngestionJobSerializer(job)
        return Response({
            'object': 'ingestion_job',
            'data': serializer.data
        })
        
    except Exception as e:
        return Response({
            'error': {
                'message': str(e),
                'type': e.__class__.__name__
            }
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['GET'])
@permission_classes([CodeEditorApiKeyPermission])
def project_stats(request, project_id):
    """Get statistics for a project"""
    try:
        from ..models import Project
        project = Project.objects.get(id=project_id)
        
        stats = RepositoryService.get_project_stats(project)
        serializer = ProjectStatsSerializer(stats)
        
        return Response({
            'object': 'project_stats',
            'data': serializer.data
        })
        
    except Project.DoesNotExist:
        return Response({
            'error': {
                'message': 'Project not found',
                'type': 'NotFound'
            }
        }, status=status.HTTP_404_NOT_FOUND)
    except Exception as e:
        return Response({
            'error': {
                'message': str(e),
                'type': e.__class__.__name__
            }
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['GET'])
@permission_classes([CodeEditorApiKeyPermission])
def ingestion_stats(request, repository_id, project_id=None):
    """Get ingestion statistics for a repository"""
    try:
        from ..models import Repository
        repository = Repository.objects.get(id=repository_id)
        if project_id is not None and repository.project_id != project_id:
            raise Repository.DoesNotExist
        
        ingestion_service = IngestionService()
        stats = ingestion_service.get_ingestion_stats(repository.id)
        serializer = IngestionStatsSerializer(stats)
        
        return Response({
            'object': 'ingestion_stats',
            'data': serializer.data
        })
        
    except Repository.DoesNotExist:
        return Response({
            'error': {
                'message': 'Repository not found',
                'type': 'NotFound'
            }
        }, status=status.HTTP_404_NOT_FOUND)
    except Exception as e:
        return Response({
            'error': {
                'message': str(e),
                'type': e.__class__.__name__
            }
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
