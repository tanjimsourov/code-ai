from rest_framework import serializers

from ..models import (
    Artifact,
    CodeEditorRequestLog,
    TaskRun,
    TaskStep,
    CandidatePatch,
)


class ChatRequestSerializer(serializers.Serializer):
    messages = serializers.ListField(
        child=serializers.DictField(
            child=serializers.CharField(),
            validators=[]
        ),
        help_text="List of chat messages"
    )
    system_prompt = serializers.CharField(required=False, allow_blank=True, help_text="Optional system prompt")
    temperature = serializers.FloatField(required=False, default=0.7, min_value=0.0, max_value=2.0, help_text="Temperature for response generation")
    max_tokens = serializers.IntegerField(required=False, min_value=1, max_value=32768, help_text="Maximum tokens to generate")
    stream = serializers.BooleanField(required=False, default=False, help_text="Whether to stream the response")

    # Repository and project context
    repository_ids = serializers.ListField(
        child=serializers.IntegerField(min_value=1),
        required=False,
        help_text="List of repository IDs to include in the context pack"
    )
    project_id = serializers.IntegerField(
        required=False,
        help_text="Optional project ID for context.  If provided, all repositories in the project may be considered."
    )
    target_files = serializers.ListField(
        child=serializers.CharField(),
        required=False,
        help_text="Specific file paths to highlight in the context pack"
    )
    include_context_pack = serializers.BooleanField(
        required=False,
        default=False,
        help_text="Whether to include a repository context pack in the response."
    )

    # Optional overrides
    provider = serializers.CharField(required=False, allow_blank=True, help_text="Optional provider override")
    model = serializers.CharField(required=False, allow_blank=True, help_text="Optional model override")

    def validate_messages(self, value):
        if not value:
            raise serializers.ValidationError("At least one message is required")
        for message in value:
            if 'role' not in message or 'content' not in message:
                raise serializers.ValidationError("Each message must have 'role' and 'content' fields")
            role = message['role']
            if role not in ['system', 'user', 'assistant']:
                raise serializers.ValidationError("Message role must be 'system', 'user', or 'assistant'")
        return value


class CompletionRequestSerializer(serializers.Serializer):
    prefix = serializers.CharField(min_length=1, help_text="Code prefix to complete")
    suffix = serializers.CharField(required=False, allow_blank=True, help_text="Optional suffix to guide completion")
    language = serializers.CharField(required=False, allow_blank=True, help_text="Programming language")
    filename = serializers.CharField(required=False, allow_blank=True, help_text="Filename for context")
    cursor_context = serializers.CharField(required=False, allow_blank=True, help_text="Cursor context")
    temperature = serializers.FloatField(required=False, default=0.7, min_value=0.0, max_value=2.0, help_text="Temperature for response generation")
    max_tokens = serializers.IntegerField(required=False, min_value=1, max_value=32768, help_text="Maximum tokens to generate")
    stream = serializers.BooleanField(required=False, default=False, help_text="Whether to stream the response")

    # Context pack parameters
    repository_ids = serializers.ListField(
        child=serializers.IntegerField(min_value=1),
        required=False,
        help_text="List of repository IDs to include in the context pack"
    )
    project_id = serializers.IntegerField(
        required=False,
        help_text="Optional project ID for context.  If provided, all repositories in the project may be considered."
    )
    target_files = serializers.ListField(
        child=serializers.CharField(),
        required=False,
        help_text="Specific file paths to highlight in the context pack"
    )
    include_context_pack = serializers.BooleanField(
        required=False,
        default=False,
        help_text="Whether to include a repository context pack in the response."
    )

    # Optional overrides
    provider = serializers.CharField(required=False, allow_blank=True, help_text="Optional provider override")
    model = serializers.CharField(required=False, allow_blank=True, help_text="Optional model override")


