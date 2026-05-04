"""
Unit tests for the OpenAI‑compatible provider.

These tests mock the underlying ``requests`` calls to verify that the
provider handles fallback endpoints, model listing, embeddings,
timeouts and provider‑unavailable errors appropriately.  They do not
require any live API server.
"""

import unittest
from unittest import mock

from typing import Optional

import requests

from code_editor.providers.openai_compatible import OpenAICompatibleProvider
from code_editor.exceptions import ProviderTimeoutException, ProviderNotAvailableException


class OpenAICompatibleProviderTests(unittest.TestCase):
    """Tests for the OpenAI‑compatible provider implementation."""

    def setUp(self) -> None:
        # Use a deterministic base URL and model for tests
        self.config = {
            'url': 'http://api.example.com',
            'model': 'gpt-test',
            'api_key': 'secret',
            'timeout': 5,
            # Use a single retry to simplify fallback logic in tests.
            # Multiple retries can cause additional calls on the same endpoint
            # which complicate mock expectations.
            'max_retries': 1,
        }

    def test_chat_completion_fallback(self) -> None:
        """
        The provider should fall back from ``/chat/completions`` to
        ``/v1/chat/completions`` when the first endpoint returns a 404.
        """
        provider = OpenAICompatibleProvider('openai_compatible', self.config)

        class StubResponse:
            """A minimal stub of ``requests.Response`` for testing."""
            def __init__(self, status_code: int, json_data: Optional[dict] = None):
                self.status_code = status_code
                self._json_data = json_data or {}

            def raise_for_status(self) -> None:
                if self.status_code >= 400:
                    http_error = requests.HTTPError()
                    http_error.response = self
                    raise http_error

            def json(self) -> dict:
                return self._json_data

        def post_side_effect(url, json=None, headers=None, timeout=None):
            """Return a stub response based on the requested URL."""
            # Treat the explicit ``/v1/chat/completions`` fallback separately
            if url.endswith('/v1/chat/completions'):
                return StubResponse(200, {
                    'choices': [
                        {
                            'message': {
                                'role': 'assistant',
                                'content': 'Hello fallback'
                            }
                        }
                    ]
                })
            elif url.endswith('/chat/completions'):
                # Simulate 404 for the first endpoint
                return StubResponse(404)
            else:
                # Any other path returns failure
                return StubResponse(404)

        with mock.patch('code_editor.providers.openai_compatible.requests.post') as mock_post:
            mock_post.side_effect = post_side_effect
            result = provider.chat_completion([
                {'role': 'user', 'content': 'Hi'}
            ], model=None, stream=False)
            # Should return the JSON from the fallback call
            self.assertIsInstance(result, dict)
            self.assertIn('choices', result)
            self.assertEqual(result['choices'][0]['message']['content'], 'Hello fallback')
            # Verify that both endpoints were attempted
            # Extract called URLs from positional arguments (``url`` is the first arg)
            called_urls = [call.args[0] for call in mock_post.mock_calls]
            self.assertIn(provider.base_url + '/chat/completions', called_urls)
            self.assertIn(provider.base_url + '/v1/chat/completions', called_urls)

    def test_get_models_success(self) -> None:
        """
        Verify that ``get_models`` returns the model list from the API.
        """
        provider = OpenAICompatibleProvider('openai_compatible', self.config)

        def get_side_effect(url, headers=None, timeout=None):
            mock_resp = mock.Mock()
            # Only one call expected to /models
            self.assertTrue(url.endswith('/models') or url.endswith('/v1/models'))
            mock_resp.status_code = 200
            mock_resp.raise_for_status = lambda: None
            mock_resp.json = lambda: {
                'data': [
                    {'id': 'model-a', 'object': 'model', 'owned_by': 'user'},
                    {'id': 'model-b', 'object': 'model', 'owned_by': 'user'},
                ]
            }
            return mock_resp

        with mock.patch('code_editor.providers.openai_compatible.requests.get') as mock_get:
            mock_get.side_effect = get_side_effect
            models = provider.get_models()
            self.assertEqual(len(models), 2)
            self.assertEqual(models[0]['id'], 'model-a')

    def test_embeddings_success(self) -> None:
        """
        The provider should correctly parse embedding responses.
        """
        provider = OpenAICompatibleProvider('openai_compatible', self.config)

        def post_side_effect(url, json=None, headers=None, timeout=None):
            # Expect call to /embeddings first
            mock_resp = mock.Mock()
            self.assertTrue(url.endswith('/embeddings') or url.endswith('/v1/embeddings'))
            mock_resp.status_code = 200
            mock_resp.raise_for_status = lambda: None
            mock_resp.json = lambda: {
                'data': [
                    {'embedding': [0.1, 0.2, 0.3], 'index': 0},
                    {'embedding': [0.4, 0.5, 0.6], 'index': 1},
                ]
            }
            return mock_resp

        with mock.patch('code_editor.providers.openai_compatible.requests.post') as mock_post:
            mock_post.side_effect = post_side_effect
            embeddings = provider.embeddings(["hello", "world"], model=None)
            self.assertEqual(len(embeddings), 2)
            self.assertEqual(embeddings[0], [0.1, 0.2, 0.3])
            self.assertEqual(embeddings[1], [0.4, 0.5, 0.6])

    def test_timeout_exception(self) -> None:
        """
        The provider should raise ``ProviderTimeoutException`` when all
        endpoints time out.
        """
        provider = OpenAICompatibleProvider('openai_compatible', self.config)

        def post_timeout(url, json=None, headers=None, timeout=None):
            raise requests.Timeout()

        with mock.patch('code_editor.providers.openai_compatible.requests.post', side_effect=post_timeout):
            with self.assertRaises(ProviderTimeoutException):
                provider.chat_completion([
                    {'role': 'user', 'content': 'test'}
                ], model=None)

    def test_provider_unavailable_exception(self) -> None:
        """
        The provider should raise ``ProviderNotAvailableException`` when
        all endpoints return HTTP errors that are not 404/405 or timeout.
        """
        provider = OpenAICompatibleProvider('openai_compatible', self.config)

        def post_server_error(url, json=None, headers=None, timeout=None):
            # Always return 500 to simulate provider unavailable
            mock_resp = mock.Mock()
            mock_resp.status_code = 500
            http_error = requests.HTTPError()
            http_error.response = mock_resp
            def raise_error():
                raise http_error
            mock_resp.raise_for_status = raise_error
            return mock_resp

        with mock.patch('code_editor.providers.openai_compatible.requests.post', side_effect=post_server_error):
            with self.assertRaises(ProviderNotAvailableException):
                provider.chat_completion([
                    {'role': 'user', 'content': 'test'}
                ], model=None)


if __name__ == '__main__':
    unittest.main()

