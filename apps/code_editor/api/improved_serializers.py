"""Improved serializers for local development use."""

from rest_framework import serializers
from django.db.models import Count
from ..models import (
    Artifact,
    CodeEditorRequestLog,
    TaskRun,
    TaskStep,
    Repository,
    Project,
    CandidatePatch,
    CandidateScore,
    ValidationRun,
    TestRun
)


class CreateTaskSerializer(serializers.Serializer):
    """Serializer for creating new tasks with enhanced validation."""
    
    repository_id = serializers.IntegerField(min_value=1)
    instruction = serializers.CharField(
        min_length=10,
        max_length=10000,
        help_text="Detailed instruction for the task (10-10000 characters)"
    )
    task_type = serializers.ChoiceField(
        choices=TaskRun.TASK_TYPES,
        default='custom',
        help_text="Type of task to perform"
    )
    request_payload = serializers.JSONField(
        required=False,
        default=dict,
        help_text="Additional request data"
    )
    config = serializers.JSONField(
        required=False,
        default=dict,
        help_text="Task configuration options"
    )
    
    def validate_instruction(self, value):
        """Validate instruction content."""
        if not value.strip():
            raise serializers.ValidationError("Instruction cannot be empty")
        
        # Check for potentially problematic content
        if len(value.split()) < 3:
            raise serializers.ValidationError("Instruction must be more descriptive")
        
        return value.strip()
    
    def validate_config(self, value):
        """Validate configuration options."""
        if not isinstance(value, dict):
            raise serializers.ValidationError("Config must be a JSON object")
        
        # Validate known config options
        valid_options = {
            'max_candidates', 'validation_timeout', 'enable_symbols',
            'patch_strategies', 'retry_count', 'debug_mode'
        }
        
        for key in value.keys():
            if key not in valid_options:
                # Allow unknown options but warn (in production would validate strictly)
                pass
        
        return value


