# Deployment & Integration Guide for `code_editor`

This document explains how to install, configure and test the
`code_editor` Django app as part of an existing project.  The
module provides a plug‑and‑play code generation and refactoring
engine with configurable model providers, retrieval/reranking,
embeddings, sandboxed validation and an optional autonomous agent
loop.  It is designed to run entirely on your own infrastructure
— either by connecting to local model servers (e.g.
llama.cpp/LocalAI, Ollama, vLLM/LM Studio) or to OpenAI‑compatible
APIs.  Advanced features such as embeddings and rerank are
optional and require additional dependencies (e.g. pgvector).

## 1. Installation into an Existing Django Project

1. **Install dependencies** – ensure you have Python 3.11+ and
   Django 4.x installed.  Install the package dependencies from the
   root of your repository (this example assumes you have already
   unpacked the module into `code_editor/`):

   ```sh
   pip install -r code_editor/requirements.txt
   # If pgvector features are desired (for retrieval), install:
   pip install pgvector psycopg
   ```

2. **Add the app to `INSTALLED_APPS`** – in your project’s
   `settings.py`, append `"code_editor"` to `INSTALLED_APPS`:

   ```python
   INSTALLED_APPS = [
       # … your existing apps …
       "code_editor",
   ]
   ```

3. **Include the URLs** – in your project’s root `urls.py`, mount
   the code editor API under the desired prefix.  All endpoints are
   namespaced beneath `/api/code-editor/`:

   ```python
   from django.urls import include, path

   urlpatterns = [
       # … your other routes …
       path("api/code-editor/", include("code_editor.api.urls")),
   ]
   ```

4. **Run migrations** – create the necessary tables in your
   database:

   ```sh
   python manage.py makemigrations code_editor
   python manage.py migrate
   ```

   If you are using the retrieval features with vector search,
   ensure the pgvector extension is enabled on your PostgreSQL
   instance (`CREATE EXTENSION IF NOT EXISTS vector;`).  Without
   pgvector the retrieval service will fall back to a lexical search.

5. **Create an API key (optional)** – if you intend to secure the
   API using API keys, set `CODE_EDITOR_REQUIRE_API_KEY=true` and
   use the Django admin to create `CodeEditorApiKey` objects.  Each
   key defines a daily quota and requests‑per‑minute (RPM) limit.
   When API keys are disabled the module operates in single‑user
   mode.

## 2. Environment Variables

Configuration is performed entirely via environment variables.
Variables beginning with `CODE_EDITOR_` take precedence over legacy
`AI_*` variables.  The following list summarises the most
important settings; see comments in `services/config.py` and other
modules for exhaustive details.

### Provider Configuration

Providers connect the app to model back‑ends.  You can configure
multiple providers and the router will choose the appropriate one
based on the request type.  For each provider type, set the
corresponding base URL, model name and enabled flag.  Supported
provider prefixes are `LOCAL`, `FAST`, `STRONG`, `OPENAI_COMPATIBLE`,
`DEEPSEEK`, `OLLAMA` and `VLLM`.  The `VLLM` provider points at a
vLLM/LM Studio server running in OpenAI compatibility mode and accepts
the same configuration variables as the OpenAI compatible provider.

| Provider type | Example variables | Notes |
|---------------|------------------|-------|
| **llama.cpp / LocalAI** | `CODE_EDITOR_LOCAL_BASE_URL="http://localhost:8080"`, `CODE_EDITOR_LOCAL_MODEL="qwen2.5-coder-7b-instruct"`, `CODE_EDITOR_LOCAL_ENABLED=true` | Use this to point at a LocalAI or llama.cpp server.  The `FAST` and `STRONG` variants allow you to specify additional endpoints for faster or larger models. |
| **OpenAI‑compatible** | `CODE_EDITOR_OPENAI_COMPATIBLE_BASE_URL="https://api.openai.com/v1"`, `CODE_EDITOR_OPENAI_COMPATIBLE_MODEL="gpt-3.5-turbo"`, `CODE_EDITOR_OPENAI_COMPATIBLE_API_KEY="sk-..."`, `CODE_EDITOR_OPENAI_COMPATIBLE_ENABLED=true` | Connects to any server implementing the OpenAI API (e.g. OpenAI, vLLM, LocalAI configured in compat mode, LM Studio).  API keys and custom headers can be passed via `_API_KEY` and `_HEADERS`. |
| **DeepSeek** | `CODE_EDITOR_DEEPSEEK_BASE_URL`, `CODE_EDITOR_DEEPSEEK_MODEL` | DeepSeek uses the same API interface as OpenAI.  Enabled when a base URL is present. |
| **Ollama** | `CODE_EDITOR_OLLAMA_BASE_URL="http://localhost:11434"`, `CODE_EDITOR_OLLAMA_MODEL="qwen2.5-coder-7b-instruct"`, `CODE_EDITOR_OLLAMA_ENABLED=true` | Connects to a local Ollama daemon. |
| **vLLM** | `CODE_EDITOR_VLLM_BASE_URL="http://localhost:8000"`, `CODE_EDITOR_VLLM_MODEL="gpt-3.5-turbo"`, `CODE_EDITOR_VLLM_API_KEY`, `CODE_EDITOR_VLLM_ENABLED=true` | Connects to a vLLM or LM Studio server exposing the OpenAI API.  Accepts the same variables as the OpenAI‑compatible provider.  Leave the API key empty for unauthenticated servers. |

