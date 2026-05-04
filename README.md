# Code AI Backend

Django backend for a local-first AI coding assistant with routing for Ollama, llama.cpp, vLLM, and generic OpenAI-compatible local endpoints.

## Current Readiness

Status: BLOCKED

Why blocked:
- Local verification gates now pass, including `pytest -q`.
- Docker validation could not be executed in this environment because the `docker` CLI is not installed.
- `python manage.py check --deploy --settings=config.settings.production` still reports a deploy warning when no real production `SECRET_KEY` is supplied.

## Quick Local Setup

1. `python -m pip install -U pip`
2. `python -m pip install -e .[dev,postgres,channels_redis]`
3. `copy .env.example .env`
4. `python manage.py migrate --settings=config.settings.local --noinput`
5. `python manage.py runserver --settings=config.settings.local`

## Quick Staging Setup

1. Set `DJANGO_SETTINGS_MODULE=config.settings.staging`
2. Configure PostgreSQL, Redis, and storage paths in the environment
3. Run `python manage.py migrate --settings=config.settings.staging --noinput`
4. Start Gunicorn, Daphne, and Celery using `deploy/systemd/`

## Docker Deployment

- `docker compose build`
- `docker compose up -d`

## VPS Deployment

- Nginx config: `nginx/code_ai.conf`
- Systemd units: `deploy/systemd/code-ai-*.service`
- Deploy helpers: `deploy/scripts/`

## Local Model Setup

See `docs/LOCAL_MODEL_SETUP.md`.

## Management Commands

See `docs/MANAGEMENT_COMMANDS.md`.

## Verification Checklist

See `docs/CODEX_COMPLETION_REPORT.md` and `docs/FINAL_DEPLOYABILITY_REPORT.md`.

## Known Limitations

- Docker build and `docker compose config` were not runnable in this environment.
- Production deploy validation still requires real deployment env vars, especially `SECRET_KEY` and host configuration.
- `CODE_EDITOR_REPOSITORY_ROOT` remains as a documented deprecated compatibility alias in repository storage resolution.
