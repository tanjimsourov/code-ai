import hashlib
import secrets
import uuid
from pathlib import Path
from urllib.parse import urlparse
from django.conf import settings
from django.db import models
from django.core.validators import MinValueValidator
from django.utils import timezone

# Use the pgvector VectorField for storing embeddings when available.
# Fall back to a simple JSON field for SQLite compatibility.
try:
    from pgvector.django import VectorField, HnswIndex
except ImportError:
    # For SQLite and other databases, use JSONField to store embeddings
    from django.db.models import JSONField
    
    class VectorField(JSONField):  # type: ignore[misc]
        def __init__(self, *args, dimensions=None, **kwargs):
            kwargs.setdefault('default', list)
            super().__init__(*args, **kwargs)

    HnswIndex = None  # type: ignore


class CodeEditorApiKey(models.Model):
    """Stored API key metadata for optional quota and usage tracking."""

    name = models.CharField(max_length=255)
    key_hash = models.CharField(max_length=64, unique=True)
    prefix = models.CharField(max_length=16, db_index=True)
    daily_quota = models.IntegerField(default=1000, validators=[MinValueValidator(0)])
    rpm_limit = models.IntegerField(default=60, validators=[MinValueValidator(1)])
    is_active = models.BooleanField(default=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='code_editor_api_keys',
    )
    last_used_at = models.DateTimeField(null=True, blank=True)
    revoked_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'code_editor_api_key'
        indexes = [
            models.Index(fields=['prefix']),
            models.Index(fields=['is_active']),
            models.Index(fields=['created_at']),
        ]
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.name} ({self.prefix})"

    @staticmethod
    def generate_key() -> tuple[str, str, str]:
        raw_key = f"sk-ce-{secrets.token_urlsafe(32)}"
        key_hash = hashlib.sha256(raw_key.encode('utf-8')).hexdigest()
        prefix = raw_key[:8]
        return raw_key, key_hash, prefix

    def revoke(self) -> None:
        self.is_active = False
        self.revoked_at = timezone.now()
        self.save(update_fields=['is_active', 'revoked_at', 'updated_at'])


class CodeEditorRequestLog(models.Model):
    """Lightweight request log for the single-user local code editor backend."""

    STATUS_CHOICES = [
        ('success', 'Success'),
        ('error', 'Error'),
        ('rate_limited', 'Rate Limited'),
        ('quota_exceeded', 'Quota Exceeded'),
    ]

    REQUEST_KINDS = [
        ('chat', 'Chat Completion'),
        ('complete', 'Text Completion'),
        ('edit', 'Code Edit'),
        ('embed', 'Embeddings'),
        ('rerank', 'Document Reranking'),
        ('models', 'Model Listing'),
        ('health', 'Health Check'),
        # Added for fill‑in‑the‑middle code completions
        ('infill', 'Fill‑in‑the‑Middle'),
    ]

    endpoint = models.CharField(max_length=255, help_text="API endpoint that was called")
    provider = models.CharField(max_length=100, help_text="AI provider used")
    model_name = models.CharField(max_length=255, help_text="Model name that was used")
    request_kind = models.CharField(max_length=20, choices=REQUEST_KINDS, help_text="Type of request")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, help_text="Request status")
    latency_ms = models.IntegerField(
        null=True,
        blank=True,
        validators=[MinValueValidator(0)],
        help_text="Request latency in milliseconds",
    )
    input_chars = models.IntegerField(
        default=0,
        validators=[MinValueValidator(0)],
        help_text="Number of input characters",
    )
    output_chars = models.IntegerField(
        default=0,
        validators=[MinValueValidator(0)],
        help_text="Number of output characters",
    )
    error_message = models.TextField(null=True, blank=True, help_text="Error message if request failed")
    api_key = models.ForeignKey(
        CodeEditorApiKey,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='request_logs',
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='code_editor_request_logs',
    )
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        db_table = 'code_editor_request_log'
        indexes = [
            models.Index(fields=['created_at']),
            models.Index(fields=['request_kind']),
            models.Index(fields=['status']),
            models.Index(fields=['provider']),
            models.Index(fields=['api_key']),
            models.Index(fields=['user']),
            # Composite index for efficient queries on API key by time range
            models.Index(fields=['api_key', 'created_at']),
            # Composite index for provider and status by time
            models.Index(fields=['provider', 'status', 'created_at']),
        ]
        ordering = ['-created_at']

    @classmethod
    def log_request(cls, **kwargs):
        """Create a request log entry while tolerating legacy no-longer-used kwargs."""
        normalized = dict(kwargs)

        if 'model' in normalized and 'model_name' not in normalized:
            normalized['model_name'] = normalized.pop('model')
        if 'input_text' in normalized and 'input_chars' not in normalized:
            normalized['input_chars'] = len(normalized.get('input_text') or '')
        if 'response_data' in normalized and 'output_chars' not in normalized:
            normalized['output_chars'] = len(str(normalized.get('response_data') or ''))

        normalized.pop('input_text', None)
        normalized.pop('response_data', None)

        normalized.setdefault('endpoint', '/api/code-editor/unknown')
        normalized.setdefault('provider', 'unknown')
        normalized.setdefault('model_name', 'unknown')
        normalized.setdefault('request_kind', 'chat')
        normalized.setdefault('status', 'success')
        normalized.setdefault('input_chars', 0)
        normalized.setdefault('output_chars', 0)

        allowed_fields = {field.name for field in cls._meta.fields}
        filtered = {key: value for key, value in normalized.items() if key in allowed_fields}
        try:
            entry = cls.objects.create(**filtered)
        except Exception:
            return None
        # Instrumentation: structured logging, metrics and provider health
        try:
            # Structured logging: emit a JSON log with context
            from code_editor.observability.logging_utils import log_event  # type: ignore
            # Prometheus metrics: counters and histograms from observability package
            from code_editor.observability.metrics import (
                REQUEST_COUNT,
                REQUEST_LATENCY,
                INPUT_TOKENS,
                OUTPUT_TOKENS,
            )  # type: ignore
            # Update provider health snapshot.  Import from current module to avoid circular import issues.
            status_map = {
                'success': 'healthy',
                'error': 'unhealthy',
                'rate_limited': 'degraded',
                'quota_exceeded': 'degraded',
            }
            provider_name = entry.provider or 'unknown'
            health_status = status_map.get(entry.status, 'unknown')
            # Update or create ProviderHealth record
            ProviderHealth.objects.update_or_create(
                provider_name=provider_name,
                defaults={
                    'status': health_status,
                    'response_time_ms': entry.latency_ms,
                    'error_message': entry.error_message or '',
                },
            )
            # Increment request counter
            try:
                if REQUEST_COUNT is not None:
                    REQUEST_COUNT.labels(
                        endpoint=entry.endpoint,
                        method=entry.request_kind,
                        status=entry.status,
                    ).inc()
            except Exception:
                pass
            # Observe latency if present
            try:
                if entry.latency_ms is not None and REQUEST_LATENCY is not None:
                    REQUEST_LATENCY.labels(
                        endpoint=entry.endpoint,
                        method=entry.request_kind,
                    ).observe(entry.latency_ms / 1000.0)
            except Exception:
                pass
            # Count input/output tokens (approximate by characters)
            try:
                if INPUT_TOKENS is not None:
                    INPUT_TOKENS.labels(
                        provider=provider_name,
                        request_type=entry.request_kind,
                    ).inc(entry.input_chars)
            except Exception:
                pass
            try:
                if OUTPUT_TOKENS is not None:
                    OUTPUT_TOKENS.labels(
                        provider=provider_name,
                        request_type=entry.request_kind,
                    ).inc(entry.output_chars)
            except Exception:
                pass
            # Emit structured log event with context.  Use API key prefix to avoid exposing full key.
            api_key_prefix = None
            try:
                if entry.api_key and getattr(entry.api_key, 'prefix', None):
                    api_key_prefix = entry.api_key.prefix
            except Exception:
                api_key_prefix = None
            log_event(
                'provider_call',
                endpoint=entry.endpoint,
                provider=provider_name,
                model=entry.model_name,
                request_kind=entry.request_kind,
                status=entry.status,
                latency_ms=entry.latency_ms,
                input_chars=entry.input_chars,
                output_chars=entry.output_chars,
                api_key_prefix=api_key_prefix,
                user_id=entry.user_id,
            )
            # Invalidate provider health cache after updating provider record
            try:
                from code_editor.services.cache_helper import CacheHelper
                CacheHelper.invalidate_provider_health_cache()
            except Exception:
                pass
        except Exception:
            # Never let instrumentation failures surface to callers.
            pass
        return entry