### Model Roles and Registry

The code editor organises model usage around **roles**.  A role
represents the purpose of a request rather than the underlying API
operation.  Roles currently defined include:

- **agent_plan** – used by the autonomous agent’s planning step.
- **chat** – general conversational exchanges.
- **edit** – editing existing code given an instruction.
- **apply** – applying a generated patch to the repository.
- **autocomplete** – completion of a code prefix (e.g. IntelliSense).
- **infill** – fill‑in‑the‑middle completions (prefix/suffix pairs).
- **embed** – generating embeddings for retrieval.
- **rerank** – reranking search results based on a query.
- **summarize** – summarising context or documents.
- **validate_explain** – generating validation explanations.

For each role you may specify an override using the environment variable
``CODE_EDITOR_MODEL_ROLE_<ROLE>`` (uppercase).  The value may be just
a model name (e.g. ``phi-3-coder``) in which case the router will
choose a suitable provider, or a ``provider:model`` pair (e.g.
``ollama:qwen2.5-coder-7b-instruct``) to pin both the provider and
model.  When no override is provided the router selects the first
configured provider that supports the required capability for the role
(e.g. chat, completion, edit, infill).  This mechanism allows you to
assign different models to planning, chat and editing without changing
application code.

To introspect the resolved mapping between roles, providers and
models, run the management command:

```sh
python manage.py show_code_editor_model_registry
```

which prints a table of roles, resolved providers, models and
capabilities.  This command does not make any external API calls and
is safe to run in any environment.

If a provider’s `*_ENABLED` variable is unset, the system will
infer enablement from the presence of a base URL.  Legacy
`AI_LOCALAI_URL`, `AI_FAST_URL`, `AI_STRONG_URL` variables are also
supported for backwards compatibility.  The router examines all
configured providers and selects one that supports the requested
capability (chat, completion, edit, infill, embeddings or rerank).

### Embeddings & Rerank

Embeddings and rerank are optional features used by the retrieval
service.  They can be toggled independently.  When disabled, the
retrieval service performs lexical search only.

| Variable | Description | Default |
|---------|-------------|---------|
| `CODE_EDITOR_EMBEDDINGS_ENABLED` | Enable embeddings globally.  If unset, falls back to `AI_ENABLE_EMBED`. | `false` |
| `CODE_EDITOR_EMBEDDINGS_PROVIDER` | Provider key to use for embeddings (e.g. `openai_compatible`, `ollama`).  If unset, inherits from `*_BASE_URL`. | – |
| `CODE_EDITOR_EMBEDDINGS_BASE_URL` | Override the embeddings endpoint. | – |
| `CODE_EDITOR_EMBEDDINGS_MODEL` | Default embeddings model. | – |
| `CODE_EDITOR_EMBEDDINGS_BATCH_SIZE` | Number of texts to embed per request. | `50` |
| `CODE_EDITOR_RERANK_ENABLED` | Enable the rerank service.  Falls back to `AI_ENABLE_RERANK`. | `false` |
| `CODE_EDITOR_RERANK_PROVIDER`, `CODE_EDITOR_RERANK_BASE_URL`, `CODE_EDITOR_RERANK_MODEL`, `CODE_EDITOR_RERANK_TOP_K` | Provider configuration for reranking tasks. | – |

### Tokenisation & Context Limits

The module estimates token counts to enforce context windows and
output lengths.  By default it uses a simple heuristic (≈4
characters per token).  You can choose a more accurate backend and
set global limits:

