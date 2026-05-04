"""Compatibility namespace package mapped to apps/code_editor."""
from pathlib import Path

_pkg_dir = Path(__file__).resolve().parent
_app_path = _pkg_dir.parent / 'apps' / 'code_editor'
if _app_path.exists():
    __path__.append(str(_app_path))
