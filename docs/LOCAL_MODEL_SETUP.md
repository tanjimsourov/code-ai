# Local Model Setup

## Ollama

- Install Ollama and run daemon.
- Set:
  - `CODE_EDITOR_OLLAMA_ENABLED=true`
  - `CODE_EDITOR_OLLAMA_BASE_URL=http://localhost:11434`
  - `CODE_EDITOR_OLLAMA_MODEL=qwen2.5-coder:7b`

## llama.cpp (OpenAI-compatible server)

- Run llama.cpp server with OpenAI-compatible API.
- Set `CODE_EDITOR_LLAMA_CPP_*` variables.

## vLLM

- Run vLLM OpenAI-compatible API endpoint.
- Set `CODE_EDITOR_VLLM_*` variables.

## Generic OpenAI-compatible local endpoint

- Set `CODE_EDITOR_OPENAI_COMPATIBLE_*` variables.

## Suggested local coding models

- Qwen coder variants
- DeepSeek coder variants (if available locally)
