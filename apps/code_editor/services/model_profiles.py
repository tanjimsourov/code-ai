"""
Model profile configuration for the code editor.

This module defines a set of default model profiles describing the
capabilities and context window sizes of various language models. A
model profile specifies the family name, the maximum number of input
tokens the model can handle in a single request, the default number
of output tokens to request, and boolean flags indicating whether
certain features (chat, completion, infill, embeddings, streaming)
are supported.  These defaults are intentionally conservative; you
can override the context window and default output tokens globally
via environment variables ``CODE_EDITOR_MAX_CONTEXT_TOKENS`` and
``CODE_EDITOR_DEFAULT_MAX_OUTPUT_TOKENS``.

Model families supported include:

* **DeepSeek** – covers ``deepseek-coder``, ``deepseek-coder-v2`` and
  ``deepseek-v3`` style models.
* **Qwen** – covers ``qwen-coder`` style models.
* **CodeLlama** – covers ``codellama`` style models.
* **StarCoder** – covers ``starcoder`` style models.
* **OpenAI-compatible** – a fallback for generic OpenAI models like
  ``gpt-3.5-turbo`` or ``gpt-4``.

These profiles are used by service layers to determine appropriate
token limits when building context for model calls.
"""

from dataclasses import dataclass
from typing import Dict
import os


@dataclass(frozen=True)
class ModelProfile:
    """Configuration describing a language model's capabilities."""
    model_family: str
    context_window_tokens: int
    default_max_output_tokens: int
    supports_chat: bool
    supports_completion: bool
    supports_infill: bool
    supports_embeddings: bool
    supports_streaming: bool


# Default model profiles.  These values reflect typical context
# window sizes and capabilities as of 2025 for popular model
# families.  They may be overridden via environment variables.
_DEFAULT_PROFILES: Dict[str, ModelProfile] = {
    'deepseek': ModelProfile(
        model_family='deepseek',
        context_window_tokens=16384,
        default_max_output_tokens=1024,
        supports_chat=True,
        supports_completion=True,
        supports_infill=True,
        supports_embeddings=True,
        supports_streaming=False,
    ),
    'qwen': ModelProfile(
        model_family='qwen',
        context_window_tokens=32768,
        default_max_output_tokens=2048,
        supports_chat=True,
        supports_completion=True,
        supports_infill=True,
        supports_embeddings=True,
        supports_streaming=False,
    ),
    'codellama': ModelProfile(
        model_family='codellama',
        context_window_tokens=16384,
        default_max_output_tokens=1024,
        supports_chat=True,
        supports_completion=True,
        supports_infill=True,
        supports_embeddings=False,
        supports_streaming=False,
    ),
    'starcoder': ModelProfile(
        model_family='starcoder',
        context_window_tokens=32768,
        default_max_output_tokens=2048,
        supports_chat=True,
        supports_completion=True,
        supports_infill=False,
        supports_embeddings=False,
        supports_streaming=False,
    ),
    'openai': ModelProfile(
        model_family='openai',
        context_window_tokens=8192,
        default_max_output_tokens=1024,
        supports_chat=True,
        supports_completion=True,
        supports_infill=False,
        supports_embeddings=True,
        supports_streaming=True,
    ),
}


def _apply_env_overrides(profile: ModelProfile) -> ModelProfile:
    """
    Apply global environment overrides to a model profile.

    Environment variables ``CODE_EDITOR_MAX_CONTEXT_TOKENS`` and
    ``CODE_EDITOR_DEFAULT_MAX_OUTPUT_TOKENS`` allow administrators to
    adjust token limits without modifying code.  Only positive integer
    values are considered; invalid values are ignored.
    """
    max_ctx = os.getenv('CODE_EDITOR_MAX_CONTEXT_TOKENS')
    def_max_out = os.getenv('CODE_EDITOR_DEFAULT_MAX_OUTPUT_TOKENS')
    context_tokens = profile.context_window_tokens
    max_output = profile.default_max_output_tokens
    try:
        if max_ctx:
            ctx_val = int(max_ctx)
            if ctx_val > 0:
                context_tokens = ctx_val
    except Exception:
        pass
    try:
        if def_max_out:
            out_val = int(def_max_out)
            if out_val > 0:
                max_output = out_val
    except Exception:
        pass
    return ModelProfile(
        model_family=profile.model_family,
        context_window_tokens=context_tokens,
        default_max_output_tokens=max_output,
        supports_chat=profile.supports_chat,
        supports_completion=profile.supports_completion,
        supports_infill=profile.supports_infill,
        supports_embeddings=profile.supports_embeddings,
        supports_streaming=profile.supports_streaming,
    )


def get_model_profile(model_name: str | None) -> ModelProfile:
    """
    Return the model profile for the given model name.

    The lookup is case-insensitive and attempts to infer the model
    family from substrings in the provided name.  If no specific
    profile matches, the generic OpenAI-compatible profile is used.
    Environment overrides are applied to the returned profile.

    :param model_name: Name of the model (may include version suffix)
    :returns: A ``ModelProfile`` describing capabilities and limits
    """
    if not model_name:
        base_profile = _DEFAULT_PROFILES['openai']
        return _apply_env_overrides(base_profile)
    lower = model_name.lower()
    if 'deepseek' in lower:
        base_profile = _DEFAULT_PROFILES['deepseek']
    elif 'qwen' in lower:
        base_profile = _DEFAULT_PROFILES['qwen']
    elif 'codellama' in lower or 'code-llama' in lower or 'llama' in lower:
        base_profile = _DEFAULT_PROFILES['codellama']
    elif 'starcoder' in lower:
        base_profile = _DEFAULT_PROFILES['starcoder']
    else:
        base_profile = _DEFAULT_PROFILES['openai']
    return _apply_env_overrides(base_profile)