"""Rebuild embeddings for indexed code in a repository.

This management command triggers regeneration of vector embeddings for a
repository or all repositories.  It can optionally limit the number of
files processed.  A ``--dry-run`` option prints the actions without
performing them.

Note: The actual embedding generation is delegated to the ``EmbeddingsService``.
In environments where this service is unavailable, the command will
report a warning and exit.
"""

from django.core.management.base import BaseCommand
from typing import Optional
from ...models import Repository, IndexedFile


class Command(BaseCommand):
    help = 'Rebuild embeddings for indexed files in one or more repositories.'

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            '--repository-id', type=str, dest='repository_id', default=None,
            help='ID of the repository to process.  If omitted, all repositories are processed.'
        )
        parser.add_argument(
            '--limit', type=int, dest='limit', default=0,
            help='Maximum number of files to process per repository (0 means unlimited).'
        )
        parser.add_argument(
            '--dry-run', action='store_true', dest='dry_run', default=False,
            help='Show what would be processed without generating embeddings.'
        )

    def handle(self, *args, **options) -> None:
        repo_id: Optional[str] = options.get('repository_id')
        limit: int = int(options.get('limit') or 0)
        dry_run: bool = bool(options.get('dry_run'))

        try:
            from ...services.embeddings_service import EmbeddingsService  # type: ignore
        except Exception:
            self.stdout.write(self.style.ERROR('Embeddings service unavailable'))
            return

        service = EmbeddingsService()

        repos = Repository.objects.all()
        if repo_id:
            repos = repos.filter(id=repo_id)
        if not repos:
            self.stdout.write(self.style.WARNING('No repositories found to process'))
            return
        for repo in repos:
            files_qs = IndexedFile.objects.filter(repository=repo).order_by('indexed_at')
            if limit > 0:
                files_qs = files_qs[:limit]
            count = files_qs.count()
            if dry_run:
                self.stdout.write(f'Would rebuild embeddings for {count} files in repository {repo.id}')
                continue
            self.stdout.write(f'Rebuilding embeddings for {count} files in repository {repo.id}...')
            for indexed in files_qs:
                try:
                    service.generate_embedding(indexed)
                except Exception as exc:
                    self.stdout.write(self.style.WARNING(f'Failed to embed {indexed.file_path}: {exc}'))
            self.stdout.write(self.style.SUCCESS(f'Finished rebuilding embeddings for repository {repo.id}'))