"""Prune old task artifacts from the code editor database and filesystem.

This management command deletes artifacts older than a given age and, if
configured, removes their associated files from disk.  Use this to clean
up stale data and free storage.  A ``--dry-run`` option shows what
would be deleted without actually performing deletions.

Example usage::

    python manage.py code_editor_prune_artifacts --days 30 --dry-run

"""

import os
import datetime
from django.core.management.base import BaseCommand
from django.utils import timezone
from ...models import Artifact


class Command(BaseCommand):
    help = 'Prune old artifacts from the database and optionally the filesystem.'

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            '--days', type=int, dest='days', default=90,
            help='Delete artifacts older than this many days (default: 90)'
        )
        parser.add_argument(
            '--dry-run', action='store_true', dest='dry_run', default=False,
            help='List artifacts that would be deleted without deleting'
        )
        parser.add_argument(
            '--remove-files', action='store_true', dest='remove_files', default=False,
            help='Also delete files on disk referenced by artifacts.  Use with caution.'
        )

    def handle(self, *args, **options) -> None:
        days = int(options.get('days') or 90)
        dry_run = bool(options.get('dry_run'))
        remove_files = bool(options.get('remove_files'))
        cutoff = timezone.now() - datetime.timedelta(days=days)

        old_artifacts = Artifact.objects.filter(created_at__lt=cutoff)
        count = old_artifacts.count()
        if dry_run:
            self.stdout.write(f'{count} artifacts older than {days} days would be deleted')
            return
        if count == 0:
            self.stdout.write('No artifacts to prune')
            return
        deleted_files = 0
        for art in old_artifacts:
            if remove_files and art.file_path:
                try:
                    if os.path.isfile(art.file_path):
                        os.remove(art.file_path)
                        deleted_files += 1
                except Exception:
                    pass
            art.delete()
        self.stdout.write(self.style.SUCCESS(f'Deleted {count} artifacts'))
        if remove_files:
            self.stdout.write(self.style.SUCCESS(f'Removed {deleted_files} files from disk'))