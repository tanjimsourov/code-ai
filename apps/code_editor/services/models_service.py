import time
from typing import Dict, Any, List, Optional
from django.utils import timezone
from ..models import CodeEditorRequestLog
from .router import RouterService
from .config import ConfigService
from ..exceptions import ProviderNotAvailableException


class ModelsService:
    """Service for handling model listing requests"""
    
    def __init__(self):
        self.router = RouterService()
    
    def get_models(self, **kwargs) -> List[Dict[str, Any]]:
        """
        Retrieve a list of all available models from configured providers.

        This method aggregates model metadata from every enabled provider via
        the router.  It enriches each model with context window size,
        inferred model family and a capabilities map that reflects both
        model‑level features (via ``model_profiles``) and provider‑level
        support (via ``get_capabilities``).  Unknown models fall back to
        provider capabilities only.  All requests are logged for
        observability.
        """
        start_time = time.time()
        try:
            # Aggregate models across all providers
            raw_models = self.router.get_all_models()
            from .model_profiles import get_model_profile
            decorated: List[Dict[str, Any]] = []
            for m in raw_models:
                # Copy model entry to avoid mutating raw provider data
                model_entry = dict(m)
                provider_name = model_entry.get('provider')
                provider = self.router.get_provider_by_name(provider_name) if provider_name else None
                # Determine the canonical model identifier; providers may use 'id' or 'model'
                model_id = model_entry.get('id') or model_entry.get('model')
                # Determine provider capabilities, defaulting to empty
                provider_caps: Dict[str, Any] = provider.get_capabilities() if provider else {}
                # Enrich with model profile when available
                try:
                    profile = get_model_profile(model_id)
                    model_entry['context_window_tokens'] = profile.context_window_tokens
                    model_entry['model_family'] = profile.model_family
                    # Combine model and provider capabilities.  A feature is supported
                    # only if both the provider and the model advertise support.
                    model_entry['capabilities'] = {
                        'chat': bool(profile.supports_chat and provider_caps.get('chat', False)),
                        'completion': bool(profile.supports_completion and provider_caps.get('completion', False)),
                        'edit': bool(provider_caps.get('edit', False)),
                        'infill': bool(profile.supports_infill and provider_caps.get('infill', False)),
                        'embeddings': bool(profile.supports_embeddings and provider_caps.get('embeddings', False)),
                        'rerank': bool(provider_caps.get('rerank', False)),
                        'streaming': bool(profile.supports_streaming and provider_caps.get('streaming', False)),
                    }
                except Exception:
                    # Unknown model profile; fall back to provider capabilities only
                    model_entry['context_window_tokens'] = None
                    model_entry['model_family'] = None
                    model_entry['capabilities'] = {
                        'chat': bool(provider_caps.get('chat', False)),
                        'completion': bool(provider_caps.get('completion', False)),
                        'edit': bool(provider_caps.get('edit', False)),
                        'infill': bool(provider_caps.get('infill', False)),
                        'embeddings': bool(provider_caps.get('embeddings', False)),
                        'rerank': bool(provider_caps.get('rerank', False)),
                        'streaming': bool(provider_caps.get('streaming', False)),
                    }
                decorated.append(model_entry)
            # Measure latency and log successful response
            latency_ms = int((time.time() - start_time) * 1000)
            self._log_request(
                endpoint='/api/code-editor/models',
                provider='multiple',
                model_name='various',
                request_kind='models',
                status='success',
                latency_ms=latency_ms,
                input_chars=0,
                output_chars=len(str(decorated))
            )
            return decorated
        except Exception as e:
            # On error, log and rethrow
            latency_ms = int((time.time() - start_time) * 1000)
            self._log_request(
                endpoint='/api/code-editor/models',
                provider='multiple',
                model_name='various',
                request_kind='models',
                status='error',
                latency_ms=latency_ms,
                input_chars=0,
                output_chars=0,
                error_message=str(e)
            )
            raise
    
    def get_provider_info(self, **kwargs) -> Dict[str, Any]:
        """Get provider information"""
        start_time = time.time()
        
        try:
            available_providers = self.router.get_available_providers()
            provider_info = {}
            
            for provider_name in available_providers:
                provider = self.router.get_provider_by_name(provider_name)
                if provider:
                    provider_info[provider_name] = {
                        'name': provider.name,
                        'available': provider.is_available(),
                        'config': {
                            'model': provider.config.get('model'),
                            'timeout': provider.config.get('timeout'),
                        }
                    }
            
            # Calculate latency
            latency_ms = int((time.time() - start_time) * 1000)
            
            # Log request
            self._log_request(
                endpoint='/api/code-editor/provider-info',
                provider='system',
                model_name='system',
                request_kind='health',
                status='success',
                latency_ms=latency_ms,
                input_chars=0,
                output_chars=len(str(provider_info))
            )
            
            return provider_info
            
        except Exception as e:
            # Calculate latency
            latency_ms = int((time.time() - start_time) * 1000)
            
            # Log error
            self._log_request(
                endpoint='/api/code-editor/provider-info',
                provider='system',
                model_name='system',
                request_kind='health',
                status='error',
                latency_ms=latency_ms,
                input_chars=0,
                output_chars=0,
                error_message=str(e)
            )
            
            raise

    def get_providers(self) -> Dict[str, Any]:
        """
        Retrieve detailed information about all configured providers.

        Returns a dictionary keyed by provider name with metadata including
        provider type, redacted base URL, availability status, capabilities,
        configured default model and context window tokens (if known).

        :returns: mapping of provider name to provider info
        """
        from urllib.parse import urlparse, urlunparse
        from .model_profiles import get_model_profile
        providers_info: Dict[str, Any] = {}
        # Iterate over all registered providers
        for name, provider in self.router._providers.items():
            # Build base info
            info: Dict[str, Any] = {
                'name': name,
                'type': type(provider).__name__,
            }
            # Redact base URL: remove query parameters and userinfo
            raw_url = ''
            try:
                # Prefer provider.base_url if available, else config url
                raw_url = getattr(provider, 'base_url', None) or provider.config.get('url') or ''
                parsed = urlparse(raw_url)
                # Remove username/password and query
                netloc = parsed.hostname or ''
                if parsed.port:
                    netloc = f"{netloc}:{parsed.port}"
                # Normalized path without trailing slash
                path = parsed.path or ''
                # Compose sanitized URL
                redacted_url = f"{parsed.scheme}://{netloc}{path}"
                info['base_url'] = redacted_url.rstrip('/')
            except Exception:
                info['base_url'] = ''
            # Health status
            try:
                is_healthy = self.router._is_provider_healthy(name)
                info['available'] = bool(is_healthy)
            except Exception:
                info['available'] = False
            # Capabilities
            try:
                info['capabilities'] = provider.get_capabilities()
            except Exception:
                info['capabilities'] = {
                    'chat': True,
                    'completion': True,
                    'edit': True,
                    'embeddings': False,
                    'rerank': False,
                    'streaming': False,
                    'infill': False,
                }
            # Default model
            default_model = provider.config.get('model') if provider and provider.config else None
            info['default_model'] = default_model
            # Context window tokens
            if default_model:
                try:
                    profile = get_model_profile(default_model)
                    info['context_window_tokens'] = profile.context_window_tokens
                except Exception:
                    info['context_window_tokens'] = None
            else:
                info['context_window_tokens'] = None
            providers_info[name] = info
        return providers_info
    
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
        CodeEditorRequestLog.log_request(
            endpoint=endpoint,
            provider=provider,
            model_name=model_name,
            request_kind=request_kind,
            status=status,
            latency_ms=latency_ms,
            input_chars=input_chars,
            output_chars=output_chars,
            error_message=error_message
        )
