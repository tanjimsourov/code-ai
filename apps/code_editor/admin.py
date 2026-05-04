from django.contrib import admin
"""Django admin configuration for Code Editor models.

This module registers all core models with the Django admin and
configures their list displays, filters, search fields and read‑only
fields to make the administrative interface safe and usable in
production.  Sensitive fields such as raw API keys, long logs and
patch contents are hidden or truncated.  When adding new models to
the project ensure they are registered here with appropriate
configuration.
"""

from django.utils.html import format_html

from .models import (
    Project,
    Repository,
    IndexedFile,
    CodeChunk,
    IngestionJob,
    CodeEditorApiKey,
    CodeEditorRequestLog,
    ProviderHealth,
    TaskRun,
    TaskStep,
    PlanNode,
    SelectedFile,
    CandidatePatch,
    CandidateScore,
    ValidationRun,
    TestRun,
    WorkspaceSnapshot,
    Artifact,
)


@admin.register(Project)
class ProjectAdmin(admin.ModelAdmin):
    list_display = ('name', 'description', 'is_active', 'created_at')
    search_fields = ('name',)


@admin.register(Repository)
class RepositoryAdmin(admin.ModelAdmin):
    list_display = (
        'id', 'name', 'project', 'access_type', 'vcs_provider', 'branch',
        'sync_status', 'indexing_status', 'commit_sha', 'last_synced_at',
        'last_indexed_at', 'file_count', 'indexed_chunk_count'
    )
    list_filter = ('access_type', 'sync_status', 'indexing_status', 'project')
    search_fields = ('name', 'project__name', 'url')
    readonly_fields = (
        'commit_sha', 'last_synced_at', 'last_indexed_at', 'file_count',
        'indexed_chunk_count', 'sync_status', 'indexing_status',
        'sync_error', 'indexing_error'
    )


@admin.register(IndexedFile)
class IndexedFileAdmin(admin.ModelAdmin):
    list_display = ('id', 'repository', 'file_path', 'language', 'file_size', 'indexed_at')
    list_filter = ('repository', 'language')
    search_fields = ('file_path',)
    readonly_fields = ('file_hash',)


@admin.register(CodeChunk)
class CodeChunkAdmin(admin.ModelAdmin):
    list_display = ('id', 'indexed_file', 'chunk_index', 'chunk_type', 'token_count', 'symbol_name')
    list_filter = ('chunk_type', 'indexed_file__repository')
    search_fields = ('indexed_file__file_path', 'symbol_name')
    readonly_fields = ('embedding',)


@admin.register(IngestionJob)
class IngestionJobAdmin(admin.ModelAdmin):
    list_display = ('id', 'repository', 'job_id', 'status', 'progress', 'files_processed', 'chunks_created', 'error_message', 'created_at')
    list_filter = ('status', 'repository')
    search_fields = ('job_id',)


# -----------------------------------------------------------------------------
# Additional admin registrations for security and operational visibility
#
# The following ModelAdmin classes register additional models with the
# Django admin.  Care is taken to avoid displaying sensitive or extremely
# large fields.  Fields containing long text (logs, diffs, descriptions)
# are truncated in list displays and marked read‑only in detail views.


@admin.register(CodeEditorApiKey)
class CodeEditorApiKeyAdmin(admin.ModelAdmin):
    """Admin for API keys.  Does not expose raw keys."""
    list_display = ('id', 'name', 'prefix', 'daily_quota', 'rpm_limit', 'is_active', 'last_used_at', 'created_at')
    list_filter = ('is_active',)
    search_fields = ('name', 'prefix')
    readonly_fields = ('key_hash', 'created_at', 'updated_at', 'last_used_at', 'revoked_at')


@admin.register(CodeEditorRequestLog)
class CodeEditorRequestLogAdmin(admin.ModelAdmin):
    """Admin for request logs.  Truncates error messages and hides raw input/output."""
    list_display = ('id', 'endpoint', 'provider', 'model_name', 'request_kind', 'status', 'created_at', 'short_error')
    list_filter = ('status', 'provider', 'request_kind')
    search_fields = ('endpoint', 'model_name', 'error_message')
    readonly_fields = ('error_message',)

    def short_error(self, obj):
        msg = obj.error_message or ''
        if len(msg) > 60:
            return f"{msg[:57]}..."
        return msg
    short_error.short_description = 'Error'