class Project(models.Model):
    """Project/workspace for organizing codebases in local single-user mode."""

    name = models.CharField(max_length=255, help_text="Project name")
    description = models.TextField(blank=True, help_text="Project description")
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'code_editor_project'
        indexes = [
            # Index active flag for quick filtering
            models.Index(fields=['is_active']),
            # Index creation timestamp for sorting and filtering
            models.Index(fields=['created_at']),
            # Index name for efficient lookup by project name
            models.Index(fields=['name']),
        ]
        ordering = ['-created_at']

    def __str__(self):
        return self.name


class Repository(models.Model):
    """Repository containing indexed code"""
    
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name='repositories')
    name = models.CharField(max_length=255, help_text="Repository name")
    url = models.URLField(help_text="Repository URL")
    # Default branch configured for this repository.  When syncing from a remote
    # source this is the branch that will be checked out.  Local repositories
    # are read directly from the file system and the branch has no effect.
    branch = models.CharField(max_length=100, default='main', help_text="Git branch")
    # How the repository is accessed.  ``local`` indicates a file system path
    # starting with ``file://``.  ``public`` and ``private`` represent remote
    # Git repositories accessible via HTTP(S).  Private repositories require
    # credentials which are never stored directly in this model.
    access_type = models.CharField(
        max_length=20,
        choices=[
            ('public', 'Public'),
            ('private', 'Private'),
            ('local', 'Local')
        ],
        default='public'
    )

    # Version control system provider.  Today only ``git`` is supported but
    # additional systems (e.g. Mercurial) may be added later.  This value is
    # used by the sync service to decide how to clone/fetch the repository.
    vcs_provider = models.CharField(
        max_length=20,
        choices=[
            ('git', 'Git'),
            ('hg', 'Mercurial'),
            ('unknown', 'Unknown'),
        ],
        default='git',
        help_text="Version control system provider",
    )

    # Commit SHA of the last successfully synced state.  This field is updated
    # whenever the sync service fetches a new commit.  For local repositories
    # this may be empty.
    commit_sha = models.CharField(
        max_length=64,
        blank=True,
        help_text="Current commit SHA after last sync"
    )
    # Timestamp of the last successful sync operation.  Updated by the sync
    # management command and repository service when remote repositories are
    # cloned or fetched.  Remains null until the first sync occurs.
    last_synced_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="When this repository was last synced from its remote source"
    )
    # Status of the last sync operation.  ``pending`` means the repository has
    # not yet been synced; ``syncing`` indicates a sync is in progress;
    # ``synced`` indicates the repository is up to date; ``failed`` means the
    # last sync encountered an error.  A failed sync stores its message in
    # ``sync_error``.
    sync_status = models.CharField(
        max_length=20,
        choices=[
            ('pending', 'Pending'),
            ('syncing', 'Syncing'),
            ('synced', 'Synced'),
            ('failed', 'Failed'),
        ],
        default='pending',
        help_text="Remote sync status",
    )
    # Human‑readable error message from the last sync attempt, if any.
    sync_error = models.TextField(
        blank=True,
        help_text="Error message if the last sync failed",
    )
    # Optional key referencing a secret or environment variable containing
    # authentication credentials for private repositories.  No raw tokens
    # should be stored here; the sync service will resolve this key at runtime.
    credential_key = models.CharField(
        max_length=255,
        blank=True,
        help_text="Environment or secret key name for repository credentials",
    )
    # Path on the local filesystem where the repository has been cloned.  This
    # path is assigned by the sync service based on configuration and is used
    # by the ingestion service to read files.  For local repositories this
    # remains empty because the URL points directly to the directory.
    storage_path = models.TextField(
        blank=True,
        help_text="Local clone path for remote repository",
    )
    # Count of all chunks indexed for this repository.  Updated by the
    # ingestion service after indexing completes.  Defaults to zero.
    indexed_chunk_count = models.IntegerField(
        default=0,
        help_text="Number of code chunks indexed for this repository",
    )
    
    # Indexing status
    last_indexed_at = models.DateTimeField(null=True, blank=True, help_text="When this repository was last indexed")
    indexing_status = models.CharField(
        max_length=20,
        choices=[
            ('pending', 'Pending'),
            ('indexing', 'Indexing'),
            ('completed', 'Completed'),
            ('failed', 'Failed'),
            ('partial', 'Partial'),
        ],
        default='pending',
        help_text="Status of the latest indexing operation"
    )
    indexing_error = models.TextField(
        blank=True,
        help_text="Error message if indexing failed or partially succeeded",
    )
    file_count = models.IntegerField(
        default=0,
        help_text="Number of files indexed in the last successful indexing",
    )
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = 'code_editor_repository'
        indexes = [
            models.Index(fields=['project']),
            models.Index(fields=['indexing_status']),
            models.Index(fields=['last_indexed_at']),
            # Index sync status for faster admin filtering
            models.Index(fields=['sync_status']),
            # Index repository URL for lookup and deduplication
            models.Index(fields=['url']),
            # Index branch and vcs_provider for remote sync operations
            models.Index(fields=['branch']),
            models.Index(fields=['vcs_provider']),
            # Index commit SHA to quickly find the latest synced commit
            models.Index(fields=['commit_sha']),
            # Composite index for workspace/project state by sync and indexing status
            models.Index(fields=['project', 'sync_status', 'indexing_status']),
        ]
        unique_together = [['project', 'name']]

    def __str__(self):
        return f"{self.project.name}/{self.name}"

    def save(self, *args, **kwargs):
        if self.access_type == 'local' and not self.storage_path:
            candidate = self.url or ''
            if candidate.startswith('file://'):
                candidate = urlparse(candidate).path or candidate.replace('file://', '', 1)
            if candidate:
                self.storage_path = str(Path(candidate).expanduser().resolve())
        super().save(*args, **kwargs)


