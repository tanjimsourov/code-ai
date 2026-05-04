import time
from typing import Any, Dict, List, Optional

from ..models import CodeEditorRequestLog
from ..services.embed_client import EmbeddingClient, RerankClient
from ..services.config import ConfigService
from ..services.context_builder import ContextBuilderService
from ..utils.token_counter import TokenCounter
from ..exceptions import InvalidRequestException, ProviderNotAvailableException


class EmbeddingsService:
    """Service for handling embedding and lightweight rerank requests.

    Optionally accepts an ``api_key`` and ``user`` for usage logging.
    Token estimates are used for input and output lengths.  When
    provided, ``api_key`` and ``user`` are attached to request logs.
    """

    def __init__(self, api_key: Optional[Any] = None, user: Optional[Any] = None) -> None:
        self.embed_client = EmbeddingClient()
        self.rerank_client = RerankClient()
        self.api_key = api_key
        self.user = user

    def generate_embeddings(
        self,
        texts: List[str],
        model: Optional[str] = None,
        task: Optional[str] = None,
        provider: Optional[str] = None,
    ) -> List[List[float]]:
        """Generate embeddings for a list of texts.

        This method handles batching, retry logic, provider‑specific
        fallback, and deterministic pseudo‑embedding generation when
        embeddings are disabled.  It uses the configured model unless
        a model override is provided.  The input texts are truncated
        based on the request limits before embedding.

        :param texts: List of input strings
        :param model: Optional explicit model name to override config
        :param task: Unused placeholder for API compatibility
        :returns: List of embedding vectors corresponding to the
          truncated input texts
        :raises ProviderNotAvailableException: If embeddings are
          enabled and all API calls fail
        """
        # If a provider override is requested and it does not match the configured provider, reject
        if provider:
            # Compare against configured provider type
            current_provider = ConfigService.get_embeddings_config().get('provider', 'generic')
            if provider != current_provider:
                raise InvalidRequestException(f"Provider override '{provider}' is not supported for embeddings")

        # If embeddings are disabled, return deterministic pseudo‑embeddings
        config = ConfigService.get_embeddings_config()
        if not config.get('enabled'):
            return [self._pseudo_embedding(t) for t in texts]
        if not texts:
            return []
        limits = ConfigService.get_request_limits()
        max_input_tokens = limits.get('max_input_tokens') or limits.get('max_input_chars')
        # Build embeddings context using token budgets.  This will
        # truncate individual texts and the list as needed.
        texts_to_embed = ContextBuilderService.build_embeddings_context(
            texts,
            # Default per-text limit of 8000 tokens; honour the total token budget
            max_chars_per_text=8000,
            max_total_chars=max_input_tokens,
        )
        # Determine batch size from configuration
        batch_size: int = config.get('batch_size', 50) or 50
        # Compute character counts for logging (used to estimate tokens)
        total_chars = sum(len(t) for t in texts)
        model_name = model or config.get('model', 'unknown')
        # Prepare result container
        all_embeddings: List[List[float]] = []
        overall_success = True
        # Record start time for logging
        start_time = time.time()
        # Process texts in batches
        for i in range(0, len(texts_to_embed), batch_size):
            batch = texts_to_embed[i:i + batch_size]
            batch_start = time.time()
            try:
                embeddings = self.embed_client.generate_embeddings(batch)
                # If embedding count mismatches, fill missing with pseudo embeddings
                if len(embeddings) != len(batch):
                    # Append available embeddings and generate pseudo for missing
                    for idx, text in enumerate(batch):
                        if idx < len(embeddings):
                            all_embeddings.append(embeddings[idx])
                        else:
                            all_embeddings.append(self._pseudo_embedding(text))
                    overall_success = False
                else:
                    all_embeddings.extend(embeddings)
                # Log success for this batch
                from ..utils.token_counter import count_tokens  # local import
                input_tokens = count_tokens(batch)
                output_tokens = count_tokens('x' * len(str(embeddings)))
                self._log_request(
                    request_kind='embed',
                    provider='embed_service',
                    model_name=model_name,
                    status='success',
                    latency_ms=int((time.time() - batch_start) * 1000),
                    input_chars=input_tokens,
                    output_chars=output_tokens,
                )
            except Exception as exc:
                # On error, generate pseudo embeddings for the batch
                all_embeddings.extend([self._pseudo_embedding(t) for t in batch])
                overall_success = False
                # Log error for this batch
                from ..utils.token_counter import count_tokens  # local import
                input_tokens = count_tokens(batch)
                self._log_request(
                    request_kind='embed',
                    provider='embed_service',
                    model_name=model_name,
                    status='error',
                    latency_ms=int((time.time() - batch_start) * 1000),
                    input_chars=input_tokens,
                    output_chars=0,
                    error_message=str(exc),
                )
                # Continue to next batch without raising
        # If there was any failure in API calls and embeddings are enabled, surface an exception
        if not overall_success:
            # If pseudo embeddings were generated due to errors, raise a provider error
            raise ProviderNotAvailableException("Embedding generation had partial failures; pseudo embeddings were used.")
        return all_embeddings

    def _pseudo_embedding(self, text: str) -> List[float]:
        """Generate a deterministic pseudo‑embedding vector for a given text.

        This fallback mechanism creates a pseudo‑embedding by hashing
        the input text and expanding the hash into a 1536‑dimensional
        vector.  The resulting vector is *not* semantically meaningful
        and is intended solely for development or testing when real
        embeddings are disabled or unavailable.

        :param text: Input string
        :returns: A list of 1536 floats between 0 and 1
        """
        import hashlib
        # Compute SHA‑256 hash of the text
        digest = hashlib.sha256(text.encode('utf-8')).digest()
        # Convert bytes to floats in [0,1]
        base_vals = [(b / 255.0) for b in digest]
        # Repeat values to fill 1536 dimensions
        embedding: List[float] = []
        while len(embedding) < 1536:
            embedding.extend(base_vals)
        return embedding[:1536]

    def rerank_documents(
        self,
        query: str,
        documents: List[str],
        model: Optional[str] = None,
        top_k: int = 10,
    ) -> List[Dict[str, Any]]:
        if not ConfigService.is_rerank_enabled():
            raise InvalidRequestException("Reranking is not enabled")
        if not query or not documents:
            return []

        config = ConfigService.get_rerank_config()
        limits = ConfigService.get_request_limits()
        max_input_tokens = limits.get('max_input_tokens') or limits.get('max_input_chars')
        # Build rerank context using token budgets
        clean_query, processed_docs = ContextBuilderService.build_rerank_context(
            query,
            documents,
            max_chars_per_doc=4000,
            max_total_chars=max_input_tokens,
        )
        # Compute character counts for logging (used to estimate tokens)
        total_chars = len(query) + sum(len(doc) for doc in documents)
        start_time = time.time()
        model_name = model or config.get('model', 'unknown')
        try:
            results = self.rerank_client.rerank_documents(clean_query, processed_docs, top_k)
            from ..utils.token_counter import count_tokens  # local import
            input_tokens = count_tokens([query] + documents)
            output_tokens = count_tokens('x' * len(str(results)))
            self._log_request(
                request_kind='rerank',
                provider='rerank_service',
                model_name=model_name,
                status='success',
                latency_ms=int((time.time() - start_time) * 1000),
                input_chars=input_tokens,
                output_chars=output_tokens,
            )
            return results
        except Exception as exc:
            from ..utils.token_counter import count_tokens  # local import
            input_tokens = count_tokens([query] + documents) if documents else 0
            self._log_request(
                request_kind='rerank',
                provider='rerank_service',
                model_name=model_name,
                status='error',
                latency_ms=int((time.time() - start_time) * 1000),
                input_chars=input_tokens,
                output_chars=0,
                error_message=str(exc),
            )
            raise ProviderNotAvailableException(f"Reranking failed: {str(exc)}")

    def _log_request(
        self,
        request_kind: str,
        provider: str,
        model_name: str,
        status: str,
        latency_ms: int,
        input_chars: int,
        output_chars: int,
        error_message: Optional[str] = None,
    ) -> None:
        """Log embeddings or rerank requests with context.

        Error messages are truncated to avoid leaking sensitive
        information.  ``input_chars`` and ``output_chars`` represent
        token counts rather than raw character counts.  When an
        ``api_key`` or ``user`` is provided on the service, they are
        included in the log.
        """
        log_kwargs = {
            'endpoint': f'/api/code-editor/{request_kind}',
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
