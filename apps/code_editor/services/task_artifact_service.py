from __future__ import annotations

import hashlib
import mimetypes
import os
from pathlib import Path
from typing import Any, Optional

from django.conf import settings

from ..models import Artifact, TaskRun
from apps.core.safe_paths import ensure_within_root


class TaskArtifactService:
    """Helpers for persisting and reading task artifacts on local storage."""

    @classmethod
    def storage_root(cls) -> Path:
        configured = os.environ.get('CODE_EDITOR_TASK_STORAGE_ROOT') or getattr(
            settings,
            'CODE_EDITOR_TASK_STORAGE_ROOT',
            '/tmp/code_editor_tasks',
        )
        root = Path(configured)
        root.mkdir(parents=True, exist_ok=True)
        return root

    @classmethod
    def task_dir(cls, task: TaskRun) -> Path:
        path = cls.storage_root() / str(task.id)
        path.mkdir(parents=True, exist_ok=True)
        return path

    @classmethod
    def persist_text_artifact(
        cls,
        *,
        task: TaskRun,
        artifact_type: str,
        relative_name: str,
        content: str,
        step=None,
        candidate_patch=None,
        validation_run=None,
        test_run=None,
        workspace_snapshot=None,
        description: str = '',
        metadata: Optional[dict[str, Any]] = None,
        content_type: Optional[str] = None,
    ) -> Artifact:
        artifact_path = cls.task_dir(task) / relative_name
        artifact_path.parent.mkdir(parents=True, exist_ok=True)
        artifact_path.write_text(content, encoding='utf-8')
        encoded = content.encode('utf-8')
        guessed_type, _ = mimetypes.guess_type(str(artifact_path))
        return Artifact.objects.create(
            task=task,
            step=step,
            candidate_patch=candidate_patch,
            validation_run=validation_run,
            test_run=test_run,
            workspace_snapshot=workspace_snapshot,
            artifact_type=artifact_type,
            name=artifact_path.name,
            description=description,
            file_path=str(artifact_path),
            text_content=content,
            content_type=content_type or guessed_type or 'text/plain',
            size_bytes=len(encoded),
            sha256=hashlib.sha256(encoded).hexdigest(),
            metadata=metadata or {},
        )

    @classmethod
    def read_content(cls, artifact: Artifact) -> str:
        if artifact.text_content:
            return artifact.text_content
        if artifact.file_path:
            path = ensure_within_root(cls.storage_root(), Path(artifact.file_path))
            return path.read_text(encoding='utf-8', errors='ignore')
        return ''
