import json
import time
from typing import Dict, Any, Generator, Optional
from django.http import StreamingHttpResponse, HttpResponse


class StreamingService:
    """Service for handling SSE streaming responses"""
    
    @staticmethod
    def create_sse_response(data_generator: Generator[Dict[str, Any], None, None]) -> StreamingHttpResponse:
        """Create Server-Sent Events response"""
        response = StreamingHttpResponse(
            StreamingService._sse_generator(data_generator),
            content_type='text/event-stream'
        )
        response['Cache-Control'] = 'no-cache'
        response['Connection'] = 'keep-alive'
        response['Access-Control-Allow-Origin'] = '*'
        response['Access-Control-Allow-Headers'] = 'Cache-Control'
        return response
    
    @staticmethod
    def _sse_generator(data_generator: Generator[Dict[str, Any], None, None]) -> Generator[str, None, None]:
        """Convert data generator to SSE format"""
        for data in data_generator:
            if data.get('type') == 'done':
                yield f"event: done\ndata: {json.dumps(data)}\n\n"
                break
            elif data.get('type') == 'error':
                yield f"event: error\ndata: {json.dumps(data)}\n\n"
                break
            else:
                # Regular content chunk
                chunk_data = {
                    'id': data.get('id', f"chunk_{int(time.time())}"),
                    'object': 'chat.completion.chunk',
                    'created': int(time.time()),
                    'model': data.get('model', 'unknown'),
                    'choices': [{
                        'index': 0,
                        'delta': {
                            'content': data.get('content', ''),
                            'role': data.get('role', 'assistant')
                        },
                        'finish_reason': None
                    }]
                }
                yield f"data: {json.dumps(chunk_data)}\n\n"
    
    @staticmethod
    def create_chunked_response(data_generator: Generator[Dict[str, Any], None, None]) -> StreamingHttpResponse:
        """Create chunked response for non-SSE streaming"""
        response = StreamingHttpResponse(
            (json.dumps(chunk) + '\n' for chunk in data_generator),
            content_type='application/json'
        )
        response['Cache-Control'] = 'no-cache'
        response['Transfer-Encoding'] = 'chunked'
        return response
    
    @staticmethod
    def wrap_provider_response_for_streaming(
        provider_response: Any,
        request_id: str,
        model: str
    ) -> Generator[Dict[str, Any], None, None]:
        """Wrap provider response for streaming.

        This helper accepts either a synchronous provider response (a
        dictionary in OpenAI format), a plain dict with a ``content``
        field, or a generator/iterator of chunks.  It normalizes all
        formats into a stream of dicts representing SSE events.  Each
        yielded dict has a ``type`` key of ``chunk``, ``done`` or
        ``error``.  The ``chunk`` event contains the incremental
        ``content`` emitted by the provider.  The ``done`` event
        signifies that the stream has completed and may include usage
        statistics.  Any unexpected format results in a single ``error``
        event.
        """
        # Import here to avoid circular import at module load time
        from ..providers.streaming import StreamChunk  # type: ignore
        from ..providers.utils import parse_text_completion_response  # type: ignore

        # If the provider_response is an iterator/generator (e.g. streaming)
        # we iterate over it and convert StreamChunk instances into
        # normalized events on the fly.  We detect iterables that are not
        # plain dicts to treat them as streaming sources.
        if hasattr(provider_response, '__iter__') and not isinstance(provider_response, dict):
            # Wrap the underlying generator
            for item in provider_response:
                try:
                    # Handle our StreamChunk dataclass
                    if isinstance(item, StreamChunk):
                        # Emit content if present
                        if item.content and not item.done:
                            yield {
                                'type': 'chunk',
                                'id': request_id,
                                'model': model,
                                'content': item.content,
                                'role': 'assistant',
                                'finish_reason': None
                            }
                        # When the provider signals completion, emit a
                        # final ``done`` event and break
                        if item.done:
                            yield {
                                'type': 'done',
                                'id': request_id,
                                'model': model,
                                'content': '',
                                'role': 'assistant',
                                'finish_reason': 'stop',
                                'usage': {}  # usage unknown for streaming
                            }
                            break
                        # Continue to next chunk
                        continue
                    # If the provider yields a dict (e.g. OpenAI delta),
                    # recurse into the dict-based handling below.  This
                    # allows streaming providers that emit OpenAI
                    # formatted messages to be processed correctly.
                    if isinstance(item, dict):
                        # Process a dict response as non-streaming
                        for subevent in StreamingService.wrap_provider_response_for_streaming(item, request_id, model):
                            yield subevent
                        # Once a dict is processed, the stream is
                        # complete (dict responses represent a full
                        # message).  Break out.
                        break
                    # Otherwise treat unknown items as raw text
                    text = str(item)
                    if text:
                        yield {
                            'type': 'chunk',
                            'id': request_id,
                            'model': model,
                            'content': text,
                            'role': 'assistant',
                            'finish_reason': None
                        }
                except Exception:
                    # On any exception during iteration, yield error and
                    # abort the stream
                    yield {
                        'type': 'error',
                        'id': request_id,
                        'model': model,
                        'content': '',
                        'role': 'assistant',
                        'error': 'Error while streaming provider response'
                    }
                    break
            return

        # At this point we have a non-streaming response assumed to be a
        # dict.  We parse various OpenAI/CodeEditor formats to produce
        # chunk/done events.  If response is missing expected fields we
        # attempt to extract content via helper functions.
        if isinstance(provider_response, dict):
            # OpenAI chat/completions format: choices array
            if 'choices' in provider_response:
                choices = provider_response['choices']
                if choices and isinstance(choices[0], dict):
                    choice = choices[0]
                    # Delta format (streaming JSON)
                    if 'delta' in choice and isinstance(choice['delta'], dict):
                        delta = choice['delta']
                        if 'content' in delta:
                            yield {
                                'type': 'chunk',
                                'id': request_id,
                                'model': model,
                                'content': delta['content'],
                                'role': 'assistant',
                                'finish_reason': None
                            }
                        # finish_reason signals end
                        if choice.get('finish_reason') is not None:
                            yield {
                                'type': 'done',
                                'id': request_id,
                                'model': model,
                                'content': '',
                                'role': 'assistant',
                                'finish_reason': choice.get('finish_reason'),
                                'usage': provider_response.get('usage', {})
                            }
                        return
                    # Message format (non-streaming chat)
                    if 'message' in choice and isinstance(choice['message'], dict):
                        message = choice['message']
                        if 'content' in message:
                            yield {
                                'type': 'chunk',
                                'id': request_id,
                                'model': model,
                                'content': message['content'],
                                'role': 'assistant',
                                'finish_reason': None
                            }
                        # finish_reason at non-streaming end
                        yield {
                            'type': 'done',
                            'id': request_id,
                            'model': model,
                            'content': '',
                            'role': 'assistant',
                            'finish_reason': choice.get('finish_reason', 'stop'),
                            'usage': provider_response.get('usage', {})
                        }
                        return
                    # Text format (non-streaming completions)
                    if 'text' in choice:
                        text = choice.get('text') or ''
                        if text:
                            yield {
                                'type': 'chunk',
                                'id': request_id,
                                'model': model,
                                'content': text,
                                'role': 'assistant',
                                'finish_reason': None
                            }
                        yield {
                            'type': 'done',
                            'id': request_id,
                            'model': model,
                            'content': '',
                            'role': 'assistant',
                            'finish_reason': choice.get('finish_reason', 'stop'),
                            'usage': provider_response.get('usage', {})
                        }
                        return
                # If choices is empty or not a list we fall through
            # Generic ``content`` key as fallback
            if 'content' in provider_response:
                content = provider_response['content'] or ''
                # Emit content in one chunk or chunk it artificially
                if content:
                    yield {
                        'type': 'chunk',
                        'id': request_id,
                        'model': model,
                        'content': content,
                        'role': 'assistant',
                        'finish_reason': None
                    }
                # Always emit done
                yield {
                    'type': 'done',
                    'id': request_id,
                    'model': model,
                    'content': '',
                    'role': 'assistant',
                    'finish_reason': provider_response.get('finish_reason', 'stop'),
                    'usage': provider_response.get('usage', {
                        'prompt_tokens': StreamingService.estimate_tokens(content),
                        'completion_tokens': StreamingService.estimate_tokens(content),
                        'total_tokens': 2 * StreamingService.estimate_tokens(content)
                    })
                }
                return
            # Attempt to parse with helper for arbitrary dicts
            try:
                text = parse_text_completion_response(provider_response)
                if text:
                    yield {
                        'type': 'chunk',
                        'id': request_id,
                        'model': model,
                        'content': text,
                        'role': 'assistant',
                        'finish_reason': None
                    }
                yield {
                    'type': 'done',
                    'id': request_id,
                    'model': model,
                    'content': '',
                    'role': 'assistant',
                    'finish_reason': provider_response.get('finish_reason', 'stop'),
                    'usage': provider_response.get('usage', {})
                }
            except Exception:
                # Could not parse content
                yield {
                    'type': 'error',
                    'id': request_id,
                    'model': model,
                    'content': '',
                    'role': 'assistant',
                    'error': 'Invalid response format from provider'
                }
            return
        # If provider_response is not iterable and not a dict, treat as raw text
        text = str(provider_response) if provider_response is not None else ''
        if text:
            yield {
                'type': 'chunk',
                'id': request_id,
                'model': model,
                'content': text,
                'role': 'assistant',
                'finish_reason': None
            }
        yield {
            'type': 'done',
            'id': request_id,
            'model': model,
            'content': '',
            'role': 'assistant',
            'finish_reason': 'stop',
            'usage': {}
        }
    
    @staticmethod
    def create_non_streaming_response(provider_response: Dict[str, Any], request_id: str, model: str) -> Dict[str, Any]:
        """Create non-streaming response in OpenAI format"""
        return {
            'id': f"chatcmpl-{int(time.time())}",
            'object': 'chat.completion',
            'created': int(time.time()),
            'model': model,
            'choices': [{
                'index': 0,
                'message': {
                    'role': 'assistant',
                    'content': provider_response.get('content', ''),
                },
                'finish_reason': provider_response.get('finish_reason', 'stop')
            }],
            'usage': provider_response.get('usage', {
                'prompt_tokens': 0,  # Would need actual token counting
                'completion_tokens': 0,
                'total_tokens': 0
            })
        }
    
    @staticmethod
    def estimate_tokens(text: str) -> int:
        """Estimate token count for text"""
        if not text:
            return 0
        # Rough estimation: ~4 characters per token for code
        return max(1, len(text) // 4)
    
    @staticmethod
    def format_usage_stats(input_text: str, output_text: str, model: str) -> Dict[str, int]:
        """Format usage statistics"""
        input_tokens = StreamingService.estimate_tokens(input_text)
        output_tokens = StreamingService.estimate_tokens(output_text)
        
        return {
            'prompt_tokens': input_tokens,
            'completion_tokens': output_tokens,
            'total_tokens': input_tokens + output_tokens
        }
