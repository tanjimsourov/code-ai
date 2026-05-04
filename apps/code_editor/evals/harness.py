"""Evaluation harness for measuring code generation quality.

This module defines a small suite of deterministic benchmarks for
assessing providers.  Each task in ``EVAL_TASKS`` includes a prompt
and a set of test cases.  The ``run_evaluations`` function executes
each task using either a stub provider (for CI) or a live provider
when ``CODE_EDITOR_RUN_LIVE_EVALS=true`` is set in the environment.

The harness returns a list of result dictionaries; each result
includes pass/fail status, provider/model identifiers, latency in
milliseconds, number of attempts and the number of tests passed.  A
corresponding Django management command is provided in
``management/commands/run_code_editor_evals.py``.
"""

from __future__ import annotations

import os
import time
import types
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Tuple, Union

from .stub_provider import StubProvider


@dataclass
class EvaluationResult:
    """Container for a single evaluation outcome."""

    task: str
    provider: str
    model: str
    passed: bool
    latency_ms: int
    repair_attempts: int
    tests_passed: int


def _extract_function_name(prompt: str) -> str:
    """Extract a function name from a Python function definition.

    This helper looks for the pattern ``def NAME(" and returns the
    extracted name.  It is intentionally simple and assumes that
    prompts are well‑formed.  Returns an empty string if no name
    could be parsed.
    """
    try:
        # Find 'def ' and extract until '(' occurs
        idx = prompt.index('def ')
        after_def = prompt[idx + 4:]
        name = after_def.split('(')[0].strip()
        return name
    except Exception:
        return ''


def _run_function_tests(code: str, func_name: str, tests: List[Tuple[Tuple[Any, ...], Any]]) -> Tuple[bool, int]:
    """Execute Python code and run provided tests against a function.

    Returns a tuple ``(passed, count)`` where ``passed`` indicates
    whether all test cases succeeded and ``count`` is the number of
    tests executed.  Any exception during execution or assertion
    failure will mark the evaluation as failed.
    """
    passed = True
    count = 0
    # Prepare an isolated namespace for execution
    local_env: Dict[str, Any] = {}
    try:
        exec(code, local_env)
        func = local_env.get(func_name)
        if not callable(func):
            return False, 0
        for args, expected in tests:
            count += 1
            result = func(*args)
            if result != expected:
                passed = False
    except Exception:
        return False, count
    return passed, count


def _run_call_tests(code: str, func_name: str, tests: List[Tuple[Tuple[Any, ...], Any]]) -> Tuple[bool, int]:
    """Execute Python code and run tests that call a top‑level function.

    This helper is used for tasks where the top level function to call
    is known (e.g. ``call_greet``) and multiple functions may be
    present in the code.  It executes the code and invokes the
    function named ``func_name`` with the provided arguments.
    """
    passed = True
    count = 0
    local_env: Dict[str, Any] = {}
    try:
        exec(code, local_env)
        func = local_env.get(func_name)
        if not callable(func):
            return False, 0
        for args, expected in tests:
            count += 1
            result = func(*args)
            if result != expected:
                passed = False
    except Exception:
        return False, count
    return passed, count


def _create_stub_provider() -> StubProvider:
    """Instantiate a stub provider with canned responses for benchmark tasks."""
    # Predefine responses for each evaluation task.  Keys may be
    # complete prompts or tuples depending on the request type.
    responses: Dict[Any, Dict[str, Any]] = {}
    # HumanEval style addition task: a simple completion
    prompt_add = (
        "def add(a: int, b: int) -> int:\n"
        "    \"\"\"Return sum of a and b\"\"\"\n"
        "    "
    )
    responses[prompt_add] = {
        'choices': [{'text': 'return a + b\n'}]
    }
    # Bug fix task: handle division by zero
    instruction_div = 'Fix the bug: handle division by zero by returning None when b is zero.'
    code_div = 'def divide(a, b):\n    return a / b\n'
    patched_div = (
        'def divide(a, b):\n'
        '    if b == 0:\n'
        '        return None\n'
        '    return a / b\n'
    )
    responses[(instruction_div, code_div)] = {
        'choices': [{'text': patched_div}]
    }
    # Refactor task: rename greet to greet_user
    instruction_greet = 'Rename function greet to greet_user.'
    code_greet = (
        'def greet(name: str) -> str:\n'
        '    return f"Hello, {name}!"\n\n'
        'def call_greet():\n'
        '    return greet("Alice")\n'
    )
    patched_greet = (
        'def greet_user(name: str) -> str:\n'
        '    return f"Hello, {name}!"\n\n'
        'def call_greet():\n'
        '    return greet_user("Alice")\n'
    )
    responses[(instruction_greet, code_greet)] = {
        'choices': [{'text': patched_greet}]
    }
    # Infill task: multiply function body
    prefix_mul = 'def multiply(a, b):\n    return'
    suffix_mul = '\n'
    responses[(prefix_mul, suffix_mul)] = {
        'choices': [{'text': ' a * b'}]
    }
    return StubProvider(responses=responses)


