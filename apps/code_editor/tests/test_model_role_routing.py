"""Tests for model role routing in the ModelRegistryService.

This test verifies that the registry selects a provider that satisfies
the capability requirements of a role.  The retrieval uses a
mocked RouterService with a dummy provider that advertises
embedding support.
"""

from unittest import TestCase, mock

from code_editor.providers.base import BaseProvider
from code_editor.services.model_registry import ModelRegistryService
from code_editor.exceptions import ProviderNotAvailableException


class DummyProvider(BaseProvider):
    """A minimal provider advertising embedding capability."""

    def __init__(self):
        super().__init__('dummy', {'model': 'dummy-model'})

    def chat_completion(self, messages, model, temperature=0.7, max_tokens=None, stream=False, **kwargs):
        return {}

    def text_completion(self, prompt, model, temperature=0.7, max_tokens=None, stream=False, **kwargs):
        return {}

    def edit_code(self, instruction, code, model, temperature=0.3, max_tokens=None, **kwargs):
        return {}

    def get_models(self):
        return [{'id': 'dummy-model', 'object': 'model', 'owned_by': self.name, 'created': 0}]

    def infill_code(self, prefix, suffix, model, language=None, filename=None, temperature=0.7, max_tokens=None, stream=False, **kwargs):
        return {}

    def supports_embeddings(self) -> bool:
        return True

    def supports_chat(self) -> bool:
        return True

    def supports_completion(self) -> bool:
        return True

    def supports_edit(self) -> bool:
        return True

    def supports_streaming(self) -> bool:
        return False

    def supports_json(self) -> bool:
        return False

    def supports_tools(self) -> bool:
        return False

    def supports_infill(self) -> bool:
        return False

    def supports_rerank(self) -> bool:
        return False

    def supports_suffix_completion(self) -> bool:
        return False


class ModelRoleRoutingTest(TestCase):
    def test_embed_role_selects_provider_with_embeddings(self):
        dummy_provider = DummyProvider()
        # Patch RouterService to return dummy provider for embed
        with mock.patch('code_editor.services.router.RouterService.get_provider') as get_provider_mock:
            get_provider_mock.return_value = dummy_provider
            # Also patch get_provider_by_name to return dummy
            with mock.patch('code_editor.services.router.RouterService.get_provider_by_name') as get_by_name_mock:
                get_by_name_mock.return_value = dummy_provider
                registry = ModelRegistryService()
                entry = registry.get_role_entry('embed')
                # Ensure provider name resolves to dummy
                self.assertEqual(entry.provider, 'dummy')
                # Ensure capability is true
                self.assertTrue(entry.capabilities.get('embeddings'))