| Variable | Description | Default |
|---------|-------------|---------|
| `CODE_EDITOR_TOKENIZER_BACKEND` | Tokenizer backend: `approximate` (heuristic), `tiktoken` or `sentencepiece`. | `approximate` |
| `CODE_EDITOR_SENTENCEPIECE_MODEL` | Path to a SentencePiece model when using the `sentencepiece` backend. | – |
| `CODE_EDITOR_MAX_CONTEXT_TOKENS` | Override the maximum input context (in tokens) for all models. | model‑specific |
| `CODE_EDITOR_DEFAULT_MAX_OUTPUT_TOKENS` | Override the default output length (in tokens) when the client does not specify a maximum. | model‑specific |

### Sandbox & Validation

The bug‑repair workflow executes unit tests and validation commands
in a restricted environment.  Use the following variables to tune
the sandbox:

| Variable | Description | Default |
|---------|-------------|---------|
| `CODE_EDITOR_SANDBOX_ENABLED` | Enable the sandbox runner.  When `false` the system will execute commands directly (not recommended in production). | `true` |
| `CODE_EDITOR_ALLOWED_TEST_COMMANDS` | Comma‑separated list of allowed commands (without arguments).  Only the first word of the command is matched. | `python` |
| `CODE_EDITOR_COMMAND_TIMEOUT_SECONDS` | Maximum time (in seconds) a command may run.  Exceeded commands are terminated and marked as timeout. | `300` |
| `CODE_EDITOR_MAX_COMMAND_OUTPUT_CHARS` | Maximum number of characters captured from stdout/stderr.  Excess output is truncated. | `10000` |
| `CODE_EDITOR_ENV_ALLOWLIST` | Additional environment variables (comma separated) that may be passed through to child processes.  By default only variables starting with `CODE_EDITOR_` are propagated. | – |

### API Keys, Quotas & Logging

To secure your deployment and track usage, the module supports
optional API key authentication and quota enforcement.  API keys are
stored in the `CodeEditorApiKey` model, and each has a daily quota
and a requests‑per‑minute limit.

| Variable | Description | Default |
|---------|-------------|---------|
| `CODE_EDITOR_REQUIRE_API_KEY` | Require a valid API key on all generative endpoints.  When disabled, the API runs in single‑user mode. | `false` |
| `CODE_EDITOR_DEFAULT_DAILY_QUOTA` | Default daily request quota assigned when a new API key is created. | `10000` |
| `CODE_EDITOR_DEFAULT_RPM_LIMIT` | Default requests per minute assigned to new API keys. | `60` |
| `CODE_EDITOR_LOG_PROMPTS` | When `true`, full prompts and code are stored in the request log.  When `false` (recommended), the log only records provider, model, latency, token counts and sanitized error messages. | `false` |

### Task Execution & Agent Loop

Several environment variables control the autonomous agent used for
bug repair tasks and the storage location for task artefacts:

| Variable | Description | Default |
|---------|-------------|---------|
| `CODE_EDITOR_TASK_STORAGE_ROOT` | Directory where task workspaces and artefacts are stored. | `/tmp/code_editor_tasks` |
| `CODE_EDITOR_TASK_USE_CELERY` | When `true`, the agent runs in a Celery task instead of synchronously in the HTTP request. | `false` |
| `CODE_EDITOR_AGENT_MAX_ITERATIONS` | Maximum planner iterations in the agent loop. | `3` |
| `CODE_EDITOR_AGENT_MAX_REPAIR_ATTEMPTS` | Maximum repair attempts per step. | `2` |
| `CODE_EDITOR_AGENT_AUTO_APPLY_PATCHES` | Automatically apply successful patches to the repository. | `false` |
| `CODE_EDITOR_AGENT_DEFAULT_TEST_TIMEOUT_SECONDS` | Timeout for each test run executed by the agent. | `120` |
| `CODE_EDITOR_AGENT_SYNC_EXECUTION_ENABLED` | Enable synchronous (in‑request) agent execution. | `true` |

### Miscellaneous

Additional variables you may encounter:

