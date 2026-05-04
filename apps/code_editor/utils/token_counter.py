"""
Token counting utility for the code editor.

This module provides a ``TokenCounter`` class that estimates the
number of tokens consumed by a given text.  When optional tokenizer
libraries are available (e.g. `tiktoken` or `sentencepiece`), they
will be used to provide more accurate counts.  Otherwise, a simple
approximation based on character count is employed.  The approximate
rule assumes that one token corresponds to roughly four characters,
which is a common heuristic for English text.

The backend used for tokenization can be selected via the
``CODE_EDITOR_TOKENIZER_BACKEND`` environment variable.  Supported
values:

* ``tiktoken`` – Use OpenAI's tiktoken library if installed.  Will
  fall back silently if unavailable.
* ``sentencepiece`` – Use SentencePiece if installed.  Will fall
  back silently if unavailable.
* ``approximate`` (default) – Use the heuristic approximation.

Example usage::

    counter = TokenCounter()
    num_tokens = counter.count_tokens("hello world")

The counter is deterministic and does not perform any external API
calls.  It is safe to use in contexts where external dependencies
may be missing.
"""

from __future__ import annotations

import os
from typing import Optional


class TokenCounter:
    """Utility class for estimating token counts."""

    def __init__(self, backend: Optional[str] = None) -> None:
        # Determine backend from argument or environment
        self.backend = backend or os.getenv('CODE_EDITOR_TOKENIZER_BACKEND', 'approximate')
        self._encoder = None
        # Attempt to load the requested backend
        if self.backend == 'tiktoken':
            try:
                import tiktoken  # type: ignore
                # Use cl100k_base encoding which closely mirrors GPT-4/3.5 tokenization
                self._encoder = tiktoken.get_encoding('cl100k_base')
            except Exception:
                self.backend = 'approximate'
        elif self.backend == 'sentencepiece':
            try:
                import sentencepiece as spm  # type: ignore
                # Attempt to load a basic English model; if unavailable, fallback
                # The SentencePiece library requires a model file.  If none is
                # provided, we cannot use it, so we fall back.
                # Users can set a path in ``CODE_EDITOR_SENTENCEPIECE_MODEL`` if
                # desired.
                model_path = os.getenv('CODE_EDITOR_SENTENCEPIECE_MODEL')
                if model_path and os.path.exists(model_path):
                    self._sp = spm.SentencePieceProcessor(model_file=model_path)
                else:
                    self.backend = 'approximate'
            except Exception:
                self.backend = 'approximate'

    def count_tokens(self, text: str) -> int:
        """
        Estimate the number of tokens in ``text``.

        If a supported tokenizer backend is available, it is used to
        compute an exact or near-exact token count.  Otherwise, a
        simple heuristic divides the character length by four.

        :param text: Input string
        :returns: Estimated token count (at least 1 for non-empty input)
        """
        if not text:
            return 0
        try:
            if self.backend == 'tiktoken' and self._encoder is not None:
                return len(self._encoder.encode(text))
            elif self.backend == 'sentencepiece' and hasattr(self, '_sp'):
                return len(self._sp.encode(text))
        except Exception:
            # Fall through to approximate below
            pass
        # Approximate token count: assume 4 characters per token
        # Ensure at least one token for non-empty input
        approx = max(1, (len(text) + 3) // 4)
        return approx


def count_tokens(text: str | list[str], backend: Optional[str] = None) -> int:
    """
    Convenience function to count tokens for a string or list of strings.
    :param text: Single string or list of strings
    :param backend: Optional backend override
    :returns: Total estimated token count
    """
    counter = TokenCounter(backend=backend)
    if isinstance(text, str):
        return counter.count_tokens(text)
    total = 0
    for t in text:
        total += counter.count_tokens(t)
    return total