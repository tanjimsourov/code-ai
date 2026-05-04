"""Streaming utilities for provider streaming responses.

This module defines a small ``StreamChunk`` dataclass used to
represent incremental pieces of content returned by providers when
streaming is enabled.  A chunk contains the text content emitted so
far, an optional event name, a flag indicating whether the stream
has finished, and the raw data associated with the chunk (useful
for debugging or custom handling).

Providers that implement streaming should yield instances of
``StreamChunk`` from their streaming methods.  Service layers can
consume these chunks and convert them into SSE or other formats
without needing to know provider‑specific details.
"""

from dataclasses import dataclass
from typing import Optional, Any


@dataclass
class StreamChunk:
    """A single chunk of streamed content from a provider.

    :param content: The text content produced by the provider for this chunk.
    :param event: Optional event name associated with the chunk (e.g. ``message``, ``delta``).
    :param done: Set to ``True`` when the provider signals that the stream has completed.
    :param raw: The raw data parsed from the provider (e.g. JSON object or string) for debugging.
    """

    content: str
    event: Optional[str] = None
    done: bool = False
    raw: Optional[Any] = None