class IndexedFile(models.Model):
    """File that has been indexed"""
    
    repository = models.ForeignKey(Repository, on_delete=models.CASCADE, related_name='indexed_files')
    file_path = models.TextField(help_text="Relative file path in repository")
    file_hash = models.CharField(max_length=64, help_text="SHA-256 hash of file content")
    file_size = models.IntegerField(help_text="File size in bytes")
    language = models.CharField(max_length=50, blank=True, help_text="Detected programming language")
    last_modified = models.DateTimeField(help_text="File last modification time")
    indexed_at = models.DateTimeField(auto_now_add=True, help_text="Indexed at")
    
    class Meta:
        db_table = 'code_editor_indexed_file'
        indexes = [
            models.Index(fields=['repository']),
            models.Index(fields=['file_path']),
            models.Index(fields=['language']),
            models.Index(fields=['indexed_at']),
            # Composite index for repository, language and indexed_at for queries on language per repo over time
            models.Index(fields=['repository', 'language', 'indexed_at']),
            # Composite index on repository and file_path for deduplication and retrieval
            models.Index(fields=['repository', 'file_path']),
        ]
        unique_together = [['repository', 'file_path']]

    def __str__(self):
        return f"{self.repository.name}:{self.file_path}"


class CodeChunk(models.Model):
    """Chunk of indexed code"""
    
    indexed_file = models.ForeignKey(IndexedFile, on_delete=models.CASCADE, related_name='chunks')
    chunk_index = models.IntegerField(help_text="Chunk order within file")
    content = models.TextField(help_text="Chunk content")
    start_line = models.IntegerField(null=True, blank=True, help_text="Starting line number")
    end_line = models.IntegerField(null=True, blank=True, help_text="Ending line number")
    chunk_type = models.CharField(
        max_length=20,
        choices=[
            ('code', 'Code'),
            ('comment', 'Comment'),
            ('docstring', 'Docstring'),
            ('import', 'Import'),
            ('function', 'Function'),
            ('class', 'Class')
        ],
        default='code'
    )
    token_count = models.IntegerField(default=0, help_text="Estimated token count")
    created_at = models.DateTimeField(auto_now_add=True, help_text="Created at")

    # Optional name of the primary symbol represented by this chunk (e.g. function or class name).
    # This field is nullable because many chunks do not correspond to a specific symbol.
    symbol_name = models.CharField(
        max_length=255,
        null=True,
        blank=True,
        help_text="Function or class name if applicable",
    )
    
    # Vector embedding (may be null until generated). Use pgvector's VectorField when available.
    embedding = VectorField(
        dimensions=1536,
        null=True,
        blank=True,
        help_text="Vector embedding of chunk content (1536-dim). Set after deferred generation."
    )
    embedding_model = models.CharField(
        max_length=100,
        default='BAAI/bge-small-en-v1.5',
        help_text="Model used to generate embedding"
    )
    
    class Meta:
        db_table = 'code_editor_code_chunk'
        # Define indexes for efficient retrieval. Avoid referencing undefined fields (e.g., language).
        indexes = [
            models.Index(fields=['indexed_file']),
            models.Index(fields=['chunk_type']),
            models.Index(fields=['created_at']),
            # Index symbol_name for faster lookup when available
            models.Index(fields=['symbol_name']),
            # Composite index to speed up chunk ordering and retrieval per file and type
            models.Index(fields=['indexed_file', 'chunk_type', 'chunk_index']),
            # Additional composite index on indexed_file and symbol_name for quickly
            # retrieving chunks by symbol scoped to a particular file/repository.  This
            # supports symbol‑based searches without requiring full scans.
            models.Index(fields=['indexed_file', 'symbol_name'], name='chunk_file_symbol_idx'),
        ]
        # Add a vector index for similarity search if pgvector is available
        if HnswIndex:
            indexes.append(
                HnswIndex(
                    name="code_editor_chunk_embedding_idx",
                    fields=["embedding"],
                    m=16,
                    ef_construction=64,
                    opclasses=["vector_cosine_ops"],
                )
            )
        unique_together = [['indexed_file', 'chunk_index']]

    def __str__(self):
        return f"{self.indexed_file.file_path}:{self.chunk_index}"


