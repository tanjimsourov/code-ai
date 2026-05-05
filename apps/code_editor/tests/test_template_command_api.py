from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework import status
from rest_framework.test import APIClient


class TemplateCommandApiTestCase(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = get_user_model().objects.create_user(username='template-user', password='secret123')
        self.client.force_login(self.user)

    def test_template_command_requires_command(self):
        response = self.client.post(
            "/api/code-editor/template-command/",
            {
                "command": "",
                "canvas": {"width": 1920, "height": 1080},
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data["error"]["message"], "Command is required")

    def test_template_command_returns_water_dashboard_fallback(self):
        response = self.client.post(
            "/api/code-editor/template-command/",
            {
                "command": "Build a water conservation dashboard for hotel guests with live usage insights",
                "canvas": {"width": 1920, "height": 1080},
                "language": "en",
                "target_audience": "hotel guests",
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["template_key"], "WaterConservationDashboard")
        self.assertIn("placement", response.data)
        self.assertGreater(response.data["placement"]["width"], 0)
        self.assertEqual(response.data["props"]["lang"], "en")
        self.assertIn("en", response.data["props"]["texts"])

    def test_template_command_supports_large_webpage(self):
        response = self.client.post(
            "/api/code-editor/template-command/",
            {
                "command": "Create a large webpage template for enterprise strategy communication",
                "canvas": {"width": 1920, "height": 1080},
                "template_mode": "webpage",
                "language": "en",
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["template_key"], "LargeWebpageTemplate")
        self.assertEqual(response.data["template_mode_used"], "webpage")
        self.assertIn("hero", response.data["props"]["texts"]["en"])
        self.assertIn("sections", response.data["props"]["texts"]["en"])

    def test_template_command_supports_large_table(self):
        response = self.client.post(
            "/api/code-editor/template-command/",
            {
                "command": "Build a big operations table with rows and columns for branch status",
                "canvas": {"width": 1920, "height": 1080},
                "template_mode": "table",
                "language": "en",
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["template_key"], "LargeDataTableTemplate")
        self.assertEqual(response.data["template_mode_used"], "table")
        self.assertIn("table", response.data["props"]["texts"]["en"])
        self.assertGreater(len(response.data["props"]["texts"]["en"]["table"]["columns"]), 0)

    @patch(
        "code_editor.services.template_command_service.TemplateCommandService._generate_ai_content",
        return_value={
            "title": "Hotel Aqua Intelligence",
            "subtitle": "Guest-facing conservation insights",
            "summary": "A premium water dashboard tailored for hospitality screens.",
            "description": "Track guest water use, conservation goals, and smart savings alerts.",
            "metric_value": "128 L",
            "goal_label": "32% Target Achieved",
            "highlights": ["44 L", "37 L", "47 L"],
        },
    )
    def test_template_command_applies_ai_overrides(self, _mock_generate):
        response = self.client.post(
            "/api/code-editor/template-command/",
            {
                "command": "Create a water command center for a hotel lobby",
                "canvas": {"width": 1600, "height": 900},
                "language": "en",
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["provider_used"], "code_editor._chat")
        self.assertEqual(
            response.data["props"]["texts"]["en"]["title"],
            "Hotel Aqua Intelligence",
        )

