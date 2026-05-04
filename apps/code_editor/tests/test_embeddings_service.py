"""
Unit tests for the embeddings service and client.

These tests cover batching behaviour, pseudo embedding generation when
embeddings are disabled, provider‑specific handling (e.g. Ollama),
OpenAI‑compatible response parsing and fallback, and error handling
in the ``EmbeddingsService``.  They use ``unittest`` and
``unittest.mock`` to stub network calls and configuration without
requiring a live embedding server or a full Django environment.

Because the ``EmbeddingsService`` logs requests via the
``CodeEditorRequestLog`` model, which requires a database, the
``log_request`` method is patched to a no‑op in all tests to avoid
database interactions.  This approach mirrors other unit tests in
this suite that avoid Django dependencies.
"""

import unittest
from unittest import mock
from typing import List

from code_editor.services.embeddings_service import EmbeddingsService
from code_editor.services.embed_client import EmbeddingClient
from code_editor.services import config as config_module


class EmbeddingsServiceTests(unittest.TestCase):
    """Tests for ``EmbeddingsService`` and ``EmbeddingClient`` behaviour."""

    def setUp(self) -> None:
        # Patch CodeEditorRequestLog.log_request to avoid DB usage
        patcher = mock.patch('code_editor.models.CodeEditorRequestLog.log_request')
        self.addCleanup(patcher.stop)
        patcher.start()

    def test_batching_calls_embedding_client_in_batches(self) -> None:
        """Ensure that texts are split into batches according to batch_size."""
        # Define a simple embedding vector to return
        dummy_vec = [0.0, 1.0, 2.0]
        call_counter = {'count': 0}

        def fake_generate_embeddings(texts: List[str]) -> List[List[float]]:
            # Count how many times this stub is called
            call_counter['count'] += 1
            # Return one dummy vector per input text
            return [dummy_vec[:] for _ in texts]

        # Patch configuration to enable embeddings and set batch size to 2
        with mock.patch.object(config_module.ConfigService, 'get_embeddings_config', return_value={
            'url': 'http://embed.example.com',
            'model': 'test-model',
            'enabled': True,
            'provider': 'generic',
            'batch_size': 2,
        }):
            # Patch request limits to allow large inputs
            with mock.patch.object(config_module.ConfigService, 'get_request_limits', return_value={
                'max_input_tokens': 100000,
                'max_input_chars': 100000,
            }):
                # Patch the EmbeddingClient.generate_embeddings method
                with mock.patch.object(EmbeddingClient, 'generate_embeddings', side_effect=fake_generate_embeddings):
                    service = EmbeddingsService()
                    texts = ['t1', 't2', 't3', 't4', 't5']
                    embeddings = service.generate_embeddings(texts)
                    # Expect 3 calls: two batches of size 2 and one batch of size 1
                    self.assertEqual(call_counter['count'], 3)
                    # Should return one embedding per input
                    self.assertEqual(len(embeddings), len(texts))
                    for vec in embeddings:
                        self.assertEqual(vec, dummy_vec)

    def test_pseudo_embeddings_when_disabled(self) -> None:
        """If embeddings are disabled, the service should return pseudo embeddings of length 1536."""
        with mock.patch.object(config_module.ConfigService, 'get_embeddings_config', return_value={
            'enabled': False
        }):
            service = EmbeddingsService()
            embeddings = service.generate_embeddings(['hello', 'world'])
            # One embedding per input
            self.assertEqual(len(embeddings), 2)
            # Each pseudo embedding should have 1536 dimensions
            self.assertEqual(len(embeddings[0]), 1536)
            self.assertEqual(len(embeddings[1]), 1536)

    def test_ollama_embeddings_calls_per_text(self) -> None:
        """Ollama provider should call the embedding API once per text and return distinct embeddings."""
        # Prepare a list of dummy embeddings to return
        dummy_vectors = [[0.1, 0.2], [0.3, 0.4]]
        call_counter = {'count': 0}

        def fake_post_request(url: str, payload: dict, headers=None) -> List[List[float]]:
            # Each call returns a list with one embedding
            idx = call_counter['count']
            call_counter['count'] += 1
            return [dummy_vectors[idx]]

        # Patch config for Ollama provider with batch_size large enough to avoid splitting
        with mock.patch.object(config_module.ConfigService, 'get_embeddings_config', return_value={
            'url': 'http://ollama.example.com',
            'model': 'ollama-model',
            'enabled': True,
            'provider': 'ollama',
            'batch_size': 10,
        }):
            with mock.patch.object(config_module.ConfigService, 'get_request_limits', return_value={
                'max_input_tokens': 100000,
                'max_input_chars': 100000,
            }):
                # Patch the underlying _post_request method used by EmbeddingClient
                with mock.patch('code_editor.services.embed_client.EmbeddingClient._post_request', side_effect=fake_post_request):
                    service = EmbeddingsService()
                    embeddings = service.generate_embeddings(['a', 'b'])
                    # Expect two calls: one per text
                    self.assertEqual(call_counter['count'], 2)
                    # Should return the dummy vectors in order
                    self.assertEqual(embeddings, dummy_vectors)

    def test_openai_embedding_response_parsing(self) -> None:
        """The embedding client should parse OpenAI‑style responses correctly."""
        # Stub response object for OpenAI embeddings
        class StubResponse:
            def __init__(self, data):
                self._data = data
                self.status_code = 200

            def raise_for_status(self) -> None:
                pass

            def json(self) -> dict:
                return self._data

        # Prepare the stubbed requests.post to return a response with ``data`` list
        def post_side_effect(url, json=None, headers=None, timeout=None):
            return StubResponse({'data': [
                {'embedding': [0.1, 0.2], 'index': 0},
                {'embedding': [0.3, 0.4], 'index': 1},
            ]})

        # Patch requests.post used by EmbeddingClient._post_request
        with mock.patch('code_editor.services.embed_client.requests.post', side_effect=post_side_effect):
            embed_client = EmbeddingClient()
            # Use a direct call to _post_request to test parsing logic
            result = embed_client._post_request('http://test', {'input': ['x', 'y']})
            self.assertEqual(result, [[0.1, 0.2], [0.3, 0.4]])

    def test_partial_failure_raises_exception(self) -> None:
        """If embedding generation partially fails, the service should raise ProviderNotAvailableException."""
        from ..exceptions import ProviderNotAvailableException

        # Patch config to enable embeddings and set small batch size
        with mock.patch.object(config_module.ConfigService, 'get_embeddings_config', return_value={
            'url': 'http://embed.example.com',
            'model': 'test-model',
            'enabled': True,
            'provider': 'generic',
            'batch_size': 10,
        }):
            with mock.patch.object(config_module.ConfigService, 'get_request_limits', return_value={
                'max_input_tokens': 100000,
                'max_input_chars': 100000,
            }):
                # Patch EmbeddingClient.generate_embeddings to return wrong number of embeddings
                def fake_generate_embeddings(texts: List[str]) -> List[List[float]]:
                    # Return only half the number of embeddings
                    return [[1.0] for _ in range(max(1, len(texts) // 2))]

                with mock.patch.object(EmbeddingClient, 'generate_embeddings', side_effect=fake_generate_embeddings):
                    service = EmbeddingsService()
                    with self.assertRaises(ProviderNotAvailableException):
                        service.generate_embeddings(['a', 'b', 'c'])


if __name__ == '__main__':
    unittest.main()

