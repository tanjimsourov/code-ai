"""Tests for OllamaProvider streaming support.

This test mocks the HTTP streaming response from an Ollama server to
verify that the provider yields StreamChunk instances with the
expected content and completion flags.  No actual network calls are
performed.
"""

import json
import types
from unittest import mock, TestCase

from code_editor.providers.ollama import OllamaProvider


class DummyStreamResponse:
    """A minimal Response‑like object for streaming tests."""

    def __init__(self, lines):
        self._lines = [l.encode('utf-8') for l in lines]
        self._index = 0

    def iter_lines(self, decode_unicode=False):
        for line in self._lines:
            yield line.decode('utf-8') if decode_unicode else line

    def raise_for_status(self):
        pass

    def close(self):
        pass


class OllamaStreamingTest(TestCase):
    def test_chat_completion_streaming(self):
        # Prepare streaming JSON lines returned by Ollama
        stream_lines = [
            json.dumps({"message": {"content": "hello"}, "done": False}),
            json.dumps({"message": {"content": " world"}, "done": True}),
        ]
        dummy_response = DummyStreamResponse(stream_lines)

        # Patch requests.post to return our dummy streaming response
        with mock.patch('requests.post') as mock_post:
            mock_post.return_value = dummy_response

            provider = OllamaProvider('ollama', {'url': 'http://localhost:11434'})
            # Ensure streaming is enabled
            provider._supports_streaming = True
            # Call chat_completion with streaming
            gen = provider.chat_completion(
                messages=[{'role': 'user', 'content': 'Hello'}],
                model='test-model',
                stream=True,
            )
            # Convert generator to list
            chunks = list(gen)
            # There should be two chunks
            self.assertEqual(len(chunks), 2)
            # First chunk content and done flag
            self.assertEqual(chunks[0].content, 'hello')
            self.assertFalse(chunks[0].done)
            # Second chunk content and done flag
            self.assertEqual(chunks[1].content, ' world')
            self.assertTrue(chunks[1].done)

