from __future__ import annotations

import os
import tempfile
from pathlib import Path

from .base import *  # noqa

DEBUG = True

if not os.getenv('DATABASE_URL'):
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.sqlite3',
            'NAME': str(Path(tempfile.gettempdir()) / 'code_ai_fresh.sqlite3'),
        }
    }

if not REDIS_URL:
    CACHES = {
        'default': {
            'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
            'LOCATION': 'code-editor-local',
        }
    }

CHANNEL_LAYERS = {
    'default': {
        'BACKEND': 'channels.layers.InMemoryChannelLayer',
    }
}
