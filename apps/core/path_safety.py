from __future__ import annotations

from pathlib import Path, PurePath
from typing import Iterable

from django.core.exceptions import ValidationError


def validate_relative_client_path(relative_path: str) -> PurePath:
    if not relative_path or not str(relative_path).strip():
        raise ValidationError('A relative path is required.')
    candidate = PurePath(str(relative_path))
    if candidate.is_absolute():
        raise ValidationError('Absolute client paths are not allowed.')
    if any(part in {'', '.', '..'} for part in candidate.parts):
        raise ValidationError('Path traversal segments are not allowed.')
    return candidate


def resolve_relative_path(root: Path, relative_path: str) -> Path:
    relative = validate_relative_client_path(relative_path)
    return ensure_within_root(root, root / relative)


def ensure_within_root(root: Path, candidate: Path) -> Path:
    root_resolved = Path(root).resolve()
    candidate_resolved = Path(candidate).resolve()
    try:
        candidate_resolved.relative_to(root_resolved)
    except ValueError as exc:
        raise ValidationError(
            f'Path "{candidate_resolved}" escapes the allowed root "{root_resolved}".'
        ) from exc
    return candidate_resolved


def ensure_within_roots(candidate: Path, allowed_roots: Iterable[Path]) -> Path:
    candidate_resolved = Path(candidate).resolve()
    for root in allowed_roots:
        root_resolved = Path(root).resolve()
        try:
            candidate_resolved.relative_to(root_resolved)
            return candidate_resolved
        except ValueError:
            continue
    joined_roots = ', '.join(str(Path(root).resolve()) for root in allowed_roots)
    raise ValidationError(
        f'Path "{candidate_resolved}" is outside the allowed roots: {joined_roots}.'
    )


def resolve_existing_path(root: Path, candidate: Path) -> Path:
    resolved = ensure_within_root(root, candidate)
    if not resolved.exists():
        raise ValidationError(f'Path "{resolved}" does not exist.')
    return resolved
