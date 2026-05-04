import time
import json
from pathlib import Path
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes, throttle_classes
from ..permissions import (
    CodeEditorApiKeyPermission,
    PublicModelListingPermission,
    PublicProviderListingPermission,
    AdminOrInternalPermission,
    CanApprovePatch,
    CanMutateRepository,
)
from .throttles import AIThrottle
# Local single-user mode keeps these endpoints open without API-key auth.
from rest_framework.response import Response
from django.utils import timezone
from django.http import StreamingHttpResponse
from ..services import ChatService, CompletionService, EditService, EmbeddingsService, RerankService, ModelsService
from ..services import InfillService
from ..services.streaming_service import StreamingService
from ..exceptions import CodeEditorException
from .serializers import (
    ChatRequestSerializer, CompletionRequestSerializer, EditRequestSerializer,
    EmbeddingsRequestSerializer, RerankRequestSerializer,
    HealthResponseSerializer, ModelResponseSerializer, ErrorResponseSerializer,
    InfillRequestSerializer,
    PatchApplySerializer, PatchRevertSerializer
)


@api_view(['GET'])
@permission_classes([
    # Only admin or staff users should access the detailed health check.
    # Use CodeEditorApiKeyPermission to require an API key in production.
    CodeEditorApiKeyPermission
])
def health_check(request):
    """Authenticated health check endpoint providing API status and provider health details.

    In production this endpoint requires authentication because it returns
    provider configuration details.  Anonymous callers should instead use
    ``/health/live`` or ``/health/ready`` from ``health_views``.
    """
    try:
        service = ModelsService()
        # Retrieve provider details including availability
        providers_info = service.get_providers()
        response_data = {
            'status': 'healthy',
            'timestamp': timezone.now().isoformat(),
            'version': '1.0.0',
            'providers': providers_info,
        }
        # Use serializer for backwards compatibility (providers as dict is accepted)
        serializer = HealthResponseSerializer(response_data)
        return Response(serializer.data)
    except Exception as e:
        return Response({
            'status': 'unhealthy',
            'error': str(e),
            'timestamp': timezone.now().isoformat()
        }, status=status.HTTP_503_SERVICE_UNAVAILABLE)


