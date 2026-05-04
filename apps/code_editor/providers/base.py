from abc import ABC, abstractmethod
from typing import Dict, List, Optional, Any, AsyncGenerator
import time


class BaseProvider(ABC):
    """Base class for AI providers"""
    
    def __init__(self, name: str, config: Dict[str, Any]):
        self.name = name
        self.config = config
        self.timeout = config.get('timeout', 30)
        self.max_retries = config.get('max_retries', 3)
    
    @abstractmethod
    def chat_completion(
        self,
        messages: List[Dict[str, str]],
        model: str,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        stream: bool = False,
        **kwargs
    ) -> Dict[str, Any]:
        """Generate chat completion"""
        pass
    
    @abstractmethod
    def text_completion(
        self,
        prompt: str,
        model: str,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        stream: bool = False,
        **kwargs
    ) -> Dict[str, Any]:
        """Generate text completion"""
        pass
    
    @abstractmethod
    def edit_code(
        self,
        instruction: str,
        code: str,
        model: str,
        temperature: float = 0.3,
        max_tokens: Optional[int] = None,
        **kwargs
    ) -> Dict[str, Any]:
        """Edit code based on instruction"""
        pass
    
    @abstractmethod
    def get_models(self) -> List[Dict[str, Any]]:
        """Get available models"""
        pass
    
    def embeddings(
        self,
        texts: List[str],
        model: str,
        **kwargs
    ) -> List[List[float]]:
        """Generate embeddings (optional)"""
        raise NotImplementedError("Embeddings not supported by this provider")
    
    def rerank(
        self,
        query: str,
        documents: List[str],
        model: str,
        **kwargs
    ) -> List[Dict[str, Any]]:
        """Rerank documents (optional)"""
        raise NotImplementedError("Reranking not supported by this provider")
    
    def is_available(self) -> bool:
        """Check if provider is available"""
        return True
    
    def get_model_info(self, model_name: str) -> Optional[Dict[str, Any]]:
        """Get information about a specific model"""
        models = self.get_models()
        for model in models:
            if model.get('id') == model_name:
                return model
        return None
    
    def _measure_time(self, func, *args, **kwargs):
        """Measure execution time of a function"""
        start_time = time.time()
        try:
            result = func(*args, **kwargs)
            latency_ms = int((time.time() - start_time) * 1000)
            return result, latency_ms
        except Exception as e:
            latency_ms = int((time.time() - start_time) * 1000)
            raise e

    # ------------------------------------------------------------------
    # Capability metadata
    #
    # Providers may support different subsets of operations.  These
    # convenience methods advertise which features are implemented by a
    # provider so that callers (e.g. RouterService) can make informed
    # choices.  Subclasses should override these methods as
    # appropriate.  The base implementation assumes only chat,
    # completion and edit operations are available.

    # Base implementations for capability flags.  Subclasses should
    # override these methods to advertise support for additional features.

    def supports_chat(self) -> bool:
        """Return ``True`` if the provider can perform chat completions."""
        return True

    def supports_completion(self) -> bool:
        """Return ``True`` if the provider can perform text completions."""
        return True

    def supports_edit(self) -> bool:
        """Return ``True`` if the provider can perform code edits."""
        return True

    def supports_streaming(self) -> bool:
        """Return ``True`` if the provider supports streaming responses."""
        return False

    def supports_embeddings(self) -> bool:
        """Return ``True`` if the provider supports embeddings generation."""
        return False

    def supports_infill(self) -> bool:
        """Return ``True`` if the provider supports infill/code completion."""
        return False

    def supports_json(self) -> bool:
        """Return ``True`` if the provider can return structured JSON responses."""
        return False

    def supports_tools(self) -> bool:
        """Return ``True`` if the provider supports tool or function calling APIs."""
        return False

    def supports_suffix_completion(self) -> bool:
        """Return ``True`` if the provider supports suffix completions or FIM natively."""
        return False

    def supports_rerank(self) -> bool:
        """Return ``True`` if the provider supports reranking documents."""
        return False

    @abstractmethod
    def infill_code(
        self,
        prefix: str,
        suffix: str,
        model: str,
        language: Optional[str] = None,
        filename: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        stream: bool = False,
        **kwargs
    ) -> Dict[str, Any]:
        """Fill in the middle of code between a prefix and a suffix.

        This method generates code that should be inserted between the
        provided ``prefix`` and ``suffix``.  Providers that implement
        fill‑in‑the‑middle (FIM) completions can override this method
        to call their native infill endpoints.  The default
        implementation is abstract and must be provided by
        subclasses.

        :param prefix: Code preceding the insertion point
        :param suffix: Code following the insertion point
        :param model: Name of the model to use
        :param language: Optional programming language hint
        :param filename: Optional filename hint
        :param temperature: Sampling temperature
        :param max_tokens: Maximum number of tokens to generate
        :param stream: Whether to stream the response
        :param kwargs: Additional provider‑specific parameters
        :returns: Provider response as a dictionary
        """
        pass

    # duplicate supports_rerank method removed; see earlier definition

    def get_capabilities(self) -> Dict[str, Any]:
        """Return a dictionary describing the provider's capabilities.

        Providers may support different subsets of operations.  This
        method gathers capability flags by calling the corresponding
        ``supports_*`` methods.  Subclasses should override those
        methods to advertise additional features.

        The returned dictionary uses consistent keys consumed by the
        ``ModelRegistryService`` and router:

        - ``chat``: chat conversation support
        - ``completion``: plain text completion support
        - ``edit``: code editing support
        - ``embeddings``: embedding generation support
        - ``rerank``: document reranking support
        - ``streaming``: incremental streaming response support
        - ``infill``: fill‑in‑the‑middle (FIM) code completion support
        - ``json``: structured JSON response support
        - ``tools``: tool/function calling support
        - ``fim``: alias for ``infill``
        - ``suffix_completion``: alias for FIM/suffix completions

        :returns: mapping of capability flags
        """
        caps: Dict[str, Any] = {
            'chat': bool(self.supports_chat()),
            'completion': bool(self.supports_completion()),
            'edit': bool(self.supports_edit()),
            'embeddings': bool(self.supports_embeddings()),
            'rerank': bool(self.supports_rerank()),
            'streaming': bool(self.supports_streaming()),
            'infill': bool(self.supports_infill()),
            'json': bool(self.supports_json()),
            'tools': bool(self.supports_tools()),
        }
        # Provide aliases for FIM and suffix completions
        caps['fim'] = caps['infill']
        caps['suffix_completion'] = bool(self.supports_suffix_completion())
        return caps
    
    def _measure_time_sync(self, func, *args, **kwargs):
        """Measure execution time of an async function"""
        start_time = time.time()
        try:
            result = func(*args, **kwargs)
            latency_ms = int((time.time() - start_time) * 1000)
            return result, latency_ms
        except Exception as e:
            latency_ms = int((time.time() - start_time) * 1000)
            raise e
