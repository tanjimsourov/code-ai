"""Tests for bounded task agent loop behavior.

These tests are designed to run inside a configured Django test environment and
use stubs/mocks so they do not call a live model provider.
"""

from unittest import mock

from django.test import TestCase

from code_editor.models import Project, Repository, TaskRun, CandidatePatch
from code_editor.services.config import ConfigService
from code_editor.workflows.task_executor import TaskExecutor


class AgentConfigTests(TestCase):
    def test_agent_config_defaults_are_bounded(self):
        config = ConfigService.get_agent_config()
        self.assertGreaterEqual(config['max_iterations'], 1)
        self.assertGreaterEqual(config['max_repair_attempts'], 0)
        self.assertGreaterEqual(config['default_test_timeout_seconds'], 1)


class BoundedAgentLoopTests(TestCase):
    def setUp(self):
        self.project = Project.objects.create(name='Agent Test', description='')
        self.repository = Repository.objects.create(
            project=self.project,
            name='repo',
            url='file:///tmp/nonexistent-agent-loop-repo',
            branch='main',
            access_type='local',
        )
        self.task = TaskRun.objects.create(
            repository=self.repository,
            task_type='bugfix',
            instruction='Update two files safely',
            status='queued',
            current_stage='queued',
        )

    @mock.patch('code_editor.workflows.task_executor.TaskExecutor._copy_repository')
    @mock.patch('code_editor.workflows.task_executor.TaskExecutor._create_workspace_snapshot')
    @mock.patch('code_editor.workflows.task_executor.TaskExecutor._generate_plan', return_value='1. inspect\n2. patch')
    @mock.patch('code_editor.workflows.task_executor.TaskExecutor._search_context', return_value=[])
    @mock.patch('code_editor.workflows.task_executor.TaskExecutor._select_files', return_value=[])
    @mock.patch('code_editor.workflows.task_executor.ConfigService.get_agent_config')
    def test_executor_represents_one_plan_step_with_stubbed_candidate(
        self,
        mocked_config,
        mocked_select,
        mocked_search,
        mocked_plan,
        mocked_snapshot,
        mocked_copy,
    ):
        mocked_config.return_value = {
            'max_iterations': 1,
            'max_repair_attempts': 0,
            'auto_apply_patches': False,
            'default_test_timeout_seconds': 1,
            'sync_execution_enabled': True,
        }
        mocked_copy.return_value = '/tmp/nonexistent-agent-loop-repo'

        candidate = CandidatePatch.objects.create(
            task=self.task,
            candidate_key='stub_candidate',
            status='generated',
            summary='deterministic stub patch',
            patch_metadata={'changed_files': ['a.py', 'b.py']},
            touched_files=['a.py', 'b.py'],
        )

        with mock.patch.object(TaskExecutor, '_generate_candidates', return_value=[candidate]):
            result = TaskExecutor(self.task).run_agent_loop()

        self.task.refresh_from_db()
        self.assertEqual(result['iterations'], 1)
        self.assertEqual(result['candidate_count'], 1)
        self.assertEqual(result['repair_attempts'], 0)
        self.assertEqual(self.task.status, 'completed')
        self.assertTrue(self.task.plan_nodes.exists())
        self.assertTrue(self.task.steps.filter(name__startswith='agent_iteration_').exists())

    @mock.patch('code_editor.workflows.task_executor.TaskExecutor._copy_repository')
    @mock.patch('code_editor.workflows.task_executor.TaskExecutor._create_workspace_snapshot')
    @mock.patch('code_editor.workflows.task_executor.TaskExecutor._generate_plan', return_value='plan')
    @mock.patch('code_editor.workflows.task_executor.TaskExecutor._search_context', return_value=[])
    @mock.patch('code_editor.workflows.task_executor.TaskExecutor._select_files', return_value=[])
    @mock.patch('code_editor.workflows.task_executor.ConfigService.get_agent_config')
    def test_repair_attempts_are_bounded(
        self,
        mocked_config,
        mocked_select,
        mocked_search,
        mocked_plan,
        mocked_snapshot,
        mocked_copy,
    ):
        mocked_config.return_value = {
            'max_iterations': 1,
            'max_repair_attempts': 0,
            'auto_apply_patches': True,
            'default_test_timeout_seconds': 1,
            'sync_execution_enabled': True,
        }
        mocked_copy.return_value = '/tmp/nonexistent-agent-loop-repo'
        candidate = CandidatePatch.objects.create(
            task=self.task,
            candidate_key='stub_candidate',
            status='generated',
            summary='deterministic stub patch',
        )
        with mock.patch.object(TaskExecutor, '_generate_candidates', return_value=[candidate]), \
             mock.patch.object(TaskExecutor, '_apply_candidate', return_value=None), \
             mock.patch('code_editor.workflows.task_executor.ValidationService.validate_candidate') as mocked_validate:
            validation = mock.Mock()
            validation.status = 'failed'
            validation.output = 'failing tests'
            mocked_validate.return_value = validation
            result = TaskExecutor(self.task).run_agent_loop()

        self.assertEqual(result['repair_attempts'], 0)
        self.assertLessEqual(result['repair_attempts'], result['max_repair_attempts'])