class TaskStepSerializer(serializers.ModelSerializer):
    """Serializer for task steps with enhanced fields."""
    
    class Meta:
        model = TaskStep
        fields = [
            'id', 'task', 'name', 'order', 'status', 'summary', 'logs', 'metadata',
            'started_at', 'completed_at', 'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'task', 'created_at', 'updated_at']
    
    duration_seconds = serializers.SerializerMethodField()
    
    def get_duration_seconds(self, obj):
        """Calculate duration in seconds."""
        if obj.started_at and obj.completed_at:
            return int((obj.completed_at - obj.started_at).total_seconds())
        return None


class TaskRunSerializer(serializers.ModelSerializer):
    """Enhanced serializer for task runs with additional fields."""
    
    steps = TaskStepSerializer(many=True, read_only=True)
    artifact_count = serializers.SerializerMethodField()
    step_count = serializers.SerializerMethodField()
    duration_seconds = serializers.SerializerMethodField()
    progress_percentage = serializers.SerializerMethodField()
    
    class Meta:
        model = TaskRun
        fields = [
            'id', 'repository', 'task_type', 'instruction', 'status', 'current_stage',
            'request_payload', 'result_payload', 'config', 'summary', 'result_summary',
            'error_message', 'error_details', 'failure_reason',
            'requested_apply_mode', 'effective_apply_mode', 'approval_status',
            'approved_by', 'approved_at', 'rejected_by', 'rejected_at', 'rejection_reason',
            'launched_via', 'runner_job_id',
            'cancellation_requested', 'cancellation_reason',
            'started_at', 'completed_at', 'cancelled_at', 'created_at', 'updated_at',
            'steps', 'artifact_count', 'step_count', 'duration_seconds', 'progress_percentage'
        ]
        read_only_fields = [
            'id', 'status', 'current_stage', 'result_payload', 'result_summary',
            'error_message', 'error_details', 'failure_reason',
            'requested_apply_mode', 'effective_apply_mode', 'approval_status',
            'approved_by', 'approved_at', 'rejected_by', 'rejected_at', 'rejection_reason',
            'launched_via', 'runner_job_id',
            'cancellation_requested', 'cancellation_reason',
            'started_at', 'completed_at', 'cancelled_at', 'created_at', 'updated_at'
        ]
    
    def get_artifact_count(self, obj):
        return obj.artifacts.count()
    
    def get_step_count(self, obj):
        return obj.steps.count()
    
    def get_duration_seconds(self, obj):
        if obj.started_at and obj.completed_at:
            return int((obj.completed_at - obj.started_at).total_seconds())
        return None
    
    def get_progress_percentage(self, obj):
        """Calculate progress based on task status and steps."""
        if obj.status in ['completed', 'failed', 'cancelled']:
            return 100
        elif obj.status == 'queued':
            return 0
        else:
            # Calculate based on completed steps
            total_steps = obj.steps.count()
            if total_steps == 0:
                return 10  # Initial planning phase
            completed_steps = obj.steps.filter(status='completed').count()
            return int((completed_steps / total_steps) * 100)


class TaskSummarySerializer(serializers.ModelSerializer):
    """Lightweight serializer for task summaries in lists."""
    
    duration_seconds = serializers.SerializerMethodField()
    has_error = serializers.SerializerMethodField()
    
    class Meta:
        model = TaskRun
        fields = [
            'id', 'task_type', 'status', 'current_stage', 'summary', 'result_summary',
            'started_at', 'completed_at', 'created_at', 'duration_seconds', 'has_error'
        ]
    
    def get_duration_seconds(self, obj):
        if obj.started_at and obj.completed_at:
            return int((obj.completed_at - obj.started_at).total_seconds())
        return None
    
    def get_has_error(self, obj):
        return bool(obj.error_message)


class ArtifactSerializer(serializers.ModelSerializer):
    """Enhanced serializer for artifacts."""
    
    content_available = serializers.SerializerMethodField()
    download_url = serializers.SerializerMethodField()
    size_formatted = serializers.SerializerMethodField()
    
    class Meta:
        model = Artifact
        fields = [
            'id', 'task', 'artifact_type', 'name', 'description', 'file_path',
            'content_type', 'size_bytes', 'sha256', 'metadata',
            'candidate_patch', 'validation_run', 'test_run', 'workspace_snapshot',
            'created_at', 'updated_at', 'content_available', 'download_url', 'size_formatted'
        ]
    
    def get_content_available(self, obj):
        return bool(obj.text_content or obj.file_path)
    
    def get_download_url(self, obj):
        if obj.id:
            return f"/api/code-editor/tasks/{obj.task.id}/artifacts/{obj.id}/content/"
        return None
    
    def get_size_formatted(self, obj):
        """Format file size in human readable format."""
        size = obj.size_bytes
        if size is None:
            return None
        if size < 1024:
            return f"{size} B"
        elif size < 1024 * 1024:
            return f"{size / 1024:.1f} KB"
        else:
            return f"{size / (1024 * 1024):.1f} MB"


class RepositorySerializer(serializers.ModelSerializer):
    """Enhanced serializer for repositories."""
    
    file_count = serializers.SerializerMethodField()
    last_indexed_ago = serializers.SerializerMethodField()
    indexing_status = serializers.SerializerMethodField()
    
    class Meta:
        model = Repository
        fields = [
            'id', 'project', 'name', 'url', 'branch',
            'file_count', 'last_indexed_at', 'indexing_status', 'last_indexed_ago',
            'indexing_error', 'created_at', 'updated_at'
        ]
    
    def get_file_count(self, obj):
        return obj.indexed_files.count()
    
    def get_last_indexed_ago(self, obj):
        if obj.last_indexed_at:
            from django.utils import timezone
            import datetime
            
            now = timezone.now()
            diff = now - obj.last_indexed_at
            
            if diff.days > 0:
                return f"{diff.days} days ago"
            elif diff.seconds > 3600:
                return f"{diff.seconds // 3600} hours ago"
            elif diff.seconds > 60:
                return f"{diff.seconds // 60} minutes ago"
            else:
                return "Just now"
        return "Never"
    
    def get_indexing_status(self, obj):
        if obj.indexing_error:
            return "error"
        elif obj.last_indexed_at:
            return "indexed"
        else:
            return "pending"


class ProjectSerializer(serializers.ModelSerializer):
    """Enhanced serializer for projects."""
    
    repository_count = serializers.SerializerMethodField()
    task_count = serializers.SerializerMethodField()
    
    class Meta:
        model = Project
        fields = [
            'id', 'name', 'description', 'is_active', 'repository_count', 'task_count',
            'created_at', 'updated_at'
        ]
    
    def get_repository_count(self, obj):
        return obj.repositories.count()
    
    def get_task_count(self, obj):
        from django.db.models import Count
        return obj.repositories.aggregate(total=Count('task_runs'))['total'] or 0


class CancelTaskSerializer(serializers.Serializer):
    """Serializer for task cancellation."""
    
    reason = serializers.CharField(
        required=False,
        allow_blank=True,
        max_length=500,
        help_text="Reason for cancellation"
    )


class CandidatePatchSerializer(serializers.ModelSerializer):
    """Serializer for candidate patches."""
    
    validation_results = serializers.SerializerMethodField()
    score_summary = serializers.SerializerMethodField()
    
    class Meta:
        model = CandidatePatch
        fields = [
            'id', 'task', 'candidate_key', 'status', 'summary', 'patch_metadata',
            'touched_files',
            'apply_mode_requested', 'apply_mode_effective', 'approval_status',
            'approved_by', 'approved_at', 'rejected_by', 'rejected_at', 'rejection_reason',
            'validation_results', 'score_summary',
            'created_at', 'updated_at', 'selected_at'
        ]
    
    def get_validation_results(self, obj):
        """Get validation results summary."""
        validation_runs = obj.validation_runs.all()
        if validation_runs.exists():
            latest = validation_runs.order_by('-created_at').first()
            return {
                'status': latest.status,
                'stage_name': latest.stage_name,
                'exit_code': latest.exit_code,
                'completed_at': latest.completed_at
            }
        return None
    
    def get_score_summary(self, obj):
        """Get scoring summary if available."""
        try:
            score = CandidateScore.objects.get(candidate_patch=obj)
            return {
                'final_score': score.final_score,
                'rank': score.rank,
                'syntax_score': score.syntax_score,
                'validation_score': score.validation_score,
                'relevance_score': score.relevance_score,
                'risk_score': score.risk_score,
                'quality_score': score.quality_score
            }
        except CandidateScore.DoesNotExist:
            return None


class ValidationRunSerializer(serializers.ModelSerializer):
    """Serializer for validation runs."""
    
    test_summary = serializers.SerializerMethodField()
    
    class Meta:
        model = ValidationRun
        fields = [
            'id', 'task', 'candidate_patch', 'step', 'stage_name', 'validation_type',
            'status', 'command', 'exit_code', 'output', 'duration_ms',
            'started_at', 'completed_at', 'test_summary'
        ]
    
    def get_test_summary(self, obj):
        """Get test run summary."""
        test_runs = obj.test_runs.all()
        if test_runs.exists():
            total_tests = sum(run.total_tests for run in test_runs)
            passed_tests = sum(run.passed_tests for run in test_runs)
            failed_tests = sum(run.failed_tests for run in test_runs)
            
            return {
                'total_tests': total_tests,
                'passed_tests': passed_tests,
                'failed_tests': failed_tests,
                'success_rate': (passed_tests / total_tests * 100) if total_tests > 0 else 0
            }
        return None


class BulkTaskSerializer(serializers.Serializer):
    """Serializer for bulk task operations."""
    
    repository_id = serializers.IntegerField(min_value=1)
    instructions = serializers.ListField(
        child=serializers.CharField(min_length=10),
        min_length=1,
        max_length=10,
        help_text="List of task instructions (1-10 items)"
    )
    task_type = serializers.ChoiceField(
        choices=TaskRun.TASK_TYPES,
        default='custom',
        help_text="Type for all tasks"
    )
    config = serializers.JSONField(
        required=False,
        default=dict,
        help_text="Configuration for all tasks"
    )
    
    def validate_instructions(self, value):
        """Validate instructions list."""
        if len(value) == 0:
            raise serializers.ValidationError("At least one instruction is required")
        
        if len(set(value)) != len(value):
            raise serializers.ValidationError("Duplicate instructions are not allowed")
        
        return value


class TaskSearchSerializer(serializers.Serializer):
    """Serializer for task search parameters."""
    
    query = serializers.CharField(
        required=False,
        allow_blank=True,
        max_length=200,
        help_text="Search query for task instructions"
    )
    status = serializers.ChoiceField(
        choices=TaskRun.STATUS_CHOICES,
        required=False,
        help_text="Filter by task status"
    )
    task_type = serializers.ChoiceField(
        choices=TaskRun.TASK_TYPES,
        required=False,
        help_text="Filter by task type"
    )
    repository_id = serializers.IntegerField(
        min_value=1,
        required=False,
        help_text="Filter by repository"
    )
    date_from = serializers.DateTimeField(
        required=False,
        help_text="Filter tasks from this date"
    )
    date_to = serializers.DateTimeField(
        required=False,
        help_text="Filter tasks to this date"
    )
    page = serializers.IntegerField(
        required=False,
        min_value=1,
        default=1,
        help_text="Page number"
    )
    page_size = serializers.IntegerField(
        required=False,
        min_value=1,
        max_value=100,
        default=20,
        help_text="Number of items per page"
    )
