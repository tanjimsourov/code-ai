"""Unit tests for the infill service and related functionality.

These tests verify that the prompt builder constructs appropriate
fill‑in‑the‑middle prompts, that the router computes the correct
provider chain for infill requests, and that the ``InfillService``
handles successful responses, validation errors and provider
unavailability correctly.  The tests rely only on Python's built‑in
``unittest`` framework and use mocks to avoid external
dependencies.  Django is not required for these tests to run.
"""

import os
import unittest
from unittest import mock

from code_editor.services.prompt_builder import PromptBuilderService
from code_editor.services.infill_service import InfillService
from code_editor.services.router import RouterService
from code_editor.exceptions import InvalidRequestException, ProviderNotAvailableException


class PromptBuilderInfillTests(unittest.TestCase):
    """Tests for the infill prompt builder."""

    def test_build_infill_prompt_includes_all_hints(self) -> None:
        prefix = 'print("Hello")'
        suffix = 'return x'
        prompt = PromptBuilderService.build_infill_prompt(
            prefix=prefix,
            suffix=suffix,
            language='python',
            filename='test.py',
            cursor_context='ctx'
        )
        # Check that all provided hints are present
        self.assertIn('Language: python', prompt)
        self.assertIn('File: test.py', prompt)
        self.assertIn('Context: ctx', prompt)
        self.assertIn(f'Prefix:\n{prefix}', prompt)
        self.assertIn(f'Suffix:\n{suffix}', prompt)


class RouterInfillChainTests(unittest.TestCase):
    """Tests for the router's infill provider chain computation."""

    def setUp(self) -> None:
        # Clear environment before each test
        self.env_patcher = mock.patch.dict(os.environ, {}, clear=True)
        self.env_patcher.start()

    def tearDown(self) -> None:
        self.env_patcher.stop()

    def test_infill_provider_chain_includes_completion_order(self) -> None:
        # Enable an OpenAI‑compatible provider so that it is appended to the chain
        os.environ['CODE_EDITOR_OPENAI_COMPATIBLE_BASE_URL'] = 'http://api.example.com'
        os.environ['CODE_EDITOR_OPENAI_COMPATIBLE_MODEL'] = 'gpt-test'
        os.environ['CODE_EDITOR_OPENAI_COMPATIBLE_ENABLED'] = 'true'
        router = RouterService()
        chain = router._get_provider_chain('infill')  # type: ignore[attr-defined]
        # The chain should start with fast, local and include openai_compatible at the end
        self.assertTrue(chain.index('fast') < chain.index('local'))
        self.assertIn('openai_compatible', chain)


class InfillServiceTests(unittest.TestCase):
    """Tests for the InfillService behaviour."""

    def setUp(self) -> None:
        # Patch request logging to avoid touching the database
        self.log_patcher = mock.patch('code_editor.models.CodeEditorRequestLog.log_request')
        self.mock_log = self.log_patcher.start()
        # Clear environment
        self.env_patcher = mock.patch.dict(os.environ, {}, clear=True)
        self.env_patcher.start()

    def tearDown(self) -> None:
        self.log_patcher.stop()
        self.env_patcher.stop()

    def test_infill_service_success_with_mock_provider(self) -> None:
        # Create a dummy provider that supports infill
        class DummyProvider:
            def __init__(self) -> None:
                self.name = 'dummy'
                self.config = {'model': 'dummy-model'}

            def supports_infill(self) -> bool:
                return True

            def infill_code(self, prefix, suffix, model, language=None, filename=None, temperature=0.7, max_tokens=None, stream=False, **kwargs):
                # Return a response similar to OpenAI format
                return {
                    'choices': [
                        {'text': 'inserted_code'}
                    ]
                }

        # Patch router to use the dummy provider
        dummy_provider = DummyProvider()
        with mock.patch.object(RouterService, '_get_provider_chain', return_value=['dummy']):
            with mock.patch.object(RouterService, 'get_provider_by_name', return_value=dummy_provider):
                service = InfillService()
                result = service.infill_code(prefix='a = 1', suffix='b = 2')
                # Should include the inserted_text extracted from provider
                self.assertEqual(result['inserted_text'], 'inserted_code')
                self.assertIn('raw_response', result)

    def test_infill_service_missing_inputs(self) -> None:
        service = InfillService()
        with self.assertRaises(InvalidRequestException):
            service.infill_code(prefix='', suffix='b = 2')
        with self.assertRaises(InvalidRequestException):
            service.infill_code(prefix='a = 1', suffix='')

    def test_infill_service_provider_not_available(self) -> None:
        # Dummy provider does not support infill
        class NoInfillProvider:
            def __init__(self) -> None:
                self.name = 'noinf'
                self.config = {'model': 'noinf-model'}
            def supports_infill(self) -> bool:
                return False
        noinf_provider = NoInfillProvider()
        # Patch router chain to include the provider
        with mock.patch.object(RouterService, '_get_provider_chain', return_value=['noinf']):
            with mock.patch.object(RouterService, 'get_provider_by_name', return_value=noinf_provider):
                service = InfillService()
                with self.assertRaises(ProviderNotAvailableException):
                    service.infill_code(prefix='a', suffix='b')


if __name__ == '__main__':
    unittest.main()

