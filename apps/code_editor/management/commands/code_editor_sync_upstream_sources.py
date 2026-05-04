"""Management command to synchronise allow-listed upstream sources."""

from django.core.management.base import BaseCommand

from ...services.upstream_sync_service import UpstreamSyncService


class Command(BaseCommand):
    help = 'Synchronise allow-listed upstream sources and prepare update candidates'

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            '--dry-run',
            action='store_true',
            default=False,
            help='Preview upstream candidate generation without creating records.',
        )

    def handle(self, *args, **options) -> None:
        service = UpstreamSyncService()
        dry_run = bool(options.get('dry_run'))
        summary = service.sync_all(dry_run=dry_run)
        mode = 'dry-run' if dry_run else 'apply'
        self.stdout.write(
            self.style.SUCCESS(
                f"Upstream sync completed ({mode}): sources={summary['sources']} candidates={summary['candidates_created']}"
            )
        )
