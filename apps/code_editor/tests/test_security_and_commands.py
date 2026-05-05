import io
import tempfile
from pathlib import Path

from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.test import TestCase
from rest_framework import status
from rest_framework.test import APIClient

from code_editor.models import Artifact, Project, Repository, TaskRun
from code_editor.services.repository_service import RepositoryService
from code_editor.services.task_artifact_service import TaskArtifactService
from code_editor.workflows.task_executor import TaskExecutor


class SecurityAndCommandTests(TestCase):
    def test_models_endpoint_is_private_by_default(self):
        response = APIClient().get('/api/code-editor/models/')
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_metrics_endpoint_is_private_by_default(self):
        response = APIClient().get('/api/code-editor/metrics/')
        self.assertIn(response.status_code, {status.HTTP_403_FORBIDDEN, status.HTTP_404_NOT_FOUND})

    def test_validate_install_command_succeeds(self):
        output = io.StringIO()
        call_command('code_editor_validate_install', stdout=output)
        self.assertIn('Installation validation completed', output.getvalue())

    def test_local_repository_storage_path_is_populated(self):
        with tempfile.TemporaryDirectory() as repo_dir:
            project = Project.objects.create(name='Local repo project')
            repository = RepositoryService.add_repository(
                project=project,
                name='local-repo',
                url=f'file://{repo_dir}',
                access_type='local',
            )

        self.assertTrue(repository.storage_path)
        self.assertTrue(Path(repository.storage_path).is_absolute())

    def test_task_executor_persists_workspace_path(self):
        with tempfile.TemporaryDirectory() as repo_dir:
            project = Project.objects.create(name='Workspace project')
            repository = Repository.objects.create(
                project=project,
                name='workspace-repo',
                url=f'file://{repo_dir}',
                access_type='local',
                storage_path=repo_dir,
            )
            task = TaskRun.objects.create(
                repository=repository,
                task_type='custom',
                instruction='Inspect workspace ownership',
            )

            executor = TaskExecutor(task)
            task.refresh_from_db()

        self.assertEqual(task.workspace_path, str(executor.workspace_dir))
        self.assertTrue(executor.workspace_dir.is_dir())

    def test_artifact_reads_reject_paths_outside_allowed_roots(self):
        project = Project.objects.create(name='Artifact project')
        repository = Repository.objects.create(
            project=project,
            name='artifact-repo',
            url='https://example.com/repo.git',
            access_type='public',
        )
        task = TaskRun.objects.create(repository=repository, instruction='Inspect artifact bounds')
        artifact = Artifact.objects.create(
            task=task,
            artifact_type='result',
            file_path=str(Path(tempfile.gettempdir()) / 'outside-artifact.txt'),
        )

        with self.assertRaises(ValidationError):
            TaskArtifactService.read_content(artifact)

    def test_smoke_check_command_succeeds(self):
        output = io.StringIO()
        call_command('code_editor_smoke_check', stdout=output)
        self.assertIn('Smoke check passed', output.getvalue())
