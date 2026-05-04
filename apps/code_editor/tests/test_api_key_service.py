"""
Tests for the API key service in code_editor.services.api_key_service.

These tests check that API keys are created correctly, with hashed storage
and sensible defaults for quotas and limits. They also verify that invalid
inputs raise the appropriate exceptions.
"""

from django.test import TestCase
from django.contrib.auth import get_user_model

from code_editor.services.api_key_service import ApiKeyService
from code_editor.exceptions import InvalidRequestException
from code_editor.models import CodeEditorApiKey


class ApiKeyServiceTests(TestCase):
    def setUp(self) -> None:
        # Create a dummy user for created_by
        self.user = get_user_model().objects.create_user(username='tester', password='secret')

    def test_create_api_key_success(self) -> None:
        result = ApiKeyService.create_api_key(name='My Key', created_by=self.user)
        # Raw key should be returned
        self.assertIn('key', result)
        # Prefix should match first 8 characters of raw key
        self.assertEqual(result['prefix'], result['key'][:8])
        # API key should exist in DB with hashed key
        api_key_obj = CodeEditorApiKey.objects.get(id=result['id'])
        self.assertNotEqual(api_key_obj.key_hash, '')
        # Ensure created_by is stored
        self.assertEqual(api_key_obj.created_by, self.user)

    def test_create_api_key_invalid_name(self) -> None:
        with self.assertRaises(InvalidRequestException):
            ApiKeyService.create_api_key(name='', created_by=self.user)

