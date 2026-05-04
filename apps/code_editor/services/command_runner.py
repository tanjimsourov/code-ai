"""
Sandboxed command execution for the code_editor application.

This module provides a small wrapper around ``subprocess.run`` that enforces
safe defaults when executing arbitrary commands.  The runner will restrict
which commands may be invoked, enforce a working directory rooted in the
repository workspace, apply a timeout and truncate excessive output.  It
reads its configuration from environment variables and falls back to
reasonable defaults when unspecified.

Configuration environment variables:

* ``CODE_EDITOR_SANDBOX_ENABLED`` – When truthy, the runner will enforce
  command allow‑listing and other safety checks.  Defaults to ``True``.
* ``CODE_EDITOR_ALLOWED_TEST_COMMANDS`` – Comma separated list of the first
  token of commands that are permitted.  Defaults to ``python,pytest,unittest,npm,yarn,make,node,tsc``.
* ``CODE_EDITOR_COMMAND_TIMEOUT_SECONDS`` – Maximum number of seconds a
  command is allowed to run.  Defaults to 300 seconds (5 minutes).
* ``CODE_EDITOR_COMMAND_MAX_OUTPUT_BYTES`` – Maximum output bytes to
  capture from combined stdout and stderr.  Longer output will be truncated
  with an informational suffix.  Defaults to 1 MiB.
* ``CODE_EDITOR_ENV_ALLOWLIST`` – Optional comma separated list of
  environment variable names that should be copied from the process
  environment into the sandboxed environment.  ``PATH`` and ``PYTHONPATH``
  are always preserved.

The runner returns a dictionary with ``exit_code``, ``output`` and
``duration_ms`` keys.  It never raises ``subprocess.TimeoutExpired`` or
``FileNotFoundError`` to the caller directly.  Instead, those conditions
result in negative exit codes and descriptive output messages.

Example usage::

    runner = CommandRunner()
    result = runner.run(["python", "-c", "print('hello')"], cwd=workspace_dir)
    if result["exit_code"] == 0:
        print(result["output"])
"""

from __future__ import annotations

import os
import shlex
import subprocess
import time
from pathlib import Path
from typing import Dict, Iterable, List, Optional


