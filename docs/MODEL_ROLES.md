# Model Roles and Routing

The backend associates higher‑level tasks with *roles*.  Roles are
resolved to specific providers and models via the `ModelRegistryService`.
Each role maps to a lower‑level *request type* (e.g. `chat`,
`completion`, `embed`) and may specify a capability requirement.  The
registry consults the `RouterService` to find a healthy provider that
advertises the required capability.

## Roles

| Role             | Request Type | Required Capability | Description |
|------------------|--------------|---------------------|-------------|
| `agent_plan`     | chat         | chat                | High‑level planning and reasoning |
| `chat`           | chat         | chat                | Conversational interactions |
| `edit`           | edit         | edit                | Code editing operations |
| `apply`          | edit         | edit                | Patch application (JSON/structured output preferred) |
| `autocomplete`   | completion   | completion          | Low‑latency single‑shot completions |
| `infill`         | infill       | infill              | Fill‑in‑the‑middle / suffix completions |
| `embed`          | embed        | embeddings          | Embedding generation |
| `rerank`         | rerank       | rerank              | Vector search reranking |
| `summarize`      | chat         | chat                | Summarisation of content |
| `validate_explain` | chat       | chat                | Explaining validation results |

Roles can be overridden via environment variables of the form
`CODE_EDITOR_MODEL_ROLE_<ROLE>=provider:model`.  When an override
specifies only a model, the registry selects the first provider that
advertises the required capability for that request type.

## Capability‑Driven Routing

Providers advertise their capabilities via `get_capabilities()`.  The
registry merges provider and model capabilities (from
`model_profiles.py`) to ensure the selected provider/model pair
supports the role.  If no provider satisfies the capability
requirement, the registry raises `ProviderNotAvailableException`.

## Suffix Completion and FIM

The `infill` role requires native suffix/FIM support.  When a
provider does not support suffix completion, the router falls back to
a prompt‑based infill strategy implemented by
`OpenAICompatibleProvider.infill_code()`.  Providers such as Ollama
advertise suffix completion via `supports_suffix_completion()` when
enabled.