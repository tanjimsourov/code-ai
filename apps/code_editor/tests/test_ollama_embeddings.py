"""Tests for the OllamaProvider embeddings implementation.

These tests mock the HTTP embedding endpoint to ensure that vectors
are returned in the expected order and shape.  No network calls are
performed.
"""

from unittest import mock, TestCase

from code_editor.providers.ollama import OllamaProvider


class OllamaEmbeddingsTest(TestCase):
    def test_embeddings_returns_vectors(self):
        # Mock _make_request to return a predictable embedding
        with mock.patch('code_editor.providers.ollama.OllamaProvider._make_request') as mock_req:
            mock_req.return_value = {'embedding': [0.1, 0.2, 0.3]}
            provider = OllamaProvider('ollama', {'url': 'http://localhost:11434'})
            provider._supports_embeddings = True
            vectors = provider.embeddings(['a', 'b'], model='test')
            # Should return a list with a vector per input
            self.assertEqual(len(vectors), 2)
            self.assertEqual(vectors[0], [0.1, 0.2, 0.3])
            self.assertEqual(vectors[1], [0.1, 0.2, 0.3])