class CommandRunner:
    """Execute commands in a restricted sandbox.

    The runner ensures that only configured commands may be executed and
    applies timeouts and output length caps.  It should be instantiated
    once and reused.
    """

    def __init__(
        self,
        *,
        sandbox_enabled: Optional[bool] = None,
        allowed_commands: Optional[Iterable[str]] = None,
        timeout_seconds: Optional[int] = None,
        max_output_chars: Optional[int] = None,
        env_allowlist: Optional[Iterable[str]] = None,
    ) -> None:
        # Derive configuration from environment variables with sensible defaults.
        env = os.environ
        if sandbox_enabled is None:
            sandbox_val = env.get("CODE_EDITOR_SANDBOX_ENABLED", "true").lower()
            sandbox_enabled = sandbox_val in {"1", "true", "yes", "on"}
        self.sandbox_enabled: bool = bool(sandbox_enabled)

        if allowed_commands is None:
            cmds = env.get(
                "CODE_EDITOR_ALLOWED_TEST_COMMANDS",
                "python,pytest,unittest,npm,yarn,make,node,tsc",
            )
            allowed_commands = [c.strip() for c in cmds.split(",") if c.strip()]
        # Normalise commands to just the base names (no spaces)
        self.allowed_commands: set[str] = set(allowed_commands)

        if timeout_seconds is None:
            try:
                timeout_seconds = int(env.get("CODE_EDITOR_COMMAND_TIMEOUT_SECONDS", "300"))
            except ValueError:
                timeout_seconds = 300
        self.timeout_seconds: int = timeout_seconds if timeout_seconds and timeout_seconds > 0 else 300

        if max_output_chars is None:
            max_output_raw = env.get("CODE_EDITOR_COMMAND_MAX_OUTPUT_BYTES")
            if max_output_raw is None:
                max_output_raw = env.get("CODE_EDITOR_MAX_COMMAND_OUTPUT_CHARS", "1048576")
            try:
                max_output_chars = int(max_output_raw)
            except ValueError:
                max_output_chars = 1048576
        self.max_output_chars: int = max_output_chars if max_output_chars and max_output_chars > 0 else 1048576

        if env_allowlist is None:
            allowlist_str = env.get("CODE_EDITOR_ENV_ALLOWLIST", "")
            if allowlist_str:
                env_allowlist = [e.strip() for e in allowlist_str.split(",") if e.strip()]
            else:
                env_allowlist = []
        # Always preserve PATH and PYTHONPATH, and any CODE_EDITOR variables
        self.env_allowlist: set[str] = set(env_allowlist) | {"PATH", "PYTHONPATH"}

        # Determine the allowed workspace root.  Commands may only be executed
        # within this root directory to prevent path traversal and accidental
        # modifications outside the task workspace.  Default to the task
        # storage root or ``/tmp`` if unspecified.  This value must be an
        # absolute path.  See also run() for enforcement.
        workspace_root_raw = os.getenv("CODE_EDITOR_TASK_STORAGE_ROOT", env.get("CODE_EDITOR_TASK_STORAGE_ROOT", ""))
        self.workspace_root: Optional[str] = os.path.abspath(workspace_root_raw) if workspace_root_raw else None

    def _prepare_env(self) -> Dict[str, str]:
        """Construct a restricted environment for subprocesses.

        We copy only whitelisted variables from os.environ, plus any that
        begin with ``CODE_EDITOR_``.  This reduces the risk of leaking
        sensitive data into executed processes.
        """
        env: Dict[str, str] = {}
        for key, value in os.environ.items():
            if key in self.env_allowlist or key.startswith("CODE_EDITOR_"):
                env[key] = value
        return env

    def _is_allowed(self, cmd: List[str]) -> bool:
        """Check whether the command should be permitted under sandbox rules."""
        if not cmd:
            return False
        base = cmd[0]
        # If it contains a path separator, take the basename
        base_name = os.path.basename(base)
        return base_name in self.allowed_commands

    def run(self, cmd: List[str], cwd: Path) -> Dict[str, object]:
        """Execute a command and return its exit status and output.

        If the sandbox is enabled and the command is not allowed, this method
        will not attempt to run it and will instead return an exit code of
        ``-3`` with a descriptive message.  If the command is missing from
        the system ``PATH``, an exit code of ``-2`` will be returned.  When
        the command exceeds the timeout, an exit code of ``-1`` is returned
        and the process is killed.  Other unexpected errors result in an
        exit code of ``-99``.
        """
        started = time.monotonic()
        # Resolve and ensure cwd exists
        try:
            workspace = cwd.resolve()
        except Exception:
            workspace = Path(cwd)
        if not workspace.exists():
            return {
                "exit_code": -4,
                "output": f"Working directory {cwd} does not exist",
                "duration_ms": int((time.monotonic() - started) * 1000),
            }

        # Enforce workspace boundary.  Prevent commands from executing outside of the
        # configured task storage root.  If the resolved working directory does not
        # start with ``self.workspace_root``, refuse execution.
        if self.workspace_root:
            try:
                allowed_root = Path(self.workspace_root).resolve()
                workspace.relative_to(allowed_root)
            except ValueError:
                duration_ms = int((time.monotonic() - started) * 1000)
                return {
                    "exit_code": -4,
                    "output": f"Working directory {workspace} escapes allowed workspace root",
                    "duration_ms": duration_ms,
                }
            except Exception:
                duration_ms = int((time.monotonic() - started) * 1000)
                return {
                    "exit_code": -4,
                    "output": "Failed to enforce workspace boundary",
                    "duration_ms": duration_ms,
                }

        # Reject commands containing path traversal or absolute paths in their arguments.
        # This naive check prevents obviously unsafe patterns such as '..' or '/etc/passwd'.
        for arg in cmd:
            try:
                # Skip flags (starting with '-')
                if arg.startswith('-'):
                    continue
                # If argument contains parent directory traversal or is absolute, reject
                if '..' in arg or os.path.isabs(arg):
                    duration_ms = int((time.monotonic() - started) * 1000)
                    return {
                        "exit_code": -3,
                        "output": f"Command argument '{arg}' contains an unsafe path",
                        "duration_ms": duration_ms,
                    }
            except Exception:
                continue

        if self.sandbox_enabled and not self._is_allowed(cmd):
            duration_ms = int((time.monotonic() - started) * 1000)
            base = os.path.basename(cmd[0]) if cmd else ""
            return {
                "exit_code": -3,
                "output": f"Command '{base}' is not allowed by sandbox configuration",
                "duration_ms": duration_ms,
            }

        # Prepare environment
        env = self._prepare_env()

        try:
            result = subprocess.run(
                cmd,
                cwd=str(workspace),
                capture_output=True,
                text=True,
                timeout=self.timeout_seconds,
                env=env,
            )
            duration_ms = int((time.monotonic() - started) * 1000)
            combined_output = (result.stdout or "") + (result.stderr or "")
            encoded = combined_output.encode("utf-8", errors="ignore")
            if len(encoded) > self.max_output_chars:
                marker = "\n... output truncated ..."
                marker_bytes = marker.encode("utf-8")
                keep_bytes = max(0, self.max_output_chars - len(marker_bytes))
                truncated = encoded[:keep_bytes].decode("utf-8", errors="ignore")
                truncated += marker
                combined_output = truncated
            return {
                "exit_code": result.returncode,
                "output": combined_output,
                "duration_ms": duration_ms,
            }
        except subprocess.TimeoutExpired:
            duration_ms = int((time.monotonic() - started) * 1000)
            return {
                "exit_code": -1,
                "output": f"Command timed out after {self.timeout_seconds} seconds",
                "duration_ms": duration_ms,
            }
        except FileNotFoundError:
            duration_ms = int((time.monotonic() - started) * 1000)
            base = os.path.basename(cmd[0]) if cmd else ""
            return {
                "exit_code": -2,
                "output": f"Command '{base}' not found",
                "duration_ms": duration_ms,
            }
        except Exception as exc:
            duration_ms = int((time.monotonic() - started) * 1000)
            return {
                "exit_code": -99,
                "output": f"Command execution error: {exc}",
                "duration_ms": duration_ms,
            }
