"""
Utility functions for parsing provider responses into standardized formats.

These helpers centralize common logic for extracting the relevant content
from responses returned by different AI providers.  Many OpenAI‑compatible
providers (e.g. LocalAI, llama.cpp, Ollama) expose similar endpoints but
structure their responses slightly differently.  For example, OpenAI and
llama.cpp return a ``choices`` list containing a ``message`` with a
``content`` field for chat completions, whereas Ollama places the
assistant message directly under a top‑level ``message`` key.  Text
completion endpoints may return a plain ``text`` field instead.

By using these helper functions, service layers can remain agnostic
about provider‑specific response shapes and can uniformly extract the
assistant output.  These helpers do **not** alter the provider response
objects themselves; they simply return the extracted text.  Existing
behaviour is preserved for callers that wish to access the raw response.

This module currently exposes two public functions:

* ``parse_chat_response`` – Extracts the assistant message from a chat
  completion response.
* ``parse_text_completion_response`` – Extracts the completion text
  from a text completion response.

Additional parsing helpers can be added here as new provider types or
response formats emerge.  Keeping this logic in one place makes it
easier to support multiple providers without scattering fragile
conditionals throughout the codebase.
"""

from typing import Any, Dict, Optional


def _first_choice(response: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Return the first choice entry in a provider response, if present.

    Many providers return a top‑level ``choices`` list.  This helper
    safely retrieves the first element if it exists.

    :param response: Raw response dictionary from a provider
    :returns: The first choice dict or ``None`` if unavailable
    """
    choices = response.get("choices")
    if isinstance(choices, list) and choices:
        first = choices[0]
        if isinstance(first, dict):
            return first
    return None


def parse_chat_response(response: Dict[str, Any]) -> str:
    """Extract the assistant's reply from a chat completion response.

    This function attempts to handle common response shapes from
    OpenAI‑compatible APIs, llama.cpp and Ollama.  If no recognised
    structure is found, it falls back to ``str(response)``.

    :param response: Raw response dictionary returned by a provider
    :returns: The assistant's message content as a string
    """
    # OpenAI/llama.cpp style: response["choices"][0]["message"]["content"]
    first = _first_choice(response)
    if first:
        message = first.get("message")
        if isinstance(message, dict):
            content = message.get("content")
            if isinstance(content, str):
                return content
        # Some text completions include a ``text`` field on each choice
        text = first.get("text")
        if isinstance(text, str):
            return text

    # Ollama style: response["message"] = {"role": "assistant", "content": "..."}
    message = response.get("message")
    if isinstance(message, dict):
        content = message.get("content")
        if isinstance(content, str):
            return content

    # Some providers may return a top‑level ``content`` field
    content = response.get("content")
    if isinstance(content, str):
        return content

    # Fallback: return string representation to avoid raising errors
    return str(response)


def parse_text_completion_response(response: Dict[str, Any]) -> str:
    """Extract the completion text from a text completion response.

    Providers may embed the completion either in a ``text`` field on
    each choice or as a ``message`` with a ``content`` field.  This
    helper covers both cases.  If no recognised structure is found,
    ``str(response)`` is returned.

    :param response: Raw response dictionary returned by a provider
    :returns: The completion text as a string
    """
    first = _first_choice(response)
    if first:
        # Prefer explicit ``text`` field
        text = first.get("text")
        if isinstance(text, str):
            return text
        # Otherwise fall back to chat message content
        message = first.get("message")
        if isinstance(message, dict):
            content = message.get("content")
            if isinstance(content, str):
                return content

    # Some providers may return a top‑level ``text``
    text = response.get("text")
    if isinstance(text, str):
        return text

    # Or a top‑level ``message`` wrapper
    message = response.get("message")
    if isinstance(message, dict):
        content = message.get("content")
        if isinstance(content, str):
            return content

    return str(response)