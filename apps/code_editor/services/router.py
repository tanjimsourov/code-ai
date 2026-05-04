from typing import List, Optional
import time
from django.core.cache import cache
from ..providers.base import BaseProvider
from ..providers.openai_compatible import OpenAICompatibleProvider
from ..providers.ollama import OllamaProvider
from ..providers.llamacpp import LlamaCppProvider
from .config import ConfigService


class RouterService:
    """Service for routing requests to appropriate AI providers"""
    
    def __init__(self):
        self._providers = {}
        self._provider_health_cache = {}
        self._initialize_providers()
    
    def _initialize_providers(self) -> None:
        """
        Initialize available providers based on configuration.

        The provider registry is populated using a data‑driven approach
        mapping provider types (``local``, ``fast``, ``strong``,
        ``openai_compatible``, ``deepseek``, ``ollama``) to concrete
        provider classes.  Each provider is only registered if it is
        explicitly enabled and a base URL is configured.  This design
        allows additional provider types to be added without requiring
        changes throughout the RouterService.
        """
        # Clear existing providers so that reinitialization is idempotent
        self._providers = {}
        # Mapping from provider type to the corresponding class
        provider_class_map = {
            'local': LlamaCppProvider,
            'fast': LlamaCppProvider,
            'strong': LlamaCppProvider,
            'openai_compatible': OpenAICompatibleProvider,
            'deepseek': OpenAICompatibleProvider,
            # vLLM is treated as an OpenAI-compatible provider
            'vllm': OpenAICompatibleProvider,
            'ollama': OllamaProvider,
        }
        # Iterate over all known provider types
        for provider_type, cls in provider_class_map.items():
            if ConfigService.is_provider_enabled(provider_type):
                config = ConfigService.get_provider_config(provider_type)
                # Skip providers without a URL configured
                if not config or not config.get('url'):
                    continue
                try:
                    # Instantiate the provider and register by its type
                    provider_instance = cls(provider_type, config)
                    self._providers[provider_type] = provider_instance
                except Exception:
                    # If instantiation fails for any reason, do not register
                    continue

        # Rerank provider is handled separately based on rerank configuration
        try:
            rerank_config = ConfigService.get_rerank_config()
            if rerank_config and rerank_config.get('enabled'):
                from ..providers.rerank import RerankProvider  # Import here to avoid circular deps
                # Instantiate even if no base URL to allow lexical fallback
                rerank_provider = RerankProvider('rerank', rerank_config)
                self._providers['rerank'] = rerank_provider
        except Exception:
            # Ignore errors in rerank provider initialization
            pass
    
    def get_provider(self, request_type: str) -> Optional[BaseProvider]:
        """Get provider for request type with fallback and health checking"""
        provider_chain = self._get_provider_chain(request_type)
        
        for provider_name in provider_chain:
            provider = self._providers.get(provider_name)
            if provider and self._is_provider_healthy(provider_name):
                return provider
        
        return None

    # ------------------------------------------------------------------
    # Role‑based provider resolution (experimental)

    def get_provider_for_role(self, role: str) -> Optional[BaseProvider]:
        """Resolve a provider based on a high‑level role.

        This helper delegates to the ``ModelRegistryService`` to
        determine which provider (if any) is assigned to the given role
        via environment variables or the default routing logic.  It
        attempts to return a healthy provider instance.  If the
        registry cannot resolve a provider or the provider is unhealthy,
        falls back to the legacy ``get_provider`` method using the
        request type inferred from the role.  Unknown roles default to
        the ``chat`` request type.

        The role names correspond to the keys defined in
        ``ModelRegistryService.ROLES``.  When adding new roles ensure
        there is a corresponding entry in the registry service.

        :param role: role name (case‑insensitive)
        :returns: a provider instance or ``None`` if none is available
        """
        try:
            from .model_registry import ModelRegistryService
            registry = ModelRegistryService()
            entry = registry.get_role_entry(role)
            provider_name = entry.provider if entry else None
            if provider_name:
                # Ensure provider is healthy
                provider = self.get_provider_by_name(provider_name)
                if provider and self._is_provider_healthy(provider_name):
                    return provider
        except Exception:
            # Ignore registry errors and fall back
            pass
        # Fallback to request type based resolution
        from .model_registry import ModelRegistryService as _MRS
        req_type = _MRS.ROLE_TO_REQUEST_TYPE.get(role.lower(), 'chat')
        return self.get_provider(req_type)
    
    def _get_provider_chain(self, request_type: str) -> List[str]:
        """
        Compute the provider priority chain for a given request type.

        The chain determines the order in which providers are queried
        for a request.  Historic behaviour prioritised the ``local``,
        ``fast`` and ``strong`` providers.  This method extends that
        logic by appending any additional configured providers
        (``openai_compatible``, ``deepseek``, ``ollama``) to the end
        of the chain, preserving the original priority order.  Only
        providers that are enabled and initialised will be included.

        :param request_type: The type of request (e.g. ``chat``, ``complete``, ``edit``)
        :returns: A list of provider names ordered by preference
        """
        chain: List[str] = []
        # Determine base chain based on request type
        if request_type == 'chat':
            # Always prefer local then fast for chat, regardless of configuration
            chain.extend(['local', 'fast'])
        elif request_type == 'complete':
            # For completion, fast then local
            chain.extend(['fast', 'local'])
        elif request_type == 'infill':
            # For infill, use the same ordering as completion (fast then local)
            chain.extend(['fast', 'local'])
        elif request_type == 'edit':
            # Strong provider is preferred for code editing if explicitly enabled
            if ConfigService.is_provider_enabled('strong'):
                chain.append('strong')
            # Always include fast and local as fallbacks for edit requests
            chain.extend(['fast', 'local'])
        elif request_type == 'embed':
            # Embeddings are handled by the embeddings service
            chain = ['embed']
        elif request_type == 'rerank':
            # Reranking is handled by the rerank provider
            chain = ['rerank']
        else:
            # Default to local for unknown request types
            chain.append('local')

        # Append additional providers if configured
        for extra_provider in ['openai_compatible', 'deepseek', 'vllm', 'ollama']:
            if extra_provider not in chain and ConfigService.is_provider_enabled(extra_provider):
                chain.append(extra_provider)

        # Remove duplicates while preserving order
        seen = set()
        deduped: List[str] = []
        for p in chain:
            if p not in seen:
                deduped.append(p)
                seen.add(p)
        return deduped
    
    def _is_provider_healthy(self, provider_name: str) -> bool:
        """Check if provider is healthy with caching"""
        if not ConfigService.provider_health_checks_enabled():
            return provider_name in self._providers
        cache_key = f"provider_health:{provider_name}"
        
        # Check cache first
        cached_health = cache.get(cache_key)
        if cached_health is not None:
            return cached_health
        
        # Check actual health
        provider = self._providers.get(provider_name)
        if not provider:
            cache.set(cache_key, False, 60)  # Cache for 1 minute
            return False
        
        is_healthy = provider.is_available()
        
        # Cache the result
        cache.set(cache_key, is_healthy, 60)  # Cache for 1 minute
        
        return is_healthy
    
    def get_available_providers(self) -> List[str]:
        """Get list of available provider names"""
        return [name for name in self._providers if self._is_provider_healthy(name)]
    
    def get_provider_by_name(self, name: str) -> Optional[BaseProvider]:
        """Get specific provider by name"""
        return self._providers.get(name)
    
    def get_all_models(self) -> List[dict]:
        """Get all available models from all providers"""
        all_models = []
        for provider_name in self.get_available_providers():
            provider = self._providers.get(provider_name)
            if provider:
                try:
                    models = provider.get_models()
                    for model in models:
                        model['provider'] = provider_name
                        model['provider_type'] = type(provider).__name__
                    all_models.extend(models)
                except Exception:
                    # Skip provider if models endpoint fails
                    continue
        return all_models
    
    def get_provider_health_status(self) -> dict:
        """Return normalised health status for all configured providers.

        Each provider entry includes:

        ``provider``: provider name/identifier
        ``status``: ``healthy``, ``unhealthy`` or ``unknown``
        ``available``: boolean indicating if the provider is currently available
        ``latency_ms``: latency of the availability check in milliseconds
        ``error``: error message if an exception occurred
        ``capabilities``: optional capability metadata if available
        ``checked_at``: timestamp when the check was performed
        """
        from typing import Any
        health: dict[str, dict[str, Any]] = {}
        for name, provider in self._providers.items():
            record: dict[str, Any] = {
                'provider': name,
                'status': 'unknown',
                'available': False,
                'latency_ms': None,
                'error': None,
                'capabilities': None,
                'checked_at': time.time(),
            }
            start_time = time.time()
            try:
                available = self._is_provider_healthy(name)
                latency_ms = int((time.time() - start_time) * 1000)
                record['available'] = available
                record['latency_ms'] = latency_ms
                record['status'] = 'healthy' if available else 'unhealthy'
                if available:
                    try:
                        record['capabilities'] = provider.get_capabilities()
                    except Exception:
                        # leave capabilities as None if provider.get_capabilities fails
                        pass
            except Exception as exc:
                latency_ms = int((time.time() - start_time) * 1000)
                record['latency_ms'] = latency_ms
                record['status'] = 'unknown'
                record['error'] = str(exc)
            health[name] = record
        return health
    
    def get_provider_capabilities(self, provider_name: str) -> dict:
        """Get capabilities of a specific provider"""
        provider = self._providers.get(provider_name)
        if not provider:
            return {}
        # Use the provider's capability metadata if available
        try:
            return provider.get_capabilities()
        except Exception:
            # Fallback to default assumption of chat/completion/edit support
            return {
                'chat': True,
                'completion': True,
                'edit': True,
                'embeddings': False,
                'rerank': False,
                'streaming': False,
                'infill': False,
            }
