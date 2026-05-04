import os
import unittest

from code_editor.evals.harness import run_evaluations


class EvaluationHarnessTestCase(unittest.TestCase):
    """Tests for the evaluation harness using the stub provider."""

    def setUp(self) -> None:
        # Preserve environment variables to restore later
        self._orig_env = os.environ.copy()
        # Ensure live evaluation is disabled for deterministic output
        os.environ.pop('code_editor.', None)

    def tearDown(self) -> None:
        # Restore original environment to avoid side effects
        os.environ.clear()
        os.environ.update(self._orig_env)

    def test_evaluations_pass_with_stub(self):
        """All stub provider evaluations should pass."""
        results = run_evaluations()
        # We expect four tasks as defined in harness.get_tasks()
        self.assertEqual(len(results), 4)
        for res in results:
            self.assertTrue(res.passed, f"Task {res.task} failed unexpectedly")
            self.assertGreaterEqual(res.latency_ms, 0)
            self.assertEqual(res.repair_attempts, 1)
            # Each task should have tests passed equal to the number of test cases
            if res.task == 'human_eval_add':
                self.assertEqual(res.tests_passed, 2)
            elif res.task == 'bug_fix_divide':
                self.assertEqual(res.tests_passed, 2)
            elif res.task == 'refactor_greet':
                self.assertEqual(res.tests_passed, 1)
            elif res.task == 'infill_multiply':
                self.assertEqual(res.tests_passed, 2)

    def test_live_evaluations_fallback_to_stub(self):
        """When live evaluations are requested but unavailable, fallback to stub provider."""
        # Set environment variable to enable live evaluation
        os.environ['code_editor.'] = 'true'
        # Run evaluations; if no live provider is configured the harness
        # should still return deterministic results via the stub provider.
        results = run_evaluations()
        self.assertEqual(len(results), 4)
        # All tasks should still pass using the stub provider
        for res in results:
            self.assertTrue(res.passed)


if __name__ == '__main__':
    unittest.main()

