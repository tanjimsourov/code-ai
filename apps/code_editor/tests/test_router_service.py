"""
Unit tests for the RouterService.  These tests verify that
providers are initialized based on environment variables and that
provider chains are computed as expected.  They do not attempt to
connect to any external model servers.

These tests use Python's built‑in ``unittest`` framework rather than
``django.test`` to avoid requiring Django at import time.  Should
Django be installed, ``SimpleTestCase`` could be used instead.
"""

import os
import unittest
from unittest import mock

from code_editor.services.router import RouterService
from code_editor.providers.llamacpp import LlamaCppProvider


class RouterServiceInitializationTests(unittest.TestCase):
    """Tests for provider initialization and configuration on RouterService."""

    def setUp(self) -> None:
        # Ensure environment is clean before each test
        self.env_patcher = mock.patch.dict(os.environ, {}, clear=True)
        self.env_patcher.start()

    def tearDown(self) -> None:
        # Restore environment
        self.env_patcher.stop()

    def test_initializes_local_provider_when_url_set(self) -> None:
        os.environ['AI_LOCALAI_URL'] = 'http://localhost:1234'
        router = RouterService()
        provider = router.get_provider_by_name('local')
        self.assertIsInstance(provider, LlamaCppProvider)

    def test_does_not_initialize_provider_when_url_missing(self) -> None:
        # No environment variables set; router should not create any providers
        router = RouterService()
        self.assertIsNone(router.get_provider_by_name('local'))
        self.assertIsNone(router.get_provider_by_name('fast'))
        self.assertIsNone(router.get_provider_by_name('strong'))

    def test_provider_chain_for_request_types(self) -> None:
        router = RouterService()
        self.assertEqual(router._get_provider_chain('chat'), ['local', 'fast'])
        self.assertEqual(router._get_provider_chain('complete'), ['fast', 'local'])
        # Edit requests include strong, fast, local when enabled
        self.assertIn('local', router._get_provider_chain('edit'))

    def test_initializes_openai_provider_when_enabled(self) -> None:
        """Router should register the OpenAI‑compatible provider when configured."""
        # Set OpenAI‑compatible provider configuration via new environment variables
        os.environ['code_editor.'] = 'http://api.example.com'
        os.environ['code_editor.'] = 'gpt-test'
        os.environ['code_editor.'] = 'true'
        router = RouterService()
        # Provider should be registered under its type name
        provider = router.get_provider_by_name('openai_compatible')
        from ..providers.openai_compatible import OpenAICompatibleProvider
        self.assertIsInstance(provider, OpenAICompatibleProvider)
        # The provider chain for chat should include openai_compatible at the end
        chain = router._get_provider_chain('chat')
        self.assertIn('openai_compatible', chain)


if __name__ == '__main__':
    unittest.main()

