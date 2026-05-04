# Code Editor Backend

Django backend project for a local-first AI coding assistant with provider routing for Ollama, llama.cpp, vLLM, and OpenAI-compatible local endpoints.

## Current Readiness

Status: BLOCKED (not staging-ready yet)

Why blocked:
- Legacy `apps/code_editor/tests` suite has failing tests.
- Some staging MVP behaviors are scaffold-level and need deeper validation.

## Quick Local Setup

1. `python -m pip install -U pip`
2. `python -m pip install -e .[dev,postgres,channels_redis]`
3. `copy .env.example .env` (Windows) or `cp .env.example .env`
4. `python manage.py migrate --settings=config.settings.local --noinput`
5. `python manage.py runserver --settings=config.settings.local`

## Quick Staging Setup

1. Set `DJANGO_SETTINGS_MODULE=config.settings.staging`
2. Configure PostgreSQL + Redis in env
3. Run migrations and collectstatic
4. Start gunicorn/daphne/celery services

## Docker Deployment

- `docker compose build`
- `docker compose up -d`

## VPS Deployment

Use files in `deploy/systemd/`, `deploy/scripts/`, and `nginx/code_editor_backend.conf`.

## Local Model Setup

See `docs/LOCAL_MODEL_SETUP.md`.

## Management Commands

See `docs/MANAGEMENT_COMMANDS.md`.

## Final Verification Checklist

Run commands listed in `docs/FINAL_DEPLOYABILITY_REPORT.md`.

## Known Limitations

- Legacy test failures must be resolved before staging-ready verdict.
- Upstream sync is metadata-only scaffold flow by default.
