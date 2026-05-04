# Provider Integration

This document describes the built‑in AI providers available in the code editor backend
and how their capabilities are exposed.

## BaseProvider

All providers inherit from `BaseProvider`, which exposes a consistent API
for chat completions, text completions, code edits, embeddings, reranking
and infill completions.  Each provider advertises its supported features via
the `get_capabilities()` method.  Capability flags include:

- `chat`: supports chat completions
- `completion`: supports plain text completions
- `edit`: supports code edits
- `embeddings`: supports embedding generation
- `rerank`: supports document reranking
- `streaming`: supports incremental streaming responses
- `infill`: supports fill‑in‑the‑middle (FIM) completions
- `json`: supports structured JSON responses
- `tools`: supports tool/function calling
- `fim`: alias of `infill`
- `suffix_completion`: indicates native suffix completion support

Subclasses override the `supports_*` methods to advertise their
features.

## OpenAICompatibleProvider

This provider talks to any API that exposes an OpenAI‑compatible HTTP
interface (including local proxies, vLLM, LM Studio and others).  It
supports chat, completion, code editing, embeddings, streaming and FIM.

Structured JSON and tool calling modes are enabled by default.  If the
underlying server does not support suffix completion, the provider
automatically falls back to a chat prompt.

## OllamaProvider

The Ollama provider calls a local Ollama server.  It supports chat and
text completions via `/api/chat` and `/api/generate`.  Streaming is
enabled by default; when `stream=True`, the provider yields
`StreamChunk` objects parsed from the server’s newline‑delimited JSON
stream.  Embeddings are supported via `/api/embed`.  Capabilities such
as JSON mode, tool calling and suffix completions can be enabled via
provider configuration.

If embeddings are disabled via configuration the provider raises a
`NotImplementedError` when attempting to generate embeddings.

## LlamaCppProvider

The llama.cpp provider targets the HTTP endpoints of a llama.cpp
server.  It currently supports chat, text completions and code edits
but does not implement streaming, embeddings, rerank, infill or tools.
These capabilities may be added in future releases.

## RerankProvider

The rerank provider (configured via `ConfigService.get_rerank_config()`)
implements document reranking for vector search.  If no rerank
provider is configured or healthy, the retrieval service falls back to
lexical ranking.