from __future__ import annotations

from pathlib import Path

from django.core.exceptions import ValidationError

from .safe_paths import ensure_within_root, safe_join


def resolve_relative_path(root: Path, relative_path: str) -> Path:
    try:
        return safe_join(root, relative_path)
    except ValueError as exc:
        raise ValidationError(str(exc)) from exc


def resolve_existing_path(root: Path, candidate: Path) -> Path:
    try:
        return ensure_within_root(root, candidate)
    except ValueError as exc:
        raise ValidationError(str(exc)) from exc
