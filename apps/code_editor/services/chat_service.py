import time
from typing import Dict, Any, List, Optional
from django.utils import timezone
from ..models import CodeEditorRequestLog
from ..utils.token_counter import count_tokens
from .router import RouterService
from .prompt_builder import PromptBuilderService
from .context_builder import ContextBuilderService
from .config import ConfigService
from .model_profiles import get_model_profile
from .context_pack_builder import ContextPackBuilderService
from ..models import Repository, Project
from ..exceptions import InvalidRequestException, ProviderNotAvailableException


class ChatService:
    """Service for handling chat completion requests.

    Optionally accepts an ``api_key`` and ``user`` for logging and
    quota attribution.  When provided, these values are stored on
    the service instance and passed through to request logging.  The
    input and output lengths logged are token estimates rather than
    raw character counts, using the ``TokenCounter`` utility.
    """

    def __init__(self, api_key: Optional[Any] = None, user: Optional[Any] = None) -> None:
        self.router = RouterService()
        self.prompt_builder = PromptBuilderService()
        self.context_builder = ContextBuilderService()
        # Capture API key and user for logging
        self.api_key = api_key
        self.user = user
    
    def chat_completion(
        self,
        messages: List[Dict[str, str]],
        system_prompt: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        stream: bool = False,
        **kwargs
    ) -> Dict[str, Any]:
        """
        Handle chat completion request.

        Supports optional ``provider`` and ``model`` overrides via
        keyword arguments.  When provided, the specified provider is
        used instead of the default provider for chat requests.  The
        specified model (if any) supersedes the provider's default
        model configuration.  If the override provider does not exist
        or does not support chat, a ``ProviderNotAvailableException``
        is raised.  Similarly, if the override model is not found
        among the provider's models, an ``InvalidRequestException`` may
        be raised.
        """
        start_time = time.time()
        
        try:
            # Validate input
            if not messages:
                raise InvalidRequestException("Messages cannot be empty")
            
            # Determine request limits and model profile
            limits = ConfigService.get_request_limits()
            # Determine provider override
            provider_override: Optional[str] = kwargs.pop('provider', None)
            model_override: Optional[str] = kwargs.pop('model', None)
            provider = None
            if provider_override:
                # If an explicit provider is requested, fetch it directly
                provider = self.router.get_provider_by_name(provider_override)
                if not provider or not provider.get_capabilities().get('chat', False):
                    raise ProviderNotAvailableException(f"Provider '{provider_override}' does not support chat or is unavailable")
            else:
                provider = self.router.get_provider('chat')
                if not provider:
                    raise ProviderNotAvailableException("No chat provider available")
            # Determine model name (override or default)
            model_name = model_override or provider.config.get('model')
            # If a model override was provided, validate that the provider offers it
            if model_override:
                try:
                    model_info = provider.get_model_info(model_override)
                except Exception:
                    model_info = None
                if not model_info:
                    raise InvalidRequestException(f"Model '{model_override}' not found for provider '{provider.name}'")
            profile = get_model_profile(model_name)
            # Determine desired output token count: either provided by caller,
            # environment default, or the profile default; also respect the
            # absolute ceiling from environment to avoid overflows.
            env_max_tokens = limits.get('max_tokens') or 0
            if max_tokens:
                output_tokens = min(max_tokens, env_max_tokens) if env_max_tokens else max_tokens
            else:
                # Use the smaller of the profile default and environment ceiling
                default_out = profile.default_max_output_tokens
                if env_max_tokens:
                    output_tokens = min(default_out, env_max_tokens)
                else:
                    output_tokens = default_out
            # Compute the maximum input token budget by subtracting the
            # output token allowance from the model's context window.  Also
            # respect any global limit from the environment (max_input_tokens)
            global_input_budget = limits.get('max_input_tokens') or limits.get('max_input_chars')
            # Avoid negative budgets
            model_input_budget = max(1, profile.context_window_tokens - output_tokens)
            if global_input_budget:
                max_input_tokens = min(model_input_budget, global_input_budget)
            else:
                max_input_tokens = model_input_budget

            # Optionally build a context pack and prepend it as a system message
            repository_ids = kwargs.pop('repository_ids', None)
            project_id = kwargs.pop('project_id', None)
            target_files = kwargs.pop('target_files', None)
            include_pack = kwargs.pop('include_context_pack', False)
            retrieved_chunks = kwargs.pop('retrieved_chunks', None)
            repositories_param = kwargs.pop('repositories', None)
            # Build context pack only if requested
            if include_pack and (repositories_param or repository_ids or project_id):
                # Resolve repositories either from injected list, explicit ids or via project
                repos: List[Repository] = []
                try:
                    if repositories_param:
                        # Caller can pass Repository objects directly for testing
                        repos = list(repositories_param)
                    elif repository_ids:
                        repos = list(Repository.objects.filter(id__in=repository_ids))
                    elif project_id:
                        # Fetch all repositories for the project
                        from ..models import Project as _Project  # local import to avoid circular
                        proj = _Project.objects.filter(id=project_id).first()
                        if proj:
                            repos = list(proj.repositories.all())
                except Exception:
                    repos = []
                # Only build pack if there are repositories
                if repos:
                    # Determine token budget equal to max_input_tokens for pack
                    builder = ContextPackBuilderService()
                    # Use the last user message as instruction for context
                    user_instr = ''
                    for m in reversed(messages):
                        if m.get('role') == 'user':
                            user_instr = m.get('content', '')
                            break
                    pack = builder.build_context_pack(
                        instruction=user_instr,
                        repositories=repos,
                        target_files=target_files,
                        retrieved_chunks=retrieved_chunks,
                        token_budget=max_input_tokens
                    )
                    pack_text = builder.render_context_pack(pack)
                    context_message = {'role': 'system', 'content': pack_text}
                    messages = [context_message] + messages
            # Build context with token limits
            context_messages = self.context_builder.build_chat_context(
                messages, max_input_tokens
            )
            # Build prompt with system message
            prompt_messages = self.prompt_builder.build_chat_prompt(
                context_messages, system_prompt
            )
            # Make request to provider.  If ``stream`` is True, this may
            # return a generator yielding streaming chunks.  We defer
            # logging until the stream has completed so that we can
            # compute the total output length.  For non-streaming
            # responses, we log immediately after the call.
            response = provider.chat_completion(
                messages=prompt_messages,
                model=model_name,
                temperature=temperature,
                max_tokens=output_tokens,
                stream=stream,
                **kwargs
            )
            # If streaming, wrap the provider response in a generator that
            # handles logging once the stream ends.
            if stream:
                # Local variables for capturing closure values
                provider_name = provider.name
                # Use the resolved model name rather than provider default
                model_cfg = model_name
                input_char_count = sum(len(msg.get('content', '')) for msg in messages)

                def stream_wrapper():
                    output_chars_total = 0
                    try:
                        # Iterate over the provider's streaming output
                        for chunk in response:
                            from ..providers.streaming import StreamChunk as _StreamChunk  # type: ignore
                            from ..providers.utils import parse_text_completion_response as _parse  # type: ignore
                            if isinstance(chunk, _StreamChunk):
                                output_chars_total += len(chunk.content or '')
                                yield chunk
                                if chunk.done:
                                    break
                                continue
                            if isinstance(chunk, dict):
                                try:
                                    text = _parse(chunk) or ''
                                except Exception:
                                    text = ''
                                output_chars_total += len(text)
                                yield chunk
                                break
                            text = str(chunk)
                            output_chars_total += len(text)
                            yield chunk
                        # Logging on successful completion
                        latency_ms = int((time.time() - start_time) * 1000)
                        # Estimate tokens for input and output
                        input_tokens = count_tokens([msg.get('content', '') for msg in messages])
                        # Approximate output tokens based on accumulated characters
                        # Use count_tokens on a string of length equal to output_chars_total
                        output_tokens = count_tokens('x' * output_chars_total)
                        self._log_request(
                            endpoint='/api/code-editor/chat',
                            provider=provider_name,
                            model_name=model_cfg,
                            request_kind='chat',
                            status='success',
                            latency_ms=latency_ms,
                            input_chars=input_tokens,
                            output_chars=output_tokens
                        )
                    except Exception as e:
                        latency_ms = int((time.time() - start_time) * 1000)
                        # Compute input tokens even on error
                        input_tokens = count_tokens([msg.get('content', '') for msg in messages])
                        self._log_request(
                            endpoint='/api/code-editor/chat',
                            provider=provider_name,
                            model_name=model_cfg,
                            request_kind='chat',
                            status='error',
                            latency_ms=latency_ms,
                            input_chars=input_tokens,
                            output_chars=0,
                            error_message=str(e)
                        )
                        raise
                return stream_wrapper()
            else:
                # Non-streaming response: compute output length and log
                output_chars = 0
                # Attempt to extract content length for logging
                try:
                    from ..providers.utils import parse_text_completion_response as _parse  # type: ignore
                    output_text = _parse(response) or ''
                    output_chars = len(output_text)
                except Exception:
                    # Fallback: length of string representation
                    output_chars = len(str(response))
                latency_ms = int((time.time() - start_time) * 1000)
                # Estimate token counts for input and output
                input_tokens = count_tokens([msg.get('content', '') for msg in messages])
                output_tokens = count_tokens('x' * output_chars)
                self._log_request(
                    endpoint='/api/code-editor/chat',
                    provider=provider.name,
                    model_name=model_name,
                    request_kind='chat',
                    status='success',
                    latency_ms=latency_ms,
                    input_chars=input_tokens,
                    output_chars=output_tokens
                )
                return response
            
        except Exception as e:
            # Calculate latency
            latency_ms = int((time.time() - start_time) * 1000)
            # Compute input tokens even on error
            input_tokens = count_tokens([msg.get('content', '') for msg in messages]) if messages else 0
            self._log_request(
                endpoint='/api/code-editor/chat',
                provider=getattr(provider, 'name', 'unknown') if 'provider' in locals() else 'unknown',
                model_name=getattr(provider, 'config', {}).get('model', 'unknown') if 'provider' in locals() else 'unknown',
                request_kind='chat',
                status='error',
                latency_ms=latency_ms,
                input_chars=input_tokens,
                output_chars=0,
                error_message=str(e)
            )
            raise
    
    def _log_request(
        self,
        endpoint: str,
        provider: str,
        model_name: str,
        request_kind: str,
        status: str,
        latency_ms: int,
        input_chars: int,
        output_chars: int,
        error_message: Optional[str] = None
    ) -> None:
        """Log the request with associated API key and user.

        Token counts are passed via the ``input_chars`` and
        ``output_chars`` fields for backward compatibility.  If an
        API key or user was provided at construction, they are
        included in the log entry.  Error messages are truncated to
        200 characters to avoid leaking sensitive details.
        """
        log_kwargs = {
            'endpoint': endpoint,
            'provider': provider,
            'model_name': model_name,
            'request_kind': request_kind,
            'status': status,
            'latency_ms': latency_ms,
            'input_chars': input_chars,
            'output_chars': output_chars,
        }
        if error_message:
            # Sanitize error message length
            log_kwargs['error_message'] = str(error_message)[:200]
        # Attach API key and user if available
        if self.api_key is not None:
            log_kwargs['api_key'] = self.api_key
        if self.user is not None and getattr(self.user, 'id', None):
            log_kwargs['user'] = self.user
        CodeEditorRequestLog.log_request(**log_kwargs)