class EditRequestSerializer(serializers.Serializer):
    instruction = serializers.CharField(min_length=1, help_text="Instruction for code editing")
    code = serializers.CharField(min_length=1, help_text="Code to edit")
    language = serializers.CharField(required=False, allow_blank=True, help_text="Programming language")
    filename = serializers.CharField(required=False, allow_blank=True, help_text="Filename for context")
    temperature = serializers.FloatField(required=False, default=0.3, min_value=0.0, max_value=2.0, help_text="Temperature for response generation")
    max_tokens = serializers.IntegerField(required=False, min_value=1, max_value=32768, help_text="Maximum tokens to generate")

    # Context pack parameters
    repository_ids = serializers.ListField(
        child=serializers.IntegerField(min_value=1),
        required=False,
        help_text="List of repository IDs to include in the context pack"
    )
    project_id = serializers.IntegerField(
        required=False,
        help_text="Optional project ID for context.  If provided, all repositories in the project may be considered."
    )
    target_files = serializers.ListField(
        child=serializers.CharField(),
        required=False,
        help_text="Specific file paths to highlight in the context pack"
    )
    include_context_pack = serializers.BooleanField(
        required=False,
        default=False,
        help_text="Whether to include a repository context pack in the response."
    )

    # Optional overrides
    provider = serializers.CharField(required=False, allow_blank=True, help_text="Optional provider override")
    model = serializers.CharField(required=False, allow_blank=True, help_text="Optional model override")


class EmbeddingsRequestSerializer(serializers.Serializer):
    texts = serializers.ListField(child=serializers.CharField(min_length=1), help_text="List of texts to embed")
    model = serializers.CharField(required=False, allow_blank=True, help_text="Model to use for embeddings")
    task = serializers.CharField(required=False, allow_blank=True, help_text="Task type (e.g., 'search', 'code')")

    # Optional overrides
    provider = serializers.CharField(required=False, allow_blank=True, help_text="Optional provider override")


class RerankRequestSerializer(serializers.Serializer):
    query = serializers.CharField(min_length=1, help_text="Query for reranking")
    documents = serializers.ListField(child=serializers.CharField(min_length=1), help_text="List of documents to rerank")
    model = serializers.CharField(required=False, allow_blank=True, help_text="Model to use for reranking")
    top_k = serializers.IntegerField(required=False, min_value=1, max_value=100, help_text="Number of top results to return")

    # Optional overrides
    provider = serializers.CharField(required=False, allow_blank=True, help_text="Optional provider override")


class InfillRequestSerializer(serializers.Serializer):
    """Serializer for infill code completion requests.

    This serializer validates the required ``prefix`` and ``suffix``
    fields and optional hints used when constructing the infill prompt.
    """
    prefix = serializers.CharField(min_length=1, help_text="Code before the insertion point")
    suffix = serializers.CharField(min_length=1, help_text="Code after the insertion point")
    language = serializers.CharField(required=False, allow_blank=True, help_text="Programming language")
    filename = serializers.CharField(required=False, allow_blank=True, help_text="Filename for context")
    cursor_context = serializers.CharField(required=False, allow_blank=True, help_text="Cursor context")
    temperature = serializers.FloatField(required=False, default=0.7, min_value=0.0, max_value=2.0, help_text="Sampling temperature")
    max_tokens = serializers.IntegerField(required=False, min_value=1, max_value=32768, help_text="Maximum tokens to generate")
    model = serializers.CharField(required=False, allow_blank=True, help_text="Optional model override")
    provider = serializers.CharField(required=False, allow_blank=True, help_text="Optional provider override")
    stream = serializers.BooleanField(required=False, default=False, help_text="Whether to stream the response")


class HealthResponseSerializer(serializers.Serializer):
    status = serializers.CharField(help_text="Health status")
    timestamp = serializers.DateTimeField(help_text="Current timestamp")
    version = serializers.CharField(help_text="API version")
    providers = serializers.DictField(help_text="Provider status")


class ModelResponseSerializer(serializers.Serializer):
    id = serializers.CharField(help_text="Model ID")
    object = serializers.CharField(help_text="Object type")
    created = serializers.IntegerField(help_text="Creation timestamp")
    owned_by = serializers.CharField(help_text="Owner")
    provider = serializers.CharField(help_text="Provider name")

    # Additional metadata for model discovery
    context_window_tokens = serializers.IntegerField(required=False, help_text="Maximum context window of the model in tokens")
    model_family = serializers.CharField(required=False, help_text="Model family/profile identifier")
    capabilities = serializers.DictField(required=False, help_text="Capabilities supported by the model (chat, completion, infill, embeddings, streaming, rerank)")


class ErrorResponseSerializer(serializers.Serializer):
    error = serializers.DictField(help_text="Error details")

    class ErrorDetailSerializer(serializers.Serializer):
        message = serializers.CharField(help_text="Error message")
        type = serializers.CharField(help_text="Error type")
        code = serializers.CharField(required=False, help_text="Error code")


class LogResponseSerializer(serializers.ModelSerializer):
    class Meta:
        model = CodeEditorRequestLog
        fields = [
            'id', 'endpoint', 'provider', 'model_name', 'request_kind',
            'status', 'latency_ms', 'input_chars', 'output_chars',
            'error_message', 'created_at'
        ]


