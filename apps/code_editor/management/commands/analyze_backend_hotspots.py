"""Management command to analyze backend performance hotspots.

This command provides a simple overview of potential performance hotspots
within the code editor backend.  It inspects counts of key models,
breaks down tasks, candidate patches and jobs by status, and lists any
tables lacking indexes on critical fields.  The output can be used as
part of a regular health check or before scaling the system to ensure
that database queries remain efficient.

Because this command does not run the application server under the
Django debug toolbar, it cannot report per‑view query counts.  For
more detailed analysis, integrate the Django debug toolbar in a
development environment and monitor query counts and timings while
exercising the API.
"""

from django.core.management.base import BaseCommand
from django.db import connection
from code_editor.models import (
    TaskRun, CandidatePatch, IngestionJob, Repository, Project
)


class Command(BaseCommand):
    help = 'Analyze backend performance hotspots and print summary statistics'

    def handle(self, *args, **options):  # type: ignore[override]
        self.stdout.write('=== Backend Hotspot Analysis ===')
        self.stdout.write('')
        # Summarise counts by status for tasks
        self.stdout.write('TaskRun status counts:')
        for status, _ in TaskRun.STATUS_CHOICES:
            count = TaskRun.objects.filter(status=status).count()
            self.stdout.write(f'  {status:20s}: {count}')
        self.stdout.write('')

        # CandidatePatch approval status
        self.stdout.write('CandidatePatch approval status counts:')
        for status, _ in CandidatePatch.APPROVAL_STATUS_CHOICES:
            count = CandidatePatch.objects.filter(approval_status=status).count()
            self.stdout.write(f'  {status:20s}: {count}')
        self.stdout.write('')

        # IngestionJob status counts
        self.stdout.write('IngestionJob status counts:')
        for status, _ in IngestionJob._meta.get_field('status').choices:
            count = IngestionJob.objects.filter(status=status).count()
            self.stdout.write(f'  {status:20s}: {count}')
        self.stdout.write('')

        # Repository indexing and sync status counts
        self.stdout.write('Repository indexing status counts:')
        for status, _ in Repository._meta.get_field('indexing_status').choices:
            count = Repository.objects.filter(indexing_status=status).count()
            self.stdout.write(f'  {status:20s}: {count}')
        self.stdout.write('')
        self.stdout.write('Repository sync status counts:')
        for status, _ in Repository._meta.get_field('sync_status').choices:
            count = Repository.objects.filter(sync_status=status).count()
            self.stdout.write(f'  {status:20s}: {count}')
        self.stdout.write('')

        # Identify tables missing expected indexes (simple check)
        self.stdout.write('Checking for missing indexes on critical columns...')
        missing = []
        with connection.cursor() as cursor:
            # Inspect each table's indexes via the information_schema (works for PostgreSQL)
            for model, fields in [
                (TaskRun, ['approval_status', 'effective_apply_mode', 'requested_apply_mode']),
                (CandidatePatch, ['approval_status', 'apply_mode_effective']),
                (Repository, ['url', 'branch', 'vcs_provider', 'commit_sha']),
                (Project, ['name']),
            ]:
                table = model._meta.db_table
                # Query to check if index exists for each field
                for field in fields:
                    index_name = f'{table}_{field}_idx'
                    cursor.execute(
                        """
                        SELECT COUNT(1)
                        FROM pg_indexes
                        WHERE schemaname = ANY (CURRENT_SCHEMAS(false))
                          AND tablename = %s
                          AND indexname = %s
                        """,
                        [table, index_name],
                    )
                    exists = cursor.fetchone()[0]
                    if exists == 0:
                        missing.append(f'{table}.{field}')
        if missing:
            self.stdout.write('Missing indexes detected:')
            for idx in missing:
                self.stdout.write(f'  {idx}')
        else:
            self.stdout.write('All critical indexes are present.')
        self.stdout.write('')
        self.stdout.write('Analysis complete.')