def get_tasks() -> List[Dict[str, Any]]:
    """Return the list of evaluation tasks.

    Each task dictionary contains a name, type and associated
    parameters.  Tests are represented as a list of argument/result
    tuples.  The harness uses this data to run the appropriate
    provider method and assess correctness.
    """
    return [
        {
            'name': 'human_eval_add',
            'type': 'completion',
            'prompt': (
                'def add(a: int, b: int) -> int:\n'
                '    \"\"\"Return sum of a and b\"\"\"\n'
                '    '
            ),
            'function_name': 'add',
            'tests': [((1, 2), 3), ((5, -1), 4)],
        },
        {
            'name': 'bug_fix_divide',
            'type': 'edit',
            'instruction': 'Fix the bug: handle division by zero by returning None when b is zero.',
            'code': 'def divide(a, b):\n    return a / b\n',
            'function_name': 'divide',
            'tests': [((6, 3), 2), ((5, 0), None)],
        },
        {
            'name': 'refactor_greet',
            'type': 'edit',
            'instruction': 'Rename function greet to greet_user.',
            'code': (
                'def greet(name: str) -> str:\n'
                '    return f"Hello, {name}!"\n\n'
                'def call_greet():\n'
                '    return greet("Alice")\n'
            ),
            'function_name': 'call_greet',
            'tests': [((), 'Hello, Alice!')],
        },
        {
            'name': 'infill_multiply',
            'type': 'infill',
            'prefix': 'def multiply(a, b):\n    return',
            'suffix': '\n',
            'function_name': 'multiply',
            'tests': [((2, 3), 6), ((5, -2), -10)],
        },
    ]


def run_evaluations(provider: Optional[Any] = None) -> List[EvaluationResult]:
    """Run all evaluation tasks using the specified provider.

    If no provider is supplied, a stub provider is used when the
    ``CODE_EDITOR_RUN_LIVE_EVALS`` environment variable is unset or
    false.  When the variable is set to ``true``, the first
    available provider supporting completion is selected via the
    router.  This design allows CI tests to run deterministically
    while still enabling manual benchmarking against real models.

    :param provider: Optional provider instance to use for all tasks
    :returns: List of ``EvaluationResult`` objects summarising the runs
    """
    # Determine provider if not explicitly supplied
    if provider is None:
        use_live = os.getenv('CODE_EDITOR_RUN_LIVE_EVALS', '').lower() == 'true'
        if use_live:
            # Defer import to avoid Django dependency at module load
            try:
                from ..services.router import RouterService  # type: ignore
                router = RouterService()
                # Try to get a provider that supports completion
                provider = router.get_provider('complete') or router.get_provider('chat')
                if provider is None:
                    # Fallback to stub if no live provider
                    provider = _create_stub_provider()
            except Exception:
                provider = _create_stub_provider()
        else:
            provider = _create_stub_provider()

    results: List[EvaluationResult] = []
    tasks = get_tasks()
    for task in tasks:
        name = task['name']
        # Determine model name; use provider configuration if available
        model_name = ''
        try:
            model_name = provider.config.get('model')  # type: ignore[attr-defined]
        except Exception:
            model_name = ''
        start_time = time.time()
        passed = False
        tests_passed = 0
        repair_attempts = 1
        try:
            if task['type'] == 'completion':
                # Text completion tasks
                prompt: str = task['prompt']
                # Perform text completion
                resp = provider.text_completion(prompt, model_name)
                # Extract text from provider response
                text = ''
                try:
                    text = resp.get('choices', [{}])[0].get('text', '')
                except Exception:
                    text = ''
                code = prompt + text
                fn_name = task.get('function_name') or _extract_function_name(prompt)
                passed, tests_passed = _run_function_tests(code, fn_name, task['tests'])
            elif task['type'] == 'edit':
                instruction = task['instruction']
                code = task['code']
                resp = provider.edit_code(instruction, code, model_name)
                new_code = ''
                try:
                    new_code = resp.get('choices', [{}])[0].get('text', '')
                except Exception:
                    new_code = code
                fn_name = task['function_name']
                passed, tests_passed = _run_function_tests(new_code, fn_name, task['tests'])
            elif task['type'] == 'infill':
                prefix = task['prefix']
                suffix = task['suffix']
                resp = provider.infill_code(prefix, suffix, model_name)
                completion = ''
                try:
                    completion = resp.get('choices', [{}])[0].get('text', '')
                except Exception:
                    completion = ''
                full_code = prefix + completion + suffix
                fn_name = task['function_name']
                passed, tests_passed = _run_function_tests(full_code, fn_name, task['tests'])
            else:
                # Unknown task type -> fail
                passed = False
                tests_passed = 0
        except Exception:
            passed = False
        latency_ms = int((time.time() - start_time) * 1000)
        results.append(
            EvaluationResult(
                task=name,
                provider=getattr(provider, 'name', 'unknown'),
                model=model_name or '',
                passed=passed,
                latency_ms=latency_ms,
                repair_attempts=repair_attempts,
                tests_passed=tests_passed,
            )
        )
    return results