@admin.register(ProviderHealth)
class ProviderHealthAdmin(admin.ModelAdmin):
    list_display = ('provider_name', 'status', 'response_time_ms', 'last_check')
    list_filter = ('status',)
    search_fields = ('provider_name',)
    readonly_fields = ('error_message',)


@admin.register(TaskRun)
class TaskRunAdmin(admin.ModelAdmin):
    list_display = ('id', 'repository', 'task_type', 'status', 'current_stage', 'requested_apply_mode', 'effective_apply_mode', 'created_at')
    list_filter = ('status', 'task_type', 'effective_apply_mode')
    search_fields = ('id', 'instruction', 'summary')
    readonly_fields = ('error_message', 'error_details')


@admin.register(TaskStep)
class TaskStepAdmin(admin.ModelAdmin):
    list_display = ('id', 'task', 'name', 'order', 'status', 'created_at')
    list_filter = ('status', 'name')
    search_fields = ('task__id', 'name')
    readonly_fields = ('logs',)


@admin.register(PlanNode)
class PlanNodeAdmin(admin.ModelAdmin):
    list_display = ('id', 'task', 'node_key', 'title', 'status', 'order', 'created_at')
    list_filter = ('status',)
    search_fields = ('task__id', 'node_key', 'title')
    readonly_fields = ('description',)


@admin.register(SelectedFile)
class SelectedFileAdmin(admin.ModelAdmin):
    # selected_by removed from display as it is not a field on SelectedFile
    list_display = ('id', 'task', 'repository', 'path', 'rank', 'created_at')
    list_filter = ('repository',)
    search_fields = ('path',)


@admin.register(CandidatePatch)
class CandidatePatchAdmin(admin.ModelAdmin):
    list_display = ('id', 'task', 'candidate_key', 'status', 'apply_mode_effective', 'approval_status', 'created_at')
    list_filter = ('status', 'approval_status', 'apply_mode_effective')
    search_fields = ('candidate_key', 'summary')
    readonly_fields = ('patch_metadata', 'touched_files', 'summary')


@admin.register(CandidateScore)
class CandidateScoreAdmin(admin.ModelAdmin):
    list_display = ('id', 'task', 'candidate_patch', 'final_score', 'rank', 'created_at')
    list_filter = ('rank',)
    search_fields = ('candidate_patch__candidate_key',)


@admin.register(ValidationRun)
class ValidationRunAdmin(admin.ModelAdmin):
    list_display = ('id', 'task', 'stage_name', 'status', 'candidate_patch', 'created_at')
    list_filter = ('status', 'stage_name')
    search_fields = ('task__id', 'stage_name')
    readonly_fields = ('command', 'output', 'metadata')


@admin.register(TestRun)
class TestRunAdmin(admin.ModelAdmin):
    list_display = ('id', 'task', 'run_type', 'status', 'candidate_patch', 'validation_run', 'created_at')
    list_filter = ('status', 'run_type')
    search_fields = ('task__id',)
    readonly_fields = ('output', 'targeted_paths', 'test_command')


@admin.register(WorkspaceSnapshot)
class WorkspaceSnapshotAdmin(admin.ModelAdmin):
    list_display = ('id', 'task', 'snapshot_type', 'status', 'created_at')
    list_filter = ('status', 'snapshot_type')
    search_fields = ('task__id',)
    readonly_fields = ('root_path', 'metadata', 'restore_error')


@admin.register(Artifact)
class ArtifactAdmin(admin.ModelAdmin):
    list_display = ('id', 'task', 'artifact_type', 'name', 'created_at')
    list_filter = ('artifact_type',)
    search_fields = ('name', 'task__id')
    readonly_fields = ('description', 'file_path', 'text_content', 'metadata')
