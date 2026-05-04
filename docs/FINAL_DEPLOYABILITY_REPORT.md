# Final Deployability Report

## Final Architecture

- Django project root with `manage.py`, `config/` settings split (`base/local/staging/production`), WSGI/ASGI/Celery entrypoints.
- Core application mounted at `apps/code_editor` with compatibility namespace `code_editor/`.
- Supporting apps scaffolded: `core`, `accounts`, `ai_providers`, `repositories`, `workspaces`, `tasks`, `artifacts`, `upstream`, `observability`.

## Apps Created

- `apps.core` (env parsing helpers, health URLs, safe path helper)
- `apps.accounts` (scaffold)
- `apps.ai_providers` (scaffold)
- `apps.repositories` (scaffold)
- `apps.workspaces` (scaffold)
- `apps.tasks` (scaffold)
- `apps.artifacts` (scaffold)
- `apps.upstream` (scaffold)
- `apps.observability` (scaffold)
- `apps.code_editor` (integrated legacy app)

## Old App Integration Summary

- Extracted `code_editor_after_command_18.zip`.
- Moved legacy app into `apps/code_editor`.
- Added compatibility package `code_editor/` to preserve legacy import paths.
- Removed `apps/code_editor/utils.py` conflict and standardized on `apps/code_editor/utils/` package.

## Migration Strategy

- Deleted legacy migration chain and regenerated a single clean migration: `apps/code_editor/migrations/0001_initial.py`.
- Verified `makemigrations --check --dry-run` returns no drift.
- Fresh local migration succeeds.

## Security Fixes

- Artifact read path constrained to storage root using `apps/core/safe_paths.py`.
- Patch apply/revert API derives workspace/repository paths server-side.
- Metrics endpoint remains protected by token/public flag.
- Command runner output cap aligned with `CODE_EDITOR_COMMAND_MAX_OUTPUT_BYTES`.

## Provider / Local AI Support

- Local/offline-first provider routing retained for Ollama, llama.cpp, vLLM, and OpenAI-compatible endpoints.
- `show_code_editor_model_registry` works offline.
- `check_code_editor_providers` now defaults to offline-safe mode; online checks require `--check-providers`.

## Task Execution Status

- Task orchestration, candidate patch workflow, and artifact APIs are integrated.
- Legacy behavior remains partially inconsistent with test expectations (see blockers).

## Upstream Governance Status

- `code_editor_sync_upstream_sources` supports `--dry-run`.
- Flow is metadata/candidate-oriented and does not auto-merge live code.

## Deployment Files Created

- `Dockerfile`
- `docker-compose.yml`
- `gunicorn.conf.py`
- `nginx/code_editor_backend.conf`
- `deploy/systemd/*.service`
- `deploy/scripts/*.sh`
- `Makefile`

## Docs Created/Updated

- `README.md`
- `docs/INSTALLATION.md`
- `docs/CONFIGURATION.md`
- `docs/DEPLOYMENT.md`
- `docs/SECURITY.md`
- `docs/OPERATIONS.md`
- `docs/MANAGEMENT_COMMANDS.md`
- `docs/UPSTREAM_GOVERNANCE.md`
- `docs/LOCAL_MODEL_SETUP.md`
- `docs/FINAL_DEPLOYABILITY_REPORT.md`

## Exact Commands Run and Results

- `python -m compileall -q .` -> PASS
- `python manage.py check --settings=config.settings.local --fail-level WARNING` -> PASS
- `python manage.py makemigrations --settings=config.settings.local --check --dry-run` -> PASS
- `rm -f /tmp/code_editor_fresh.sqlite3` -> FAIL on PowerShell (`rm -f` unsupported)
- Equivalent run: `Remove-Item C:\tmp\code_editor_fresh.sqlite3 -Force` -> PASS
- `python manage.py migrate --settings=config.settings.local --noinput` -> PASS
- `python manage.py code_editor_smoke_check --settings=config.settings.local` -> PASS
- `python manage.py code_editor_validate_install --settings=config.settings.local` -> PASS
- `python manage.py show_code_editor_model_registry --settings=config.settings.local` -> PASS
- `python manage.py code_editor_sync_upstream_sources --settings=config.settings.local --dry-run` -> PASS
- `pytest -q` -> FAIL

## Remaining Limitations / Blockers

- `pytest -q` has multiple failing legacy tests in `apps/code_editor/tests` (permissions behavior, command runner expectations, provider init expectations, retrieval API expectations, and streaming expectations).
- `grep` diagnostics still show `AllowAny` usage in `improved_task_views.py` for info endpoint and internal `workspace_dir`/`repository_dir` identifiers in service/test code.
- Legacy fallback alias `CODE_EDITOR_REPOSITORY_ROOT` remains in repository service (documented compatibility path).

## Final Verdict

BLOCKED
