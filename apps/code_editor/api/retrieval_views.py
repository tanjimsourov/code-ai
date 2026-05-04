import time
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes, throttle_classes
from ..permissions import CodeEditorApiKeyPermission
from .throttles import AIThrottle
# Local single-user mode keeps these endpoints open without API-key auth.
from rest_framework.response import Response
from ..services import RetrievalService
from ..exceptions import CodeEditorException, InvalidRequestException
from .retrieval_serializers import (
    SearchRequestSerializer, SearchResponseSerializer, SearchResultSerializer,
    ContextRequestSerializer, ContextResponseSerializer,
    FileSearchRequestSerializer, FileSearchResultSerializer
)

# Import ValidationError for catching input validation issues.  Some test
# harnesses may provide only a stubbed rest_framework with limited API
# surface area.  Attempt to import ValidationError from DRF and fall
# back to a basic Exception subclass if unavailable.
try:
    from rest_framework.serializers import ValidationError  # type: ignore
except Exception:
    class ValidationError(Exception):  # type: ignore
        """Fallback validation error used when DRF is not installed"""
        pass


@api_view(['POST'])
@permission_classes([CodeEditorApiKeyPermission])
@throttle_classes([AIThrottle])
def search_chunks(request):
    """Search for relevant code chunks"""
    # Enforce daily quota and rate limit
    api_key = getattr(request, 'auth', None)
    if api_key:
        from ..services.quota_service import QuotaService
        try:
            QuotaService.enforce_limits_atomic(api_key)
        except Exception as exc:
            return Response({
                'error': {
                    'message': str(exc),
                    'type': exc.__class__.__name__,
                }
            }, status=status.HTTP_429_TOO_MANY_REQUESTS)

    start_time = time.time()
    try:
        serializer = SearchRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        # Require repository_ids to avoid unbounded searches
        repo_ids = serializer.validated_data.get('repository_ids')
        if not repo_ids:
            return Response({
                'error': {
                    'message': 'repository_ids parameter is required',
                    'type': 'InvalidRequestError'
                }
            }, status=status.HTTP_400_BAD_REQUEST)
        retrieval_service = RetrievalService()
        # Use default values when optional parameters are omitted. DRF will
        # include keys with ``None`` values for optional fields, so we use
        # ``get(..., default)`` to supply sensible defaults when not
        # provided.  This prevents KeyError when stubs are used in tests.
        results = retrieval_service.search_chunks(
            query=serializer.validated_data['query'],
            repository_ids=repo_ids,
            file_paths=serializer.validated_data.get('file_paths'),
            languages=serializer.validated_data.get('languages'),
            chunk_types=serializer.validated_data.get('chunk_types'),
            limit=serializer.validated_data.get('limit', 10),
            similarity_threshold=serializer.validated_data.get('similarity_threshold', 0.7),
            use_rerank=serializer.validated_data.get('use_rerank', True),
        )

        search_time_ms = int((time.time() - start_time) * 1000)

        response_serializer = SearchResponseSerializer({
            'results': results,
            'total': len(results),
            'query': serializer.validated_data['query'],
            'search_time_ms': search_time_ms
        })

        return Response(response_serializer.data)

    except ValidationError as ve:
        # Explicitly handle serializer validation errors with a 400 response.
        return Response({
            'error': {
                'message': str(ve),
                'type': ve.__class__.__name__,
            }
        }, status=status.HTTP_400_BAD_REQUEST)
    except Exception as e:
        return Response({
            'error': {
                'message': str(e),
                'type': e.__class__.__name__
            }
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['POST'])
@permission_classes([CodeEditorApiKeyPermission])
@throttle_classes([AIThrottle])
def get_chunk_context(request):
    """Get surrounding context for a chunk"""
    # Enforce daily quota and rate limit
    api_key = getattr(request, 'auth', None)
    if api_key:
        from ..services.quota_service import QuotaService
        try:
            QuotaService.enforce_limits_atomic(api_key)
        except Exception as exc:
            return Response({
                'error': {
                    'message': str(exc),
                    'type': exc.__class__.__name__,
                }
            }, status=status.HTTP_429_TOO_MANY_REQUESTS)

    try:
        serializer = ContextRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        
        retrieval_service = RetrievalService()
        context = retrieval_service.get_context_for_chunk(
            chunk_id=serializer.validated_data['chunk_id'],
            context_lines=serializer.validated_data['context_lines']
        )
        
        response_serializer = ContextResponseSerializer(context)
        return Response(response_serializer.data)
        
    except Exception as e:
        return Response({
            'error': {
                'message': str(e),
                'type': e.__class__.__name__
            }
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['POST'])
@permission_classes([CodeEditorApiKeyPermission])
@throttle_classes([AIThrottle])
def search_files(request):
    """Search chunks by file path pattern"""
    # Enforce daily quota and rate limit
    api_key = getattr(request, 'auth', None)
    if api_key:
        from ..services.quota_service import QuotaService
        try:
            QuotaService.enforce_limits_atomic(api_key)
        except Exception as exc:
            return Response({
                'error': {
                    'message': str(exc),
                    'type': exc.__class__.__name__,
                }
            }, status=status.HTTP_429_TOO_MANY_REQUESTS)

    try:
        serializer = FileSearchRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        repo_ids = serializer.validated_data.get('repository_ids')
        if not repo_ids:
            return Response({
                'error': {
                    'message': 'repository_ids parameter is required',
                    'type': 'InvalidRequestError'
                }
            }, status=status.HTTP_400_BAD_REQUEST)
        retrieval_service = RetrievalService()
        results = retrieval_service.search_by_file_path(
            file_path_pattern=serializer.validated_data['file_path_pattern'],
            repository_ids=repo_ids,
            limit=serializer.validated_data['limit']
        )
        
        # Convert to FileSearchResult format
        formatted_results = []
        for result in results:
            formatted_results.append({
                'chunk_id': result['chunk_id'],
                'file_path': result['file_path'],
                'repository_id': result['repository_id'],
                'repository_name': result['repository_name'],
                'content': result['content'],
                'start_line': result['start_line'],
                'end_line': result['end_line'],
                'chunk_type': result['chunk_type'],
                'language': result['language'],
                'token_count': result['token_count']
            })
        
        response_serializer = FileSearchResultSerializer(formatted_results, many=True)
        return Response({
            'object': 'list',
            'data': response_serializer.data,
            'total': len(formatted_results)
        })
        
    except Exception as e:
        return Response({
            'error': {
                'message': str(e),
                'type': e.__class__.__name__
            }
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