class IngestionJob(models.Model):
    """Background job for repository ingestion"""
    
    repository = models.ForeignKey(Repository, on_delete=models.CASCADE, related_name='ingestion_jobs')
    job_id = models.CharField(max_length=100, unique=True, help_text="Celery job ID")
    status = models.CharField(
        max_length=20,
        choices=[
            ('pending', 'Pending'),
            ('running', 'Running'),
            ('completed', 'Completed'),
            ('failed', 'Failed'),
            ('cancelled', 'Cancelled')
        ],
        default='pending'
    )
    progress = models.IntegerField(default=0, help_text="Progress percentage (0-100)")
    files_processed = models.IntegerField(default=0, help_text="Number of files processed")
    chunks_created = models.IntegerField(default=0, help_text="Number of chunks created")
    error_message = models.TextField(blank=True, help_text="Error message if failed")
    started_at = models.DateTimeField(null=True, blank=True, help_text="Started at")
    completed_at = models.DateTimeField(null=True, blank=True, help_text="Completed at")
    created_at = models.DateTimeField(auto_now_add=True, help_text="Created at")
    
    class Meta:
        db_table = 'code_editor_ingestion_job'
        indexes = [
            models.Index(fields=['repository']),
            models.Index(fields=['status']),
            models.Index(fields=['created_at']),
        ]

    def __str__(self):
        return f"{self.repository.name}:{self.job_id}"


class ProviderHealth(models.Model):
    """Health status of AI providers"""
    
    provider_name = models.CharField(max_length=50, help_text="Provider identifier")
    status = models.CharField(
        max_length=20,
        choices=[
            ('healthy', 'Healthy'),
            ('degraded', 'Degraded'),
            ('unhealthy', 'Unhealthy'),
            ('unknown', 'Unknown'),
        ],
        help_text="Health status"
    )
    response_time_ms = models.IntegerField(null=True, blank=True, help_text="Last response time in milliseconds")
    error_message = models.TextField(blank=True, help_text="Last error message")
    last_check = models.DateTimeField(auto_now=True, help_text="Last check")
    
    class Meta:
        db_table = 'code_editor_provider_health'
        indexes = [
            models.Index(fields=['provider_name']),
            models.Index(fields=['status']),
            models.Index(fields=['last_check']),
        ]
        unique_together = [['provider_name']]

    def __str__(self):
        return f"{self.provider_name}:{self.status}"


# -----------------------------------------------------------------------------
# Task orchestration models
#
# These models provide the persisted task engine foundation for the
# autonomous coding workflow. They intentionally capture more structure than
# the current executor uses today so future planning, candidate generation,
# validation and rollback stages can evolve without another schema reset.


