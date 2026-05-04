"""Tests for the OpenAICompatibleProvider infill adapter.

This test verifies that when the native completion endpoint does not
support suffix completions the provider falls back to the chat
completion API.
"""

from unittest import mock, TestCase

from code_editor.providers.openai_compatible import OpenAICompatibleProvider
from code_editor.exceptions import ProviderNotAvailableException


class OpenAIInfillAdapterTest(TestCase):
    def test_infill_fallback_to_chat(self):
        provider = OpenAICompatibleProvider('openai', {'url': 'http://fake:1234'})
        # Mock _request_with_fallback to raise ProviderNotAvailableException for suffix completions
        with mock.patch.object(OpenAICompatibleProvider, '_request_with_fallback', side_effect=ProviderNotAvailableException()):
            # Mock chat_completion to return predictable response
            expected_response = {'choices': [{'message': {'content': 'inserted code'}}]}
            with mock.patch.object(OpenAICompatibleProvider, 'chat_completion', return_value=expected_response) as mock_chat:
                result = provider.infill_code('pre', 'post', model='test')
                # Should call chat_completion once
                mock_chat.assert_called_once()
                # Should return the chat response
                self.assertEqual(result, expected_response)

