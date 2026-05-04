# Implementation Notes and Upgrade Path

This document provides a high–level overview of the current public API
surface of the `code_editor` module and outlines future
compatibility plans.  It is intended for developers working on the
codebase rather than end users.

## Public API Endpoints

All endpoints are rooted at `/api/code-editor/`.  The primary
endpoints currently exposed include:

- `health/` – Basic health check for the API and underlying model
  providers.  Returns the server status, timestamp and available
  providers.
- `models/` – List all models available across configured providers.
- `chat/` – Execute a chat completion request.  Accepts a list of
  messages and optional parameters and returns a provider response.
- `completion/` – Execute a text completion request.  Accepts a
  prefix/suffix and returns the raw provider response.
- `edit/` – Perform a code editing operation.  Returns the provider
  response.
- `embed/` – Generate embeddings for a list of input texts.
- `rerank/` – Rerank a set of documents based on a query.
- `template-command/` – Render and execute a predefined template
  command.

### Retrieval and Search

Retrieval–related endpoints live in the root namespace for backwards
compatibility and under the `retrieval/` prefix:

- `search/` – `POST` endpoint to search for relevant code chunks.
- `context/` – `POST` endpoint to fetch surrounding context for a
  particular code chunk.
- `files/` – `POST` endpoint to search for files by path pattern.

The `retrieval/` namespace exposes the same functionality but uses
explicit defaults and improved error handling via the serializers in
`retrieval_views.py`.

### Repository and Project Management

Repository and project management endpoints are routed via
`repository_urls.py`.  These include CRUD operations for
repositories/projects, and are mounted both at the root (legacy) and
under `repositories/` for namespacing.  See `repository_views.py` for
details.

### Task Orchestration (v1)

The `/tasks/` endpoints provide the original task engine API.  They
allow clients to create a task, fetch task details, list execution
steps, retrieve artifacts and obtain results.  This API is relatively
minimal, returning simple JSON objects with limited validation.

### Enhanced Task API (v2)

An improved version of the task engine is available under the
`/v2/` prefix.  These endpoints live in `improved_task_views.py` and
provide richer responses, stricter input validation (via
`improved_serializers.py`) and more detailed metadata.  For example,
`/v2/tasks/<uuid>/result/` returns timing information and the best
candidate patch score when available.

The v2 API also exposes repository and project management endpoints
(`repository_list`, `repository_detail`, `project_list` and
`project_detail`) that mirror the v1 behaviour but return more
descriptive payloads.

## Duplicate and Legacy Views

Several parts of the API have both “simple” and “improved” variants:

- **Task API:** `task_views.py` contains the original v1 task endpoints.
  `improved_task_views.py` provides enhanced v2 endpoints under the
  `/v2/` prefix.
- **Retrieval API:** `retrieval_views_simple.py` contains a basic
  implementation of search and context endpoints.  `retrieval_views.py`
  introduces default values for optional parameters and explicit 400
  responses for validation errors.

Both sets of endpoints are kept for backward compatibility.  Future
development should target the improved versions, but the simple
variants should remain as thin wrappers until all clients have
migrated.

## Provider Architecture

The `services.router.RouterService` is responsible for choosing
which provider to use for a given request type.  Providers are
dynamically configured via environment variables:

| Provider key | Environment variables              | Default model            |
|--------------|------------------------------------|--------------------------|
| `local`      | `AI_LOCALAI_URL`, `AI_LOCALAI_MODEL`| `qwen2.5-coder-7b-instruct` |
| `fast`       | `AI_FAST_URL`, `AI_FAST_MODEL`      | `qwen2.5-coder-1.5b-instruct` |
| `strong`     | `AI_STRONG_URL`, `AI_STRONG_MODEL`  | `code-llama-34b-instruct` |

Each provider is implemented as a subclass of `BaseProvider`.  The
project currently includes:

- `LlamaCppProvider` – Connects to a llama.cpp or LocalAI server.
- `OllamaProvider` – Connects to a local Ollama daemon.
- `OpenAICompatibleProvider` – Connects to any OpenAI‑compatible API.

Only the `LlamaCppProvider` is used by default.  Others can be
enabled by environment variables or invoked directly.  To simplify
future integrations, response parsing logic has been extracted into
`providers/utils.py`.  The helper functions `parse_chat_response` and
`parse_text_completion_response` can extract the assistant message or
completion text from heterogeneous provider payloads.  Service layers
should defer to these helpers when they need the generated content
rather than the full provider response.

### Model Registry and Role Resolution

A complementary service, `ModelRegistryService` (added in Command 03),
exposes a high‑level registry of model assignments keyed by
**roles**.  Roles represent the purpose of a request (planning,
chatting, editing, etc.) rather than the underlying API call.  The
registry honours environment variable overrides of the form
`CODE_EDITOR_MODEL_ROLE_<ROLE>` and falls back to the router when no
override is present.  It combines provider capabilities with
model‑profile metadata (from `model_profiles.py`) to produce a
uniform view of context limits and supported features (chat,
completion, edit, infill, embeddings, rerank, streaming).  At the
moment the service is used by the `show_code_editor_model_registry`
management command and for documentation purposes.  Future
improvements may integrate it more deeply into the chat/completion
services to automatically select models based on role.

## Planned Upgrades

The following improvements are planned but have not yet been applied:

1. **Consolidate duplicate endpoints:** The simple v1 views will be
   refactored into thin wrappers around the improved v2
   implementations.  New functionality should only be added to the
   improved views.
2. **Provider agnosticism:** Service layers will consume the
   standardized parsing helpers in `providers/utils.py` so that
   switching providers does not require custom response handling.
3. **Extensible provider registry:** Future provider types (e.g.
   `DeepSeekProvider`, `StarCoderProvider`) can be added to the
   `providers` package.  As long as they implement the `BaseProvider`
   interface and return OpenAI‑compatible payloads, they will work
   seamlessly.
4. **Enhanced test coverage:** Additional unit tests have been added
   for `RouterService` initialization and response parsing.  When
   Django is available, integration tests should be expanded to cover
   the improved APIs and new providers.

Keeping backwards compatibility remains a guiding principle.  All
changes should preserve existing URL patterns, serializer names,
model migrations and service method signatures unless explicitly
versioned.