| Variable | Description | Default |
|---------|-------------|---------|
| `CODE_EDITOR_RUN_LIVE_EVALS` | When `true`, the evaluation harness uses real providers instead of the stub.  Only enable during manual benchmarking. | `false` |
| `AI_PROVIDER_TIMEOUT` | Global timeout (seconds) for provider HTTP requests. | `30` |
| `AI_PROVIDER_MAX_RETRIES` or `AI_PROVIDER_RETRIES` | Number of retries for provider requests. | `3` |
| `CODE_EDITOR_PROVIDER_TIMEOUT` | Global timeout (seconds) for provider HTTP requests.  Overrides `AI_PROVIDER_TIMEOUT` when set. | `30` |
| `CODE_EDITOR_PROVIDER_MAX_RETRIES` | Number of retries for provider requests.  Overrides `AI_PROVIDER_MAX_RETRIES`/`AI_PROVIDER_RETRIES` when set. | `3` |

## 3. API Endpoint Reference

All endpoints reside under the `/api/code-editor/` prefix.  The API
is versionless; incompatible changes are introduced via new
resource names rather than path parameters.  This section summarises
the most commonly used endpoints.  Refer to the `IMPLEMENTATION_NOTES.md`
file for developer‑oriented details.

### Health & Discovery

| Method/Path | Description |
|-------------|-------------|
| **GET `/health/`** | Returns server status, timestamp, version and a summary of configured providers.  The provider entries include provider name, type, redacted base URL, default model, health status and supported capabilities. |
| **GET `/providers/`** | Lists all configured providers with their capabilities, redacted base URLs, default models, context limits and health status.  Useful for building UI drop‑downs. |
| **GET `/models/`** | Lists all models available across enabled providers.  Each entry contains the model identifier, provider key, context window tokens, model family (if known) and capabilities (chat, completion, edit, infill, embeddings, rerank, streaming). |

### Chat & Completion

| Method/Path | Description |
|-------------|-------------|
| **POST `/chat/`** | Perform a chat conversation.  Body contains a list of messages (role: `system`, `user` or `assistant`) and optional `temperature`, `max_tokens`, `stream` flags and per‑request `provider`/`model` overrides.  Returns the assistant’s message or a streaming chunk sequence. |
| **POST `/completion/`** | Execute a text completion.  Body includes a `prompt`, optional `suffix` (for fill‑in‑the‑middle), `temperature`, `max_tokens`, `stream`, and optional provider/model overrides.  Returns the generated text or streamed chunks. |
| **POST `/edit/`** | Apply a code edit operation.  Body includes an input `document` (string), optional instructions, and provider/model overrides.  Returns the edited document. |
| **POST `/infill/`** | Complete a missing portion of code between a prefix and a suffix.  Body includes `prefix`, `suffix`, optional `max_tokens` and provider/model overrides.  Returns the inserted text. |

### Embeddings & Rerank

| Method/Path | Description |
|-------------|-------------|
| **POST `/embeddings/`** | Generate embeddings for a list of texts.  Request body includes an array of `texts`, optional `model` and `provider` fields.  Requires embeddings to be enabled via environment variables. |
| **POST `/rerank/`** | Rerank a list of documents given a query.  Body contains the `query`, an array of `documents`, optional `model` and `provider` overrides.  Returns documents ordered by relevance.  Requires rerank to be enabled. |

### Retrieval & Repository Management

Retrieval endpoints exist both at the root (for backwards
compatibility) and under a `retrieval/` prefix.  The latter
provides improved defaults and error handling.

| Method/Path | Description |
|-------------|-------------|
| **POST `/search/`** or **POST `/retrieval/search/`** | Search for relevant code chunks using vector similarity (when embeddings are enabled) or lexical fallback.  Filters allow limiting by repository, file path, language or chunk type.  Returns snippets with metadata and similarity scores. |
| **POST `/context/`** or **POST `/retrieval/context/`** | Given a `chunk_id`, fetch surrounding lines of code to provide context.  Supports specifying the number of lines before and after. |
| **POST `/files/`** or **POST `/retrieval/files/`** | Search for files by wildcard path patterns and optional repository/language filters. |
| **CRUD under `/repositories/`** | Endpoints to create, list, retrieve, update and delete repositories and projects.  These correspond to models in `repository_views.py` and are namespaced under both `/repositories/` and legacy root paths. |

### Tasks & Autonomous Bug Repair

The task API orchestrates multi‑step bug fixing workflows.  There
are two versions: v1 (original) and v2 (enhanced).  In most cases
you should use the v2 endpoints under `/v2/tasks/`.

