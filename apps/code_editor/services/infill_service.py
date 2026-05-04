"""Infill service for fill‑in‑the‑middle code completions.

This service coordinates with the router to find a provider that
supports fill‑in‑the‑middle (FIM) completions.  It truncates the
provided prefix and suffix based on token budgets, builds the
appropriate prompt, invokes the provider and returns the inserted
code along with the raw provider response.  When no infill‑capable
provider is available, a ``ProviderNotAvailableException`` is raised.

The service logs each request using ``CodeEditorRequestLog`` for
auditing and metering purposes.  The token budgets and model
defaults are derived from environment configuration via
``ConfigService`` and ``model_profiles``.
"""

from __future__ import annotations

import time
from typing import Dict, Any, Optional

from django.utils import timezone  # noqa: F401  # imported for parity with other services

from ..models import CodeEditorRequestLog
from ..providers.utils import parse_text_completion_response
from ..exceptions import InvalidRequestException, ProviderNotAvailableException
from .router import RouterService
from .prompt_builder import PromptBuilderService
from .context_builder import ContextBuilderService
from .config import ConfigService
from .model_profiles import get_model_profile


class InfillService:
    """Service for handling fill‑in‑the‑middle code completion requests.

    This service coordinates with the router to find a provider that
    supports fill‑in‑the‑middle (FIM) completions.  It truncates the
    provided prefix and suffix based on token budgets, builds the
    appropriate prompt, invokes the provider and returns the inserted
    code along with the raw provider response.

    When instantiated with ``api_key`` and ``user`` parameters, these
    values are recorded in the request logs.  Token estimates are
    computed using the ``count_tokens`` helper and stored in the
    ``input_chars`` and ``output_chars`` fields of
    ``CodeEditorRequestLog`` (for historical compatibility these
    fields record token counts when using the new logging logic).
    """

    def __init__(self, api_key: Optional[Any] = None, user: Optional[Any] = None) -> None:
        self.router = RouterService()
        self.prompt_builder = PromptBuilderService()
        self.context_builder = ContextBuilderService()
        # Optional API key and user for logging.  These values are
        # persisted to CodeEditorRequestLog via _log_request.
        self.api_key = api_key
        self.user = user

    def infill_code(
        self,
        prefix: str,
        suffix: str,
        language: Optional[str] = None,
        filename: Optional[str] = None,
        cursor_context: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        model: Optional[str] = None,
        stream: bool = False,
        **kwargs
    ) -> Dict[str, Any]:
        """Handle a fill‑in‑the‑middle request.

        :param prefix: Code before the insertion point (required)
        :param suffix: Code after the insertion point (required)
        :param language: Optional programming language hint
        :param filename: Optional filename for context
        :param cursor_context: Optional additional context near the cursor
        :param temperature: Sampling temperature
        :param max_tokens: Maximum number of tokens to generate
        :param model: Optional override for model name
        :param stream: Whether to stream the response
        :param kwargs: Additional provider‑specific parameters
        :returns: Dictionary with ``inserted_text`` and ``raw_response``
        :raises InvalidRequestException: if prefix or suffix are empty
        :raises ProviderNotAvailableException: if no infill provider is available
        """
        start_time = time.time()
        # Validate inputs
        if not prefix:
            raise InvalidRequestException("Prefix cannot be empty for infill")
        if suffix is None or suffix == "":
            raise InvalidRequestException("Suffix cannot be empty for infill")
        try:
            # Determine request limits and model profile
            limits = ConfigService.get_request_limits()
            # Check for provider override
            provider_override: Optional[str] = kwargs.pop('provider', None)
            # Determine provider chain (infill chain) or explicit provider
            if provider_override:
                chain = [provider_override]
            else:
                chain = self.router._get_provider_chain('infill')  # type: ignore[attr-defined]
            last_exception: Optional[Exception] = None
            for provider_name in chain:
                provider = self.router.get_provider_by_name(provider_name)
                if not provider:
                    continue
                # Skip providers that do not advertise infill capability
                try:
                    if not provider.supports_infill():
                        continue
                except Exception:
                    continue
                # Determine model name for this provider: explicit override or provider default
                model_name = model or provider.config.get('model')
                # If an explicit model override is provided, ensure the provider has it
                if model:
                    try:
                        model_info = provider.get_model_info(model)
                    except Exception:
                        model_info = None
                    if not model_info:
                        # If the override provider is set explicitly, raise; otherwise skip this provider
                        if provider_override:
                            raise InvalidRequestException(f"Model '{model}' not found for provider '{provider.name}'")
                        else:
                            continue
                # Retrieve model profile
                profile = get_model_profile(model_name)
                # Determine desired output tokens
                env_max_tokens = limits.get('max_tokens') or 0
                if max_tokens:
                    output_tokens = min(max_tokens, env_max_tokens) if env_max_tokens else max_tokens
                else:
                    default_out = profile.default_max_output_tokens
                    if env_max_tokens:
                        output_tokens = min(default_out, env_max_tokens)
                    else:
                        output_tokens = default_out
                # Compute maximum input token budget
                global_input_budget = limits.get('max_input_tokens') or limits.get('max_input_chars')
                model_input_budget = max(1, profile.context_window_tokens - output_tokens)
                if global_input_budget:
                    max_input_tokens = min(model_input_budget, global_input_budget)
                else:
                    max_input_tokens = model_input_budget
                # Build context using token limits (reuse completion context)
                context = self.context_builder.build_completion_context(
                    prefix, suffix, max_input_tokens
                )
                truncated_prefix = context.get('prefix', '')
                truncated_suffix = context.get('suffix', '') if context.get('suffix') is not None else suffix
                try:
                    # Invoke provider's infill method.  This may return a
                    # streaming generator if ``stream`` is True.
                    response = provider.infill_code(
                        prefix=truncated_prefix,
                        suffix=truncated_suffix,
                        model=model_name,
                        language=language,
                        filename=filename,
                        temperature=temperature,
                        max_tokens=output_tokens,
                        stream=stream,
                        **kwargs
                    )
                    # If streaming, wrap response to log after stream
                    if stream:
                        provider_name = provider.name
                        model_cfg = model_name
                        # Estimate input tokens for logging
                        from ..utils.token_counter import count_tokens  # local import
                        input_tokens = count_tokens([prefix, suffix])
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
                                # Estimate output tokens based on accumulated output chars
                                output_tokens = count_tokens('x' * output_chars_total)
                                self._log_request(
                                    endpoint='/api/code-editor/infill',
                                    provider=provider_name,
                                    model_name=model_cfg,
                                    request_kind='infill',
                                    status='success',
                                    latency_ms=latency_ms,
                                    input_chars=input_tokens,
                                    output_chars=output_tokens
                                )
                            except Exception as e:
                                latency_ms = int((time.time() - start_time) * 1000)
                                self._log_request(
                                    endpoint='/api/code-editor/infill',
                                    provider=provider_name,
                                    model_name=model_cfg,
                                    request_kind='infill',
                                    status='error',
                                    latency_ms=latency_ms,
                                    input_chars=input_tokens,
                                    output_chars=0,
                                    error_message=str(e)
                                )
                                raise
                        # Return the streaming generator directly.  The API
                        # layer will convert to SSE.
                        return stream_wrapper()
                    # Non-streaming: parse inserted text and log
                    inserted_text = parse_text_completion_response(response)
                    latency_ms = int((time.time() - start_time) * 1000)
                    from ..utils.token_counter import count_tokens  # local import
                    input_tokens = count_tokens([prefix, suffix])
                    output_tokens = count_tokens('x' * len(inserted_text))
                    self._log_request(
                        endpoint='/api/code-editor/infill',
                        provider=provider.name,
                        model_name=model_name,
                        request_kind='infill',
                        status='success',
                        latency_ms=latency_ms,
                        input_chars=input_tokens,
                        output_chars=output_tokens
                    )
                    return {
                        'inserted_text': inserted_text,
                        'raw_response': response,
                    }
                except Exception as ex:
                    # Record exception and try next provider
                    last_exception = ex
                    continue
            # If we exit the loop without returning, no provider succeeded
            if last_exception:
                raise ProviderNotAvailableException(str(last_exception))
            else:
                raise ProviderNotAvailableException('No infill provider available')
        except Exception as e:
            # Log error
            latency_ms = int((time.time() - start_time) * 1000)
            from ..utils.token_counter import count_tokens  # local import
            input_tokens = count_tokens([prefix, suffix])
            self._log_request(
                endpoint='/api/code-editor/infill',
                provider='unknown',
                model_name='unknown',
                request_kind='infill',
                status='error',
                latency_ms=latency_ms,
                input_chars=input_tokens,
                output_chars=0,
                error_message=str(e)
            )
            raise

    def _log_request(
        self,
        *,
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
        """Internal helper to log infill requests.

        This method wraps ``CodeEditorRequestLog.log_request`` and
        ensures that the optional ``api_key`` and ``user`` attributes
        supplied to the service constructor are passed through to the
        log.  The ``input_chars`` and ``output_chars`` arguments
        represent estimated token counts rather than raw character
        counts.
        """
        # Sanitize error messages to avoid logging long stack traces
        err_msg = None
        if error_message:
            err_msg = str(error_message)[:500]
        CodeEditorRequestLog.log_request(
            endpoint=endpoint,
            provider=provider,
            model_name=model_name,
            request_kind=request_kind,
            status=status,
            latency_ms=latency_ms,
            input_chars=input_chars,
            output_chars=output_chars,
            error_message=err_msg,
            api_key=self.api_key,
            user=self.user,
        )