import requests
import json
from typing import Dict, List, Optional, Any
from urllib.parse import urlparse

from .base import BaseProvider
from ..exceptions import ProviderNotAvailableException, ProviderTimeoutException
from .streaming import StreamChunk


class OpenAICompatibleProvider(BaseProvider):
    """Provider for OpenAI‑compatible APIs, including llama.cpp, vLLM, LM Studio and DeepSeek.

    This implementation normalises the base URL, supports configurable
    headers and API keys, retries requests and falls back to
    ``/v1/`` endpoints when ``/`` endpoints are unavailable.
    """

    def __init__(self, name: str, config: Dict[str, Any]):
        super().__init__(name, config)
        # Normalise base URL to remove trailing slashes and any API
        # version suffixes (e.g. /v1)
        raw_url = config.get('url', '') or config.get('base_url', '') or ''
        self.base_url = self._normalize_base_url(raw_url)
        self.default_model = config.get('model', 'gpt-3.5-turbo')
        self.api_key = config.get('api_key') or config.get('token')
        # Prepare headers; allow user‑supplied headers to override
        self.headers: Dict[str, str] = {
            'Content-Type': 'application/json',
        }
        # Include API key in Authorization header if provided
        if self.api_key:
            self.headers['Authorization'] = f'Bearer {self.api_key}'
        # Merge any custom headers from config
        for key, value in (config.get('headers') or {}).items():
            # Do not allow overriding Authorization via headers
            if key.lower() != 'authorization':
                self.headers[key] = value

    # ------------------------------------------------------------------
    # Capability overrides

    def supports_chat(self) -> bool:
        """Return True if chat completions are supported."""
        return True

    def supports_completion(self) -> bool:
        """Return True if plain text completions are supported."""
        return True

    def supports_edit(self) -> bool:
        """Return True if code editing is supported."""
        return True

    def supports_streaming(self) -> bool:
        """OpenAI‑compatible APIs generally support streaming."""
        return True

    def supports_embeddings(self) -> bool:
        """Return True as OpenAI‑compatible APIs support embeddings."""
        return True

    def supports_infill(self) -> bool:
        """Return True to indicate this provider can handle infill completions.

        OpenAI‑compatible providers typically accept a ``suffix``
        parameter on the ``/completions`` endpoint.  When the
        underlying server does not support suffix natively, a
        fallback prompt will be used.
        """
        return True

    def supports_json(self) -> bool:
        """Return True to indicate support for structured JSON responses.

        Many OpenAI‑compatible providers support the ``response_format``
        parameter which yields JSON output when set to ``{"type": "json_object"}``.
        """
        return True

    def supports_tools(self) -> bool:
        """Return True if function/tool calling is supported.

        Some OpenAI‑compatible servers implement the ``functions`` or
        ``tools`` API.  We optimistically enable this capability; callers
        should handle errors if unsupported.
        """
        return True

    def supports_suffix_completion(self) -> bool:
        """Return True to indicate suffix/FIM completions are supported."""
        return True

    # ------------------------------------------------------------------
    # Utility methods

    def _normalize_base_url(self, url: str) -> str:
        """Normalize base URL to avoid duplicate path segments and API versions."""
        if not url:
            return ''
        parsed = urlparse(url)
        base_path = parsed.path.rstrip('/')
        # Remove API version prefixes (/v1 or /api/v1)
        api_prefixes = ['/v1', '/api', '/api/v1']
        for prefix in api_prefixes:
            if base_path.endswith(prefix):
                base_path = base_path[:-len(prefix)]
                break
        if base_path:
            normalized = f"{parsed.scheme}://{parsed.netloc}{base_path}"
        else:
            normalized = f"{parsed.scheme}://{parsed.netloc}"
        return normalized.rstrip('/')

    def _request_with_fallback(
        self,
        method: str,
        endpoints: List[str],
        data: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Attempt a request against multiple endpoints with retries.

        :param method: HTTP method (GET or POST)
        :param endpoints: list of endpoint paths to try in order
        :param data: JSON payload for POST requests
        :returns: parsed JSON response from the first successful endpoint
        :raises ProviderTimeoutException: on timeout
        :raises ProviderNotAvailableException: when no endpoints succeed
        """
        last_timeout = False
        for endpoint in endpoints:
            url = f"{self.base_url}{endpoint}"
            for attempt in range(max(1, self.max_retries)):
                try:
                    if method.upper() == 'GET':
                        response = requests.get(url, headers=self.headers, timeout=self.timeout)
                    else:
                        response = requests.post(url, json=data, headers=self.headers, timeout=self.timeout)
                    # Raise for HTTP errors
                    response.raise_for_status()
                    # Successful response
                    try:
                        return response.json()
                    except Exception:
                        # Unexpected content type; return empty dict
                        return {}
                except requests.Timeout:
                    # Timeout; mark and retry (if attempts remain)
                    last_timeout = True
                    continue
                except requests.HTTPError as http_err:
                    status_code = 0
                    if hasattr(http_err, 'response') and http_err.response is not None:
                        status_code = http_err.response.status_code
                    # 404/405 => try next endpoint
                    if status_code in {404, 405}:
                        break  # break retry loop; try next endpoint
                    # 5xx => provider unavailable; break to next endpoint
                    if status_code >= 500:
                        break  # provider likely unavailable; try next endpoint
                    # Other HTTP errors => do not retry; treat as provider unavailable
                    break
                except Exception:
                    # Unknown error; break to next endpoint
                    break
            # after attempts, proceed to next endpoint
            continue
        # If we get here, none of the endpoints succeeded
        if last_timeout:
            raise ProviderTimeoutException()
        raise ProviderNotAvailableException()

    # ------------------------------------------------------------------
    # Streaming request helpers

    def _stream_request_with_fallback(
        self,
        endpoints: List[str],
        data: Optional[Dict[str, Any]] = None
    ) -> Any:
        """Attempt a streaming POST request against multiple endpoints.

        When ``stream`` is requested on an API call (e.g. chat, completions),
        this helper tries each endpoint in sequence with streaming
        enabled on the HTTP client.  The first endpoint that returns a
        successful response will be used.  The response body is
        parsed incrementally and yielded as ``StreamChunk`` objects.  If
        all endpoints fail due to client or server errors, the helper
        raises the appropriate exception.

        :param endpoints: list of endpoint paths to try in order
        :param data: JSON payload to send with the request
        :returns: generator of ``StreamChunk`` objects
        :raises ProviderTimeoutException: on timeout
        :raises ProviderNotAvailableException: when no endpoints succeed
        """
        last_timeout = False

        for endpoint in endpoints:
            url = f"{self.base_url}{endpoint}"
            # Attempt streaming request on this endpoint
            for attempt in range(max(1, self.max_retries)):
                try:
                    response = requests.post(
                        url,
                        json=data,
                        headers=self.headers,
                        timeout=self.timeout,
                        stream=True
                    )
                    # Raise for HTTP errors
                    response.raise_for_status()
                    # Return a generator that parses the stream
                    return self._parse_stream_response(response)
                except requests.Timeout:
                    last_timeout = True
                    # try again if retries remain
                    continue
                except requests.HTTPError as http_err:
                    # Check status codes for fallback logic
                    status_code = 0
                    if hasattr(http_err, 'response') and http_err.response is not None:
                        status_code = http_err.response.status_code
                    # 404/405 => try next endpoint
                    if status_code in {404, 405}:
                        break
                    # 5xx => provider unavailable; break to next endpoint
                    if status_code >= 500:
                        break
                    # Other HTTP errors => stop trying this endpoint
                    break
                except Exception:
                    # Unknown error; try next endpoint
                    break
            # proceed to next endpoint if this one failed
            continue
        # If we get here, none of the endpoints succeeded
        if last_timeout:
            raise ProviderTimeoutException()
        raise ProviderNotAvailableException()

    def _parse_stream_response(self, response: requests.Response) -> Any:
        """Parse a streaming HTTP response into chunks.

        This generator reads lines from the streaming HTTP response
        returned by the provider and yields ``StreamChunk`` instances
        representing incremental pieces of content.  It supports
        parsing Server‑Sent Events (SSE) lines prefixed with
        ``data:``, OpenAI delta/text chunks and Ollama‑style JSON
        messages.  When a completion is finished (e.g. a
        ``finish_reason`` field is present, or a ``[DONE]`` marker is
        encountered), a final chunk with ``done=True`` is yielded
        before exiting.

        :param response: The HTTP response object from ``requests`` with
            ``stream=True``
        :returns: generator yielding ``StreamChunk`` objects
        """
        # Use iter_lines to process SSE lines incrementally
        iterator = response.iter_lines(decode_unicode=True, chunk_size=1)
        for raw_line in iterator:
            if not raw_line:
                continue
            line = raw_line  # decode_unicode returns str
            data = None
            # SSE lines may include multiple fields (event:, data:).  We
            # focus on data lines and ignore event lines.  If the line
            # starts with ``data:``, extract the payload; otherwise treat
            # the entire line as payload (for providers that emit plain
            # JSON per line).
            if line.startswith('data:'):
                data = line[len('data:'):].strip()
            else:
                # Skip comments and event lines
                if line.startswith('event:') or line.startswith(':'):
                    continue
                data = line.strip()
            # Empty data after stripping indicates no content
            if not data:
                continue
            # Handle explicit stream termination marker
            if data == '[DONE]':
                yield StreamChunk(content='', done=True, raw=data)
                break
            # Attempt to parse JSON payload
            try:
                payload = json.loads(data)
            except Exception:
                # Non‑JSON payload; yield raw text as content
                yield StreamChunk(content=data, raw=data)
                continue
            # Determine content and completion status
            content = ''
            done_flag = False
            # OpenAI/llama.cpp style: payload["choices"][0]
            if isinstance(payload, dict):
                choices = payload.get('choices')
                if isinstance(choices, list) and choices:
                    choice = choices[0]
                    if isinstance(choice, dict):
                        # Delta format
                        if 'delta' in choice and isinstance(choice['delta'], dict):
                            delta = choice['delta']
                            content = delta.get('content') or ''
                            # finish_reason indicates stream end
                            if choice.get('finish_reason') is not None:
                                done_flag = True
                        # Text format
                        elif 'text' in choice:
                            # Text completions may include newline or partial
                            content = choice.get('text') or ''
                            if choice.get('finish_reason') is not None:
                                done_flag = True
                        # Message format
                        elif 'message' in choice and isinstance(choice['message'], dict):
                            msg = choice['message']
                            content = msg.get('content') or ''
                            if choice.get('finish_reason') is not None:
                                done_flag = True
                else:
                    # Ollama style: top‑level message or content
                    if 'message' in payload and isinstance(payload['message'], dict):
                        msg = payload['message']
                        content = msg.get('content') or ''
                        # Many Ollama streams include a ``done`` boolean
                        if payload.get('done') or msg.get('finish_reason') is not None:
                            done_flag = True
                    else:
                        # Fallback: plain ``content`` field
                        content = payload.get('content') or ''
                        if payload.get('finish_reason') is not None or payload.get('done'):
                            done_flag = True
            # Yield the chunk if any content
            yield StreamChunk(content=content, done=done_flag, raw=payload)
            if done_flag:
                break
        # Ensure the response is fully consumed/closed
        try:
            response.close()
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Public API methods

    def is_available(self) -> bool:
        """A provider is considered available if a base URL is configured."""
        return bool(self.base_url)

    def chat_completion(
        self,
        messages: List[Dict[str, str]],
        model: Optional[str],
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        stream: bool = False,
        **kwargs
    ) -> Dict[str, Any]:
        """Generate a chat completion via POST /chat/completions or fallback."""
        data: Dict[str, Any] = {
            'model': model or self.default_model,
            'messages': messages,
            'temperature': temperature,
            'stream': stream,
        }
        if max_tokens is not None:
            data['max_tokens'] = max_tokens
        # Merge additional parameters
        for key, value in kwargs.items():
            if value is not None:
                data[key] = value
        # If streaming is requested, return a generator
        if stream:
            return self._stream_request_with_fallback(
                ['/chat/completions', '/v1/chat/completions'],
                data
            )
        # Otherwise perform a standard request
        return self._request_with_fallback(
            'POST',
            ['/chat/completions', '/v1/chat/completions'],
            data
        )

    def text_completion(
        self,
        prompt: str,
        model: Optional[str],
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        stream: bool = False,
        **kwargs
    ) -> Dict[str, Any]:
        """Generate a text completion via POST /completions or fallback."""
        data: Dict[str, Any] = {
            'model': model or self.default_model,
            'prompt': prompt,
            'temperature': temperature,
            'stream': stream,
        }
        if max_tokens is not None:
            data['max_tokens'] = max_tokens
        for key, value in kwargs.items():
            if value is not None:
                data[key] = value
        # Streaming: return generator
        if stream:
            return self._stream_request_with_fallback(
                ['/completions', '/v1/completions'],
                data
            )
        # Non‑streaming: return full response
        return self._request_with_fallback(
            'POST',
            ['/completions', '/v1/completions'],
            data
        )

    def edit_code(
        self,
        instruction: str,
        code: str,
        model: Optional[str],
        temperature: float = 0.3,
        max_tokens: Optional[int] = None,
        **kwargs
    ) -> Dict[str, Any]:
        """Edit code by issuing a chat completion request with special prompts."""
        messages = [
            {
                'role': 'system',
                'content': 'You are a code editing assistant. Follow the instruction to edit the provided code.'
            },
            {
                'role': 'user',
                'content': f'Instruction: {instruction}\n\nCode:\n```\n{code}\n```'
            }
        ]
        return self.chat_completion(
            messages=messages,
            model=model or self.default_model,
            temperature=temperature,
            max_tokens=max_tokens,
            **kwargs
        )

    def get_models(self) -> List[Dict[str, Any]]:
        """List available models via GET /models or fallback."""
        try:
            response = self._request_with_fallback('GET', ['/models', '/v1/models'])
            # Many providers return {'data': [..]} for models
            models = response.get('data') or response.get('models') or []
            if isinstance(models, list):
                return models
            return []
        except ProviderTimeoutException:
            raise
        except Exception:
            # Return the default model if listing fails
            return [
                {
                    'id': self.default_model,
                    'object': 'model',
                    'created': 0,
                    'owned_by': self.name,
                }
            ]

    def embeddings(
        self,
        texts: List[str],
        model: Optional[str],
        **kwargs
    ) -> List[List[float]]:
        """Generate embeddings via POST /embeddings or fallback."""
        data: Dict[str, Any] = {
            'model': model or self.default_model,
            # OpenAI expects 'input'; other APIs may support 'input' or 'prompt'
            'input': texts,
        }
        for key, value in kwargs.items():
            if value is not None:
                data[key] = value
        response = self._request_with_fallback(
            'POST',
            ['/embeddings', '/v1/embeddings'],
            data
        )
        embeddings_data = response.get('data') or []
        result: List[List[float]] = []
        for item in embeddings_data:
            if isinstance(item, dict):
                # OpenAI returns {'embedding': [...], 'index': i}
                embedding = item.get('embedding') or item.get('vector')
                if embedding is not None:
                    result.append(embedding)
        return result

    # ------------------------------------------------------------------
    # Fill‑in‑the‑middle (infill) API

    def infill_code(
        self,
        prefix: str,
        suffix: str,
        model: Optional[str],
        language: Optional[str] = None,
        filename: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        stream: bool = False,
        **kwargs
    ) -> Dict[str, Any]:
        """Generate code to insert between ``prefix`` and ``suffix``.

        This method first attempts to call the native OpenAI‑compatible
        ``/completions`` endpoint with both ``prompt`` and ``suffix``
        parameters.  Should that endpoint be unavailable (for example
        on servers that do not support the ``suffix`` argument), the
        provider falls back to using a chat completion with an
        instructional prompt instructing the model to return only the
        inserted code.  The fallback prompt includes optional
        language and filename hints when provided.

        :param prefix: Code appearing before the insertion point
        :param suffix: Code appearing after the insertion point
        :param model: Name of the model to use (defaults to configured model)
        :param language: Optional programming language of the code
        :param filename: Optional filename for additional context
        :param temperature: Sampling temperature
        :param max_tokens: Maximum number of tokens to generate
        :param stream: Whether to stream the response
        :param kwargs: Additional provider‑specific parameters
        :returns: Provider response dictionary
        """
        # First try native completions API with suffix support
        data: Dict[str, Any] = {
            'model': model or self.default_model,
            'prompt': prefix,
            'suffix': suffix,
            'temperature': temperature,
            'stream': stream,
        }
        if max_tokens is not None:
            data['max_tokens'] = max_tokens
        # Merge any additional parameters
        for key, value in kwargs.items():
            if value is not None:
                data[key] = value
        try:
            if stream:
                return self._stream_request_with_fallback(
                    ['/completions', '/v1/completions'],
                    data
                )
            else:
                return self._request_with_fallback(
                    'POST',
                    ['/completions', '/v1/completions'],
                    data
                )
        except ProviderTimeoutException:
            # Propagate timeout errors directly
            raise
        except ProviderNotAvailableException:
            # Underlying server did not support suffix completions; fall back
            pass
        # Fallback: construct a chat prompt instructing the model to insert code
        system_prompt = (
            'You are a code insertion assistant. Insert the missing code '
            'between the provided prefix and suffix. Return only the code that '
            'should be inserted without any additional explanations or markup.'
        )
        # Include optional hints in system prompt
        if language:
            system_prompt += f' The code is written in {language}.'
        if filename:
            system_prompt += f' The file name is {filename}.'
        user_prompt = f'Prefix:\n{prefix}\n\nSuffix:\n{suffix}'
        try:
            return self.chat_completion(
                messages=[
                    {'role': 'system', 'content': system_prompt},
                    {'role': 'user', 'content': user_prompt}
                ],
                model=model or self.default_model,
                temperature=temperature,
                max_tokens=max_tokens,
                stream=stream,
                **kwargs
            )
        except Exception:
            # As a last resort, raise ProviderNotAvailableException to indicate failure
            raise ProviderNotAvailableException()
