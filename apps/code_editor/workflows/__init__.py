"""Workflow coordination package for code_editor.

The ``workflows`` package contains the autonomous task engine used to
coordinate long‑running coding tasks such as bug fixes and feature
implementations.  See :mod:`.task_executor` for the primary entry point.
"""

from .task_executor import TaskExecutor  # noqa: F401