@api_view(['GET'])
@permission_classes([PublicModelListingPermission])
def models_list(request):
    """List available models.

    This endpoint is authenticated by default.  Set the environment
    variable ``CODE_EDITOR_PUBLIC_MODEL_LISTING`` to a truthy value to
    allow anonymous access.  When enabled the underlying permission
    class short‑circuits authentication and allows any caller.
    """
    try:
        service = ModelsService()
        models = service.get_models()
        serializer = ModelResponseSerializer(models, many=True)
        return Response({
            'object': 'list',
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
@permission_classes([PublicProviderListingPermission])
def providers_list(request):
    """List configured providers with metadata.

    Like ``models_list`` this endpoint is authenticated by default but
    can be exposed publicly by setting
    ``CODE_EDITOR_PUBLIC_PROVIDER_LISTING``.  Only a safe subset of
    provider metadata is returned.
    """
    try:
        service = ModelsService()
        providers = service.get_providers()
        # Convert dict to list for response
        providers_list = []
        for name, info in providers.items():
            entry = dict(info)
            providers_list.append(entry)
        return Response({
            'object': 'list',
            'data': providers_list
        })
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
def chat_completion(request):
    """Chat completion endpoint.

    This endpoint enforces API key authentication, per‑request quotas,
    and rate limits.  Calls to the underlying provider are delegated
    through ``ChatService``.  When streaming is requested, an SSE
    response is returned.
    """
    # Enforce daily quota and rate limit for the authenticated API key
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
        serializer = ChatRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        # Instantiate service with API key and user for logging
        service = ChatService(api_key=getattr(request, 'auth', None), user=request.user)
        result = service.chat_completion(
            messages=serializer.validated_data['messages'],
            system_prompt=serializer.validated_data.get('system_prompt'),
            temperature=serializer.validated_data.get('temperature', 0.7),
            max_tokens=serializer.validated_data.get('max_tokens'),
            stream=serializer.validated_data.get('stream', False),
            repository_ids=serializer.validated_data.get('repository_ids'),
            project_id=serializer.validated_data.get('project_id'),
            target_files=serializer.validated_data.get('target_files'),
            include_context_pack=serializer.validated_data.get('include_context_pack', False),
            provider=serializer.validated_data.get('provider'),
            model=serializer.validated_data.get('model'),
        )
        if serializer.validated_data.get('stream', False):
            # Handle streaming response
            request_id = f"chatcmpl-{int(time.time())}"
            data_generator = StreamingService.wrap_provider_response_for_streaming(
                result, request_id, serializer.validated_data.get('model', 'unknown')
            )
            return StreamingService.create_sse_response(data_generator)
        else:
            # Non-streaming response
            return Response({
                'object': 'chat.completion',
                'choices': [{
                    'index': 0,
                    'message': {
                        'role': 'assistant',
                        'content': result.get('content', ''),
                    },
                    'finish_reason': result.get('finish_reason', 'stop')
                }],
                'usage': {
                    'prompt_tokens': result.get('prompt_tokens', 0),
                    'completion_tokens': result.get('completion_tokens', 0),
                    'total_tokens': result.get('total_tokens', 0)
                }
            })
    except CodeEditorException:
        raise
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
def text_completion(request):
    """Text completion endpoint with rate limiting and quota enforcement."""
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
        serializer = CompletionRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        service = CompletionService(api_key=getattr(request, 'auth', None), user=request.user)
        result = service.text_completion(
            prefix=serializer.validated_data['prefix'],
            suffix=serializer.validated_data.get('suffix'),
            language=serializer.validated_data.get('language'),
            filename=serializer.validated_data.get('filename'),
            cursor_context=serializer.validated_data.get('cursor_context'),
            temperature=serializer.validated_data.get('temperature', 0.7),
            max_tokens=serializer.validated_data.get('max_tokens'),
            stream=serializer.validated_data.get('stream', False),
            repository_ids=serializer.validated_data.get('repository_ids'),
            project_id=serializer.validated_data.get('project_id'),
            target_files=serializer.validated_data.get('target_files'),
            include_context_pack=serializer.validated_data.get('include_context_pack', False),
            provider=serializer.validated_data.get('provider'),
            model=serializer.validated_data.get('model'),
        )
        # If streaming is requested, convert the provider response to SSE
        if serializer.validated_data.get('stream', False):
            request_id = f"cmpl-{int(time.time())}"
            model_name = serializer.validated_data.get('model', 'unknown')
            data_generator = StreamingService.wrap_provider_response_for_streaming(
                result, request_id, model_name
            )
            return StreamingService.create_sse_response(data_generator)
        return Response(result)
    except CodeEditorException:
        raise
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
def edit_code(request):
    """Code editing endpoint with quota and rate enforcement."""
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
        serializer = EditRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        service = EditService(api_key=getattr(request, 'auth', None), user=request.user)
        result = service.edit_code(
            instruction=serializer.validated_data['instruction'],
            code=serializer.validated_data['code'],
            language=serializer.validated_data.get('language'),
            filename=serializer.validated_data.get('filename'),
            temperature=serializer.validated_data.get('temperature', 0.3),
            max_tokens=serializer.validated_data.get('max_tokens'),
            repository_ids=serializer.validated_data.get('repository_ids'),
            project_id=serializer.validated_data.get('project_id'),
            target_files=serializer.validated_data.get('target_files'),
            include_context_pack=serializer.validated_data.get('include_context_pack', False),
            provider=serializer.validated_data.get('provider'),
            model=serializer.validated_data.get('model'),
        )
        return Response(result)
    except CodeEditorException:
        raise
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
def generate_embeddings(request):
    """Embeddings generation endpoint with quota and rate enforcement."""
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
        serializer = EmbeddingsRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        service = EmbeddingsService(api_key=getattr(request, 'auth', None), user=request.user)
        embeddings = service.generate_embeddings(
            texts=serializer.validated_data['texts'],
            model=serializer.validated_data.get('model'),
            task=serializer.validated_data.get('task'),
            provider=serializer.validated_data.get('provider'),
        )
        return Response({
            'object': 'list',
            'data': [
                {'object': 'embedding', 'embedding': embedding, 'index': i}
                for i, embedding in enumerate(embeddings)
            ]
        })
    except CodeEditorException:
        raise
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
def rerank_documents(request):
    """Document reranking endpoint with quota and rate limits."""
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
        serializer = RerankRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        service = RerankService(api_key=getattr(request, 'auth', None), user=request.user)
        results = service.rerank_documents(
            query=serializer.validated_data['query'],
            documents=serializer.validated_data['documents'],
            model=serializer.validated_data.get('model'),
            top_k=serializer.validated_data.get('top_k'),
            provider=serializer.validated_data.get('provider'),
        )
        return Response({
            'object': 'list',
            'data': results
        })
    except CodeEditorException:
        raise
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
def infill_code(request):
    """Fill‑in‑the‑middle (infill) code completion endpoint with quota and rate limits."""
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
        serializer = InfillRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        service = InfillService(api_key=getattr(request, 'auth', None), user=request.user)
        result = service.infill_code(
            prefix=serializer.validated_data['prefix'],
            suffix=serializer.validated_data['suffix'],
            language=serializer.validated_data.get('language'),
            filename=serializer.validated_data.get('filename'),
            cursor_context=serializer.validated_data.get('cursor_context'),
            temperature=serializer.validated_data.get('temperature', 0.7),
            max_tokens=serializer.validated_data.get('max_tokens'),
            model=serializer.validated_data.get('model'),
            provider=serializer.validated_data.get('provider'),
            stream=serializer.validated_data.get('stream', False)
        )
        if serializer.validated_data.get('stream', False):
            request_id = f"infill-{int(time.time())}"
            model_name = serializer.validated_data.get('model', 'unknown')
            data_generator = StreamingService.wrap_provider_response_for_streaming(
                result, request_id, model_name
            )
            return StreamingService.create_sse_response(data_generator)
        return Response(result)
    except CodeEditorException:
        raise
    except Exception as e:
        return Response({
            'error': {
                'message': str(e),
                'type': e.__class__.__name__
            }
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


# -----------------------------------------------------------------------------
# Patch management endpoints
# -----------------------------------------------------------------------------

@api_view(['POST'])
@permission_classes([CanApprovePatch])
def apply_patch(request):
    """Apply a generated candidate patch to the server-owned workspace."""
    serializer = PatchApplySerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    candidate_id = serializer.validated_data['candidate_id']
    try:
        from ..models import CandidatePatch
        candidate = CandidatePatch.objects.get(id=candidate_id)
    except CandidatePatch.DoesNotExist:
        return Response({'error': {'message': 'Candidate not found', 'type': 'NotFound'}}, status=status.HTTP_404_NOT_FOUND)
    from ..services.task_artifact_service import TaskArtifactService
    # Determine workspace directory from the candidate task.  We no longer
    # accept arbitrary workspace paths from clients.
    workspace_path = TaskArtifactService.task_dir(candidate.task) / 'workspace'
    # Apply patch via PatchService
    try:
        from ..services.patch_service import PatchService
        artifact = candidate.task.artifacts.filter(artifact_type='patch', candidate_patch=candidate).first()
        if not artifact:
            return Response({'error': {'message': 'No patch artifact found', 'type': 'NotFound'}}, status=status.HTTP_404_NOT_FOUND)
        PatchService.apply_patch(json.loads(
            TaskArtifactService.read_content(artifact)
        ), workspace_path)
        # update status
        candidate.status = 'applied'
        candidate.save(update_fields=['status'])
        return Response({'status': 'applied'})
    except Exception as exc:
        return Response({'error': {'message': str(exc), 'type': exc.__class__.__name__}}, status=status.HTTP_400_BAD_REQUEST)


@api_view(['POST'])
@permission_classes([CanMutateRepository])
def revert_patch(request):
    """Revert a previously applied candidate patch using server-owned paths."""
    serializer = PatchRevertSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    candidate_id = serializer.validated_data['candidate_id']
    try:
        from ..models import CandidatePatch
        candidate = CandidatePatch.objects.get(id=candidate_id)
    except CandidatePatch.DoesNotExist:
        return Response({'error': {'message': 'Candidate not found', 'type': 'NotFound'}}, status=status.HTTP_404_NOT_FOUND)
    try:
        from ..services.task_artifact_service import TaskArtifactService
        from ..services.patch_service import PatchService
        artifact = candidate.task.artifacts.filter(artifact_type='patch', candidate_patch=candidate).first()
        if not artifact:
            return Response({'error': {'message': 'No patch artifact found', 'type': 'NotFound'}}, status=status.HTTP_404_NOT_FOUND)
        patch_data = json.loads(TaskArtifactService.read_content(artifact))
        # Derive workspace and repository paths from server configuration
        workspace_path = TaskArtifactService.task_dir(candidate.task) / 'workspace'
        # Determine repository directory based on access_type and storage_path
        repo = candidate.task.repository
        from pathlib import Path as _Path
        if repo.access_type == 'local':
            # For local repositories, the URL should start with file://
            url = repo.url or ''
            if url.startswith('file://'):
                repo_path = _Path(url.replace('file://', ''))
            else:
                repo_path = _Path(url)
        else:
            if repo.storage_path:
                repo_path = _Path(repo.storage_path)
            else:
                return Response({'error': {'message': 'Repository storage path missing', 'type': 'InvalidRepository'}}, status=status.HTTP_400_BAD_REQUEST)
        PatchService.revert_patch(patch_data, workspace_path, repository_dir=repo_path)
        # update candidate status
        candidate.status = 'rolled_back'
        candidate.save(update_fields=['status'])
        return Response({'status': 'rolled_back'})
    except Exception as exc:
        return Response({'error': {'message': str(exc), 'type': exc.__class__.__name__}}, status=status.HTTP_400_BAD_REQUEST)
