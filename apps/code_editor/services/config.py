import os
from typing import Dict, Any, Optional


class ConfigService:
    """Service for accessing configuration from environment variables.

    The configuration layer supports multiple provider types (e.g. local,
    fast, strong, openai_compatible, deepseek, ollama) with a
    consistent naming convention.  New ``CODE_EDITOR_*`` environment
    variables take precedence over legacy ``AI_*`` variables for
    backwards compatibility.
    """

    # Map provider type to environment prefix used for new variables
    _ENV_PREFIXES = {
        'local': 'CODE_EDITOR_LOCAL',
        'fast': 'CODE_EDITOR_FAST',
        'strong': 'CODE_EDITOR_STRONG',
        'openai_compatible': 'CODE_EDITOR_OPENAI_COMPATIBLE',
        'deepseek': 'CODE_EDITOR_DEEPSEEK',
        'ollama': 'CODE_EDITOR_OLLAMA',
        # Add vLLM provider prefix for OpenAI-compatible vLLM endpoints
        'vllm': 'CODE_EDITOR_VLLM',
    }

    @staticmethod
    def _get_env_bool(var_name: str, default: Optional[bool] = None) -> Optional[bool]:
        """Parse a boolean environment variable. Returns None if not set."""
        value = os.getenv(var_name)
        if value is None:
            return default
        return value.lower() in {'1', 'true', 'yes', 'on'}

    @staticmethod
    def get_provider_config(provider_type: str) -> Dict[str, Any]:
        """Get configuration for a specific provider type.

        New ``CODE_EDITOR_*`` variables override legacy ``AI_*`` ones.  If
        no relevant variables are set, an empty config is returned.
        """
        config: Dict[str, Any] = {}
        prefix = ConfigService._ENV_PREFIXES.get(provider_type)
        # Determine if provider is enabled explicitly
        enabled_var = f"{prefix}_ENABLED" if prefix else None
        enabled: Optional[bool] = None
        if enabled_var:
            enabled = ConfigService._get_env_bool(enabled_var)
        # Determine base URL and model using new naming convention
        base_url_var = f"{prefix}_BASE_URL" if prefix else None
        model_var = f"{prefix}_MODEL" if prefix else None
        api_key_var = f"{prefix}_API_KEY" if prefix else None
        # Custom headers may be provided via a JSON string; keep it simple
        headers_var = f"{prefix}_HEADERS" if prefix else None
        base_url = os.getenv(base_url_var or '', '') if base_url_var else ''
        model = os.getenv(model_var or '', '') if model_var else ''
        api_key = os.getenv(api_key_var or '', None) if api_key_var else None
        headers = os.getenv(headers_var or '', None) if headers_var else None
        # Parse headers JSON if provided
        headers_dict: Dict[str, Any] = {}
        if headers:
            try:
                import json as _json
                parsed = _json.loads(headers)
                if isinstance(parsed, dict):
                    headers_dict = parsed
            except Exception:
                pass
        # Timeout and retries are shared across providers.  New
        # `CODE_EDITOR_PROVIDER_TIMEOUT` and `CODE_EDITOR_PROVIDER_MAX_RETRIES`
        # variables take precedence over the legacy `AI_PROVIDER_*` ones.
        timeout = int(os.getenv('CODE_EDITOR_PROVIDER_TIMEOUT',
                              os.getenv('AI_PROVIDER_TIMEOUT', '30')))
        max_retries = int(os.getenv('CODE_EDITOR_PROVIDER_MAX_RETRIES',
                                   os.getenv('AI_PROVIDER_MAX_RETRIES',
                                            os.getenv('AI_PROVIDER_RETRIES', '3'))))

        if provider_type in {'local', 'fast', 'strong'}:
            # Legacy fallback variables for llama.cpp providers
            legacy_url_vars = {
                'local': 'AI_LOCALAI_URL',
                'fast': 'AI_FAST_URL',
                'strong': 'AI_STRONG_URL',
            }
            legacy_model_vars = {
                'local': 'AI_LOCALAI_MODEL',
                'fast': 'AI_FAST_MODEL',
                'strong': 'AI_STRONG_MODEL',
            }
            if not base_url:
                base_url = os.getenv(legacy_url_vars.get(provider_type, ''), '')
            if not model:
                model = os.getenv(legacy_model_vars.get(provider_type, ''), '')
            # Determine enabled if not explicitly set
            if enabled is None:
                enabled = bool(base_url)
            config = {
                'url': base_url,
                'model': model or ConfigService._default_model_for(provider_type),
                'timeout': timeout,
                'max_retries': max_retries,
                'enabled': enabled,
            }
        elif provider_type == 'openai_compatible':
            if enabled is None:
                enabled = bool(base_url)
            config = {
                'url': base_url,
                'model': model or 'gpt-3.5-turbo',
                'api_key': api_key,
                'headers': headers_dict,
                'timeout': timeout,
                'max_retries': max_retries,
                'enabled': enabled,
            }
        elif provider_type == 'deepseek':
            # DeepSeek models follow the same API as OpenAI
            if enabled is None:
                enabled = bool(base_url)
            config = {
                'url': base_url,
                'model': model or 'deepseek-coder',
                'api_key': api_key,
                'headers': headers_dict,
                'timeout': timeout,
                'max_retries': max_retries,
                'enabled': enabled,
            }
        elif provider_type == 'ollama':
            if enabled is None:
                enabled = bool(base_url)
            config = {
                'url': base_url,
                'model': model or 'qwen2.5-coder-7b-instruct',
                'timeout': timeout,
                'max_retries': max_retries,
                'enabled': enabled,
            }
        elif provider_type == 'vllm':
            # vLLM shares the OpenAI-compatible API semantics.  Treat it the same as the
            # generic OpenAI-compatible provider with its own configuration prefix.
            if enabled is None:
                enabled = bool(base_url)
            config = {
                'url': base_url,
                'model': model or 'gpt-3.5-turbo',
                'api_key': api_key,
                'headers': headers_dict,
                'timeout': timeout,
                'max_retries': max_retries,
                'enabled': enabled,
            }
        else:
            # Unknown provider type
            config = {}
        return config

    @staticmethod
    def _default_model_for(provider_type: str) -> str:
        """Return a reasonable default model name for a given provider type."""
        defaults = {
            'local': 'qwen2.5-coder-7b-instruct',
            'fast': 'qwen2.5-coder-1.5b-instruct',
            'strong': 'code-llama-34b-instruct',
        }
        return defaults.get(provider_type, '')
    
    @staticmethod
    def is_provider_enabled(provider_type: str) -> bool:
        """Check if a provider is enabled.

        Returns ``True`` if the provider's configuration marks it as
        enabled.  This checks the ``enabled`` key on the config; if
        absent, falls back to whether a URL is present.
        """
        config = ConfigService.get_provider_config(provider_type)
        if not config:
            return False
        enabled = config.get('enabled')
        if enabled is not None:
            return bool(enabled)
        return bool(config.get('url'))
    
    @staticmethod
    def is_localai_enabled() -> bool:
        """Check if LocalAI provider is enabled"""
        return ConfigService.is_provider_enabled('local')
    
    @staticmethod
    def is_fast_enabled() -> bool:
        """Check if fast provider is enabled"""
        return ConfigService.is_provider_enabled('fast')
    
    @staticmethod
    def is_strong_enabled() -> bool:
        """Check if strong provider is enabled"""
        return ConfigService.is_provider_enabled('strong')

    @staticmethod
    def is_openai_compatible_enabled() -> bool:
        """Check if the OpenAI‑compatible provider is enabled."""
        return ConfigService.is_provider_enabled('openai_compatible')

    @staticmethod
    def is_deepseek_enabled() -> bool:
        return ConfigService.is_provider_enabled('deepseek')

    @staticmethod
    def is_ollama_enabled() -> bool:
        return ConfigService.is_provider_enabled('ollama')
    
    @staticmethod
    def is_embeddings_enabled() -> bool:
        """Check if embeddings are enabled.

        Embeddings may be enabled explicitly via the new
        ``CODE_EDITOR_EMBEDDINGS_ENABLED`` environment variable.  If
        this variable is unset, we fall back to the legacy
        ``AI_ENABLE_EMBED`` variable.  Any truthy value ("1", "true",
        "yes", "on") enables embeddings.
        """
        env = os.getenv('CODE_EDITOR_EMBEDDINGS_ENABLED')
        if env is not None:
            return env.lower() in {'1', 'true', 'yes', 'on'}
        # Legacy fallback
        return os.getenv('AI_ENABLE_EMBED', 'false').lower() in {'1', 'true', 'yes', 'on'}
    
    @staticmethod
    def is_rerank_enabled() -> bool:
        """Check if reranking is enabled.

        This first checks the new ``CODE_EDITOR_RERANK_ENABLED``
        environment variable.  If unset, it falls back to the legacy
        ``AI_ENABLE_RERANK`` variable.

        Returns ``True`` if a truthy value (``"1"``, ``"true"``,
        ``"yes"``, ``"on"``) is set, otherwise ``False``.
        """
        env = os.getenv('CODE_EDITOR_RERANK_ENABLED')
        if env is not None:
            return env.lower() in {'1', 'true', 'yes', 'on'}
        return os.getenv('AI_ENABLE_RERANK', 'false').lower() in {'1', 'true', 'yes', 'on'}
    
    @staticmethod
    def get_localai_config() -> Dict[str, Any]:
        """Get LocalAI provider configuration"""
        return ConfigService.get_provider_config('local')
    
    @staticmethod
    def get_fast_config() -> Dict[str, Any]:
        """Get fast provider configuration"""
        return ConfigService.get_provider_config('fast')
    
    @staticmethod
    def get_strong_config() -> Dict[str, Any]:
        """Get strong provider configuration"""
        return ConfigService.get_provider_config('strong')

    @staticmethod
    def get_openai_compatible_config() -> Dict[str, Any]:
        """Get OpenAI‑compatible provider configuration."""
        return ConfigService.get_provider_config('openai_compatible')

    @staticmethod
    def get_deepseek_config() -> Dict[str, Any]:
        return ConfigService.get_provider_config('deepseek')

    @staticmethod
    def get_ollama_config() -> Dict[str, Any]:
        return ConfigService.get_provider_config('ollama')
    
    @staticmethod
    def get_embeddings_config() -> Dict[str, Any]:
        """Get embeddings service configuration.

        The embeddings configuration can be customized via several
        environment variables.  New ``CODE_EDITOR_EMBEDDINGS_*``
        variables take precedence over legacy ``AI_EMBED_*`` values.

        Supported environment variables:

        - ``CODE_EDITOR_EMBEDDINGS_ENABLED`` – explicit toggle to
          enable or disable embeddings.  Falls back to
          ``AI_ENABLE_EMBED`` if unset.
        - ``CODE_EDITOR_EMBEDDINGS_PROVIDER`` – provider key to use
          for embeddings (e.g. "openai_compatible", "ollama",
          "local").  Determines how to construct requests.
        - ``CODE_EDITOR_EMBEDDINGS_BASE_URL`` – base URL for the
          embeddings endpoint.  If unset, falls back to the
          corresponding provider's base URL (see
          :func:`get_provider_config`).  If still unset, falls back
          to ``AI_EMBED_URL``.
        - ``CODE_EDITOR_EMBEDDINGS_MODEL`` – default model name for
          embeddings.  Falls back to the provider's model or
          ``AI_EMBED_MODEL`` if unset.
        - ``CODE_EDITOR_EMBEDDINGS_BATCH_SIZE`` – number of texts
          to send in a single embeddings API call.  Defaults to 50.

        :returns: A dict containing URL, model, timeout, enabled flag,
          provider key, batch_size, optional API key and headers,
          and max_retries values.
        """
        # Determine provider from new env var
        provider = os.getenv('CODE_EDITOR_EMBEDDINGS_PROVIDER', '').strip().lower() or None
        # Base URL and model overrides from new vars
        base_url = os.getenv('CODE_EDITOR_EMBEDDINGS_BASE_URL', '')
        model = os.getenv('CODE_EDITOR_EMBEDDINGS_MODEL', '')
        batch_size = int(os.getenv('CODE_EDITOR_EMBEDDINGS_BATCH_SIZE', '50'))
        # Determine if embeddings are enabled using new or legacy env vars
        enabled_flag = ConfigService._get_env_bool('CODE_EDITOR_EMBEDDINGS_ENABLED')
        enabled: bool
        if enabled_flag is not None:
            enabled = bool(enabled_flag)
        else:
            # Fallback to legacy
            enabled = ConfigService.is_embeddings_enabled()
        # Default values from legacy variables
        legacy_base = os.getenv('AI_EMBED_URL', '')
        legacy_model = os.getenv('AI_EMBED_MODEL', '')
        timeout = int(os.getenv('AI_PROVIDER_TIMEOUT', '30'))
        # Provider-specific configuration
        api_key = None
        headers: Dict[str, Any] = {}
        max_retries: Optional[int] = None
        if provider:
            # Look up provider configuration for base URL, model and API key
            provider_config = ConfigService.get_provider_config(provider)
            # Use provider's URL if not explicitly set
            if not base_url:
                base_url = provider_config.get('url', '')
            # Use provider's model if not explicitly set
            if not model:
                model = provider_config.get('model', '')
            # Capture API key and headers from provider config
            api_key = provider_config.get('api_key')
            headers = provider_config.get('headers', {}) or {}
            max_retries = provider_config.get('max_retries')
        # Fall back to legacy variables if still unset
        if not base_url:
            base_url = legacy_base
        if not model:
            model = legacy_model or 'BAAI/bge-small-en-v1.5'
        # Default batch size if invalid
        if batch_size <= 0:
            batch_size = 50
        # Build embeddings config
        config: Dict[str, Any] = {
            'url': base_url,
            'model': model,
            'timeout': timeout,
            'enabled': enabled,
            'provider': provider or 'generic',
            'batch_size': batch_size,
        }
        if api_key:
            config['api_key'] = api_key
        if headers:
            config['headers'] = headers
        if max_retries is not None:
            config['max_retries'] = max_retries
        return config
    
    @staticmethod
    def get_rerank_config() -> Dict[str, Any]:
        """Get reranking service configuration.

        Configuration is derived from new ``CODE_EDITOR_RERANK_*``
        environment variables with fallback to provider configuration
        and legacy variables.  The returned dictionary contains the
        following keys:

        - ``url``: Base URL of the rerank endpoint (no trailing slash).
        - ``model``: Default model name for reranking.
        - ``provider``: Provider key (e.g. ``openai_compatible``,
          ``lexical``).  Defaults to ``lexical`` if unspecified.
        - ``top_k``: Optional integer specifying how many results the
          API should return.  ``None`` indicates all results should
          be returned.
        - ``timeout``: Request timeout in seconds.
        - ``enabled``: Boolean toggle from
          ``CODE_EDITOR_RERANK_ENABLED`` or legacy fallback.
        - ``api_key``: Optional API key inherited from provider config.
        - ``headers``: Optional custom headers inherited from provider config.
        - ``max_retries``: Optional max retries inherited from provider config.
        """
        # Determine provider key and overrides from new variables
        provider = os.getenv('CODE_EDITOR_RERANK_PROVIDER', '').strip().lower() or None
        base_url = os.getenv('CODE_EDITOR_RERANK_BASE_URL', '')
        model = os.getenv('CODE_EDITOR_RERANK_MODEL', '')
        top_k_var = os.getenv('CODE_EDITOR_RERANK_TOP_K', '')
        try:
            top_k: Optional[int] = int(top_k_var) if str(top_k_var).strip() else None
        except Exception:
            top_k = None
        # Determine enabled flag using new or legacy variables
        env_enabled = ConfigService._get_env_bool('CODE_EDITOR_RERANK_ENABLED')
        if env_enabled is not None:
            enabled = bool(env_enabled)
        else:
            enabled = ConfigService.is_rerank_enabled()
        # Use legacy base URL and model if still unset
        legacy_base = os.getenv('AI_RERANK_URL', '')
        legacy_model = os.getenv('AI_RERANK_MODEL', '')
        # Start with default timeout and retries
        timeout = int(os.getenv('AI_PROVIDER_TIMEOUT', '30'))
        max_retries: Optional[int] = None
        api_key: Optional[str] = None
        headers: Dict[str, Any] = {}
        # If provider specified, inherit configuration from that provider
        if provider:
            p_config = ConfigService.get_provider_config(provider)
            # If no explicit base URL, use provider's URL
            if not base_url:
                base_url = p_config.get('url', '')
            # If no explicit model, use provider's model
            if not model:
                model = p_config.get('model', '')
            # Inherit API key and headers from provider
            api_key = p_config.get('api_key')
            headers = p_config.get('headers', {}) or {}
            # Inherit timeout and max retries if available
            if p_config.get('timeout'):
                timeout = p_config['timeout']
            if p_config.get('max_retries') is not None:
                max_retries = p_config['max_retries']
        # Fall back to legacy variables if still unset
        if not base_url:
            base_url = legacy_base
        if not model:
            model = legacy_model or 'BAAI/bge-reranker-base'
        config: Dict[str, Any] = {
            'url': base_url.rstrip('/'),
            'model': model,
            'provider': provider or 'lexical',
            'top_k': top_k,
            'timeout': timeout,
            'enabled': enabled,
        }
        if api_key:
            config['api_key'] = api_key
        if headers:
            config['headers'] = headers
        if max_retries is not None:
            config['max_retries'] = max_retries
        return config
    
    @staticmethod
    def get_request_limits() -> Dict[str, Any]:
        """
        Get request limits for API calls.

        The returned dictionary includes both character‑named keys and
        token‑named keys for backward compatibility.  Historically,
        ``max_input_chars`` referred to the maximum number of input
        characters allowed in a request.  With the introduction of
        token‑aware context management, these values are now
        interpreted as token budgets.  Environment variables can
        override the defaults to adjust the global context window and
        output token limits.

        Supported environment variables:

        - ``CODE_EDITOR_MAX_CONTEXT_TOKENS`` – Overrides the maximum
          input token budget.  Falls back to ``AI_MAX_INPUT_CHARS``
          for legacy compatibility if unset.
        - ``CODE_EDITOR_DEFAULT_MAX_OUTPUT_TOKENS`` – Overrides the
          default number of output tokens requested when the caller
          does not specify a ``max_tokens`` value.  Falls back to
          ``AI_DEFAULT_MAX_TOKENS`` if unset.
        - ``AI_MAX_TOKENS`` – Sets an absolute ceiling on the
          ``max_tokens`` value.  If unspecified, defaults to 4000.

        :returns: A dictionary with the keys ``max_input_chars``,
                  ``max_input_tokens``, ``default_max_tokens`` and
                  ``max_tokens``.  ``max_input_chars`` and
                  ``max_input_tokens`` will contain the same value.
        """
        # Determine the maximum input token budget.  Use the new
        # CODE_EDITOR_MAX_CONTEXT_TOKENS variable if provided; fall
        # back to the legacy AI_MAX_INPUT_CHARS for compatibility.
        max_input_tokens = int(
            os.getenv(
                'CODE_EDITOR_MAX_CONTEXT_TOKENS',
                os.getenv('AI_MAX_INPUT_CHARS', '50000'),
            )
        )
        # Determine the default maximum output tokens.  Use the new
        # CODE_EDITOR_DEFAULT_MAX_OUTPUT_TOKENS variable if provided;
        # fall back to AI_DEFAULT_MAX_TOKENS for compatibility.
        default_max_tokens = int(
            os.getenv(
                'CODE_EDITOR_DEFAULT_MAX_OUTPUT_TOKENS',
                os.getenv('AI_DEFAULT_MAX_TOKENS', '2000'),
            )
        )
        # Determine the absolute maximum tokens allowed in a request.
        # This ceiling is not dynamically adjusted by model profiles
        # but can be used to restrict the ``max_tokens`` parameter on
        # outbound API calls.
        max_tokens = int(os.getenv('AI_MAX_TOKENS', '4000'))
        return {
            # Keep legacy key name for backward compatibility – this
            # value represents a token limit, not a character count.
            'max_input_chars': max_input_tokens,
            # Explicit token key for new code
            'max_input_tokens': max_input_tokens,
            'default_max_tokens': default_max_tokens,
            'max_tokens': max_tokens,
        }
    

    @staticmethod
    def _get_env_int(var_name: str, default: int, min_value: Optional[int] = None) -> int:
        """Parse an integer environment variable with a safe default and optional clamp."""
        try:
            value = int(os.getenv(var_name, str(default)))
        except (TypeError, ValueError):
            value = default
        if min_value is not None:
            value = max(min_value, value)
        return value

    @staticmethod
    def get_agent_config() -> Dict[str, Any]:
        """Get bounded synchronous agent loop settings.

        Environment variables:
        - CODE_EDITOR_AGENT_MAX_ITERATIONS
        - CODE_EDITOR_AGENT_MAX_REPAIR_ATTEMPTS
        - CODE_EDITOR_AGENT_AUTO_APPLY_PATCHES
        - CODE_EDITOR_AGENT_DEFAULT_TEST_TIMEOUT_SECONDS
        - CODE_EDITOR_AGENT_SYNC_EXECUTION_ENABLED
        """
        auto_apply = ConfigService._get_env_bool('CODE_EDITOR_AGENT_AUTO_APPLY_PATCHES', False)
        sync_enabled = ConfigService._get_env_bool('CODE_EDITOR_AGENT_SYNC_EXECUTION_ENABLED', True)
        return {
            'max_iterations': ConfigService._get_env_int('CODE_EDITOR_AGENT_MAX_ITERATIONS', 3, 1),
            'max_repair_attempts': ConfigService._get_env_int('CODE_EDITOR_AGENT_MAX_REPAIR_ATTEMPTS', 2, 0),
            'auto_apply_patches': bool(auto_apply),
            'default_test_timeout_seconds': ConfigService._get_env_int(
                'CODE_EDITOR_AGENT_DEFAULT_TEST_TIMEOUT_SECONDS', 120, 1
            ),
            'sync_execution_enabled': bool(sync_enabled),
        }

    @staticmethod
    def get_quota_defaults() -> Dict[str, Any]:
        """
        Get default quota settings.

        For backward compatibility, provide both ``rpm_limit`` and ``rpm`` keys
        with the same value. Some parts of the codebase may still refer to
        ``rpm`` instead of ``rpm_limit``.
        """
        """
        Get default quota settings for new API keys.

        This method checks for new ``CODE_EDITOR_*`` environment variables
        first, falling back to legacy ``AI_*`` variables for backward
        compatibility.  Specifically, it looks for
        ``CODE_EDITOR_DEFAULT_DAILY_QUOTA`` and
        ``CODE_EDITOR_DEFAULT_RPM_LIMIT``.  If unset, it falls back to
        ``AI_DAILY_QUOTA_DEFAULT`` and ``AI_RPM_LIMIT_DEFAULT``.  The
        returned dictionary includes both ``rpm_limit`` and ``rpm`` keys
        mapped to the same value for compatibility with code that still
        references the legacy ``rpm`` key.
        """
        # Daily quota: new variable overrides legacy default
        daily_quota_str = os.getenv('CODE_EDITOR_DEFAULT_DAILY_QUOTA')
        if daily_quota_str is None:
            daily_quota_str = os.getenv('AI_DAILY_QUOTA_DEFAULT', '1000')
        try:
            daily_quota = int(daily_quota_str)
        except Exception:
            daily_quota = 1000
        # RPM limit: new variable overrides legacy default
        rpm_str = os.getenv('CODE_EDITOR_DEFAULT_RPM_LIMIT')
        if rpm_str is None:
            rpm_str = os.getenv('AI_RPM_LIMIT_DEFAULT', '60')
        try:
            rpm_value = int(rpm_str)
        except Exception:
            rpm_value = 60
        return {
            'daily_quota': daily_quota,
            'rpm_limit': rpm_value,
            'rpm': rpm_value,
        }

    @staticmethod
    def require_api_key() -> bool:
        """Return True if API key authentication is required.

        Checks the ``CODE_EDITOR_REQUIRE_API_KEY`` environment
        variable.  If unset, returns ``False``.  Truthy values include
        ``"1"``, ``"true"``, ``"yes"``, and ``"on"``.  All other
        values result in ``False``.
        """
        return ConfigService._get_env_bool('CODE_EDITOR_REQUIRE_API_KEY', False) or False

    # --------------------------------------------------------------------------
    # Public surface configuration
    #
    # The following helpers gate whether specific endpoints are exposed
    # anonymously.  In production the default is to require an API key for
    # anything beyond basic liveness/readiness checks.  Operators may
    # explicitly enable limited public access by setting the associated
    # environment variable to a truthy value ("1", "true", "yes", or "on").

    @staticmethod
    def public_model_listing_enabled() -> bool:
        """
        Return True if the /models endpoint should be publicly accessible.

        When disabled (default), callers must authenticate with an API key to
        retrieve the list of available models.  Use the environment
        variable ``CODE_EDITOR_PUBLIC_MODEL_LISTING`` to override.
        """
        return ConfigService._get_env_bool('CODE_EDITOR_PUBLIC_MODEL_LISTING', False) or False

    @staticmethod
    def public_provider_listing_enabled() -> bool:
        """
        Return True if the /providers endpoint should be publicly accessible.

        When disabled (default), callers must authenticate with an API key
        to retrieve provider metadata.  Use the environment variable
        ``CODE_EDITOR_PUBLIC_PROVIDER_LISTING`` to override.
        """
        return ConfigService._get_env_bool('CODE_EDITOR_PUBLIC_PROVIDER_LISTING', False) or False

    @staticmethod
    def public_openai_model_listing_enabled() -> bool:
        """
        Return True if the OpenAI‑compatible /models endpoint should be
        publicly accessible.

        When disabled (default), callers must authenticate with an API key
        to retrieve OpenAI model metadata.  Use the environment variable
        ``CODE_EDITOR_PUBLIC_OPENAI_MODEL_LISTING`` to override.
        """
        return ConfigService._get_env_bool('CODE_EDITOR_PUBLIC_OPENAI_MODEL_LISTING', False) or False

    @staticmethod
    def public_metrics_enabled() -> bool:
        """
        Return True if metrics should be exposed publicly.

        Metrics endpoints (e.g. /metrics) should generally only be served on
        internal or authenticated channels.  This flag allows operators to
        expose them without authentication when explicitly enabled via
        ``CODE_EDITOR_PUBLIC_METRICS``.
        """
        return ConfigService._get_env_bool('CODE_EDITOR_PUBLIC_METRICS', False) or False

    @staticmethod
    def log_prompts_enabled() -> bool:
        """Return True if prompt logging is enabled.

        When enabled via the ``CODE_EDITOR_LOG_PROMPTS`` environment
        variable, request input content may be stored in logs.  By
        default, this returns ``False`` to avoid leaking user code or
        instructions into persistent storage.  Truthy values include
        ``"1"``, ``"true"``, ``"yes"``, and ``"on"``.
        """
        return ConfigService._get_env_bool('CODE_EDITOR_LOG_PROMPTS', False) or False
