from django.apps import AppConfig
from pathlib import Path


class CodeEditorConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'code_editor'
    label = 'code_editor'
    path = str(Path(__file__).resolve().parent)
