import time
from typing import Dict, Any, Optional
from django.utils import timezone
from ..models import CodeEditorRequestLog
from .router import RouterService
from .prompt_builder import PromptBuilderService
from .context_builder import ContextBuilderService
from .config import ConfigService
from .model_profiles import get_model_profile
from ..exceptions import ProviderNotAvailableException, InvalidRequestException


class EditService:
    """Service for handling code edit requests.

    Accepts optional ``api_key`` and ``user`` parameters to record
    usage in request logs.  Input and output lengths logged are
    expressed as token estimates using the ``TokenCounter`` heuristic.
    """

    def __init__(self, api_key: Optional[Any] = None, user: Optional[Any] = None) -> None:
        self.router = RouterService()
        self.prompt_builder = PromptBuilderService()
        self.context_builder = ContextBuilderService()
        self.api_key = api_key
        self.user = user
    
    def edit_code(
        self,
        instruction: str,
        code: str,
        language: Optional[str] = None,
        filename: Optional[str] = None,
        temperature: float = 0.3,
        max_tokens: Optional[int] = None,
        **kwargs
    ) -> Dict[str, Any]:
        """Handle code edit request"""
        start_time = time.time()
        
        try:
            # Validate input
            if not instruction:
                raise InvalidRequestException("Instruction cannot be empty")
            if not code:
                raise InvalidRequestException("Code cannot be empty")
            
            # Determine limits and provider, with optional overrides
            limits = ConfigService.get_request_limits()
            provider_override: Optional[str] = kwargs.pop('provider', None)
            model_override: Optional[str] = kwargs.pop('model', None)
            provider = None
            if provider_override:
                provider = self.router.get_provider_by_name(provider_override)
                if not provider or not provider.get_capabilities().get('edit', False):
                    raise ProviderNotAvailableException(f"Provider '{provider_override}' does not support edit or is unavailable")
            else:
                provider = self.router.get_provider('edit')
                if not provider:
                    raise ProviderNotAvailableException("No edit provider available")
            model_name = model_override or provider.config.get('model')
            # Validate model override exists on provider
            if model_override:
                try:
                    model_info = provider.get_model_info(model_override)
                except Exception:
                    model_info = None
                if not model_info:
                    raise InvalidRequestException(f"Model '{model_override}' not found for provider '{provider.name}'")
            profile = get_model_profile(model_name)
            # Determine desired output tokens, respecting environment ceiling
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

            # Optionally build a context pack and prepend it to the instruction
            repository_ids = kwargs.pop('repository_ids', None)
            project_id = kwargs.pop('project_id', None)
            target_files = kwargs.pop('target_files', None)
            include_pack = kwargs.pop('include_context_pack', False)
            retrieved_chunks = kwargs.pop('retrieved_chunks', None)
            repositories_param = kwargs.pop('repositories', None)
            if include_pack and (repositories_param or repository_ids or project_id):
                from ..models import Repository as _Repository, Project as _Project  # local import to avoid cycles
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
                    user_instr = instruction or ''
                    pack = builder.build_context_pack(
                        instruction=user_instr,
                        repositories=repos,
                        target_files=target_files,
                        retrieved_chunks=retrieved_chunks,
                        token_budget=max_input_tokens
                    )
                    pack_text = builder.render_context_pack(pack)
                    instruction = pack_text + '\n\n' + instruction
            # Build context within token budget
            context = self.context_builder.build_edit_context(
                instruction, code, max_input_tokens
            )
            # Build prompt
            messages = self.prompt_builder.build_edit_prompt(
                instruction=context['instruction'],
                code=context['code'],
                language=language,
                filename=filename
            )
            # Make request
            response = provider.edit_code(
                instruction=context['instruction'],
                code=context['code'],
                model=model_name,
                temperature=temperature,
                max_tokens=output_tokens,
                **kwargs
            )
            
            # Calculate latency
            latency_ms = int((time.time() - start_time) * 1000)
            
            # Estimate token counts for input and output
            from ..utils.token_counter import count_tokens  # local import to avoid cycles
            input_tokens = count_tokens([instruction, code])
            output_tokens = count_tokens('x' * len(str(response)))
            # Log request
            self._log_request(
                endpoint='/api/code-editor/edit',
                provider=provider.name,
                model_name=model_name,
                request_kind='edit',
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
            from ..utils.token_counter import count_tokens  # local import
            input_tokens = count_tokens([instruction, code]) if instruction and code else 0
            # Log error
            self._log_request(
                endpoint='/api/code-editor/edit',
                provider=getattr(provider, 'name', 'unknown') if 'provider' in locals() else 'unknown',
                model_name=getattr(provider, 'config', {}).get('model', 'unknown') if 'provider' in locals() else 'unknown',
                request_kind='edit',
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
        """Log the edit request with API key and user context.

        Error messages are truncated to 200 characters.  ``input_chars``
        and ``output_chars`` denote token counts rather than raw
        characters.
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
