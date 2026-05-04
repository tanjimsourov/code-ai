import requests
import json
import time
from typing import List, Dict, Any, Optional
from urllib.parse import urljoin
from ..services.config import ConfigService


class EmbeddingClient:
    """Client for embedding service integration.

    This client supports multiple embedding providers including
    OpenAI‑compatible APIs, Ollama, and generic embedding services.
    Configuration is read from :func:`ConfigService.get_embeddings_config`.
    """

    def __init__(self) -> None:
        config = ConfigService.get_embeddings_config()
        # Base URL for embedding API (without trailing slash)
        self.base_url: str = config.get('url', '').rstrip('/')
        # Model name to request
        self.model: str = config.get('model', 'BAAI/bge-small-en-v1.5')
        # Request timeout in seconds
        self.timeout: int = config.get('timeout', 30)
        # Provider key (e.g. openai_compatible, ollama, generic)
        self.provider: str = config.get('provider', 'generic')
        # API key if configured (used for OpenAI‑compatible providers)
        self.api_key: Optional[str] = config.get('api_key')
        # Headers dict may include custom headers (e.g. for OpenAI)
        self.headers: Dict[str, Any] = {
            'Content-Type': 'application/json',
        }
        # Merge any custom headers from configuration
        cfg_headers = config.get('headers', {}) or {}
        for key, value in cfg_headers.items():
            self.headers[key] = value
        # Maximum number of retries for a single API call; if None, no retry
        self.max_retries: int = config.get('max_retries', 3)

    def generate_embeddings(self, texts: List[str]) -> List[List[float]]:
        """Generate embeddings for a list of texts.

        Dispatches to a provider‑specific method based on
        configuration.  Raises an exception if no base URL is
        configured.

        :param texts: List of input strings
        :returns: List of embedding vectors (one per input)
        """
        if not self.base_url:
            raise ValueError("Embedding service URL not configured")
        if not texts:
            return []
        provider = (self.provider or 'generic').lower()
        if provider in {'openai_compatible', 'deepseek'}:
            return self._generate_openai_embeddings(texts)
        if provider == 'ollama':
            return self._generate_ollama_embeddings(texts)
        # Default to generic embedding service
        return self._generate_generic_embeddings(texts)

    def _generate_generic_embeddings(self, texts: List[str]) -> List[List[float]]:
        """Call a generic embedding endpoint returning embeddings in list format.

        This is used for custom embedding services that expose an
        ``/embed`` endpoint.  The payload includes the model and the
        input texts.  Responses are expected to contain either a
        top‑level list or a ``data``/``embeddings`` field.
        """
        endpoint = urljoin(self.base_url + '/', 'embed')
        payload = {
            'model': self.model,
            'input': texts,
        }
        return self._post_request(endpoint, payload)

    def _generate_openai_embeddings(self, texts: List[str]) -> List[List[float]]:
        """Call an OpenAI‑compatible embeddings endpoint.

        Attempts the ``/embeddings`` endpoint first, falling back to
        ``/v1/embeddings`` if needed.  If the returned number of
        embeddings does not match the number of inputs, individual
        calls are made per text to ensure one embedding per input.
        """
        # Prepare headers with authorization if API key is provided
        headers = dict(self.headers)
        if self.api_key and 'authorization' not in {k.lower() for k in headers}:
            headers['Authorization'] = f'Bearer {self.api_key}'
        # Candidate paths in order of preference
        candidate_paths = ['embeddings', 'v1/embeddings']
        errors: List[str] = []
        for path in candidate_paths:
            endpoint = urljoin(self.base_url + '/', path)
            payload = {
                'model': self.model,
                'input': texts,
            }
            try:
                embeddings = self._post_request(endpoint, payload, headers=headers)
                # Ensure correct length; some servers may return a single embedding
                if len(embeddings) == len(texts):
                    return embeddings
                # If only one embedding returned for multiple texts, fallback to per‑text calls
            except Exception as e:
                errors.append(str(e))
                continue
            # Fallback: call per text if number of embeddings mismatched
            per_results: List[List[float]] = []
            success_all = True
            for text in texts:
                payload_single = {
                    'model': self.model,
                    'input': [text],
                }
                try:
                    result_single = self._post_request(endpoint, payload_single, headers=headers)
                    if result_single:
                        per_results.append(result_single[0])
                    else:
                        success_all = False
                        break
                except Exception:
                    success_all = False
                    break
            if success_all and len(per_results) == len(texts):
                return per_results
        # If all attempts failed, raise error
        raise RuntimeError(f"Failed to retrieve OpenAI embeddings: {errors}")

    def _generate_ollama_embeddings(self, texts: List[str]) -> List[List[float]]:
        """Generate embeddings using an Ollama API.

        Ollama currently supports embeddings only one text at a time
        via ``/api/embeddings``.  We call the endpoint once per text
        and collect the resulting vector.  If ``/api/embeddings`` is
        unavailable, a fallback to ``/embeddings`` is attempted.
        """
        embeddings: List[List[float]] = []
        # Candidate paths to attempt in order
        candidate_paths = ['api/embeddings', 'embeddings']
        for text in texts:
            success = False
            for path in candidate_paths:
                endpoint = urljoin(self.base_url + '/', path)
                payload = {
                    'model': self.model,
                    # Ollama API uses ``prompt`` for embeddings
                    'prompt': text,
                }
                try:
                    emb_vecs = self._post_request(endpoint, payload)
                    # ``_post_request`` returns a list of embeddings; for Ollama we expect a single embedding
                    if emb_vecs:
                        embeddings.append(emb_vecs[0])
                        success = True
                        break
                except Exception:
                    # Try next path
                    continue
            if not success:
                raise RuntimeError(f"Failed to retrieve embedding from Ollama for text: {text[:30]}")
        return embeddings

    def _post_request(self, url: str, payload: Dict[str, Any], headers: Optional[Dict[str, Any]] = None) -> List[List[float]]:
        """Perform a POST request with retries and parse embeddings.

        Returns a list of embeddings parsed from the response.  Uses
        simple retry logic based on the configured ``max_retries``.

        :param url: Endpoint URL
        :param payload: JSON payload to send
        :param headers: Additional headers for the request
        :returns: Parsed list of embedding vectors
        :raises: Exception if all retries fail
        """
        # Merge headers with defaults
        req_headers = dict(self.headers)
        if headers:
            for k, v in headers.items():
                req_headers[k] = v
        last_exc: Optional[Exception] = None
        retries = max(1, self.max_retries or 1)
        for attempt in range(retries):
            try:
                response = requests.post(
                    url,
                    json=payload,
                    headers=req_headers,
                    timeout=self.timeout,
                )
                response.raise_for_status()
                # Parse JSON content
                try:
                    result = response.json()
                except json.JSONDecodeError:
                    raise ValueError(f"Invalid JSON from embedding service: {response.text[:100]}")
                # Interpret different response structures
                # OpenAI: {"data": [{"embedding": [...]}, ...]}
                if isinstance(result, dict):
                    if 'data' in result and isinstance(result['data'], list):
                        return [item['embedding'] for item in result['data'] if 'embedding' in item]
                    if 'embeddings' in result and isinstance(result['embeddings'], list):
                        return result['embeddings']
                    # Ollama: {"embedding": [...], ...}
                    if 'embedding' in result and isinstance(result['embedding'], list):
                        return [result['embedding']]
                    # Some services may nest embeddings under ``result`` key
                    if 'result' in result and isinstance(result['result'], list):
                        return result['result']
                # Raw list of embeddings
                if isinstance(result, list):
                    # Could be list of lists or list of dicts with 'embedding'
                    if result and isinstance(result[0], dict) and 'embedding' in result[0]:
                        return [item['embedding'] for item in result]
                    return result
                raise ValueError(f"Unexpected response format: {result}")
            except Exception as exc:
                last_exc = exc
                # Retry on any exception except HTTP client errors (4xx)
                if isinstance(exc, requests.HTTPError) and 400 <= exc.response.status_code < 500:
                    # Do not retry client errors
                    break
                # Otherwise sleep briefly and retry (could add backoff)
                time.sleep(0.1)
                continue
        # If all retries failed, propagate the last exception
        raise last_exc if last_exc else RuntimeError("Unknown error during embedding request")


