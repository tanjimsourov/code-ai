from __future__ import annotations

from pathlib import Path


def safe_join(root: Path, relative_path: str) -> Path:
    if not relative_path:
        raise ValueError('Path is required')
    rel = Path(relative_path)
    if rel.is_absolute() or '..' in rel.parts:
        raise ValueError('Unsafe relative path')
    root_resolved = root.resolve()
    candidate = (root_resolved / rel).resolve()
    try:
        candidate.relative_to(root_resolved)
    except ValueError as exc:
        raise ValueError('Resolved path escapes allowed root') from exc
    return candidate


def ensure_within_root(root: Path, candidate: Path) -> Path:
    root_resolved = root.resolve()
    candidate_resolved = candidate.resolve()
    try:
        candidate_resolved.relative_to(root_resolved)
    except ValueError as exc:
        raise ValueError('Path escapes allowed root') from exc
    return candidate_resolved
