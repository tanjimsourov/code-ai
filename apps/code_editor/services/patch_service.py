"""Safe patch parsing, application, and reversion helpers.

Patch payloads are JSON-compatible dictionaries with:
- diff: unified diff text
- changed_files: list of relative file paths
- files: mapping of path -> new content or {"after": "..."}
- status: proposed/applied/failed/rejected/rolled_back
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional
import shutil


class PatchService:
    """Validate and apply reviewable patch payloads safely."""

    @staticmethod
    def _is_safe_relative_path(file_path: str) -> bool:
        if not file_path or file_path.startswith('/'):
            return False
        path = Path(file_path)
        return not path.is_absolute() and all(part not in ('..', '') for part in path.parts)

    @classmethod
    def _resolve_inside(cls, root: Path, file_path: str) -> Path:
        if not cls._is_safe_relative_path(file_path):
            raise ValueError(f"Unsafe file path in patch: {file_path}")
        root_resolved = root.resolve()
        target = (root_resolved / file_path).resolve()
        try:
            target.relative_to(root_resolved)
        except ValueError:
            raise ValueError(f"Patch path escapes workspace: {file_path}")
        return target

    @classmethod
    def validate_patch(cls, patch: Dict[str, Any]) -> None:
        if not isinstance(patch, dict):
            raise ValueError("Patch must be a dictionary")
        files = patch.get('files')
        if not isinstance(files, dict) or not files:
            raise ValueError("Patch must contain a non-empty 'files' mapping")
        for file_path, entry in files.items():
            if not cls._is_safe_relative_path(file_path):
                raise ValueError(f"Unsafe file path in patch: {file_path}")
            if not isinstance(entry, (str, dict)):
                raise ValueError(f"Invalid patch entry for {file_path}")
            if isinstance(entry, dict) and 'after' not in entry:
                raise ValueError(f"Patch entry for {file_path} must include 'after'")

    @classmethod
    def changed_files(cls, patch: Dict[str, Any]) -> list[str]:
        cls.validate_patch(patch)
        changed = patch.get('changed_files') or list(patch.get('files', {}).keys())
        for file_path in changed:
            if not cls._is_safe_relative_path(file_path):
                raise ValueError(f"Unsafe file path in patch: {file_path}")
        return list(changed)

    @classmethod
    def apply_patch(cls, patch: Dict[str, Any], workspace_dir: Path, *, repository_dir: Optional[Path] = None) -> None:
        cls.validate_patch(patch)
        workspace_dir.mkdir(parents=True, exist_ok=True)
        for file_path, entry in patch['files'].items():
            target = cls._resolve_inside(workspace_dir, file_path)
            content = entry.get('after', '') if isinstance(entry, dict) else str(entry)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding='utf-8')

    @classmethod
    def revert_patch(cls, patch: Dict[str, Any], workspace_dir: Path, *, repository_dir: Path) -> None:
        changed = cls.changed_files(patch)
        for file_path in changed:
            target = cls._resolve_inside(workspace_dir, file_path)
            original = cls._resolve_inside(repository_dir, file_path)
            if original.exists():
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(original, target)
            elif target.exists():
                target.unlink()
