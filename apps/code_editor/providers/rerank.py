"""
Rerank provider implementation.

This provider wraps calls to a reranking API or performs a local
lexical fallback when no API is available.  It supports both
OpenAI‑compatible endpoints (``/rerank`` and ``/v1/rerank``) and
generic/local HTTP endpoints.  When configured with
``provider=lexical`` or no base URL, it deterministically scores
documents based on simple lexical features (term frequency) for
testing and development purposes.
"""

from typing import List, Dict, Any, Optional
import requests
import re

from .base import BaseProvider


class RerankProvider(BaseProvider):
    """Provider that performs document reranking."""

    def __init__(self, name: str, config: Dict[str, Any]):
        super().__init__(name, config)
        self.base_url: str = config.get('url', '').rstrip('/')
        # Default model to use for reranking
        self.model: str = config.get('model', 'BAAI/bge-reranker-base')
        # Provider type (e.g. ``openai_compatible``, ``generic``, ``lexical``)
        self.provider: str = (config.get('provider') or 'generic').lower()
        # Optional API key for authentication
        self.api_key: Optional[str] = config.get('api_key')
        # Custom headers to include with each request
        self.headers: Dict[str, str] = {
            'Content-Type': 'application/json',
        }
        custom_headers = config.get('headers') or {}
        for k, v in custom_headers.items():
            self.headers[k] = v
        # Optional top_k override from config
        self.top_k: Optional[int] = config.get('top_k')

    # ------------------------------------------------------------------
    # BaseProvider abstract methods not applicable to reranking
    # These raise NotImplementedError to indicate that chat, completion
    # and edit operations are not supported by this provider.

    def chat_completion(self, *args, **kwargs) -> Dict[str, Any]:  # type: ignore[override]
        raise NotImplementedError("RerankProvider does not support chat completions")

    def text_completion(self, *args, **kwargs) -> Dict[str, Any]:  # type: ignore[override]
        raise NotImplementedError("RerankProvider does not support text completions")

    def edit_code(self, *args, **kwargs) -> Dict[str, Any]:  # type: ignore[override]
        raise NotImplementedError("RerankProvider does not support code editing")

    def get_models(self) -> List[Dict[str, Any]]:  # type: ignore[override]
        """Return available models for reranking.

        For simplicity, this returns a single entry for the configured model
        when a base URL is provided.  In lexical mode, no models are
        available.
        """
        if self.provider == 'lexical' or not self.base_url:
            return []
        return [
            {
                'id': self.model,
                'object': 'model',
                'owned_by': 'system',
            }
        ]

    def infill_code(self, *args, **kwargs) -> Dict[str, Any]:  # type: ignore[override]
        raise NotImplementedError("RerankProvider does not support code infill")

    # ------------------------------------------------------------------
    # Capability flags
    def supports_rerank(self) -> bool:  # type: ignore[override]
        return True

    # ------------------------------------------------------------------
    # Reranking operation
    def rerank(
        self,
        query: str,
        documents: List[str],
        model: Optional[str] = None,
        top_k: Optional[int] = None,
        **kwargs,
    ) -> List[Dict[str, Any]]:
        """Rerank a set of documents for a given query.

        :param query: Query string
        :param documents: List of documents to rank
        :param model: Optional model name override
        :param top_k: Optional number of top results to return
        :returns: List of dicts with ``index`` and ``relevance_score`` keys
        """
        if not documents:
            return []
        # Determine how many results to return
        k = top_k or self.top_k or len(documents)
        # Lexical fallback if no base URL or provider is lexical
        if not self.base_url or self.provider == 'lexical':
            return self._lexical_rerank(query, documents, k)
        # Prepare request payload
        payload = {
            'model': model or self.model,
            'query': query,
            'documents': documents,
        }
        if k:
            payload['top_k'] = k
        # Compose candidate endpoint paths for OpenAI‑compatible and generic APIs
        candidate_paths = ['rerank', 'v1/rerank']
        # Prepare headers with API key if provided
        headers = dict(self.headers)
        if self.api_key and 'authorization' not in {k.lower() for k in headers}:
            headers['Authorization'] = f'Bearer {self.api_key}'
        errors: List[str] = []
        for path in candidate_paths:
            url = f"{self.base_url}/{path}".rstrip('/')
            try:
                response = requests.post(
                    url,
                    json=payload,
                    headers=headers,
                    timeout=self.timeout,
                )
                response.raise_for_status()
                data = response.json()
                items: List[Any]
                # Determine the list of results from possible response structures
                if isinstance(data, dict):
                    if 'data' in data and isinstance(data['data'], list):
                        items = data['data']
                    elif 'results' in data and isinstance(data['results'], list):
                        items = data['results']
                    else:
                        # Some services may nest under another key; fall back to value list
                        items = next((v for v in data.values() if isinstance(v, list)), [])
                elif isinstance(data, list):
                    items = data
                else:
                    items = []
                results: List[Dict[str, Any]] = []
                for idx, item in enumerate(items):
                    if isinstance(item, dict):
                        # Accept variations in field names
                        index_val = item.get('index', idx)
                        score_val = item.get('relevance_score')
                        if score_val is None:
                            score_val = item.get('score', item.get('similarity'))
                        doc_val = item.get('document')
                        # Coerce score to float if possible
                        try:
                            score_float = float(score_val) if score_val is not None else 0.0
                        except Exception:
                            score_float = 0.0
                        results.append({'index': index_val, 'relevance_score': score_float, 'document': doc_val})
                    else:
                        # If item is scalar, use position as index and value as score
                        try:
                            score_float = float(item)
                        except Exception:
                            score_float = 0.0
                        results.append({'index': idx, 'relevance_score': score_float, 'document': None})
                if results:
                    # Limit to k results
                    return results[:k]
            except Exception as exc:
                errors.append(str(exc))
                continue
        # If all endpoints fail, fall back to lexical ranking
        return self._lexical_rerank(query, documents, k)

    def _lexical_rerank(self, query: str, documents: List[str], k: int) -> List[Dict[str, Any]]:
        """Compute a simple lexical relevance score for each document.

        The score is based on case‑insensitive term frequency of query words.
        :param query: Query string
        :param documents: List of documents
        :param k: Number of top results to return
        :returns: List of dicts with index and relevance_score
        """
        # Tokenise query into terms (alphanumeric)
        terms = [t.lower() for t in re.findall(r"[A-Za-z0-9_]+", query) if t]
        if not terms:
            # If no query terms, score all documents equally
            return [{'index': i, 'relevance_score': 0.0, 'document': None} for i in range(min(k, len(documents)))]
        scores: List[tuple] = []
        for i, doc in enumerate(documents):
            score = 0.0
            doc_lower = doc.lower()
            for term in terms:
                # Count occurrences
                score += doc_lower.count(term)
            scores.append((score, i))
        # Sort descending by score
        scores.sort(key=lambda x: x[0], reverse=True)
        top_results: List[Dict[str, Any]] = []
        for rank, (score, idx) in enumerate(scores[:k]):
            top_results.append({'index': idx, 'relevance_score': float(score), 'document': None})
        return top_results
