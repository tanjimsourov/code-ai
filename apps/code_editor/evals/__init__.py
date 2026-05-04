"""Evaluation harness for the code editor.

This package contains lightweight evaluation tasks and a harness for
running them.  The goals of the evaluation harness are to provide
deterministic benchmarks for continuous integration and to enable
optional live runs against real providers.  When the environment
variable ``CODE_EDITOR_RUN_LIVE_EVALS`` is set to a truthy value,
the harness will attempt to use the configured providers via the
service layer.  Otherwise, it uses a stub provider that returns
pre‑determined results for each benchmark.

To add a new evaluation, create an entry in ``benchmarks.py``
describing the task and expected behaviour.  See existing examples
for guidance.
"""

from .harness import run_evaluations  # noqa: F401