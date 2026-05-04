# Evaluation Harness

This directory contains a simple benchmarking framework for
measuring the quality of code generation models.  The harness is
deliberately lightweight and uses a handful of deterministic tasks
that do not require downloading any large datasets.  It is intended
for developers who wish to track the impact of changes to the
``code_editor`` module over time.

## Running Evaluations

Evaluations can be invoked in two ways:

1. **Via the Django management command** (recommended in a project
   context):

   ```sh
   # From within the Django project environment
   python manage.py run_code_editor_evals
   ```

   This command will automatically select a live provider when the
   environment variable `CODE_EDITOR_RUN_LIVE_EVALS` is set to
   `true`.  Otherwise, it falls back to a stub provider that
   produces deterministic outputs suitable for CI.  The command
   prints a report summarising pass/fail status, provider/model,
   latency and test counts.

2. **Directly from Python code** using the harness API:

   ```python
   from code_editor.evals.harness import run_evaluations

   # Use the default provider selection (stub unless
   # CODE_EDITOR_RUN_LIVE_EVALS=true)
   results = run_evaluations()
   for r in results:
       print(r)
   ```

The returned `EvaluationResult` objects contain detailed metrics
for each benchmark task.

## Benchmark Tasks

The current suite (`harness.get_tasks()`) includes four sample
problems:

* **HumanEval-style function generation** – generates a simple
  arithmetic function given its signature and docstring.  The
  harness checks the output by executing the generated code and
  running a few test cases.

* **Bug-fix task** – provides a buggy function and asks the model
  to correct it.  The stub provider returns a patched version
  containing the expected fix, and the harness verifies the
  behaviour via test inputs.

* **Refactor task** – renames a function and ensures all call
  sites are updated.  This simulates a simple multi‑file refactor
  within a single string.

* **Infill task** – asks the model to complete a missing portion
  of code between a prefix and a suffix.  The harness assembles
  the final code and executes tests against it.

Additional tasks can be added by extending the `get_tasks` function
in `harness.py` and providing appropriate canned responses in
`_create_stub_provider` for the stub provider.  When
`CODE_EDITOR_RUN_LIVE_EVALS` is set and live providers are
available, tasks will automatically be passed through the router.

## Opting Into Live Evaluation

By default, the harness uses a stub provider so that CI systems
remain deterministic and do not rely on network access.  To run
evaluations against a live model, set the `CODE_EDITOR_RUN_LIVE_EVALS`
environment variable to `true` before invoking the management
command or calling `run_evaluations`.  If no provider supporting
completion is available, the harness will fall back to the stub.

```sh
export CODE_EDITOR_RUN_LIVE_EVALS=true
python manage.py run_code_editor_evals
```

Live evaluations can help gauge progress toward Codex/Claude‑like
quality, but they are optional and should not be run in CI.