| Method/Path | Description |
|-------------|-------------|
| **POST `/tasks/`** | Create a new bug repair task (v1).  Body includes repository URL, failing test command and optional parameters.  Returns a `task_id`. |
| **GET `/tasks/<id>/`** | Retrieve task details and current status. |
| **GET `/tasks/<id>/steps/`** | List execution steps of a task. |
| **GET `/tasks/<id>/artifacts/`** | List artifacts generated during task execution. |
| **GET `/tasks/<id>/result/`** (v2) | Retrieve the final patch and associated metadata once the task completes. |
| **POST `/v2/tasks/`** | Create a v2 task with improved validation and response formats.  Additional endpoints (`/v2/tasks/<id>/steps/`, `/result/`) mirror those above. |

### Evaluation Harness

The `code_editor.evals` package provides a lightweight benchmarking
harness.  A Django management command `run_code_editor_evals` runs
a suite of deterministic tasks.  By default it uses a stub
provider so that CI results are reproducible.  To benchmark against
a real model, set `CODE_EDITOR_RUN_LIVE_EVALS=true`.  The command
prints pass/fail status, provider/model, latency and test counts.

## 4. Enabling & Disabling Features

The table below summarises how to enable or disable major features:

| Feature | How to enable | How to disable |
|--------|---------------|----------------|
| **Embeddings** | Set `CODE_EDITOR_EMBEDDINGS_ENABLED=true` and configure a provider. | Remove or set `false`; retrieval falls back to lexical search. |
| **Rerank** | Set `CODE_EDITOR_RERANK_ENABLED=true` and configure provider/model. | Remove or set `false`; retrieval returns initial vector or lexical results. |
| **Streaming responses** | Include `"stream": true` in chat or completion requests. | Omit the flag or set `false`. |
| **Sandboxed test execution** | Ensure `CODE_EDITOR_SANDBOX_ENABLED=true`; optionally restrict `CODE_EDITOR_ALLOWED_TEST_COMMANDS` and tune timeouts. | Set `false` to disable the sandbox (not recommended for untrusted input). |
| **Agent loop** | Accept default values or adjust `CODE_EDITOR_AGENT_MAX_ITERATIONS`, `CODE_EDITOR_AGENT_MAX_REPAIR_ATTEMPTS`, etc. | There is no global disable; avoid calling task endpoints or set strict quotas/timeouts. |
| **API key auth** | Set `CODE_EDITOR_REQUIRE_API_KEY=true` and create API keys. | Remove or set `false`; all requests are allowed. |
| **Prompt logging** | Set `CODE_EDITOR_LOG_PROMPTS=true` to store full prompts/code in `CodeEditorRequestLog`. | Leave unset/false to log only metadata (recommended). |

## 5. Manual Testing Checklist

To verify your installation, walk through the following steps after
configuring your providers and environment variables:

1. **Health check** – request `GET /api/code-editor/health/` to
   confirm that the server is up and that your provider is listed
   with a healthy status and expected capabilities.  If no
   providers appear, double‑check your environment variables.

2. **Provider listing** – call `GET /api/code-editor/providers/` to
   view all configured providers.  Verify that base URLs are
   redacted (secrets removed) and that the default model and
   capabilities are as expected.

3. **Model list** – call `GET /api/code-editor/models/` and ensure
   that the models you configured appear with the correct provider,
   context window and capabilities.  Unknown fields may be `null`
   when the model family or token limits cannot be inferred.

4. **Chat request** – send a sample conversation to
   `POST /api/code-editor/chat/` with a simple prompt (e.g.
   `[{"role": "user", "content": "hello"}]`).  Check that
   responses are returned from the expected provider/model.

5. **Completion request** – call `POST /api/code-editor/completion/`
   with a prompt and optional suffix.  Confirm that the API returns
   a completion.  Try the `stream` flag to test streaming behaviour.

6. **Infill request** – send a prefix and suffix to
   `POST /api/code-editor/infill/`.  Verify that the returned text
   fills the gap appropriately.  If the provider does not support
   infill, the router should fall back to completion or return an
   error indicating lack of support.

7. **Repository ingestion** – create a repository via `POST
   /api/code-editor/repositories/` with a `file://` URL pointing at
   a local folder.  Use the retrieval API to index files and
   confirm that files and code chunks appear in the database.

8. **Retrieval search** – call `POST /api/code-editor/retrieval/search/`
   with a query term.  When embeddings are enabled, results should
   be ordered by similarity; otherwise lexical ranking will be used.
   Test the fallback by disabling embeddings.

9. **Task plan generation** – create a bug repair task via
   `POST /api/code-editor/v2/tasks/` with a failing test command.
   Poll `GET /api/code-editor/v2/tasks/<id>/result/` until the
   status is success or error.  Inspect the plan and steps.

