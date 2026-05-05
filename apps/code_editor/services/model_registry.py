"""
Model registry service for the code editor.

This module defines a ModelRegistryService that resolves model
assignments based on logical roles rather than raw request types.
Roles correspond to the high level tasks performed by the backend
such as planning, chatting, editing, applying patches, autocomplete,
fill‑in‑the‑middle, embeddings, reranking and summarisation.  Each
role can be overridden via environment variables using the naming
convention ``CODE_EDITOR_MODEL_ROLE_<ROLE>`` where ``<ROLE>`` is
uppercase (e.g. ``CODE_EDITOR_MODEL_ROLE_CHAT``).  The value of
these variables may be either a bare model name (in which case the
provider will be auto‑discovered) or a ``provider:model`` pair.

The registry attempts to discover a suitable provider for a role by
consulting the router service (which in turn inspects configured
providers and their capabilities) and by falling back to sensible
defaults when no override is present.  It enriches each entry with
capability flags from both the provider and the model profile and
includes context window and default output limits.  The registry is
designed to avoid network calls during resolution and therefore
does not validate external provider state beyond what is already
cached by the router.

Example usage::

    from code_editor.services.model_registry import ModelRegistryService
    registry = ModelRegistryService()
    mapping = registry.get_registry()
    for role, info in mapping.items():
        print(role, info['provider'], info['model'])

This service is primarily intended for administrative tooling and
documentation and is not currently invoked by the chat/completion
services.  Future updates may integrate it more deeply with the
router.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, asdict
from typing import Dict, Any, Optional, Tuple, List

from .router import RouterService
from django.core.cache import cache
from .config import ConfigService
from .model_profiles import get_model_profile
from ..exceptions import ProviderNotAvailableException


@dataclass
class RoleEntry:
    """Data structure describing a resolved role mapping."""
    role: str
    provider: Optional[str]
    model: Optional[str]
    provider_type: Optional[str]
    capabilities: Dict[str, bool]
    context_window_tokens: Optional[int]
    default_max_output_tokens: Optional[int]
    temperature: Optional[float]
    enabled: bool

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class ModelRegistryService:
    """Service for resolving model and provider assignments by role."""

    #: List of recognised roles.  New roles may be added here without
    #: affecting existing behaviour.  Roles are case‑insensitive.
    ROLES: Tuple[str, ...] = (
        'planning',
        'agent_plan',
        'chat',
        'code',
        'edit',
        'apply',
        'autocomplete',
        'infill',
        'embeddings',
        'embed',
        'review',
        'rerank',
        'summarize',
        'validate_explain',
    )

    #: Mapping from role to the router request type.  This mapping
    #: defines how roles map onto the lower‑level request types used by
    #: RouterService when no explicit override is provided.  Most roles
    #: reuse the same request type (e.g. summarise uses chat).  Unknown
    #: roles default to ``chat``.
    ROLE_TO_REQUEST_TYPE: Dict[str, str] = {
        'planning': 'chat',
        'agent_plan': 'chat',
        'chat': 'chat',
        'code': 'edit',
        'edit': 'edit',
        'apply': 'edit',
        'autocomplete': 'complete',
        'infill': 'infill',
        'embeddings': 'embed',
        'embed': 'embed',
        'review': 'chat',
        'rerank': 'rerank',
        'summarize': 'chat',
        'validate_explain': 'chat',
    }

    #: Mapping from role to the capability it requires on a provider.
    #: Providers that do not advertise the required capability will be
    #: skipped during discovery.  When ``None`` the role is considered
    #: always supported by the provider and model.  These keys align
    #: with the keys returned by ``BaseProvider.get_capabilities()``.
    ROLE_TO_CAPABILITY_KEY: Dict[str, Optional[str]] = {
        'planning': 'chat',
        'agent_plan': 'chat',
        'chat': 'chat',
        'code': 'edit',
        'edit': 'edit',
        'apply': 'edit',
        'autocomplete': 'completion',
        'infill': 'infill',
        'embeddings': 'embeddings',
        'embed': 'embeddings',
        'review': 'chat',
        'rerank': 'rerank',
        'summarize': 'chat',
        'validate_explain': 'chat',
    }

    def __init__(self) -> None:
        self.router = RouterService()

    # ------------------------------------------------------------------
    # Public API

    def get_registry(self) -> Dict[str, Dict[str, Any]]:
        """Return a dictionary mapping each role to its resolved entry.

        The returned dictionary maps role names to a serialisable
        ``RoleEntry`` representation (as plain dictionaries).  Roles
        absent from ``ROLES`` are ignored.  Any errors during
        resolution will result in the ``enabled`` flag being set to
        ``False`` and the provider/model set to ``None``.

        :returns: mapping of role to entry dict
        """
        registry: Dict[str, Dict[str, Any]] = {}
        for role in self.ROLES:
            try:
                entry = self.get_role_entry(role)
                registry[role] = entry.to_dict()
            except Exception:
                # In the event of unexpected errors, mark the role as
                # disabled but still include it in the registry.  Do
                # not propagate exceptions outside the registry.
                registry[role] = RoleEntry(
                    role=role,
                    provider=None,
                    model=None,
                    provider_type=None,
                    capabilities={},
                    context_window_tokens=None,
                    default_max_output_tokens=None,
                    temperature=None,
                    enabled=False,
                ).to_dict()
        return registry
    def get_role_entry(self, role: str) -> RoleEntry:
        """Return the resolved entry for a specific role with caching."""
        role_key = role.lower()
        cache_key = f"code_editor:model_registry:{role_key}"
        entry_dict = cache.get(cache_key)
        if entry_dict:
            try:
                return RoleEntry(**entry_dict)
            except Exception:
                cache.delete(cache_key)
        entry = self._resolve_role(role_key)
        cache.set(cache_key, entry.to_dict(), timeout=300)
        return entry
    def _resolve_role(self, role: str) -> RoleEntry:
        """Resolve a role into a provider and model.

        This method first checks for an environment variable override
        using the naming convention ``CODE_EDITOR_MODEL_ROLE_<ROLE>``.  If
        present, it attempts to parse the value as ``provider:model``.
        When a provider is specified explicitly, it is used even if
        multiple providers support the role.  When only a model is
        specified, providers are searched in the order returned by
        ``RouterService.get_available_providers()``.  If no override is
        found, the router is consulted using the request type derived
        from the role via ``ROLE_TO_REQUEST_TYPE``.

        Capability requirements are enforced: providers must advertise
        support for the capability required by the role (e.g. chat,
        completion, edit).  Model profiles are used to merge model
        capabilities with provider capabilities, yielding a final set
        of flags for the entry.

        :param role: role name (lowercase)
        :returns: resolved ``RoleEntry``
        :raises ProviderNotAvailableException: if no provider is available
        """
        role_key = role.lower()
        # Determine environment variable override
        env_var = f"CODE_EDITOR_MODEL_ROLE_{role_key.upper()}"
        override = os.getenv(env_var)
        provider_name: Optional[str] = None
        model_name: Optional[str] = None
        if override:
            # If the override contains a colon, treat the left hand
            # component as the provider name and the right as the model.
            if ':' in override:
                parts = override.split(':', 1)
                provider_name = parts[0].strip() or None
                model_name = parts[1].strip() or None
            else:
                # No provider specified; treat the entire value as the model
                model_name = override.strip() or None
        # Determine request type for fallback
        request_type = self.ROLE_TO_REQUEST_TYPE.get(role_key, 'chat')
        # Determine required capability
        required_cap = self.ROLE_TO_CAPABILITY_KEY.get(role_key)
        # Resolve provider instance
        provider = None
        if provider_name:
            provider = self.router.get_provider_by_name(provider_name)
            if provider is None:
                raise ProviderNotAvailableException(
                    f"Provider '{provider_name}' specified for role '{role_key}' is not configured"
                )
        else:
            # Auto discover provider using router based on request type
            provider = self.router.get_provider(request_type)
            if provider is None:
                raise ProviderNotAvailableException(
                    f"No provider available for role '{role_key}'"
                )
        # Validate provider capability
        if required_cap:
            caps = provider.get_capabilities() or {}
            if not caps.get(required_cap, False):
                raise ProviderNotAvailableException(
                    f"Provider '{provider.name}' does not support required capability '{required_cap}' for role '{role_key}'"
                )
        # Determine model name
        resolved_model: Optional[str]
        if model_name:
            resolved_model = model_name
        else:
            # Use provider's default model if unspecified
            resolved_model = provider.config.get('model')
        # Build capabilities map by combining model profile and provider capabilities
        capabilities = self._combine_capabilities(provider, resolved_model)
        # Load model profile to get limits
        profile = get_model_profile(resolved_model) if resolved_model else None
        context_window = profile.context_window_tokens if profile else None
        default_max_out = profile.default_max_output_tokens if profile else None
        # Heuristic default temperatures per role (configurable via env?)
        temperature = None
        # Determine provider type (local vs remote) heuristically: treat
        # providers named 'local', 'fast', 'strong' and 'ollama' as local
        local_names = {'llama_cpp', 'local', 'fast', 'strong', 'ollama', 'vllm'}
        provider_type = 'local' if provider.name in local_names else 'remote'
        # Determine if the role is enabled (provider exists and model resolved)
        enabled = provider is not None and bool(resolved_model)
        return RoleEntry(
            role=role_key,
            provider=provider.name if provider else None,
            model=resolved_model,
            provider_type=provider_type,
            capabilities=capabilities,
            context_window_tokens=context_window,
            default_max_output_tokens=default_max_out,
            temperature=temperature,
            enabled=enabled,
        )

    def _combine_capabilities(self, provider: Any, model_name: Optional[str]) -> Dict[str, bool]:
        """Combine provider and model capability flags.

        This helper merges provider‑level capability flags with model‑level
        information from the model profile.  A capability is marked
        ``True`` only if both the provider and the model (when known)
        support it.  Unknown model profiles are assumed to support all
        capabilities offered by the provider.

        :param provider: provider instance
        :param model_name: name of the model or ``None``
        :returns: mapping of capability names to boolean values
        """
        caps = provider.get_capabilities() or {}
        try:
            profile = get_model_profile(model_name) if model_name else None
        except Exception:
            profile = None
        # Basic capabilities
        combined: Dict[str, bool] = {
            'chat': bool(caps.get('chat', False) and (profile.supports_chat if profile else True)),
            'completion': bool(caps.get('completion', False) and (profile.supports_completion if profile else True)),
            'edit': bool(caps.get('edit', False)),
            'infill': bool(caps.get('infill', False) and (profile.supports_infill if profile else True)),
            'embeddings': bool(caps.get('embeddings', False) and (profile.supports_embeddings if profile else True)),
            'rerank': bool(caps.get('rerank', False)),
            'streaming': bool(caps.get('streaming', False) and (profile.supports_streaming if profile else True)),
        }
        # Additional optional flags.  Providers may advertise support for
        # tool calling or JSON mode via custom keys.  Default to False.
        for optional_key in ['tools', 'json']:
            combined[optional_key] = bool(caps.get(optional_key, False))
        # FIM (fill‑in‑the‑middle) is indicated by the infill capability
        combined['fim'] = combined['infill']
        # Native suffix completion is an alias for infill.  Use the provider's
        # advertised suffix_completion flag when available and ensure the
        # model profile (if any) permits infill.
        try:
            combined['suffix_completion'] = bool(
                caps.get('suffix_completion', False) and (profile.supports_infill if profile else True)
            )
        except Exception:
            combined['suffix_completion'] = False
        # Native suffix completion is an alias for infill.  Use the provider's
        # advertised suffix_completion flag when available and ensure the
        # model profile (if any) permits infill.
        try:
            combined['suffix_completion'] = bool(
                caps.get('suffix_completion', False) and (profile.supports_infill if profile else True)
            )
        except Exception:
            combined['suffix_completion'] = False
        return combined
