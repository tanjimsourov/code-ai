"""Stub provider for deterministic evaluation runs.

This provider implements the ``BaseProvider`` interface but does
not invoke any external services.  Instead it returns preconfigured
responses for specific inputs.  The evaluation harness uses the
``StubProvider`` to run sample benchmarks without requiring live
models or network access.  Responses are matched based on the
provided prompt, instruction, or prefix/suffix tuples.
"""

from typing import Dict, Any, List, Optional, Tuple, Union

from ..providers.base import BaseProvider


class StubProvider(BaseProvider):
    """A simple provider that returns canned responses for known inputs.

    Instances of this class are initialised with a mapping between
    input keys and response payloads.  Keys can be strings (for
    matching against chat or completion prompts), two‑element tuples
    of ``(instruction, code)`` for matching edit requests, or
    three‑element tuples of ``(prefix, suffix)`` for matching
    infill requests.  If an input does not match any known key,
    the provider returns an empty completion.  The returned
    payloads follow the OpenAI API format used throughout the
    codebase: a dictionary with a ``choices`` list containing a
    single element whose ``text`` field holds the completion.
    """

    def __init__(self, responses: Optional[Dict[Any, Dict[str, Any]]] = None) -> None:
        # Use a dummy configuration; the router assigns provider type
        super().__init__('stub', {'model': 'stub-model'})
        # Store responses mapping; default to empty
        self.responses: Dict[Any, Dict[str, Any]] = responses or {}

    # The following provider methods inspect the incoming request and
    # return the first matching canned response.  If no entry is
    # found, an empty text completion is returned.  Responses should
    # follow the OpenAI API format used by other providers.

    def chat_completion(
        self,
        messages: List[Dict[str, str]],
        model: str,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        stream: bool = False,
        **kwargs
    ) -> Dict[str, Any]:
        # Concatenate message contents for matching
        prompt = ''.join(m.get('content', '') for m in messages)
        return self._lookup_response(prompt)

    def text_completion(
        self,
        prompt: str,
        model: str,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        stream: bool = False,
        **kwargs
    ) -> Dict[str, Any]:
        return self._lookup_response(prompt)

    def edit_code(
        self,
        instruction: str,
        code: str,
        model: str,
        temperature: float = 0.3,
        max_tokens: Optional[int] = None,
        **kwargs
    ) -> Dict[str, Any]:
        # For edit requests, match on a tuple of (instruction, code)
        key = (instruction, code)
        return self.responses.get(key, {'choices': [{'text': code}]})

    def infill_code(
        self,
        prefix: str,
        suffix: str,
        model: str,
        language: Optional[str] = None,
        filename: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        stream: bool = False,
        **kwargs
    ) -> Dict[str, Any]:
        # For infill requests, match on a tuple of (prefix, suffix)
        key = (prefix, suffix)
        return self.responses.get(key, {'choices': [{'text': ''}]})

    def get_models(self) -> List[Dict[str, Any]]:
        # The stub provider exposes a single dummy model for testing
        return [
            {
                'id': 'stub-model',
                'object': 'model',
                'created': None,
                'owned_by': 'stub',
                'parent': None,
            }
        ]

    def _lookup_response(self, prompt: str) -> Dict[str, Any]:
        # Match by substring against any string keys in the mapping
        for key, resp in self.responses.items():
            if isinstance(key, str) and key in prompt:
                return resp
        # Default empty completion
        return {'choices': [{'text': ''}]}