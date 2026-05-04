# Task Execution Lifecycle

This document describes how the autonomous task engine drives a
`TaskRun` from creation through planning, patch generation, validation
and finalisation.  Understanding these stages will help operators
monitor tasks, interpret logs and diagnose failures.

## Stages and Statuses

Each `TaskRun` progresses through a series of **stages**.  The
`status` field on the task reflects the current stage or final
outcome.  Intermediate statuses include:

- `queued`: waiting to be executed by a worker.
- `planning`: generating a high‑level plan of action from the user
  instruction.
- `generating_patch`: producing candidate patches based on selected
  files.
- `applying_patch`: applying a selected patch to an isolated
  workspace.
- `validating`: running syntax checks and tests against the applied
  patch.
- `awaiting_review`: a candidate has been generated but requires
  manual approval before applying.

Terminal statuses indicate that no further automated processing will
occur:

- `completed`: the patch was validated successfully and the task
  finished.
- `completed_with_warnings`: validation passed but non‑blocking
  issues were detected (e.g. lint warnings).
- `validation_failed`: the patch failed validation (tests did not
  pass or syntax errors were found).
- `failed`: an unrecoverable error occurred during execution.
- `cancelled`: the user requested cancellation and the task stopped.

The `failure_reason` field categorises why a task failed, such as
`patch_generation_failure`, `patch_apply_failure` or
`validation_failure`.  This aids triaging and metrics.

## Task Steps

For each stage the executor creates a `TaskStep` record.  Steps are
ordered and store `started_at`, `completed_at`, `status`, `summary`
and free‑form `logs`.  These fields allow reconstructing an
execution timeline and measuring durations.  When a step completes
successfully its status is set to `completed`; if an error occurs it
is marked `failed`.  Cancelled steps are marked `cancelled`.

Artifacts such as plans, context, selected files, diffs and result
payloads are stored on disk under the task’s directory and linked to
steps via `Artifact` records.  Use the admin to inspect these
artifacts.

## Workspace Isolation

Every task runs in an isolated workspace under
`CODE_EDITOR_TASK_STORAGE_ROOT/<task_id>`.  The executor creates
subdirectories for:

- `workspace/`: a working copy of the repository where patches are
  applied and tests run.
- `artifacts/`: persisted artifacts such as plans, diffs and logs
  (managed by `TaskArtifactService`).
- `snapshots/`: saved workspace snapshots for rollback and auditing.
- `validation/`: temporary files used during validation.

The command runner enforces that all commands execute within the
workspace and prevents absolute paths or parent directory traversal.
If the working directory escapes the configured root the command is
rejected.

## Heartbeats and Cancellation

The executor records a heartbeat by updating `last_heartbeat_at` and
`current_stage` periodically.  External monitors can watch for
stale heartbeats to detect hung tasks.  Cancellation requests set
`cancellation_requested` on the task; the executor checks this flag
between stages and aborts if set, transitioning the task to the
`cancelled` status.
