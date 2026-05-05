import tempfile
from pathlib import Path
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework import status
from rest_framework.test import APIClient

from code_editor.models import Artifact, Project, Repository, TaskRun, TaskStep
from code_editor.services.task_artifact_service import TaskArtifactService


class TaskApiTestCase(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = get_user_model().objects.create_user(username='task-user', password='secret123')
        self.client.force_login(self.user)
        self.project = Project.objects.create(name='Task API Project', description='')
        self.repo_dir = tempfile.TemporaryDirectory()
        repo_root = Path(self.repo_dir.name)
        (repo_root / 'app.py').write_text('print("hello")\n', encoding='utf-8')
        self.repository = Repository.objects.create(
            project=self.project,
            name='task-repo',
            url=f'file://{repo_root}',
            access_type='local',
            branch='main',
        )

    def tearDown(self):
        self.repo_dir.cleanup()

    def test_create_task_returns_resource_without_inline_execution(self):
        with patch('code_editor.api.task_views.launch_task_run', return_value={'launched_via': 'thread', 'runner_job_id': 'thread:demo'}) as mock_launch:
            response = self.client.post(
                '/api/code-editor/tasks/',
                {
                    'repository_id': self.repository.id,
                    'instruction': 'Fix the bug in app.py',
                    'task_type': 'bugfix',
                },
                format='json',
            )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data['object'], 'task_run')
        self.assertEqual(response.data['data']['status'], 'queued')
        mock_launch.assert_called_once()

    def test_task_detail_returns_steps(self):
        task = TaskRun.objects.create(
            repository=self.repository,
            task_type='bugfix',
            instruction='Fix bug',
            status='planning',
            current_stage='planning',
        )
        TaskStep.objects.create(task=task, name='planning', order=0, status='completed', summary='Planned', logs='ok')

        response = self.client.get(f'/api/code-editor/tasks/{task.id}/')

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['data']['id'], str(task.id))
        self.assertEqual(len(response.data['data']['steps']), 1)

    def test_task_steps_endpoint(self):
        task = TaskRun.objects.create(
            repository=self.repository,
            task_type='bugfix',
            instruction='Fix bug',
            status='selecting_files',
        )
        TaskStep.objects.create(task=task, name='planning', order=0, status='completed')
        TaskStep.objects.create(task=task, name='selecting_files', order=1, status='selecting_files')

        response = self.client.get(f'/api/code-editor/tasks/{task.id}/steps/')

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['object'], 'list')
        self.assertEqual(len(response.data['data']), 2)
        self.assertEqual(response.data['data'][0]['name'], 'planning')

    def test_task_artifacts_and_content_endpoints(self):
        task = TaskRun.objects.create(
            repository=self.repository,
            task_type='bugfix',
            instruction='Fix bug',
            status='completed',
        )
        artifact = TaskArtifactService.persist_text_artifact(
            task=task,
            artifact_type='result',
            relative_name='result.json',
            content='{"status": "ok"}',
            description='Result payload',
        )

        list_response = self.client.get(f'/api/code-editor/tasks/{task.id}/artifacts/')
        detail_response = self.client.get(f'/api/code-editor/tasks/{task.id}/artifacts/{artifact.id}/?include_content=true')
        content_response = self.client.get(f'/api/code-editor/tasks/{task.id}/artifacts/{artifact.id}/content/')

        self.assertEqual(list_response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(list_response.data['data']), 1)
        self.assertEqual(detail_response.status_code, status.HTTP_200_OK)
        self.assertEqual(detail_response.data['data']['id'], str(artifact.id))
        self.assertIn('status', detail_response.data['content'])
        self.assertEqual(content_response.status_code, status.HTTP_200_OK)
        self.assertIn('content', content_response.data['data'])

    def test_task_result_endpoint(self):
        task = TaskRun.objects.create(
            repository=self.repository,
            task_type='bugfix',
            instruction='Fix bug',
            status='completed',
            summary='Task finished',
            result_summary='Validation passed',
            result_payload={'best_candidate_key': 'candidate_0'},
        )

        response = self.client.get(f'/api/code-editor/tasks/{task.id}/result/')

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['object'], 'task_result')
        self.assertEqual(response.data['data']['result_payload']['best_candidate_key'], 'candidate_0')

    def test_cancel_task_marks_queued_task_cancelled(self):
        task = TaskRun.objects.create(
            repository=self.repository,
            task_type='bugfix',
            instruction='Fix bug',
            status='queued',
            current_stage='queued',
        )

        response = self.client.post(
            f'/api/code-editor/tasks/{task.id}/cancel/',
            {'reason': 'User requested stop'},
            format='json',
        )

        task.refresh_from_db()
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(task.cancellation_requested)
        self.assertEqual(task.status, 'cancelled')

