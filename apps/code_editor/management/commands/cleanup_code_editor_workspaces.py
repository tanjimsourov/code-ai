"""Management command to delete old or unused task workspaces.

This command cleans up task workspace directories created by the TaskExecutor.
Workspaces are stored under ``CODE_EDITOR_TASK_STORAGE_ROOT`` and may consume
significant disk space over time.  Deleting old workspaces helps manage
resources.  The command supports dry-run mode to preview deletions and a
maximum age filter to retain recent workspaces.

Usage::

    python manage.py cleanup_code_editor_workspaces --max-age=7 --dry-run

This example would list workspaces older than 7 days without deleting them.

Options:

    --dry-run        Print workspaces that would be deleted without removing them.
    --max-age DAYS   Only delete workspaces whose last modified time is older than
                     the specified number of days.  If unspecified, all
                     workspaces may be deleted.

The command prints a summary of how many directories were deleted and how many
were skipped due to age or other conditions.
"""

from __future__ import annotations

import argparse
import datetime
import os
import shutil
from pathlib import Path
from typing import Iterable

from django.core.management.base import BaseCommand

from ...services.task_artifact_service import TaskArtifactService


class Command(BaseCommand):
    help = "Cleanup old task workspace directories"

    def add_arguments(self, parser: argparse.ArgumentParser) -> None:
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Preview which workspaces would be deleted without removing them',
        )
        parser.add_argument(
            '--max-age',
            type=int,
            default=None,
            help='Only delete workspaces older than the specified number of days',
        )

    def handle(self, *args: str, **options: str) -> None:
        dry_run: bool = bool(options.get('dry_run'))
        max_age_days: int | None = options.get('max_age')

        storage_root: Path = TaskArtifactService.storage_root()
        if not storage_root.exists():
            self.stdout.write(self.style.NOTICE(f"No workspace directory found at {storage_root}"))
            return

        now = datetime.datetime.now()
        deleted_count = 0
        skipped_count = 0
        targets: Iterable[Path] = [p for p in storage_root.iterdir() if p.is_dir()]

        for workspace_dir in targets:
            try:
                # Determine age of the directory by modification time
                mtime = datetime.datetime.fromtimestamp(workspace_dir.stat().st_mtime)
                age_days = (now - mtime).days
            except Exception:
                skipped_count += 1
                continue

            if max_age_days is not None and age_days < max_age_days:
                skipped_count += 1
                continue

            if dry_run:
                self.stdout.write(f"[DRY RUN] Would delete {workspace_dir} (age={age_days}d)")
            else:
                try:
                    shutil.rmtree(workspace_dir)
                    deleted_count += 1
                    self.stdout.write(f"Deleted {workspace_dir} (age={age_days}d)")
                except Exception as exc:
                    self.stderr.write(f"Failed to delete {workspace_dir}: {exc}")
                    skipped_count += 1

        # Summary
        if dry_run:
            self.stdout.write(self.style.NOTICE(f"Dry run complete. {deleted_count} workspaces would be deleted, {skipped_count} skipped."))
        else:
            self.stdout.write(self.style.SUCCESS(f"Deleted {deleted_count} workspace(s). {skipped_count} skipped."))