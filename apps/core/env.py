from __future__ import annotations

import os
from pathlib import Path
from urllib.parse import urlparse


def env_str(name: str, default: str = '') -> str:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip()


def env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {'1', 'true', 'yes', 'on'}


def env_int(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None:
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def env_list(name: str, default: list[str] | None = None) -> list[str]:
    raw = os.getenv(name, '')
    if not raw:
        return list(default or [])
    return [item.strip() for item in raw.split(',') if item.strip()]


def parse_database_url(database_url: str, *, sqlite_fallback_path: Path) -> dict:
    if not database_url:
        return {
            'ENGINE': 'django.db.backends.sqlite3',
            'NAME': str(sqlite_fallback_path),
        }

    parsed = urlparse(database_url)
    scheme = parsed.scheme.lower()

    if scheme in {'sqlite', 'sqlite3'}:
        name = parsed.path or '/db.sqlite3'
        if name.startswith('/') and name != '/:memory:':
            name = name[1:]
        return {
            'ENGINE': 'django.db.backends.sqlite3',
            'NAME': ':memory:' if parsed.path == '/:memory:' else name,
        }

    if scheme in {'postgres', 'postgresql', 'psql'}:
        return {
            'ENGINE': 'django.db.backends.postgresql',
            'NAME': parsed.path.lstrip('/') or 'postgres',
            'USER': parsed.username or '',
            'PASSWORD': parsed.password or '',
            'HOST': parsed.hostname or 'localhost',
            'PORT': parsed.port or 5432,
            'CONN_MAX_AGE': env_int('DJANGO_DB_CONN_MAX_AGE', 60),
            'OPTIONS': {},
        }

    raise ValueError(f'Unsupported DATABASE_URL scheme: {scheme}')