class TaskRun(models.Model):
    """Persisted lifecycle record for a single autonomous task run."""

    TASK_TYPES = [
        ('feature', 'Feature'),
        ('bugfix', 'Bug Fix'),
        ('refactor', 'Refactor'),
        ('test', 'Test Generation'),
        ('migration', 'Migration'),
        ('convert', 'Convert'),
        ('analysis', 'Analysis'),
        ('custom', 'Custom'),
    ]
    # Status values for a task.  These have been expanded to clearly indicate
    # intermediate stages, review states and failure categories.  When adding
    # or renaming statuses, ensure you update any logic that checks for
    # specific strings (e.g. is_terminal) and keep backwards compatibility
    # where possible.
    STATUS_CHOICES = [
        ('queued', 'Queued'),
        ('planning', 'Planning'),
        ('retrieving_context', 'Retrieving Context'),
        # File selection and context retrieval may be combined; keep a separate
        # stage for clarity.
        ('selecting_files', 'Selecting Files'),
        # Generate candidate patches – previously called generating_patch_candidates
        ('generating_patch', 'Generating Patch'),
        # Apply a selected candidate to the isolated workspace
        ('applying_patch', 'Applying Patch'),
        # Run validation on the applied patch
        ('validating', 'Validating'),
        # Score candidates based on multiple criteria
        ('scoring', 'Scoring'),
        # Persist artifacts and snapshots to storage
        ('saving_artifacts', 'Saving Artifacts'),
        # Awaiting manual review before applying the patch
        ('awaiting_review', 'Awaiting Review'),
        # Validation failed (e.g. tests did not pass)
        ('validation_failed', 'Validation Failed'),
        # Completed but warnings were detected (e.g. non-blocking lint issues)
        ('completed_with_warnings', 'Completed with Warnings'),
        ('completed', 'Completed'),
        ('failed', 'Failed'),
        ('cancel_requested', 'Cancel Requested'),
        ('cancelled', 'Cancelled'),
        ('rollback_pending', 'Rollback Pending'),
        ('rolled_back', 'Rolled Back'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    repository = models.ForeignKey(
        'Repository',
        on_delete=models.CASCADE,
        related_name='task_runs',
        help_text='Repository on which this task operates',
    )
    task_type = models.CharField(max_length=20, choices=TASK_TYPES, default='custom')
    instruction = models.TextField(help_text='Primary user instruction for the task')
    status = models.CharField(max_length=32, choices=STATUS_CHOICES, default='queued')
    current_stage = models.CharField(max_length=64, blank=True, help_text='Current stage key when available')
    request_payload = models.JSONField(default=dict, blank=True, help_text='Structured request payload')
    result_payload = models.JSONField(default=dict, blank=True, help_text='Structured result payload')
    config = models.JSONField(default=dict, blank=True, help_text='Execution configuration and task options')
    summary = models.TextField(blank=True, help_text='Latest or final high-level summary')
    result_summary = models.TextField(blank=True, help_text='Final result summary')
    workspace_path = models.TextField(
        blank=True,
        help_text='Server-owned workspace path for this task run',
    )
    error_message = models.TextField(blank=True, help_text='Error message if the task failed')
    error_details = models.JSONField(default=dict, blank=True, help_text='Structured error details')
    launched_via = models.CharField(max_length=32, blank=True, help_text='thread, celery, or other launch mode')
    runner_job_id = models.CharField(max_length=255, blank=True, help_text='Queue job identifier when applicable')
    cancellation_requested = models.BooleanField(default=False)
    cancellation_reason = models.TextField(blank=True)
    cancellation_requested_at = models.DateTimeField(null=True, blank=True)
    cancelled_at = models.DateTimeField(null=True, blank=True)
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    last_heartbeat_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    # The high‑level reason for failure when a task ends unsuccessfully.  This
    # helps operators understand why a task stopped.  Valid values are
    # documented in docs and include: provider_failure, no_repository_files,
    # context_retrieval_failure, patch_generation_failure, patch_apply_failure,
    # validation_failure, cancellation, permission_denied, quota_exceeded,
    # workspace_setup_failure.
    failure_reason = models.CharField(
        max_length=64,
        blank=True,
        help_text='Categorical failure reason when the task does not complete successfully',
    )

    # Apply mode requested by the user or policy.  This determines whether a
    # generated patch is proposed, drafted, applied in the workspace, auto applied
    # after validation, or requires manual approval.
    APPLY_MODE_CHOICES = [
        ('suggest', 'Suggest'),
        ('draft_patch', 'Draft Patch'),
        ('apply_to_workspace', 'Apply to Workspace'),
        ('auto_apply_if_validated', 'Auto Apply If Validated'),
        ('manual_approval_required', 'Manual Approval Required'),
    ]
    requested_apply_mode = models.CharField(
        max_length=32,
        choices=APPLY_MODE_CHOICES,
        default='suggest',
        help_text='Requested apply mode for generated patches',
    )
    # The effective apply mode used during execution after policy evaluation.
    effective_apply_mode = models.CharField(
        max_length=32,
        choices=APPLY_MODE_CHOICES,
        default='suggest',
        help_text='Effective apply mode used after applying policy decisions',
    )
    # Approval status for the task.  When a patch is proposed and manual
    # approval is required, this field tracks whether the patch was approved or
    # rejected and by whom.  The default pending state indicates no decision
    # has been made yet.
    APPROVAL_STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('approved', 'Approved'),
        ('rejected', 'Rejected'),
    ]
    approval_status = models.CharField(
        max_length=16,
        choices=APPROVAL_STATUS_CHOICES,
        default='pending',
        help_text='Approval status for manual review of the task result',
    )
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='approved_tasks',
    )
    approved_at = models.DateTimeField(null=True, blank=True)
    rejected_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='rejected_tasks',
    )
    rejected_at = models.DateTimeField(null=True, blank=True)
    rejection_reason = models.TextField(blank=True)

    class Meta:
        db_table = 'code_editor_task_run'
        indexes = [
            models.Index(fields=['repository']),
            models.Index(fields=['task_type']),
            models.Index(fields=['status']),
            models.Index(fields=['created_at']),
            models.Index(fields=['started_at']),
            models.Index(fields=['workspace_path']),
            # Index approval_status to efficiently query pending tasks for review
            models.Index(fields=['approval_status']),
            # Index effective apply mode for policy analysis
            models.Index(fields=['effective_apply_mode']),
            models.Index(fields=['requested_apply_mode']),
            # Composite index on repository, status and created_at for efficient filtering
            models.Index(fields=['repository', 'status', 'created_at']),
        ]
        ordering = ['-created_at']

    def __str__(self) -> str:
        return f"Task {self.id} ({self.task_type}) - {self.status}"

    @property
    def is_terminal(self) -> bool:
        """Return True if the task is in a terminal state.

        Terminal states include all statuses where no further processing
        should occur automatically.  Tasks awaiting review are not considered
        terminal because manual approval may still transition them to an
        applied state.  Completed_with_warnings and validation_failed are
        terminal because there is no automatic continuation.
        """
        return self.status in {
            'completed',
            'completed_with_warnings',
            'validation_failed',
            'failed',
            'cancelled',
            'rolled_back',
        }