class RerankClient:
    """Client for reranking service integration"""
    
    def __init__(self):
        self.base_url = ConfigService.get_rerank_config().get('url', '')
        self.model = ConfigService.get_rerank_config().get('model', 'BAAI/bge-reranker-base')
        self.timeout = ConfigService.get_rerank_config().get('timeout', 30)
        self.headers = {
            'Content-Type': 'application/json',
        }
    
    def rerank_documents(self, query: str, documents: List[str], top_k: int = 10) -> List[Dict[str, Any]]:
        """Rerank documents based on query"""
        if not self.base_url:
            raise ValueError("Rerank service URL not configured")
        
        # Normalize URL
        base_url = self.base_url.rstrip('/')
        endpoint = urljoin(base_url + '/', 'rerank')
        
        data = {
            'model': self.model,
            'query': query,
            'documents': documents,
            'top_k': top_k
        }
        
        try:
            response = requests.post(
                endpoint,
                json=data,
                headers=self.headers,
                timeout=self.timeout
            )
            response.raise_for_status()
            
            result = response.json()
            
            # Handle different response formats
            if 'data' in result:
                return result['data']
            elif 'results' in result:
                return result['results']
            elif isinstance(result, list):
                return result
            else:
                raise ValueError(f"Unexpected response format: {result}")
                
        except requests.Timeout:
            raise TimeoutError(f"Rerank service timeout after {self.timeout}s")
        except requests.HTTPError as e:
            if e.response.status_code >= 500:
                raise ConnectionError(f"Rerank service unavailable: {e}")
            raise ValueError(f"Rerank service error: {e}")
        except Exception as e:
            raise RuntimeError(f"Rerank client error: {e}")
