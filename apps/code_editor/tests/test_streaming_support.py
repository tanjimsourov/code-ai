"""
Tests for streaming support in providers and the streaming service.

These tests focus on verifying that streaming responses from an
OpenAI‑compatible provider are correctly parsed into ``StreamChunk``
instances and that the ``StreamingService`` can wrap streaming
generators into the normalized SSE format.  They do not require
Django to be installed; a minimal stub of the ``django`` module is
injected into ``sys.modules`` to satisfy imports in the
``streaming_service`` module.
"""

import sys
import types
import unittest
from unittest import mock

# -------------------------------------------------------------------
# Inject minimal stubs for django modules so that importing the
# streaming_service does not raise ImportError.  The StreamingService
# uses ``django.http.StreamingHttpResponse`` and ``django.http.HttpResponse``,
# which we stub out with no‑op callables.  Similarly, the
# ``django.utils.timezone`` module is stubbed to provide a ``now``
# function.  These stubs are only used for testing purposes and
# should not affect production code.
django_stub = types.ModuleType("django")
http_stub = types.ModuleType("django.http")

def _dummy_response(*args, **kwargs):
    class DummyResponse:
        def __init__(self):
            self.headers = {}
        def __setitem__(self, key, value):
            self.headers[key] = value
    return DummyResponse()

# Assign dummy response classes
http_stub.StreamingHttpResponse = _dummy_response
http_stub.HttpResponse = _dummy_response
django_stub.http = http_stub

utils_stub = types.ModuleType("django.utils")
timezone_stub = types.ModuleType("django.utils.timezone")
def _now():
    return None
timezone_stub.now = _now
utils_stub.timezone = timezone_stub
django_stub.utils = utils_stub

sys.modules.setdefault('django', django_stub)
sys.modules.setdefault('django.http', http_stub)
sys.modules.setdefault('django.utils', utils_stub)
sys.modules.setdefault('django.utils.timezone', timezone_stub)

# Import modules under test after stubbing django
from code_editor.providers.openai_compatible import OpenAICompatibleProvider
from code_editor.providers.streaming import StreamChunk
from code_editor.services.streaming_service import StreamingService


class StreamingSupportTests(unittest.TestCase):
    """Unit tests for streaming support and parsing."""

    def setUp(self) -> None:
        # Configure a minimal provider with a deterministic base URL
        self.config = {
            'url': 'http://api.example.com',
            'model': 'test-model',
            'api_key': 'secret',
            'timeout': 5,
            'max_retries': 1,
        }

    def test_openai_stream_parse(self) -> None:
        """The provider should parse SSE streaming responses into StreamChunk objects."""
        provider = OpenAICompatibleProvider('openai_compatible', self.config)

        # Define a stub ``requests.Response`` with an ``iter_lines`` method
        class StubResponse:
            status_code = 200
            def raise_for_status(self) -> None:
                return None
            def iter_lines(self, decode_unicode: bool = False, chunk_size: int = 1):
                # Simulate two delta chunks and a final [DONE] marker
                lines = [
                    'data: {"choices":[{"delta":{"content":"Hello"},"index":0,"finish_reason":null}]}',
                    'data: {"choices":[{"delta":{"content":" world"},"index":0,"finish_reason":"stop"}]}',
                    'data: [DONE]',
                ]
                for line in lines:
                    yield line

        def post_side_effect(url, json=None, headers=None, timeout=None, stream=False):
            # Return the stub response regardless of URL
            return StubResponse()

        # Patch ``requests.post`` within the provider to return our stub
        with mock.patch('code_editor.providers.openai_compatible.requests.post', side_effect=post_side_effect):
            # Invoke chat completion with streaming
            gen = provider.chat_completion([
                {'role': 'user', 'content': 'Hi'}
            ], model=None, stream=True)
            # Collect chunks from the generator
            chunks = list(gen)
            # We expect two chunks: one with content 'Hello', another with no
            # content signalling completion (done=True)
            self.assertEqual(len(chunks), 2)
            self.assertIsInstance(chunks[0], StreamChunk)
            self.assertEqual(chunks[0].content, 'Hello')
            self.assertFalse(chunks[0].done)
            # The second chunk marks completion and may not carry content
            self.assertTrue(chunks[1].done)

    def test_wrap_provider_response_stream(self) -> None:
        """The wrap helper should convert streaming chunks into SSE dicts."""
        # Define a simple generator of StreamChunk objects
        def simple_gen():
            yield StreamChunk(content='foo', done=False)
            yield StreamChunk(content='bar', done=True)

        wrapped = list(StreamingService.wrap_provider_response_for_streaming(simple_gen(), 'req1', 'model-x'))
        # Expect two events: a chunk and a done event
        self.assertEqual(len(wrapped), 2)
        self.assertEqual(wrapped[0]['type'], 'chunk')
        self.assertEqual(wrapped[0]['content'], 'foo')
        self.assertEqual(wrapped[1]['type'], 'done')


if __name__ == '__main__':
    unittest.main()

