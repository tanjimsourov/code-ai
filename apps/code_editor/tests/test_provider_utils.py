"""
Unit tests for the provider response parsing helpers.

These tests ensure that ``parse_chat_response`` and
``parse_text_completion_response`` correctly extract the assistant
message or completion text from a variety of common provider response
shapes.  The goal is to verify that the helpers gracefully handle
OpenAI‑style ``choices`` lists, Ollama‑style ``message`` fields and
other fallback cases.

The tests are designed to run without Django and use the built‑in
``unittest`` framework.
"""

import unittest

from code_editor.providers.utils import parse_chat_response, parse_text_completion_response


class ProviderUtilsTests(unittest.TestCase):
    """Tests for response parsing utility functions."""

    def test_parse_chat_response_openai_style(self) -> None:
        response = {
            'choices': [
                {
                    'index': 0,
                    'message': {
                        'role': 'assistant',
                        'content': 'Hello from OpenAI'
                    },
                    'finish_reason': 'stop'
                }
            ],
            'usage': {}
        }
        self.assertEqual(parse_chat_response(response), 'Hello from OpenAI')

    def test_parse_chat_response_ollama_style(self) -> None:
        response = {
            'model': 'llama2',
            'created_at': '2024-01-01T00:00:00Z',
            'message': {
                'role': 'assistant',
                'content': 'Hi from Ollama'
            },
            'done': True
        }
        self.assertEqual(parse_chat_response(response), 'Hi from Ollama')

    def test_parse_chat_response_fallback(self) -> None:
        # Unknown structure should return string representation
        response = {'unexpected': 'format'}
        self.assertEqual(parse_chat_response(response), str(response))

    def test_parse_text_completion_response_openai_style(self) -> None:
        response = {
            'choices': [
                {
                    'text': 'Completed text',
                    'index': 0,
                    'finish_reason': 'stop'
                }
            ],
            'usage': {}
        }
        self.assertEqual(parse_text_completion_response(response), 'Completed text')

    def test_parse_text_completion_response_chat_format(self) -> None:
        # Some providers return a message object instead of text
        response = {
            'choices': [
                {
                    'message': {
                        'role': 'assistant',
                        'content': 'Completion via chat message'
                    },
                    'index': 0
                }
            ]
        }
        self.assertEqual(parse_text_completion_response(response), 'Completion via chat message')

    def test_parse_text_completion_response_fallback(self) -> None:
        response = {'data': 'something'}
        self.assertEqual(parse_text_completion_response(response), str(response))


if __name__ == '__main__':
    unittest.main()

