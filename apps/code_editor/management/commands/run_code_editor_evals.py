"""Django management command to run evaluation benchmarks.

This command executes the evaluation harness defined in
``code_editor.evals.harness`` and prints a simple report to
standard output.  When the environment variable
``CODE_EDITOR_RUN_LIVE_EVALS`` is set to ``true``, the command
attempts to use a live provider via the router; otherwise it falls
back to the stub provider for deterministic results.  The command
can be invoked using:

    python manage.py run_code_editor_evals

The output lists each task with its pass/fail status, latency,
provider name and model identifier.  An overall summary is printed
at the end.
"""

from django.core.management.base import BaseCommand

from ...evals.harness import run_evaluations


class Command(BaseCommand):
    help = 'Run code editor evaluation harness'

    def handle(self, *args, **options) -> None:
        # Execute evaluations and print formatted results
        results = run_evaluations()
        passed_count = 0
        total_tests = len(results)
        self.stdout.write('Code Editor Evaluation Results\n')
        self.stdout.write('-' * 40)
        for res in results:
            status = 'PASS' if res.passed else 'FAIL'
            self.stdout.write(
                f"Task: {res.task}\n"
                f"  Status: {status}\n"
                f"  Provider: {res.provider}\n"
                f"  Model: {res.model}\n"
                f"  Latency: {res.latency_ms} ms\n"
                f"  Tests passed: {res.tests_passed}\n"
                f"  Repair attempts: {res.repair_attempts}\n"
            )
            if res.passed:
                passed_count += 1
        self.stdout.write('-' * 40)
        self.stdout.write(f"Summary: {passed_count}/{total_tests} tasks passed")