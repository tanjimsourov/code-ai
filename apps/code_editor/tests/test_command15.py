import os
import tempfile
import unittest
from pathlib import Path

from django.test import TestCase

from code_editor.services.command_runner import CommandRunner
from code_editor.services.validation_service import ValidationService
from code_editor.models import Project, Repository, TaskRun, CandidatePatch


class CommandRunnerSafetyTest(unittest.TestCase):
    """Additional safety tests for the sandboxed CommandRunner."""

    def test_path_traversal_rejected(self) -> None:
        """Runner should reject commands containing relative or absolute path traversal."""
        runner = CommandRunner(sandbox_enabled=True, allowed_commands=['python'])
        with tempfile.TemporaryDirectory() as tmp:
            cwd = Path(tmp)
            # Attempt to run a file outside the workspace via .. traversal
            result = runner.run(['python', '../outside.py'], cwd=cwd)
            self.assertEqual(result['exit_code'], -3)
            self.assertIn('unsafe path', result['output'])
        

class ValidationServiceRelevantFilesTest(TestCase):
    """Tests for the ValidationService's targeted test file discovery."""

    def setUp(self) -> None:
        # Create a simple project and repository for the task
        self.project = Project.objects.create(name='cmd15_proj', description='')
        self.repo = Repository.objects.create(
            project=self.project,
            name='cmd15_repo',
            url='file:///tmp/cmd15_repo',
            branch='main',
            access_type='local',
        )

    def test_find_relevant_test_files_handles_json_lists(self) -> None:
        """The helper should flatten JSON lists and strings in touched_files."""
        task = TaskRun.objects.create(repository=self.repo, instruction='test instruction')
        # Candidate with a list of touched files
        CandidatePatch.objects.create(
            task=task,
            candidate_key='cand1',
            status='applied',
            touched_files=['src/foo.py', 'bar/baz.py'],
        )
        # Candidate with a string in touched_files (legacy)
        CandidatePatch.objects.create(
            task=task,
            candidate_key='cand2',
            status='applied',
            touched_files='utils/qux.py',
        )
        service = ValidationService()
        # Prepare a temporary workspace with test files matching our patterns
        with tempfile.TemporaryDirectory() as tmp:
            ws = Path(tmp)
            # For foo.py expect test_foo.py and foo_test.py patterns
            (ws / 'test_foo.py').write_text('print("foo")')
            (ws / 'foo_test.py').write_text('print("foo test")')
            # For baz.py expect baz_test.py
            (ws / 'baz_test.py').write_text('print("baz test")')
            # For qux.py expect test_qux.py
            (ws / 'test_qux.py').write_text('print("qux test")')
            files = service._find_relevant_test_files(ws, task)
            # Ensure deduplicated list contains expected test files
            self.assertIn('test_foo.py', files)
            self.assertIn('foo_test.py', files)
            self.assertIn('baz_test.py', files)
            self.assertIn('test_qux.py', files)


if __name__ == '__main__':
    unittest.main()

