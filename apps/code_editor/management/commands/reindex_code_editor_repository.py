"""Management command to (re)index a repository.

This command wraps the ingestion service to allow administrators to
trigger a reindex of a repository.  Reindexing reads files from the
repository (performing a sync for remote repositories) and updates the
IndexedFile and CodeChunk tables.  Existing indexed files that no
longer exist in the repository are removed.  Options include a dry
run (which only reports the number of files that would be indexed)
and forcing a full reindex (which deletes existing index entries
before indexing).
"""

from django.core.management.base import BaseCommand, CommandError
from code_editor.models import Repository, IndexedFile, CodeChunk
from code_editor.services.ingestion_service import IngestionService
from code_editor.services.repository_service import RepositoryService


class Command(BaseCommand):
    help = "Index or reindex a code editor repository"

    def add_arguments(self, parser):
        parser.add_argument('repository_id', type=int, help='ID of the Repository to index')
        parser.add_argument('--dry-run', action='store_true', dest='dry_run', help='Report counts without indexing')
        parser.add_argument('--full', action='store_true', dest='full', help='Perform a full reindex (delete existing index entries)')

    def handle(self, *args, **options):
        repo_id = options['repository_id']
        dry_run = options.get('dry_run', False)
        full = options.get('full', False)
        try:
            repository = Repository.objects.get(id=repo_id)
        except Repository.DoesNotExist:
            raise CommandError(f"Repository with ID {repo_id} does not exist")
        # Sync repository if not local
        if repository.access_type != 'local':
            try:
                RepositoryService.sync_repository(repository)
            except Exception as exc:
                raise CommandError(f"Failed to sync repository before indexing: {exc}")
        # Get files to be indexed
        files = RepositoryService.get_repository_files(repository)
        if dry_run:
            self.stdout.write(self.style.WARNING(
                f"Dry run: {len(files)} files would be indexed for repository {repository.id}"))
            return
        # If full reindex requested, delete existing indexed files and chunks
        if full:
            try:
                # Bulk delete chunks to avoid cascades
                chunk_qs = CodeChunk.objects.filter(indexed_file__repository=repository)
                deleted_chunks = chunk_qs.count()
                chunk_qs.delete()
                file_qs = IndexedFile.objects.filter(repository=repository)
                deleted_files = file_qs.count()
                file_qs.delete()
                self.stdout.write(self.style.WARNING(
                    f"Deleted {deleted_files} existing indexed files and {deleted_chunks} chunks for repository {repository.id}"))
            except Exception as exc:
                self.stderr.write(self.style.ERROR(f"Error deleting existing index: {exc}"))
        # Create ingestion job and run synchronously
        ingestion = IngestionService()
        # We create a fake job ID to tie ingestion to this repository
        import uuid
        job_id = uuid.uuid4().hex
        from code_editor.models import IngestionJob
        job = IngestionJob.objects.create(repository=repository, job_id=job_id, status='pending')
        result = ingestion.ingest_repository(job_id)
        # Summarise
        if result.get('status') == 'completed':
            self.stdout.write(self.style.SUCCESS(
                f"Indexed {result['files_processed']} files and {result['chunks_created']} chunks for repository {repository.id}"))
        else:
            self.stderr.write(self.style.ERROR(
                f"Reindex failed: {result.get('error') or 'unknown error'}"))