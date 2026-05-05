# Code AI Backend

Complete Django backend for a local-first AI coding assistant. The project is designed to run against local or self-hosted model endpoints such as Ollama, llama.cpp, vLLM, and generic OpenAI-compatible servers, with optional free providers only when you explicitly configure them.

## What It Includes

- Django + DRF + Channels backend with REST and websocket entrypoints
- Repository registration, indexing, retrieval, task orchestration, patch review, and artifact storage
- Offline-safe provider registry with role-aware model routing
- Approval-gated upstream metadata sync flow
- Deployment assets for Docker, systemd, Gunicorn, Daphne, Redis, PostgreSQL, and Nginx

## Local Setup

1. `python -m pip install -U pip setuptools wheel`
2. `python -m pip install -e .[dev,celery,providers,observability,postgres,channels_redis]`
3. Copy `.env.example` to `.env` and adjust the values for your machine
4. `python manage.py migrate --settings=config.settings.local --noinput`
5. `python manage.py runserver --settings=config.settings.local`

## Verification

- `python -m compileall -q .`
- `python manage.py check --settings=config.settings.local --fail-level WARNING`
- `python manage.py makemigrations --settings=config.settings.local --check --dry-run`
- `python manage.py migrate --settings=config.settings.local --noinput`
- `python manage.py code_editor_smoke_check --settings=config.settings.local`
- `python manage.py code_editor_validate_install --settings=config.settings.local`
- `python manage.py show_code_editor_model_registry --settings=config.settings.local`
- `python manage.py code_editor_sync_upstream_sources --settings=config.settings.local --dry-run`
- `pytest -q --create-db`

## Deployment

- Docker: `docker build --pull -t code-ai:latest .`
- Compose: `docker compose up -d`
- VPS:
  `/opt/code-ai`, `deploy/systemd/code-ai-*.service`, `deploy/scripts/*.sh`, and `nginx/code_ai.conf`

## Local Model Setup

- Ollama: set `CODE_EDITOR_OLLAMA_ENABLED=true`, `CODE_EDITOR_OLLAMA_BASE_URL`, and `CODE_EDITOR_OLLAMA_MODEL`
- llama.cpp: set `CODE_EDITOR_LLAMA_CPP_ENABLED=true`, `CODE_EDITOR_LLAMA_CPP_BASE_URL`, and `CODE_EDITOR_LLAMA_CPP_MODEL`
- vLLM: set `CODE_EDITOR_VLLM_ENABLED=true`, `CODE_EDITOR_VLLM_BASE_URL`, and `CODE_EDITOR_VLLM_MODEL`
- Generic OpenAI-compatible endpoint: set `CODE_EDITOR_OPENAI_COMPATIBLE_ENABLED=true`, `CODE_EDITOR_OPENAI_COMPATIBLE_BASE_URL`, and `CODE_EDITOR_OPENAI_COMPATIBLE_MODEL`

## Security Defaults

- Sensitive APIs are private by default
- Metrics are private by default and can be token-protected
- Model listing is private by default
- Task workspaces, repository clones, patch application, and artifact reads use server-owned validated paths
- Upstream sync never auto-merges live application code

## Docs

- [Installation](docs/INSTALLATION.md)
- [Configuration](docs/CONFIGURATION.md)
- [Deployment](docs/DEPLOYMENT.md)
- [Security](docs/SECURITY.md)
- [Management Commands](docs/MANAGEMENT_COMMANDS.md)
- [Local Model Setup](docs/LOCAL_MODEL_SETUP.md)
- [Completion Report](docs/CODEX_COMPLETION_REPORT.md)
- [Deployability Report](docs/FINAL_DEPLOYABILITY_REPORT.md)

## Known Limitations

- Real production validation still requires a deployment environment with valid hosts, TLS, database, Redis, and local model endpoints
- Docker verification cannot be completed on a machine that does not have the `docker` CLI installed
- `CODE_EDITOR_REPOSITORY_ROOT` is still accepted as a documented deprecated alias for repository storage resolution