10. **Patch proposal & sandboxed tests** – follow the v2 task
   workflow: after plan generation the agent will propose patches
   and run tests via the sandbox runner.  Review artifacts via
   `GET /api/code-editor/v2/tasks/<id>/artifacts/` and confirm that
   commands are truncated or rejected according to your sandbox
   settings.  Ensure that environment variables and test commands
   cannot escape the workspace.

## 6. Troubleshooting

Here are some common issues and remedies when deploying `code_editor`:

* **No provider available** – `RouterService` raises an exception if
  no provider is configured or if none supports the requested
  capability.  Check that at least one provider’s `*_BASE_URL`
  variable is set and that `*_ENABLED` is `true`.  For chat you
  need a provider that implements chat; for completions a
  provider must support text completion.

* **Model server timeout** – the provider times out or returns an
  error.  Adjust `AI_PROVIDER_TIMEOUT` and `AI_PROVIDER_MAX_RETRIES`
  or inspect network connectivity.  For self‑hosted servers ensure
  that the service is reachable at the configured base URL.

* **Embeddings disabled** – attempting to use embeddings or rerank
  without enabling them yields an exception.  Set
  `CODE_EDITOR_EMBEDDINGS_ENABLED=true` and/or
  `CODE_EDITOR_RERANK_ENABLED=true`, and configure the corresponding
  provider and model.

* **pgvector unavailable** – vector search requires the pgvector
  extension.  If your Postgres database does not include pgvector,
  install the extension or rely on lexical search.  The retrieval
  service automatically falls back to lexical search when vectors
  are absent.

* **Tokenizer unavailable** – using the `tiktoken` or
  `sentencepiece` backends without installing the respective
  packages or models will silently fall back to the approximate
  heuristic.  To improve accuracy, install `tiktoken` via pip or
  provide a SentencePiece model via `CODE_EDITOR_SENTENCEPIECE_MODEL`.

* **Sandbox command rejected** – the sandbox runner denies
  execution when the first word of the command is not in
  `CODE_EDITOR_ALLOWED_TEST_COMMANDS` or when the command tries
  to escape the workspace.  Modify the allowlist or run tests
  directly (not recommended) by setting `CODE_EDITOR_SANDBOX_ENABLED=false`.

* **Quota exceeded or rate limit hit** – requests return 429
  responses when the API key has exhausted its daily quota or RPM
  limit.  Increase `daily_quota` or `rpm_limit` on the key via the
  admin panel, or reduce your request rate.

* **Provider override validation** – if you supply an invalid
  `provider` or `model` override in a request body, the API
  returns a 400 response.  Confirm that the provider exists and
  supports the requested capability by consulting
  `/api/code-editor/providers/`.

## 9. Zero‑cost Architecture and Local Deployment

The code editor is designed to run entirely on your own hardware
without incurring per‑request API charges.  By configuring the
``local``, ``fast``, ``strong`` and ``ollama`` providers to point at
locally hosted model servers you can handle chat, edit and
autocomplete requests at zero cost.  You can also deploy a vLLM or
LM Studio server to expose OpenAI‑compatible endpoints on your own
infrastructure.  When multiple providers are enabled, the router
prioritises local providers first and falls back to hosted providers
only when necessary.  Embeddings and rerank services are similarly
pluggable: enable `CODE_EDITOR_EMBEDDINGS_ENABLED` and point
`CODE_EDITOR_EMBEDDINGS_BASE_URL` at your own embeddings service to
avoid external dependencies.

Default model assignments can be controlled via the model role
environment variables described above.  For example, to run planning
and normal chat on a local 7 B model while using a larger model for
edits you might set:

```env
CODE_EDITOR_MODEL_ROLE_AGENT_PLAN=ollama:qwen2.5-coder-7b-instruct
CODE_EDITOR_MODEL_ROLE_CHAT=ollama:qwen2.5-coder-7b-instruct
CODE_EDITOR_MODEL_ROLE_EDIT=fast:code-llama-34b-instruct
```

If a role has no override the router will choose the first enabled
provider that supports the required capability.  Use the management
command `show_code_editor_model_registry` to inspect the resolved
mappings for your deployment.

With these instructions and environment settings in place, you
should be able to integrate `code_editor` into your project and
iterate on its capabilities safely.  See
`code_editor/evals/README.md` for details on the evaluation
harness, and `IMPLEMENTATION_NOTES.md` for developer‑level
information about the public API surface.