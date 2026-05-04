import os
import tempfile
import unittest
from pathlib import Path

from code_editor.services.command_runner import CommandRunner


class SandboxRunnerTestCase(unittest.TestCase):
    """Tests for the sandboxed ``CommandRunner`` utility."""

    def setUp(self) -> None:
        # Preserve environment variables to restore later
        self._orig_env = os.environ.copy()

    def tearDown(self) -> None:
        # Restore original environment to avoid side effects
        os.environ.clear()
        os.environ.update(self._orig_env)

    def _with_runner(self, **env_overrides):
        """Helper to create a runner with specific environment overrides."""
        os.environ.update(env_overrides)
        return CommandRunner()

    def test_safe_command_allowed(self):
        """Runner should execute allowed commands and capture output."""
        runner = self._with_runner(
            CODE_EDITOR_SANDBOX_ENABLED='true',
            CODE_EDITOR_ALLOWED_TEST_COMMANDS='python',
            CODE_EDITOR_COMMAND_TIMEOUT_SECONDS='5',
            CODE_EDITOR_MAX_COMMAND_OUTPUT_CHARS='1000',
        )
        with tempfile.TemporaryDirectory() as tmp:
            cwd = Path(tmp)
            result = runner.run(['python', '-c', "print('hello')"], cwd=cwd)
            self.assertEqual(result['exit_code'], 0)
            self.assertIn('hello', result['output'])

    def test_rejected_command(self):
        """Runner should reject commands not in the allow‑list."""
        runner = self._with_runner(
            CODE_EDITOR_SANDBOX_ENABLED='true',
            CODE_EDITOR_ALLOWED_TEST_COMMANDS='python',
        )
        with tempfile.TemporaryDirectory() as tmp:
            cwd = Path(tmp)
            # Using ``echo`` which is typically a shell builtin; expect rejection
            result = runner.run(['echo', 'hi'], cwd=cwd)
            # -3 exit code indicates command not allowed
            self.assertEqual(result['exit_code'], -3)
            self.assertIn('not allowed', result['output'])

    def test_timeout_handling(self):
        """Runner should time out long running commands."""
        runner = self._with_runner(
            CODE_EDITOR_SANDBOX_ENABLED='true',
            CODE_EDITOR_ALLOWED_TEST_COMMANDS='python',
            CODE_EDITOR_COMMAND_TIMEOUT_SECONDS='1',
        )
        with tempfile.TemporaryDirectory() as tmp:
            cwd = Path(tmp)
            result = runner.run(['python', '-c', 'import time; time.sleep(2)'], cwd=cwd)
            self.assertEqual(result['exit_code'], -1)
            self.assertIn('timed out', result['output'])

    def test_output_truncation(self):
        """Runner should truncate output longer than configured limit."""
        runner = self._with_runner(
            CODE_EDITOR_SANDBOX_ENABLED='true',
            CODE_EDITOR_ALLOWED_TEST_COMMANDS='python',
            CODE_EDITOR_MAX_COMMAND_OUTPUT_CHARS='50',
        )
        with tempfile.TemporaryDirectory() as tmp:
            cwd = Path(tmp)
            # Produce a long line of characters
            result = runner.run(['python', '-c', "print('x' * 200)"], cwd=cwd)
            self.assertEqual(result['exit_code'], 0)
            # Ensure output is truncated and contains the truncation marker
            self.assertLessEqual(len(result['output']), 60)
            self.assertIn('output truncated', result['output'])

    def test_cwd_restriction(self):
        """Runner should respect the provided working directory."""
        runner = self._with_runner(
            CODE_EDITOR_SANDBOX_ENABLED='true',
            CODE_EDITOR_ALLOWED_TEST_COMMANDS='python',
        )
        with tempfile.TemporaryDirectory() as tmp:
            cwd = Path(tmp)
            result = runner.run(['python', '-c', 'import os, sys; sys.stdout.write(os.getcwd())'], cwd=cwd)
            self.assertEqual(result['exit_code'], 0)
            # The printed cwd should match the temporary directory
            self.assertEqual(result['output'], str(cwd))


if __name__ == '__main__':
    unittest.main()

