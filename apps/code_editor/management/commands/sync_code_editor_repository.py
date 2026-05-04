"""Management command to synchronise a repository from its remote source.

Usage:

    python manage.py sync_code_editor_repository <repository_id> [--branch BRANCH] [--dry-run]

The command invokes the RepositoryService.sync_repository method to clone
or fetch a repository.  If --dry-run is specified no network
operations are performed; instead the command reports what would be
done and updates the sync status to reflect a pending or synced
state.  On success the current commit SHA is printed.  Errors are
reported to stderr and the repository's sync status is set to
"failed".
"""

from django.core.management.base import BaseCommand, CommandError
from code_editor.models import Repository
from code_editor.services.repository_service import RepositoryService


class Command(BaseCommand):
    help = "Synchronise a code editor repository from its remote source"

    def add_arguments(self, parser):
        parser.add_argument('repository_id', type=int, help='ID of the Repository to sync')
        parser.add_argument('--branch', dest='branch', default=None, help='Override branch to sync')
        parser.add_argument('--dry-run', action='store_true', dest='dry_run', help='Perform a dry run without making changes')

    def handle(self, *args, **options):
        repo_id = options['repository_id']
        branch = options.get('branch')
        dry_run = options.get('dry_run', False)
        try:
            repository = Repository.objects.get(id=repo_id)
        except Repository.DoesNotExist:
            raise CommandError(f"Repository with ID {repo_id} does not exist")
        # Remember previous commit to report changes
        prev_commit = repository.commit_sha
        try:
            RepositoryService.sync_repository(repository, branch=branch, dry_run=dry_run)
        except Exception as exc:
            self.stderr.write(self.style.ERROR(f"Sync failed: {exc}"))
            return
        # Report outcome
        if dry_run:
            self.stdout.write(self.style.WARNING(f"Dry run completed for repository {repository.id}"))
        else:
            if repository.commit_sha and repository.commit_sha != prev_commit:
                self.stdout.write(self.style.SUCCESS(
                    f"Repository {repository.id} synced to commit {repository.commit_sha} (was {prev_commit or 'N/A'})"
                ))
            else:
                self.stdout.write(self.style.SUCCESS(
                    f"Repository {repository.id} is up to date at commit {repository.commit_sha or 'unknown'}"
                ))