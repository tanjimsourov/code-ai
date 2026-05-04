import time
from typing import Dict, Any, Optional
from django.utils import timezone
from ..models import CodeEditorRequestLog
from ..utils.token_counter import count_tokens
from .router import RouterService
from .prompt_builder import PromptBuilderService
from .context_builder import ContextBuilderService
from .config import ConfigService
from .model_profiles import get_model_profile
from ..exceptions import ProviderNotAvailableException, InvalidRequestException


class CompletionService:
    """Service for handling text completion requests.

    Accepts optional ``api_key`` and ``user`` parameters to record
    usage in request logs.  Logged input and output lengths are
    reported as token estimates using the ``TokenCounter`` utility
    rather than raw character counts.
    """

    def __init__(self, api_key: Optional[Any] = None, user: Optional[Any] = None) -> None:
        self.router = RouterService()
        self.prompt_builder = PromptBuilderService()
        self.context_builder = ContextBuilderService()
        self.api_key = api_key
        self.user = user
    
    def text_completion(
        self,
        prefix: Optional[str] = None,
        suffix: Optional[str] = None,
        language: Optional[str] = None,
        filename: Optional[str] = None,
        cursor_context: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        stream: bool = False,
        prompt: Optional[str] = None,
        **kwargs
    ) -> Dict[str, Any]:
        """
        Handle text completion requests.

        This service accepts either a `prefix`/`suffix` pair or a single
        `prompt` parameter for compatibility with OpenAI-style requests.
        It builds a context-limited prompt and forwards it to the provider for
        completion. Upon success or failure, it logs the request and returns
        the provider response.
        """
        start_time = time.time()

        try:
            # Accept `prompt` as an alias for `prefix` when provided
            if prompt is not None and prefix is None:
                prefix = prompt

            # Validate that we have at least a prefix
            if not prefix:
                raise InvalidRequestException("Prefix cannot be empty")
            
            # Determine limits and provider, supporting overrides
            limits = ConfigService.get_request_limits()
            provider_override: Optional[str] = kwargs.pop('provider', None)
            model_override: Optional[str] = kwargs.pop('model', None)
            provider = None
            if provider_override:
                provider = self.router.get_provider_by_name(provider_override)
                if not provider or not provider.get_capabilities().get('completion', False):
                    raise ProviderNotAvailableException(f"Provider '{provider_override}' does not support completion or is unavailable")
            else:
                provider = self.router.get_provider('complete')
                if not provider:
                    raise ProviderNotAvailableException("No completion provider available")
            model_name = model_override or provider.config.get('model')
            # Validate model override exists on provider if provided
            if model_override:
                try:
                    model_info = provider.get_model_info(model_override)
                except Exception:
                    model_info = None
                if not model_info:
                    raise InvalidRequestException(f"Model '{model_override}' not found for provider '{provider.name}'")
            profile = get_model_profile(model_name)
            # Determine desired output tokens respecting environment ceiling
            env_max_tokens = limits.get('max_tokens') or 0
            if max_tokens:
                output_tokens = min(max_tokens, env_max_tokens) if env_max_tokens else max_tokens
            else:
                default_out = profile.default_max_output_tokens
                if env_max_tokens:
                    output_tokens = min(default_out, env_max_tokens)
                else:
                    output_tokens = default_out
            # Compute max input token budget
            global_input_budget = limits.get('max_input_tokens') or limits.get('max_input_chars')
            model_input_budget = max(1, profile.context_window_tokens - output_tokens)
            if global_input_budget:
                max_input_tokens = min(model_input_budget, global_input_budget)
            else:
                max_input_tokens = model_input_budget

            # Optionally build a context pack and prefix it to the code prefix
            repository_ids = kwargs.pop('repository_ids', None)
            project_id = kwargs.pop('project_id', None)
            target_files = kwargs.pop('target_files', None)
            include_pack = kwargs.pop('include_context_pack', False)
            retrieved_chunks = kwargs.pop('retrieved_chunks', None)
            repositories_param = kwargs.pop('repositories', None)
            if include_pack and (repositories_param or repository_ids or project_id):
                from ..models import Repository as _Repository, Project as _Project  # avoid circular import
                repos: List[_Repository] = []
                try:
                    if repositories_param:
                        repos = list(repositories_param)
                    elif repository_ids:
                        repos = list(_Repository.objects.filter(id__in=repository_ids))
                    elif project_id:
                        proj = _Project.objects.filter(id=project_id).first()
                        if proj:
                            repos = list(proj.repositories.all())
                except Exception:
                    repos = []
                if repos:
                    from .context_pack_builder import ContextPackBuilderService  # local import
                    builder = ContextPackBuilderService()
                    user_instr = prefix or ''
                    pack = builder.build_context_pack(
                        instruction=user_instr,
                        repositories=repos,
                        target_files=target_files,
                        retrieved_chunks=retrieved_chunks,
                        token_budget=max_input_tokens
                    )
                    pack_text = builder.render_context_pack(pack)
                    prefix = pack_text + '\n\n' + (prefix or '')
            # Build context limited by input tokens
            context = self.context_builder.build_completion_context(
                prefix, suffix, max_input_tokens
            )
            # Build prompt
            prompt = self.prompt_builder.build_completion_prompt(
                prefix=context['prefix'],
                suffix=context.get('suffix'),
                language=language,
                filename=filename,
                cursor_context=cursor_context
            )
            # Make request to provider.  If stream=True, the provider may
            # return a generator.  Defer logging until streaming is
            # complete so that output size can be measured.
            response = provider.text_completion(
                prompt=prompt,
                model=model_name,
                temperature=temperature,
                max_tokens=output_tokens,
                stream=stream,
                **kwargs
            )
            input_chars = len(prefix) + (len(suffix) if suffix else 0)
            # Streaming path
            if stream:
                provider_name = provider.name
                model_cfg = model_name
                def stream_wrapper():
                    output_chars_total = 0
                    try:
                        from ..providers.streaming import StreamChunk as _StreamChunk  # type: ignore
                        from ..providers.utils import parse_text_completion_response as _parse  # type: ignore
                        for chunk in response:
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
                        latency_ms = int((time.time() - start_time) * 1000)
                        # Estimate token counts
                        input_tokens = count_tokens([prefix or '', suffix or ''])
                        # Approximate output tokens from character count
                        output_tokens = count_tokens('x' * output_chars_total)
                        self._log_request(
                            endpoint='/api/code-editor/complete',
                            provider=provider_name,
                            model_name=model_cfg,
                            request_kind='complete',
                            status='success',
                            latency_ms=latency_ms,
                            input_chars=input_tokens,
                            output_chars=output_tokens
                        )
                    except Exception as e:
                        latency_ms = int((time.time() - start_time) * 1000)
                        input_tokens = count_tokens([prefix or '', suffix or ''])
                        self._log_request(
                            endpoint='/api/code-editor/complete',
                            provider=provider_name,
                            model_name=model_cfg,
                            request_kind='complete',
                            status='error',
                            latency_ms=latency_ms,
                            input_chars=input_tokens,
                            output_chars=0,
                            error_message=str(e)
                        )
                        raise
                return stream_wrapper()
            else:
                # Non-streaming: parse output size and log
                output_chars = 0
                try:
                    from ..providers.utils import parse_text_completion_response as _parse  # type: ignore
                    output_text = _parse(response) or ''
                    output_chars = len(output_text)
                except Exception:
                    output_chars = len(str(response))
                latency_ms = int((time.time() - start_time) * 1000)
                # Estimate token counts
                input_tokens = count_tokens([prefix or '', suffix or ''])
                output_tokens = count_tokens('x' * output_chars)
                self._log_request(
                    endpoint='/api/code-editor/complete',
                    provider=provider.name,
                    model_name=model_name,
                    request_kind='complete',
                    status='success',
                    latency_ms=latency_ms,
                    input_chars=input_tokens,
                    output_chars=output_tokens
                )
                return response
            
        except Exception as e:
            # Calculate latency
            latency_ms = int((time.time() - start_time) * 1000)
            
            # Estimate input tokens on error
            input_tokens = count_tokens([prefix or '', suffix or ''])
            # Log error
            self._log_request(
                endpoint='/api/code-editor/complete',
                provider=getattr(provider, 'name', 'unknown') if 'provider' in locals() else 'unknown',
                model_name=getattr(provider, 'config', {}).get('model', 'unknown') if 'provider' in locals() else 'unknown',
                request_kind='complete',
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
    ):
        """Log the request"""
        """Log the completion request with API key and user context.

        Error messages are truncated to 200 characters.  ``input_chars``
        and ``output_chars`` represent token estimates rather than raw
        character counts.
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
            log_kwargs['error_message'] = str(error_message)[:200]
        if self.api_key is not None:
            log_kwargs['api_key'] = self.api_key
        if self.user is not None and getattr(self.user, 'id', None):
            log_kwargs['user'] = self.user
        CodeEditorRequestLog.log_request(**log_kwargs)
