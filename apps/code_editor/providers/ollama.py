import json
import requests
from typing import Dict, List, Optional, Any
from .base import BaseProvider
from ..exceptions import ProviderNotAvailableException, ProviderTimeoutException


class OllamaProvider(BaseProvider):
    """Ollama provider for local model serving.

    This provider wraps a local or remote Ollama instance.  It
    supports chat completions, text completions and code editing.  When
    enabled via configuration it also supports streaming responses and
    embedding generation.  Capabilities such as JSON mode, tools and
    suffix completion may be toggled via the provider configuration.
    """
    
    def __init__(self, name: str, config: Dict[str, Any]):
        super().__init__(name, config)
        self.base_url = config.get('url', 'http://localhost:11434').rstrip('/')
        self.default_model = config.get('model', 'qwen2.5-coder-7b-instruct')
        # Determine capability flags from config; default to True for
        # streaming and embeddings since Ollama typically supports
        # streaming chat/generate endpoints and embeddings via /api/embed.
        self._supports_streaming: bool = bool(config.get('streaming', True))
        self._supports_embeddings: bool = bool(config.get('embeddings', True))
        self._supports_json: bool = bool(config.get('json', False))
        self._supports_tools: bool = bool(config.get('tools', False))
        self._supports_suffix_completion: bool = bool(config.get('suffix_completion', False))
        # HTTP headers for requests
        self.headers = {
            'Content-Type': 'application/json',
        }
    
    def is_available(self) -> bool:
        """Check if Ollama is available"""
        try:
            response = requests.get(f"{self.base_url}/api/tags", timeout=5)
            return response.status_code == 200
        except Exception:
            return False
    
    def _make_request(self, endpoint: str, data: Dict[str, Any]) -> Dict[str, Any]:
        """Make HTTP request to Ollama"""
        url = f"{self.base_url}{endpoint}"
        
        try:
            response = requests.post(url, json=data, headers=self.headers, timeout=self.timeout)
            response.raise_for_status()
            return response.json()
        except requests.Timeout:
            raise ProviderTimeoutException()
        except requests.HTTPError as e:
            if e.response.status_code >= 500:
                raise ProviderNotAvailableException()
            raise
        except Exception as e:
            raise ProviderNotAvailableException(f"Ollama error: {str(e)}")
    
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
        data = {
            'model': model or self.default_model,
            'messages': messages,
            'temperature': temperature,
            'stream': stream,
        }
        
        if max_tokens:
            data['num_predict'] = max_tokens
        
        # Add any additional parameters
        for key, value in kwargs.items():
            if key not in ['model', 'messages', 'temperature', 'stream', 'num_predict']:
                data[key] = value
        
        # If streaming requested and supported, return a generator
        if stream and self._supports_streaming:
            return self._stream_request('/api/chat', data)
        return self._make_request('/api/chat', data)
    
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
        data = {
            'model': model or self.default_model,
            'prompt': prompt,
            'temperature': temperature,
            'stream': stream,
        }
        
        if max_tokens:
            data['num_predict'] = max_tokens
        
        # Add any additional parameters
        for key, value in kwargs.items():
            if key not in ['model', 'prompt', 'temperature', 'stream', 'num_predict']:
                data[key] = value
        
        if stream and self._supports_streaming:
            return self._stream_request('/api/generate', data)
        return self._make_request('/api/generate', data)
    
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
        # Use chat completion for code editing
        messages = [
            {
                'role': 'system',
                'content': 'You are a code editing assistant. Follow the instruction to edit the provided code. Return only the modified code without explanations.'
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
        """Get available models"""
        try:
            response = requests.get(f"{self.base_url}/api/tags", timeout=self.timeout)
            response.raise_for_status()
            data = response.json()
            
            models = []
            for model in data.get('models', []):
                models.append({
                    'id': model.get('name', 'unknown'),
                    'object': 'model',
                    'created': 0,
                    'owned_by': self.name,
                    'size': model.get('size', 0),
                    'digest': model.get('digest', ''),
                })
            
            return models
        except Exception:
            # Return default model if endpoint fails
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
        model: str,
        **kwargs
    ) -> List[List[float]]:
        """Generate embeddings for a list of texts.

        If embeddings are not supported by configuration, raise
        NotImplementedError.  Otherwise call the ``/api/embed`` endpoint
        once per input to obtain a vector.  Ollama returns the vector
        in the ``embedding`` field of the response.  The returned list
        preserves the order of ``texts``.
        """
        if not self._supports_embeddings:
            raise NotImplementedError("Embeddings not supported by this Ollama provider")
        results: List[List[float]] = []
        for text in texts:
            payload = {
                'model': model or self.default_model,
                'prompt': text,
            }
            try:
                resp = self._make_request('/api/embed', payload)
            except Exception:
                # Some versions use /api/embeddings
                resp = self._make_request('/api/embeddings', payload)
            vector = resp.get('embedding') or resp.get('vector')
            if not isinstance(vector, list):
                vector = []
            results.append(vector)
        return results

    # ------------------------------------------------------------------
    # Capability overrides

    def supports_chat(self) -> bool:
        return True

    def supports_completion(self) -> bool:
        return True

    def supports_edit(self) -> bool:
        return True

    def supports_streaming(self) -> bool:
        return self._supports_streaming

    def supports_embeddings(self) -> bool:
        return self._supports_embeddings

    def supports_json(self) -> bool:
        return self._supports_json

    def supports_tools(self) -> bool:
        return self._supports_tools

    def supports_infill(self) -> bool:
        """Ollama does not currently support fill‑in‑the‑middle completions."""
        return False

    def supports_suffix_completion(self) -> bool:
        return self._supports_suffix_completion

    def supports_rerank(self) -> bool:
        return False

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
        prompt_parts = [
            "Fill in the missing code between the prefix and suffix.",
            "Return only the code to insert.",
        ]
        if language:
            prompt_parts.append(f"Language: {language}")
        if filename:
            prompt_parts.append(f"Filename: {filename}")
        prompt_parts.extend(["Prefix:", prefix, "Suffix:", suffix])
        return self.text_completion(
            prompt="\n".join(prompt_parts),
            model=model or self.default_model,
            temperature=temperature,
            max_tokens=max_tokens,
            stream=stream,
            **kwargs
        )

    # ------------------------------------------------------------------
    # Internal streaming helper

    def _stream_request(self, endpoint: str, data: Dict[str, Any]) -> Any:
        """Perform a streaming request to an Ollama endpoint.

        This helper sends a POST request with ``stream=True`` and yields
        ``StreamChunk`` objects as each line of JSON is received.  The
        stream terminates when a message with ``done`` truthy value is
        encountered.

        :param endpoint: API endpoint path (e.g. ``/api/chat``)
        :param data: JSON payload to send
        :returns: generator of ``StreamChunk`` instances
        """
        url = f"{self.base_url}{endpoint}"
        try:
            response = requests.post(url, json=data, headers=self.headers, timeout=self.timeout, stream=True)
            response.raise_for_status()
        except requests.Timeout:
            raise ProviderTimeoutException()
        except Exception as exc:
            # Bubble up any other errors
            raise ProviderNotAvailableException(str(exc))
        # Iterate over lines; Ollama streams JSON objects per line
        def _iter() -> Any:
            from .streaming import StreamChunk  # import locally to avoid circular deps
            for raw_line in response.iter_lines(decode_unicode=True):
                if not raw_line:
                    continue
                line = raw_line.strip()
                # Ignore keepalive or comments
                if not line or line.startswith(':'):
                    continue
                try:
                    payload = json.loads(line)
                except Exception:
                    # Non‑JSON chunk; yield raw text
                    yield StreamChunk(content=line, raw=line)
                    continue
                # Extract content fields
                content = ''
                thinking = None
                tool_calls = None
                done_flag = False
                # Ollama chat/generate streams may include ``message`` with ``content``
                if isinstance(payload, dict):
                    # Standard message structure
                    msg = payload.get('message') or {}
                    if isinstance(msg, dict):
                        content = msg.get('content') or ''
                        thinking = msg.get('thinking')
                        tool_calls = msg.get('tool_calls')
                        done_flag = bool(payload.get('done')) or msg.get('finish_reason') is not None
                    else:
                        content = payload.get('content') or ''
                        done_flag = bool(payload.get('done')) or payload.get('finish_reason') is not None
                yield StreamChunk(content=content, event=None, done=done_flag, raw=payload)
                if done_flag:
                    break
            try:
                response.close()
            except Exception:
                pass
        return _iter()
    
    def get_model_info(self, model_name: str) -> Optional[Dict[str, Any]]:
        """Get information about a specific model"""
        try:
            response = requests.get(f"{self.base_url}/api/tags", timeout=self.timeout)
            response.raise_for_status()
            data = response.json()
            
            for model in data.get('models', []):
                if model.get('name') == model_name:
                    return {
                        'id': model.get('name'),
                        'object': 'model',
                        'created': 0,
                        'owned_by': self.name,
                        'size': model.get('size', 0),
                        'digest': model.get('digest', ''),
                        'details': model
                    }
            return None
        except Exception:
            return None
