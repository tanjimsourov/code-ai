"""
Unit tests for rerank provider and rerank integration.

These tests cover lexical fallback behaviour, OpenAI/generic API
parsing, provider registration in the router, rerank service
disable/enable scenarios, and correct ordering of search results
after reranking.  They use ``unittest`` and mock the relevant
configuration and network interactions so they can run without a
live Django or external services.
"""

import unittest
from unittest import mock
from typing import List, Dict, Any

from code_editor.providers.rerank import RerankProvider
from code_editor.services.router import RouterService
from code_editor.services.rerank_service import RerankService
from code_editor.services.retrieval_service import RetrievalService
from code_editor.services import config as config_module
from code_editor.exceptions import InvalidRequestException, ProviderNotAvailableException


class RerankProviderTests(unittest.TestCase):
    """Tests for the RerankProvider implementation."""

    def setUp(self) -> None:
        # Patch out log_request to avoid touching the database
        patcher = mock.patch('code_editor.models.CodeEditorRequestLog.log_request')
        self.addCleanup(patcher.stop)
        patcher.start()

    def test_lexical_rerank(self) -> None:
        """Lexical provider should rank documents by term frequency."""
        config = {
            'url': '',
            'model': 'ignored',
            'provider': 'lexical',
            'enabled': True,
        }
        provider = RerankProvider('rerank', config)
        query = 'foo bar'
        docs = [
            'foo bar baz',   # two terms
            'foo',           # one term
            'bar baz foo',   # two terms
            'nothing here',  # zero terms
        ]
        results = provider.rerank(query, docs)
        # Expect the docs with two terms to come first (indices 0 and 2)
        self.assertEqual(results[0]['index'], 0)
        self.assertEqual(results[1]['index'], 2)
        self.assertEqual(results[2]['index'], 1)
        self.assertEqual(results[3]['index'], 3)

    def test_api_rerank_parsing(self) -> None:
        """OpenAI/generic API responses should be parsed into normalized results."""
        # Config for provider with base URL and generic provider
        config = {
            'url': 'http://example.com',
            'model': 'rerank-model',
            'provider': 'generic',
            'enabled': True,
            'timeout': 5,
        }
        provider = RerankProvider('rerank', config)

        class StubResponse:
            def __init__(self, data):
                self._data = data
                self.status_code = 200
            def raise_for_status(self):
                pass
            def json(self):
                return self._data

        # Stub requests.post to return a response with a list of result dicts
        def post_side_effect(url, json=None, headers=None, timeout=None):
            # Use only the first path regardless of candidate paths
            return StubResponse({
                'data': [
                    {'index': 1, 'relevance_score': 0.9},
                    {'index': 0, 'relevance_score': 0.8},
                ]
            })

        with mock.patch('code_editor.providers.rerank.requests.post', side_effect=post_side_effect):
            # Should return results ordered as given in the API response
            results = provider.rerank('query', ['doc0', 'doc1'])
            self.assertEqual(len(results), 2)
            self.assertEqual(results[0]['index'], 1)
            self.assertAlmostEqual(results[0]['relevance_score'], 0.9)
            self.assertEqual(results[1]['index'], 0)
            self.assertAlmostEqual(results[1]['relevance_score'], 0.8)


class RouterRerankRegistrationTests(unittest.TestCase):
    """Tests for router registration of the rerank provider."""

    def setUp(self) -> None:
        patcher = mock.patch('code_editor.models.CodeEditorRequestLog.log_request')
        self.addCleanup(patcher.stop)
        patcher.start()

    def test_rerank_provider_registered_when_enabled(self) -> None:
        """Router should register rerank provider based on configuration."""
        with mock.patch.object(config_module.ConfigService, 'get_rerank_config', return_value={
            'url': 'http://localhost:5000',
            'model': 'test-model',
            'provider': 'generic',
            'enabled': True,
        }):
            router = RouterService()
            provider = router.get_provider('rerank')
            from code_editor.providers.rerank import RerankProvider
            self.assertIsInstance(provider, RerankProvider)

    def test_rerank_provider_not_registered_when_disabled(self) -> None:
        """Router should not register rerank provider when disabled."""
        with mock.patch.object(config_module.ConfigService, 'get_rerank_config', return_value={
            'enabled': False,
        }):
            router = RouterService()
            provider = router.get_provider('rerank')
            self.assertIsNone(provider)


class RerankServiceTests(unittest.TestCase):
    """Tests for RerankService handling of enabled/disabled and provider failures."""

    def setUp(self) -> None:
        patcher = mock.patch('code_editor.models.CodeEditorRequestLog.log_request')
        self.addCleanup(patcher.stop)
        patcher.start()

    def test_rerank_service_disabled(self) -> None:
        """If rerank is disabled, rerank_documents should raise InvalidRequestException."""
        with mock.patch.object(config_module.ConfigService, 'get_rerank_config', return_value={
            'enabled': False
        }):
            service = RerankService()
            with self.assertRaises(InvalidRequestException):
                service.rerank_documents('query', ['doc'])

    def test_rerank_service_provider_unavailable(self) -> None:
        """If provider is unavailable, rerank_documents should raise ProviderNotAvailableException."""
        # Config says enabled but no provider
        with mock.patch.object(config_module.ConfigService, 'get_rerank_config', return_value={
            'enabled': True,
            'url': '',
            'model': 'model',
            'provider': 'generic',
        }):
            # Patch router to return None for rerank provider
            with mock.patch.object(RouterService, 'get_provider', return_value=None):
                service = RerankService()
                with self.assertRaises(ProviderNotAvailableException):
                    service.rerank_documents('query', ['doc'])


class RetrievalRerankTests(unittest.TestCase):
    """Tests for retrieval service reranking integration."""

    def setUp(self) -> None:
        patcher = mock.patch('code_editor.models.CodeEditorRequestLog.log_request')
        self.addCleanup(patcher.stop)
        patcher.start()

    def test_rerank_result_ordering(self) -> None:
        """_rerank_results should reorder results based on scores from rerank service."""
        # Prepare dummy results
        results: List[Dict[str, Any]] = [
            {'content': 'doc0', 'other': 1},
            {'content': 'doc1', 'other': 2},
            {'content': 'doc2', 'other': 3},
        ]
        # Patch rerank service to return custom ordering (2 -> highest, then 0)
        rerank_scores = [
            {'index': 2, 'relevance_score': 0.9},
            {'index': 0, 'relevance_score': 0.5},
        ]
        with mock.patch.object(RerankService, 'rerank_documents', return_value=rerank_scores):
            retrieval = RetrievalService()
            # Invoke rerank and get new ordering
            reranked = retrieval._rerank_results('query', results, limit=3)
            # The first element should correspond to index 2
            self.assertEqual(reranked[0]['content'], 'doc2')
            # The second element should correspond to index 0
            self.assertEqual(reranked[1]['content'], 'doc0')


if __name__ == '__main__':
    unittest.main()

