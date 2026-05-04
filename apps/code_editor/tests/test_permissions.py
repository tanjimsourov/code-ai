"""Targeted permission tests for Code Editor API.

These tests verify that the most sensitive endpoints require API key
authentication when configured to do so and that read‑only listing
endpoints honour the public surface flags.  The tests are intentionally
minimal to avoid exercising unrelated functionality.
"""

import os
from django.test import TestCase
from rest_framework.test import APIRequestFactory

from code_editor.api import views as core_views
from code_editor.api import openai_views


class PermissionTests(TestCase):
    """Ensure endpoints require API key when configured."""

    def setUp(self) -> None:
        # Require API key for these tests
        os.environ['code_editor.'] = '1'
        # Disable public model listing
        os.environ['code_editor.'] = '0'
        os.environ['code_editor.'] = '0'
        os.environ['code_editor.'] = '0'

    def test_chat_completion_requires_api_key(self):
        factory = APIRequestFactory()
        request = factory.post('/api/code-editor/chat/', {'messages': []}, format='json')
        response = core_views.chat_completion(request)
        # Expect 401 unauthorized due to missing API key
        self.assertEqual(response.status_code, 401)

    def test_models_list_requires_api_key_when_not_public(self):
        factory = APIRequestFactory()
        request = factory.get('/api/code-editor/models/')
        response = core_views.models_list(request)
        # Expect 401 unauthorized since public listing is disabled
        self.assertEqual(response.status_code, 401)

    def test_openai_models_requires_api_key_when_not_public(self):
        factory = APIRequestFactory()
        request = factory.get('/v1/models/')
        response = openai_views.openai_models(request)
        # Should be unauthorized due to disabled public listing
        self.assertEqual(response.status_code, 401)