class CreateTaskSerializer(serializers.Serializer):
    repository_id = serializers.IntegerField(min_value=1)
    instruction = serializers.CharField(min_length=1)
    task_type = serializers.ChoiceField(choices=TaskRun.TASK_TYPES, default='bugfix')
    request_payload = serializers.JSONField(required=False)
    config = serializers.JSONField(required=False)


class TaskStepSerializer(serializers.ModelSerializer):
    class Meta:
        model = TaskStep
        fields = [
            'id', 'name', 'order', 'status', 'summary', 'logs', 'metadata',
            'started_at', 'completed_at', 'created_at', 'updated_at',
        ]


class ArtifactSerializer(serializers.ModelSerializer):
    content_available = serializers.SerializerMethodField()

    class Meta:
        model = Artifact
        fields = [
            'id', 'artifact_type', 'name', 'description', 'file_path', 'content_type',
            'size_bytes', 'sha256', 'metadata', 'created_at', 'updated_at',
            'candidate_patch', 'validation_run', 'test_run', 'workspace_snapshot',
            'content_available',
        ]

    def get_content_available(self, obj):
        return bool(obj.text_content or obj.file_path)


class TaskRunSerializer(serializers.ModelSerializer):
    steps = TaskStepSerializer(many=True, read_only=True)
    artifact_count = serializers.SerializerMethodField()
    step_count = serializers.SerializerMethodField()

    def get_artifact_count(self, obj):
        return obj.artifacts.count()

    def get_step_count(self, obj):
        return obj.steps.count()

    class Meta:
        model = TaskRun
        fields = [
            'id', 'repository', 'task_type', 'instruction', 'status', 'current_stage',
            'request_payload', 'result_payload', 'config', 'summary', 'result_summary',
            'error_message', 'error_details', 'failure_reason',
            'requested_apply_mode', 'effective_apply_mode', 'approval_status',
            'approved_by', 'approved_at', 'rejected_by', 'rejected_at', 'rejection_reason',
            'launched_via', 'runner_job_id',
            'cancellation_requested', 'cancellation_reason', 'cancellation_requested_at',
            'cancelled_at', 'started_at', 'completed_at', 'last_heartbeat_at',
            'created_at', 'updated_at', 'artifact_count', 'step_count', 'steps',
        ]


class TaskSummarySerializer(serializers.ModelSerializer):
    class Meta:
        model = TaskRun
        fields = [
            'id', 'status', 'summary', 'result_summary', 'result_payload',
            'error_message', 'error_details', 'started_at', 'completed_at', 'updated_at',
        ]


class CancelTaskSerializer(serializers.Serializer):
    reason = serializers.CharField(required=False, allow_blank=True)


class CandidatePatchSerializer(serializers.ModelSerializer):
    """Serializer for reviewable candidate patches."""

    class Meta:
        model = CandidatePatch
        fields = [
            'id', 'task', 'candidate_key', 'status', 'summary',
            'patch_metadata', 'touched_files',
            'apply_mode_requested', 'apply_mode_effective', 'approval_status',
            'approved_by', 'approved_at', 'rejected_by', 'rejected_at', 'rejection_reason',
            'created_at', 'updated_at', 'selected_at',
        ]


class ApprovePatchSerializer(serializers.Serializer):
    """Approve a candidate patch and optionally apply it to the task workspace.

    The API no longer accepts an arbitrary ``workspace_dir`` for security reasons.
    If ``auto_apply`` is set, the server will derive the appropriate
    workspace path from the task and apply the patch.  Clients should not
    provide filesystem paths.
    """

    candidate_id = serializers.UUIDField(required=False)
    auto_apply = serializers.BooleanField(required=False, default=False)

# Patch management serializers
class PatchApplySerializer(serializers.Serializer):
    """Serializer for applying a generated patch to a workspace.

    Requires only the ID of the candidate patch.  The workspace directory is
    derived by the server based on the associated task.  For security
    reasons, clients must not supply arbitrary filesystem paths.
    """

    candidate_id = serializers.UUIDField(help_text="ID of the candidate patch to apply")


class PatchRevertSerializer(serializers.Serializer):
    """Serializer for reverting a previously applied patch.

    Requires only the ID of the candidate patch.  The server will derive
    both the workspace and repository locations.  Arbitrary filesystem
    paths from the client are not accepted for security reasons.
    """

    candidate_id = serializers.UUIDField(help_text="ID of the candidate patch to revert")
