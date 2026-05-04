import time
from typing import Any, Dict, List, Optional

from ..models import CodeEditorRequestLog
from .router import RouterService
from .prompt_builder import PromptBuilderService
from .context_builder import ContextBuilderService
from .config import ConfigService
# Note: model profiles and token counter are not needed here yet
from ..exceptions import ProviderNotAvailableException, InvalidRequestException


class RerankService:
    """Service for handling reranking requests.

    Optionally accepts an ``api_key`` and ``user`` for usage logging.
    Input and output lengths in logs are recorded as token counts.
    """

    def __init__(self, api_key: Optional[Any] = None, user: Optional[Any] = None) -> None:
        self.router = RouterService()
        self.prompt_builder = PromptBuilderService()
        self.context_builder = ContextBuilderService()
        self.api_key = api_key
        self.user = user

    def rerank_documents(
        self,
        query: str,
        documents: List[str],
        model: Optional[str] = None,
        top_k: Optional[int] = None,
        **kwargs,
    ) -> List[Dict[str, float]]:
        start_time = time.time()
        provider: Optional[Any] = None
        try:
            # Validate inputs
            if not query:
                raise InvalidRequestException("Query cannot be empty")
            if not documents:
                raise InvalidRequestException("Documents cannot be empty")
            if len(documents) > 100:
                raise InvalidRequestException("Too many documents (max 100)")

            # Check rerank configuration
            rerank_config = ConfigService.get_rerank_config()
            if not rerank_config.get('enabled'):
                raise InvalidRequestException("Reranking is not enabled")

            # Build token-aware context
            limits = ConfigService.get_request_limits()
            max_input_tokens = limits.get('max_input_tokens') or limits.get('max_input_chars')
            clean_query, processed_docs = self.context_builder.build_rerank_context(
                query,
                documents,
                max_chars_per_doc=4000,
                max_total_chars=max_input_tokens,
            )

            # Get rerank provider via router, supporting optional override
            provider_override: Optional[str] = kwargs.pop('provider', None)
            if provider_override:
                provider = self.router.get_provider_by_name(provider_override)
                # Validate provider supports rerank
                if not provider or not provider.get_capabilities().get('rerank', False):
                    raise ProviderNotAvailableException(f"Provider '{provider_override}' does not support rerank or is unavailable")
            else:
                provider = self.router.get_provider('rerank')
                if not provider:
                    raise ProviderNotAvailableException("No rerank provider available")

            # Determine model and top_k from config or arguments
            model_name = model or rerank_config.get('model')
            top_k_val: Optional[int] = None
            # Use explicit argument first, then config
            if top_k is not None and top_k > 0:
                top_k_val = top_k
            elif rerank_config.get('top_k') is not None:
                top_k_val = rerank_config.get('top_k')

            # Call provider to perform reranking
            rerank_results = provider.rerank(
                query=clean_query,
                documents=processed_docs,
                model=model_name,
                top_k=top_k_val,
                **kwargs,
            )
            # Truncate to top_k results if provided
            if top_k_val and top_k_val > 0:
                rerank_results = rerank_results[:top_k_val]

            # Log success
            latency_ms = int((time.time() - start_time) * 1000)
            # Estimate token counts for input and output
            from ..utils.token_counter import count_tokens  # local import
            input_tokens = count_tokens([query] + documents)
            output_tokens = count_tokens('x' * len(str(rerank_results)))
            self._log_request(
                endpoint='/api/code-editor/rerank',
                provider=provider.name,
                model_name=model_name or 'unknown',
                request_kind='rerank',
                status='success',
                latency_ms=latency_ms,
                input_chars=input_tokens,
                output_chars=output_tokens,
            )
            return rerank_results
        except Exception as exc:
            # Log error
            latency_ms = int((time.time() - start_time) * 1000)
            from ..utils.token_counter import count_tokens  # local import
            input_tokens = count_tokens([query] + documents) if documents else 0
            self._log_request(
                endpoint='/api/code-editor/rerank',
                provider=getattr(provider, 'name', 'unknown') if provider else 'unknown',
                model_name=model or 'unknown',
                request_kind='rerank',
                status='error',
                latency_ms=latency_ms,
                input_chars=input_tokens,
                output_chars=0,
                error_message=str(exc),
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
        error_message: Optional[str] = None,
    ) -> None:
        """Log rerank requests with API key and user context.

        Error messages are truncated to 200 characters.  ``input_chars``
        and ``output_chars`` denote token counts rather than raw
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
        if getattr(self, 'api_key', None) is not None:
            log_kwargs['api_key'] = self.api_key
        if getattr(self, 'user', None) is not None and getattr(self.user, 'id', None):
            log_kwargs['user'] = self.user
        CodeEditorRequestLog.log_request(**log_kwargs)
