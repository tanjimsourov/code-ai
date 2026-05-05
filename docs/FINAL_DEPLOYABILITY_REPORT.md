# Final Deployability Report

## Architecture Summary

- Django project with split settings modules for `base`, `local`, `staging`, and `production`
- REST + websocket backend for chat, completion, edit, retrieval, tasks, patch review, and artifact access
- Provider routing for Ollama, llama.cpp, vLLM, and generic OpenAI-compatible local endpoints
- Approval-gated upstream sync flow that records candidates instead of auto-merging code

## Security Summary

- Sensitive endpoints are authenticated by default.
- Patch approval and rejection require an authenticated Django user.
- Metrics are private by default and token-aware.
- Model listing is private by default unless explicitly opened.
- Task workspaces, repositories, patch targets, and artifacts are resolved from server-owned validated paths.
- No `shell=True` application usage remains.

## Migration Summary

- Added `0002_taskrun_workspace_path_and_more`.
- Fresh local migration works.
- `makemigrations --check --dry-run` is clean.

## Local AI Support

- Ollama
- llama.cpp
- vLLM
- generic OpenAI-compatible endpoints

All provider loading is offline-safe by default. Network health checks only happen when explicitly requested.

## Deployment Assets

- `Dockerfile`
- `docker-compose.yml`
- `gunicorn.conf.py`
- `nginx/code_ai.conf`
- `deploy/systemd/code-ai-web.service`
- `deploy/systemd/code-ai-worker.service`
- `deploy/systemd/code-ai-daphne.service`
- `deploy/scripts/deploy.sh`
- `deploy/scripts/migrate.sh`
- `deploy/scripts/collectstatic.sh`
- `deploy/scripts/healthcheck.sh`
- `.github/workflows/ci.yml`

## Verification Results

- Local Django checks -> PASS
- Migration checks -> PASS
- Smoke command -> PASS
- Install validation command -> PASS
- Model registry command -> PASS
- Upstream sync dry-run -> PASS
- Pytest suite -> PASS
- Production deploy settings check -> PASS
- Docker build -> FAIL, `docker` CLI unavailable in this environment
- Docker compose config -> FAIL, `docker` CLI unavailable in this environment

## Exact Commands Run

- `python -m compileall -q .`
- `python manage.py check --settings=config.settings.local --fail-level WARNING`
- `python manage.py makemigrations --settings=config.settings.local --check --dry-run`
- `python manage.py migrate --settings=config.settings.local --noinput`
- `python manage.py code_editor_smoke_check --settings=config.settings.local`
- `python manage.py code_editor_validate_install --settings=config.settings.local`
- `python manage.py show_code_editor_model_registry --settings=config.settings.local`
- `python manage.py code_editor_sync_upstream_sources --settings=config.settings.local --dry-run`
- `pytest -q --create-db`
- `python manage.py check --deploy --settings=config.settings.production`
- `docker build --pull -t code-ai:production-check .`
- `docker compose config`

## Remaining Limitations

- Container validation is blocked by the current workstation not having Docker installed.
- Production deployment still needs real host-level validation for reverse proxy, TLS, PostgreSQL, Redis, and model endpoint availability.
- `AllowAny` remains only on the safe public `api_info` endpoint in `apps/code_editor/api/improved_task_views.py`.

## Final Verdict

BLOCKED
