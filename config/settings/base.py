from __future__ import annotations

import os
from pathlib import Path

from apps.core.env import env_bool, env_int, env_list, env_str, parse_database_url

BASE_DIR = Path(__file__).resolve().parent.parent.parent

SECRET_KEY = env_str('SECRET_KEY', 'insecure-local-secret-change-me')
DEBUG = env_bool('DEBUG', False)
ALLOWED_HOSTS = env_list('ALLOWED_HOSTS', ['127.0.0.1', 'localhost'])

CSRF_TRUSTED_ORIGINS = env_list('CSRF_TRUSTED_ORIGINS', [])

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'rest_framework',
    'channels',
    'apps.core.apps.CoreConfig',
    'apps.accounts.apps.AccountsConfig',
    'apps.ai_providers.apps.AiProvidersConfig',
    'apps.repositories.apps.RepositoriesConfig',
    'apps.workspaces.apps.WorkspacesConfig',
    'apps.tasks.apps.TasksConfig',
    'apps.artifacts.apps.ArtifactsConfig',
    'apps.upstream.apps.UpstreamConfig',
    'apps.observability.apps.ObservabilityConfig',
    'apps.code_editor.apps.CodeEditorConfig',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'config.urls'
TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'config.wsgi.application'
ASGI_APPLICATION = 'config.asgi.application'

DATABASES = {
    'default': parse_database_url(
        env_str('DATABASE_URL', ''),
        sqlite_fallback_path=BASE_DIR / 'db.sqlite3',
    )
}

AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

LANGUAGE_CODE = 'en-us'
TIME_ZONE = env_str('TIME_ZONE', 'UTC')
USE_I18N = True
USE_TZ = True

STATIC_URL = '/static/'
STATIC_ROOT = Path(env_str('STATIC_ROOT', str(BASE_DIR / 'staticfiles')))
MEDIA_URL = '/media/'
MEDIA_ROOT = Path(env_str('MEDIA_ROOT', str(BASE_DIR / 'media')))

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

CODE_EDITOR_TASK_STORAGE_ROOT = env_str('CODE_EDITOR_TASK_STORAGE_ROOT', str(BASE_DIR / 'var' / 'tasks'))
CODE_EDITOR_REPOSITORY_STORAGE_ROOT = env_str('CODE_EDITOR_REPOSITORY_STORAGE_ROOT', str(BASE_DIR / 'var' / 'repositories'))
CODE_EDITOR_ARTIFACT_STORAGE_ROOT = env_str('CODE_EDITOR_ARTIFACT_STORAGE_ROOT', str(BASE_DIR / 'var' / 'artifacts'))
CODE_EDITOR_REPOSITORY_ROOT = env_str('CODE_EDITOR_REPOSITORY_ROOT', CODE_EDITOR_REPOSITORY_STORAGE_ROOT)
CODE_EDITOR_COMMAND_TIMEOUT_SECONDS = env_int('CODE_EDITOR_COMMAND_TIMEOUT_SECONDS', 120)
CODE_EDITOR_COMMAND_MAX_OUTPUT_BYTES = env_int('CODE_EDITOR_COMMAND_MAX_OUTPUT_BYTES', 1048576)
CODE_EDITOR_PUBLIC_MODEL_LISTING = env_bool('CODE_EDITOR_PUBLIC_MODEL_LISTING', False)
CODE_EDITOR_PUBLIC_METRICS = env_bool('CODE_EDITOR_PUBLIC_METRICS', False)
CODE_EDITOR_METRICS_TOKEN = env_str('CODE_EDITOR_METRICS_TOKEN', '')

REDIS_URL = env_str('REDIS_URL', '')

if REDIS_URL:
    CACHES = {
        'default': {
            'BACKEND': 'django.core.cache.backends.redis.RedisCache',
            'LOCATION': REDIS_URL,
        }
    }
else:
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
if REDIS_URL:
    try:
        import channels_redis  # noqa: F401
        CHANNEL_LAYERS = {
            'default': {
                'BACKEND': 'channels_redis.core.RedisChannelLayer',
                'CONFIG': {'hosts': [REDIS_URL]},
            }
        }
    except Exception:
        pass

REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': [
        'rest_framework.authentication.SessionAuthentication',
        'rest_framework.authentication.BasicAuthentication',
    ],
    'DEFAULT_PERMISSION_CLASSES': [
        'rest_framework.permissions.IsAuthenticated',
    ],
    'DEFAULT_THROTTLE_CLASSES': [
        'rest_framework.throttling.UserRateThrottle',
        'rest_framework.throttling.AnonRateThrottle',
    ],
    'DEFAULT_THROTTLE_RATES': {
        'user': env_str('CODE_EDITOR_THROTTLE_RATE_USER', '1000/day'),
        'anon': env_str('CODE_EDITOR_THROTTLE_RATE_ANON', '100/day'),
    },
    'DEFAULT_PAGINATION_CLASS': 'rest_framework.pagination.PageNumberPagination',
    'PAGE_SIZE': 20,
}

CELERY_BROKER_URL = env_str('CELERY_BROKER_URL', env_str('REDIS_URL', 'redis://localhost:6379/1'))
CELERY_RESULT_BACKEND = env_str('CELERY_RESULT_BACKEND', env_str('REDIS_URL', 'redis://localhost:6379/2'))
CELERY_TASK_ALWAYS_EAGER = env_bool('CELERY_TASK_ALWAYS_EAGER', True)
CELERY_TASK_EAGER_PROPAGATES = True

LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'standard': {
            'format': '%(asctime)s %(levelname)s %(name)s %(message)s',
        },
    },
    'handlers': {
        'console': {
            'class': 'logging.StreamHandler',
            'formatter': 'standard',
        },
    },
    'root': {
        'handlers': ['console'],
        'level': env_str('LOG_LEVEL', 'INFO'),
    },
}