class TaskStep(models.Model):
    """Ordered execution record for an individual task stage."""

    STATUS_CHOICES = TaskRun.STATUS_CHOICES

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    task = models.ForeignKey(TaskRun, on_delete=models.CASCADE, related_name='steps')
    name = models.CharField(max_length=64, help_text='Stage or step name')
    order = models.PositiveIntegerField(help_text='Execution order starting at zero')
    status = models.CharField(max_length=32, choices=STATUS_CHOICES, default='queued')
    summary = models.TextField(blank=True, help_text='Short summary of what happened in this step')
    logs = models.TextField(blank=True, help_text='Accumulated human-readable logs')
    metadata = models.JSONField(default=dict, blank=True, help_text='Structured step metadata')
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'code_editor_task_step'
        ordering = ['task_id', 'order']
        constraints = [
            models.UniqueConstraint(fields=['task', 'order'], name='code_editor_task_step_unique_order'),
        ]
        indexes = [
            models.Index(fields=['task']),
            models.Index(fields=['status']),
            models.Index(fields=['name']),
        ]

    def __str__(self) -> str:
        return f"{self.task_id}:{self.order}:{self.name}"


class PlanNode(models.Model):
    """Decomposition node recorded during planning."""

    STATUS_CHOICES = [
        ('planned', 'Planned'),
        ('in_progress', 'In Progress'),
        ('completed', 'Completed'),
        ('skipped', 'Skipped'),
        ('failed', 'Failed'),
        ('blocked', 'Blocked'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    task = models.ForeignKey(TaskRun, on_delete=models.CASCADE, related_name='plan_nodes')
    parent = models.ForeignKey('self', null=True, blank=True, on_delete=models.CASCADE, related_name='children')
    node_key = models.CharField(max_length=100)
    title = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    action_type = models.CharField(max_length=64, blank=True)
    order = models.PositiveIntegerField(default=0)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='planned')
    depends_on = models.JSONField(default=list, blank=True, help_text='Dependency node keys or ids')
    metadata = models.JSONField(default=dict, blank=True, help_text='Structured planning metadata')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'code_editor_plan_node'
        ordering = ['task_id', 'order', 'created_at']
        constraints = [
            models.UniqueConstraint(fields=['task', 'node_key'], name='code_editor_plan_node_unique_key'),
        ]
        indexes = [
            models.Index(fields=['task']),
            models.Index(fields=['parent']),
            models.Index(fields=['status']),
        ]

    def __str__(self) -> str:
        return f"{self.task_id}:{self.node_key}"


class SelectedFile(models.Model):
    """Repository file chosen as relevant for a task."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    task = models.ForeignKey(TaskRun, on_delete=models.CASCADE, related_name='selected_files')
    repository = models.ForeignKey('Repository', on_delete=models.CASCADE, related_name='selected_files')
    indexed_file = models.ForeignKey('IndexedFile', null=True, blank=True, on_delete=models.SET_NULL, related_name='task_selections')
    plan_node = models.ForeignKey(PlanNode, null=True, blank=True, on_delete=models.SET_NULL, related_name='selected_files')
    path = models.TextField(help_text='Repository-relative file path')
    why_selected = models.TextField(blank=True)
    selection_score = models.FloatField(default=0.0)
    rank = models.PositiveIntegerField(default=0)
    evidence = models.JSONField(default=dict, blank=True, help_text='Ranking evidence and source metadata')
    symbol_hints = models.JSONField(default=list, blank=True, help_text='Potential symbols relevant to the task')
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'code_editor_selected_file'
        ordering = ['task_id', 'rank', 'created_at']
        constraints = [
            models.UniqueConstraint(fields=['task', 'path'], name='code_editor_selected_file_unique_path'),
        ]
        indexes = [
            models.Index(fields=['task']),
            models.Index(fields=['repository']),
            models.Index(fields=['rank']),
        ]

    def __str__(self) -> str:
        return f"{self.task_id}:{self.path}"


class CandidatePatch(models.Model):
    """Candidate patch proposal tracked for a task."""

    STATUS_CHOICES = [
        ('draft', 'Draft'),
        ('generated', 'Generated'),
        ('applied', 'Applied'),
        ('validated', 'Validated'),
        ('selected', 'Selected'),
        ('rejected', 'Rejected'),
        ('failed', 'Failed'),
        ('rolled_back', 'Rolled Back'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    task = models.ForeignKey(TaskRun, on_delete=models.CASCADE, related_name='candidate_patches')
    plan_node = models.ForeignKey(PlanNode, null=True, blank=True, on_delete=models.SET_NULL, related_name='candidate_patches')
    candidate_key = models.CharField(max_length=100, help_text='Stable candidate identifier within a task run')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='draft')
    summary = models.TextField(blank=True)
    patch_metadata = models.JSONField(default=dict, blank=True)
    touched_files = models.JSONField(default=list, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    selected_at = models.DateTimeField(null=True, blank=True)

    # Apply mode requested for this candidate.  This mirrors the TaskRun
    # apply mode but allows per-candidate overrides when multiple patches
    # are generated.  See TaskRun.APPLY_MODE_CHOICES for definitions.
    apply_mode_requested = models.CharField(
        max_length=32,
        choices=TaskRun.APPLY_MODE_CHOICES,
        default='suggest',
        help_text='Requested apply mode for this candidate patch',
    )
    # The effective apply mode after policy decisions.  This may differ
    # from the requested apply mode if policy restricts or overrides the
    # request (e.g. auto apply not permitted on a sensitive repository).
    apply_mode_effective = models.CharField(
        max_length=32,
        choices=TaskRun.APPLY_MODE_CHOICES,
        default='suggest',
        help_text='Effective apply mode for this candidate after policy evaluation',
    )
    # Approval status for the candidate.  When manual review is required
    # this tracks whether the candidate has been approved or rejected and by
    # whom.  Pending indicates no decision yet.
    APPROVAL_STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('approved', 'Approved'),
        ('rejected', 'Rejected'),
    ]
    approval_status = models.CharField(
        max_length=16,
        choices=APPROVAL_STATUS_CHOICES,
        default='pending',
        help_text='Approval status for this candidate patch',
    )
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='approved_candidate_patches',
    )
    approved_at = models.DateTimeField(null=True, blank=True)
    rejected_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='rejected_candidate_patches',
    )
    rejected_at = models.DateTimeField(null=True, blank=True)
    rejection_reason = models.TextField(blank=True)

    class Meta:
        db_table = 'code_editor_candidate_patch'
        ordering = ['task_id', 'created_at']
        constraints = [
            models.UniqueConstraint(fields=['task', 'candidate_key'], name='code_editor_candidate_patch_unique_key'),
        ]
        indexes = [
            models.Index(fields=['task']),
            models.Index(fields=['status']),
            # Index approval status for faster bulk approval/rejection queries
            models.Index(fields=['approval_status']),
            # Index effective apply mode for analytics
            models.Index(fields=['apply_mode_effective']),
            # Composite index on task, status and selected_at for analysis and filtering
            models.Index(fields=['task', 'status', 'selected_at']),
        ]

    def __str__(self) -> str:
        return f"{self.task_id}:{self.candidate_key}"


class CandidateScore(models.Model):
    """Scoring summary for an individual candidate patch."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    task = models.ForeignKey(TaskRun, on_delete=models.CASCADE, related_name='candidate_scores')
    candidate_patch = models.OneToOneField(CandidatePatch, on_delete=models.CASCADE, related_name='score')
    syntax_score = models.FloatField(default=0.0)
    validation_score = models.FloatField(default=0.0)
    relevance_score = models.FloatField(default=0.0)
    risk_score = models.FloatField(default=0.0)
    quality_score = models.FloatField(default=0.0)
    final_score = models.FloatField(default=0.0)
    rank = models.PositiveIntegerField(default=0)
    scoring_metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'code_editor_candidate_score'
        ordering = ['task_id', 'rank', '-final_score']
        indexes = [
            models.Index(fields=['task']),
            models.Index(fields=['rank']),
            models.Index(fields=['final_score']),
        ]

    def __str__(self) -> str:
        return f"Score {self.candidate_patch_id}={self.final_score}"


class ValidationRun(models.Model):
    """Validation command execution linked to a task and optionally a candidate."""

    STATUS_CHOICES = [
        ('queued', 'Queued'),
        ('running', 'Running'),
        ('passed', 'Passed'),
        ('failed', 'Failed'),
        ('error', 'Error'),
        ('skipped', 'Skipped'),
        ('cancelled', 'Cancelled'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    task = models.ForeignKey(TaskRun, on_delete=models.CASCADE, related_name='validation_runs')
    step = models.ForeignKey(TaskStep, null=True, blank=True, on_delete=models.SET_NULL, related_name='validation_runs')
    candidate_patch = models.ForeignKey(CandidatePatch, null=True, blank=True, on_delete=models.SET_NULL, related_name='validation_runs')
    stage_name = models.CharField(max_length=100)
    validation_type = models.CharField(max_length=64, default='command')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='queued')
    command = models.TextField(blank=True)
    exit_code = models.IntegerField(null=True, blank=True)
    output = models.TextField(blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    duration_ms = models.PositiveIntegerField(null=True, blank=True)
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'code_editor_validation_run'
        ordering = ['task_id', 'created_at']
        indexes = [
            models.Index(fields=['task']),
            models.Index(fields=['status']),
            models.Index(fields=['stage_name']),
            # Composite index on task, status and created_at for query performance
            models.Index(fields=['task', 'status', 'created_at']),
        ]

    def __str__(self) -> str:
        return f"{self.task_id}:{self.stage_name}:{self.status}"


class TestRun(models.Model):
    """Tracked targeted or regression test execution."""

    RUN_TYPES = [
        ('targeted', 'Targeted'),
        ('regression', 'Regression'),
        ('smoke', 'Smoke'),
        ('custom', 'Custom'),
    ]
    STATUS_CHOICES = [
        ('queued', 'Queued'),
        ('running', 'Running'),
        ('passed', 'Passed'),
        ('failed', 'Failed'),
        ('error', 'Error'),
        ('skipped', 'Skipped'),
        ('cancelled', 'Cancelled'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    task = models.ForeignKey(TaskRun, on_delete=models.CASCADE, related_name='test_runs')
    candidate_patch = models.ForeignKey(CandidatePatch, null=True, blank=True, on_delete=models.SET_NULL, related_name='test_runs')
    validation_run = models.ForeignKey(ValidationRun, null=True, blank=True, on_delete=models.SET_NULL, related_name='test_runs')
    run_type = models.CharField(max_length=20, choices=RUN_TYPES, default='regression')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='queued')
    test_command = models.TextField(blank=True)
    targeted_paths = models.JSONField(default=list, blank=True)
    total_tests = models.PositiveIntegerField(default=0)
    passed_tests = models.PositiveIntegerField(default=0)
    failed_tests = models.PositiveIntegerField(default=0)
    skipped_tests = models.PositiveIntegerField(default=0)
    output = models.TextField(blank=True)
    # Exit code from the executed test command.  A zero value indicates
    # success, non-zero indicates failure or error.  Persisting this
    # explicitly avoids writing arbitrary fields into the model via
    # attribute assignment.
    exit_code = models.IntegerField(null=True, blank=True)
    duration_ms = models.PositiveIntegerField(null=True, blank=True)
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'code_editor_test_run'
        ordering = ['task_id', 'created_at']
        indexes = [
            models.Index(fields=['task']),
            models.Index(fields=['status']),
            models.Index(fields=['run_type']),
            # Composite index on task, status and created_at for query performance
            models.Index(fields=['task', 'status', 'created_at']),
        ]

    def __str__(self) -> str:
        return f"{self.task_id}:{self.run_type}:{self.status}"


class WorkspaceSnapshot(models.Model):
    """Restorable workspace snapshot or rollback point."""

    STATUS_CHOICES = [
        ('created', 'Created'),
        ('restored', 'Restored'),
        ('failed', 'Failed'),
    ]
    SNAPSHOT_TYPES = [
        ('baseline', 'Baseline'),
        ('pre_apply', 'Pre Apply'),
        ('post_apply', 'Post Apply'),
        ('rollback', 'Rollback'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    task = models.ForeignKey(TaskRun, on_delete=models.CASCADE, related_name='workspace_snapshots')
    candidate_patch = models.ForeignKey(CandidatePatch, null=True, blank=True, on_delete=models.SET_NULL, related_name='workspace_snapshots')
    snapshot_type = models.CharField(max_length=20, choices=SNAPSHOT_TYPES, default='baseline')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='created')
    root_path = models.TextField(help_text='Filesystem path to the snapshot root or archive')
    metadata = models.JSONField(default=dict, blank=True)
    restore_error = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    restored_at = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'code_editor_workspace_snapshot'
        ordering = ['task_id', 'created_at']
        indexes = [
            models.Index(fields=['task']),
            models.Index(fields=['status']),
            models.Index(fields=['snapshot_type']),
        ]

    def __str__(self) -> str:
        return f"{self.task_id}:{self.snapshot_type}:{self.status}"


class Artifact(models.Model):
    """Artifact produced during task execution."""

    ARTIFACT_TYPES = [
        ('plan', 'Plan Document'),
        ('context', 'Context Data'),
        ('selection', 'Selected Files'),
        ('patch', 'Patch'),
        ('log', 'Log Output'),
        ('test', 'Test Report'),
        ('result', 'Result'),
        ('report', 'Report'),
        ('diff_bundle', 'Diff Bundle'),
        ('snapshot', 'Snapshot'),
        # Added to support validation run outputs
        ('validation', 'Validation Report'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    task = models.ForeignKey(TaskRun, on_delete=models.CASCADE, related_name='artifacts')
    step = models.ForeignKey(TaskStep, null=True, blank=True, on_delete=models.SET_NULL, related_name='artifacts')
    candidate_patch = models.ForeignKey(CandidatePatch, null=True, blank=True, on_delete=models.SET_NULL, related_name='artifacts')
    validation_run = models.ForeignKey(ValidationRun, null=True, blank=True, on_delete=models.SET_NULL, related_name='artifacts')
    test_run = models.ForeignKey(TestRun, null=True, blank=True, on_delete=models.SET_NULL, related_name='artifacts')
    workspace_snapshot = models.ForeignKey(WorkspaceSnapshot, null=True, blank=True, on_delete=models.SET_NULL, related_name='artifacts')
    artifact_type = models.CharField(max_length=32, choices=ARTIFACT_TYPES)
    name = models.CharField(max_length=255, blank=True)
    description = models.TextField(blank=True)
    file_path = models.TextField(blank=True, help_text='Filesystem path where the artifact is stored')
    text_content = models.TextField(blank=True, help_text='Inline textual content when stored directly')
    content_type = models.CharField(max_length=255, blank=True)
    size_bytes = models.BigIntegerField(null=True, blank=True)
    sha256 = models.CharField(max_length=64, blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'code_editor_task_artifact'
        ordering = ['created_at']
        indexes = [
            models.Index(fields=['task']),
            models.Index(fields=['artifact_type']),
            models.Index(fields=['created_at']),
        ]

    def __str__(self) -> str:
        label = self.name or self.artifact_type
        return f"{label} for {self.task_id}"
