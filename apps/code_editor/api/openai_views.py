import time
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes, throttle_classes
from ..permissions import (
    CodeEditorApiKeyPermission,
    PublicOpenAIModelListingPermission,
)
from .throttles import AIThrottle
# Local single-user mode keeps these endpoints open without API-key auth.
from rest_framework.response import Response
from django.utils import timezone
from django.http import StreamingHttpResponse
from ..services import ChatService, CompletionService, ModelsService
from ..services.streaming_service import StreamingService
from ..exceptions import CodeEditorException


@api_view(['GET'])
@permission_classes([PublicOpenAIModelListingPermission])
def openai_models(request):
    """OpenAI-compatible models endpoint"""
    try:
        service = ModelsService()
        models = service.get_models()
        
        return Response({
            'object': 'list',
            'data': models
        })
        
    except CodeEditorException as e:
        return Response({
            'error': {
                'message': str(e),
                'type': e.__class__.__name__,
                'code': getattr(e, 'default_status_code', 500)
            }
        }, status=getattr(e, 'default_status_code', 500))
    except Exception as e:
        return Response({
            'error': {
                'message': 'Internal server error',
                'type': 'InternalServerError',
                'code': 500
            }
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['POST'])
@permission_classes([CodeEditorApiKeyPermission])
@throttle_classes([AIThrottle])
def openai_chat_completions(request):
    """OpenAI-compatible chat completions endpoint with streaming support"""
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
        data = request.data
        
        # Validate required fields
        if 'messages' not in data:
            return Response({
                'error': {
                    'message': 'Missing required field: messages',
                    'type': 'InvalidRequestError'
                }
            }, status=status.HTTP_400_BAD_REQUEST)
        
        messages = data['messages']
        model = data.get('model')
        temperature = data.get('temperature', 0.7)
        max_tokens = data.get('max_tokens')
        stream = data.get('stream', False)
        
        # Filter messages for OpenAI format
        system_prompt = None
        filtered_messages = []
        for message in messages:
            if message.get('role') == 'system':
                system_prompt = message.get('content')
            else:
                filtered_messages.append(message)
        
        # Generate a unique request identifier for tracing. Do this before calling
        # the service so it's available regardless of streaming mode.
        request_id = f"chatcmpl-{int(timezone.now().timestamp())}"

        # Call internal service
        service = ChatService()
        result = service.chat_completion(
            messages=filtered_messages,
            system_prompt=system_prompt,
            temperature=temperature,
            max_tokens=max_tokens,
            stream=stream
        )

        # Handle streaming response
        if stream:
            data_generator = StreamingService.wrap_provider_response_for_streaming(
                result, request_id, model or 'unknown'
            )
            return StreamingService.create_sse_response(data_generator)
        else:
            # Non-streaming response
            openai_response = StreamingService.create_non_streaming_response(
                result, request_id, model or 'unknown'
            )
            return Response(openai_response)
            
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
def openai_completions(request):
    """OpenAI-compatible text completions endpoint with streaming support"""
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
        # Extract OpenAI format data
        data = request.data
        
        if 'prompt' not in data:
            return Response({
                'error': {
                    'message': 'Missing required field: prompt',
                    'type': 'InvalidRequestError'
                }
            }, status=status.HTTP_400_BAD_REQUEST)
        
        prompt = data['prompt']
        model = data.get('model')
        temperature = data.get('temperature', 0.7)
        max_tokens = data.get('max_tokens')
        stream = data.get('stream', False)
        
        # Generate a unique request identifier for tracing
        request_id = f"cmpl-{int(timezone.now().timestamp())}"

        # Build internal prefix and suffix from the OpenAI ``prompt``.  The prompt
        # may be a string or an array of strings.  If a list is provided, the
        # first element becomes the prefix and the last element (if more than
        # one) becomes the suffix.  Any intermediate elements are concatenated
        # onto the prefix separated by newlines.  When a ``suffix`` field is
        # provided explicitly in the request body it takes precedence over
        # values derived from the prompt array.
        service = CompletionService(api_key=getattr(request, 'auth', None), user=request.user)
        suffix_value = None
        if isinstance(prompt, list):
            parts = [str(p) for p in prompt]
            if len(parts) == 1:
                prefix_value = parts[0]
            else:
                prefix_value = parts[0]
                if len(parts) > 2:
                    prefix_value += "\n" + "\n".join(parts[1:-1])
                suffix_value = parts[-1]
        else:
            prefix_value = str(prompt)
        # Override suffix if provided explicitly
        suffix_value = data.get('suffix', suffix_value)
        result = service.text_completion(
            prefix=prefix_value,
            suffix=suffix_value,
            temperature=temperature,
            max_tokens=max_tokens,
            stream=stream,
            repository_ids=data.get('repository_ids'),
            project_id=data.get('project_id'),
            target_files=data.get('target_files'),
            include_context_pack=data.get('include_context_pack', False),
            provider=data.get('provider'),
            model=data.get('model'),
        )

        if stream:
            data_generator = StreamingService.wrap_provider_response_for_streaming(
                result, request_id, model or 'unknown'
            )
            return StreamingService.create_sse_response(data_generator)
        else:
            openai_response = StreamingService.create_non_streaming_response(
                result, request_id, model or 'unknown'
            )
            return Response(openai_response)
            
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
def openai_embeddings(request):
    """OpenAI-compatible embeddings endpoint"""
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
        # Check if embeddings are enabled
        from ..services.config import ConfigService
        if not ConfigService.is_embeddings_enabled():
            return Response({
                'error': {
                    'message': 'Embeddings are not enabled',
                    'type': 'InvalidRequestError',
                    'code': 400
                }
            }, status=status.HTTP_400_BAD_REQUEST)
        
        # Extract OpenAI format data
        data = request.data
        
        # Handle both single string and list
        input_data = data.get('input', [])
        if isinstance(input_data, str):
            texts = [input_data]
        elif isinstance(input_data, list):
            texts = input_data
        else:
            return Response({
                'error': {
                    'message': 'Input must be a string or array of strings',
                    'type': 'InvalidRequestError',
                    'code': 400
                }
            }, status=status.HTTP_400_BAD_REQUEST)
        
        model = data.get('model')
        
        # Call internal service
        from ..services import EmbeddingsService
        service = EmbeddingsService()
        embeddings = service.generate_embeddings(
            texts=texts,
            model=model
        )
        
        # Convert to OpenAI format
        openai_response = {
            'object': 'list',
            'data': [
                {
                    'object': 'embedding',
                    'embedding': embedding,
                    'index': i
                }
                for i, embedding in enumerate(embeddings)
            ],
            'model': model or 'unknown',
            'usage': {
                'prompt_tokens': 0,  # Would need token counting
                'total_tokens': 0
            }
        }
        
        return Response(openai_response)
        
    except CodeEditorException as e:
        return Response({
            'error': {
                'message': str(e),
                'type': e.__class__.__name__,
                'code': getattr(e, 'default_status_code', 500)
            }
        }, status=getattr(e, 'default_status_code', 500))
    except Exception as e:
        return Response({
            'error': {
                'message': 'Internal server error',
                'type': 'InternalServerError',
                'code': 500
            }
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
