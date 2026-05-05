import requests
from typing import Dict, List, Optional, Any
from urllib.parse import urljoin, urlparse
from .base import BaseProvider
from ..exceptions import ProviderNotAvailableException, ProviderTimeoutException


class LlamaCppProvider(BaseProvider):
    """llama.cpp provider for local model serving"""
    
    def __init__(self, name: str, config: Dict[str, Any]):
        super().__init__(name, config)
        self.base_url = self._normalize_base_url(config.get('url', ''))
        self.default_model = config.get('model', 'qwen2.5-coder-7b-instruct')
        self.headers = {
            'Content-Type': 'application/json',
        }
    
    def _normalize_base_url(self, url: str) -> str:
        """Normalize base URL to avoid duplicate path segments"""
        if not url:
            return ''
        
        # Parse URL
        parsed = urlparse(url)
        base_path = parsed.path.rstrip('/')
        
        # Remove common API path prefixes
        api_prefixes = ['/v1', '/api', '/api/v1']
        for prefix in api_prefixes:
            if base_path.endswith(prefix):
                base_path = base_path[:-len(prefix)]
                break
        
        # Reconstruct URL without API path
        if base_path:
            normalized = f"{parsed.scheme}://{parsed.netloc}{base_path}"
        else:
            normalized = f"{parsed.scheme}://{parsed.netloc}"
        
        return normalized.rstrip('/')
    
    def _get_endpoint_url(self, endpoint: str) -> str:
        """Get full endpoint URL with proper path handling"""
        # If base_url already includes the endpoint, don't double-add
        if endpoint.startswith(self.base_url):
            return endpoint
        return urljoin(self.base_url + '/', endpoint.lstrip('/'))
    
    def is_available(self) -> bool:
        """Check if llama.cpp is available"""
        try:
            # Try different possible health endpoints
            health_endpoints = [
                '/health',
                '/v1/health', 
                '/api/health',
                '/models',
                '/v1/models'
            ]
            
            for endpoint in health_endpoints:
                try:
                    url = self._get_endpoint_url(endpoint)
                    response = requests.get(url, timeout=5)
                    if response.status_code == 200:
                        return True
                except Exception:
                    continue
            
            return False
        except Exception:
            return False
    
    def _make_request(self, endpoint: str, data: Dict[str, Any], method: str = 'POST') -> Dict[str, Any]:
        """Make HTTP request to llama.cpp"""
        url = self._get_endpoint_url(endpoint)
        
        try:
            if method.upper() == 'GET':
                response = requests.get(url, headers=self.headers, timeout=self.timeout)
            else:
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
            raise ProviderNotAvailableException(f"llama.cpp error: {str(e)}")
    
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
        # Try different endpoint formats
        endpoints = ['/v1/chat/completions', '/chat/completions', '/completions']
        
        for endpoint in endpoints:
            try:
                data = {
                    'model': model or self.default_model,
                    'messages': messages,
                    'temperature': temperature,
                    'stream': stream,
                }
                
                if max_tokens:
                    data['max_tokens'] = max_tokens
                
                # Add any additional parameters
                for key, value in kwargs.items():
                    if key not in ['model', 'messages', 'temperature', 'stream', 'max_tokens']:
                        data[key] = value
                
                return self._make_request(endpoint, data)
                
            except Exception as e:
                # Try next endpoint format
                continue
        
        raise ProviderNotAvailableException("No compatible endpoint found")
    
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
        # Try different endpoint formats
        endpoints = ['/v1/completions', '/completions']
        
        for endpoint in endpoints:
            try:
                data = {
                    'model': model or self.default_model,
                    'prompt': prompt,
                    'temperature': temperature,
                    'stream': stream,
                }
                
                if max_tokens:
                    data['max_tokens'] = max_tokens
                
                # Add any additional parameters
                for key, value in kwargs.items():
                    if key not in ['model', 'prompt', 'temperature', 'stream', 'max_tokens']:
                        data[key] = value
                
                return self._make_request(endpoint, data)
                
            except Exception as e:
                continue
        
        raise ProviderNotAvailableException("No compatible endpoint found")
    
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
        # Try different model endpoint formats
        endpoints = ['/v1/models', '/models']
        
        for endpoint in endpoints:
            try:
                response = self._make_request(endpoint, {}, method='GET')
                
                # Handle different response formats
                if 'data' in response:
                    models = response['data']
                elif 'models' in response:
                    models = response['models']
                elif isinstance(response, list):
                    models = response
                else:
                    models = []
                
                # Normalize to OpenAI format
                normalized_models = []
                for model in models:
                    if isinstance(model, str):
                        normalized_models.append({
                            'id': model,
                            'object': 'model',
                            'created': 0,
                            'owned_by': self.name,
                        })
                    elif isinstance(model, dict):
                        normalized_models.append({
                            'id': model.get('id', model.get('model', 'unknown')),
                            'object': 'model',
                            'created': model.get('created', 0),
                            'owned_by': self.name,
                            'size': model.get('size', 0),
                        })
                
                return normalized_models
                
            except Exception as e:
                continue
        
        # Fallback: return default model
        return [
            {
                'id': self.default_model,
                'object': 'model',
                'created': 0,
                'owned_by': self.name,
            }
        ]

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
            "Return only the inserted code.",
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
    # Capability overrides

    def supports_chat(self) -> bool:
        return True

    def supports_completion(self) -> bool:
        return True

    def supports_edit(self) -> bool:
        return True

    def supports_streaming(self) -> bool:
        # llama.cpp HTTP servers often support streaming via Server‑Sent Events,
        # but this implementation currently does not implement incremental parsing.
        return False

    def supports_embeddings(self) -> bool:
        return False

    def supports_json(self) -> bool:
        return False

    def supports_tools(self) -> bool:
        return False

    def supports_infill(self) -> bool:
        return False

    def supports_suffix_completion(self) -> bool:
        return False

    def supports_rerank(self) -> bool:
        return False
    
    def embeddings(
        self,
        texts: List[str],
        model: str,
        **kwargs
    ) -> List[List[float]]:
        """Generate embeddings"""
        # This provider typically doesn't support embeddings
        # Would be handled by separate embedding service
        raise NotImplementedError("Embeddings not supported by llama.cpp provider")
    
    def rerank(
        self,
        query: str,
        documents: List[str],
        model: str,
        **kwargs
    ) -> List[Dict[str, Any]]:
        """Rerank documents"""
        # This provider typically doesn't support reranking
        # Would be handled by separate reranking service
        raise NotImplementedError("Reranking not supported by llama.cpp provider")
    
    def get_model_info(self, model_name: str) -> Optional[Dict[str, Any]]:
        """Get information about a specific model"""
        models = self.get_models()
        for model in models:
            if model.get('id') == model_name:
                return model
        return None
