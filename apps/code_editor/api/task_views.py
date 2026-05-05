"""Task API endpoints for the code_editor task engine foundation."""

from __future__ import annotations

from django.utils import timezone
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes, throttle_classes
from ..permissions import CanApprovePatch, CodeEditorApiKeyPermission
from .throttles import AIThrottle
from rest_framework.response import Response

from ..models import Artifact, Repository, TaskRun, CandidatePatch
from ..services.task_artifact_service import TaskArtifactService
from ..services.patch_generation_service import PatchGenerationService
from ..tasks import launch_task_run
from .serializers import (
    ArtifactSerializer,
    CancelTaskSerializer,
    CreateTaskSerializer,
    TaskRunSerializer,
    TaskStepSerializer,
    TaskSummarySerializer,
    CandidatePatchSerializer,
    ApprovePatchSerializer,
)


@api_view(['POST'])
@permission_classes([CodeEditorApiKeyPermission])
@throttle_classes([AIThrottle])
def create_task(request):
    """Create a task resource and launch execution asynchronously."""

    # Enforce daily quota and rate limit for the authenticated API key
    api_key = getattr(request, 'auth', None)
    if api_key:
        from ..services.quota_service import QuotaService
        try:
            QuotaService.enforce_limits_atomic(api_key)
        except Exception as exc:
            return Response({
                'error': {
                    'message': str(exc),
                    'type': exc.__class__.__name__,
                }
            }, status=status.HTTP_429_TOO_MANY_REQUESTS)
    serializer = CreateTaskSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)

    repository_id = serializer.validated_data['repository_id']
    try:
        repository = Repository.objects.get(id=repository_id)
    except Repository.DoesNotExist:
        return Response(
            {
                'error': {
                    'message': f'Repository {repository_id} does not exist',
                    'type': 'NotFound',
                }
            },
            status=status.HTTP_404_NOT_FOUND,
        )

    task = TaskRun.objects.create(
        repository=repository,
        task_type=serializer.validated_data['task_type'],
        instruction=serializer.validated_data['instruction'].strip(),
        request_payload=serializer.validated_data.get('request_payload', {}),
        config=serializer.validated_data.get('config', {}),
        status='queued',
        current_stage='queued',
        summary='Task queued',
    )
    launch_info = launch_task_run(task)
    if launch_info:
        task.refresh_from_db()

    response_serializer = TaskRunSerializer(task)
    return Response(
        {
            'object': 'task_run',
            'data': response_serializer.data,
            'links': {
                'self': f'/api/code-editor/tasks/{task.id}/',
                'steps': f'/api/code-editor/tasks/{task.id}/steps/',
                'artifacts': f'/api/code-editor/tasks/{task.id}/artifacts/',
                'result': f'/api/code-editor/tasks/{task.id}/result/',
            },
        },
        status=status.HTTP_201_CREATED,
    )


@api_view(['GET'])
@permission_classes([CodeEditorApiKeyPermission])
def task_detail(request, task_id):
    try:
        task = TaskRun.objects.get(id=task_id)
    except TaskRun.DoesNotExist:
        return Response(
            {'error': {'message': 'Task not found', 'type': 'NotFound'}},
            status=status.HTTP_404_NOT_FOUND,
        )

    serializer = TaskRunSerializer(task)
    return Response({'object': 'task_run', 'data': serializer.data})


@api_view(['GET'])
@permission_classes([CodeEditorApiKeyPermission])
def task_steps(request, task_id):
    try:
        task = TaskRun.objects.get(id=task_id)
    except TaskRun.DoesNotExist:
        return Response(
            {'error': {'message': 'Task not found', 'type': 'NotFound'}},
            status=status.HTTP_404_NOT_FOUND,
        )

    serializer = TaskStepSerializer(task.steps.order_by('order'), many=True)
    return Response({'object': 'list', 'data': serializer.data})


@api_view(['GET'])
@permission_classes([CodeEditorApiKeyPermission])
def task_artifacts(request, task_id):
    try:
        task = TaskRun.objects.get(id=task_id)
    except TaskRun.DoesNotExist:
        return Response(
            {'error': {'message': 'Task not found', 'type': 'NotFound'}},
            status=status.HTTP_404_NOT_FOUND,
        )

    serializer = ArtifactSerializer(task.artifacts.order_by('created_at'), many=True)
    return Response({'object': 'list', 'data': serializer.data})


@api_view(['GET'])
@permission_classes([CodeEditorApiKeyPermission])
def task_patches(request, task_id):
    """List reviewable candidate patches for a task."""
    try:
        task = TaskRun.objects.get(id=task_id)
    except TaskRun.DoesNotExist:
        return Response(
            {'error': {'message': 'Task not found', 'type': 'NotFound'}},
            status=status.HTTP_404_NOT_FOUND,
        )

    patches = task.candidate_patches.order_by('created_at')
    serializer = CandidatePatchSerializer(patches, many=True)
    return Response({'object': 'list', 'data': serializer.data})


@api_view(['GET'])
@permission_classes([CodeEditorApiKeyPermission])
def task_artifacts_and_patches(request, task_id):
    """List artifacts and patches together for review UIs."""
    try:
        task = TaskRun.objects.get(id=task_id)
    except TaskRun.DoesNotExist:
        return Response(
            {'error': {'message': 'Task not found', 'type': 'NotFound'}},
            status=status.HTTP_404_NOT_FOUND,
        )

    artifacts = ArtifactSerializer(task.artifacts.order_by('created_at'), many=True)
    patches = CandidatePatchSerializer(task.candidate_patches.order_by('created_at'), many=True)
    return Response({
        'object': 'task_review_bundle',
        'data': {
            'artifacts': artifacts.data,
            'patches': patches.data,
        },
    })


@api_view(['POST'])
@permission_classes([CanApprovePatch])
def approve_patch(request, task_id, candidate_id=None):
    """
    Approve a candidate patch and optionally apply it.

    This endpoint updates both the candidate and the parent task with
    appropriate approval metadata. When ``auto_apply`` is true the
    patch is applied to the task's workspace using the patch generation
    service.  When ``auto_apply`` is false, the candidate remains
    selected for manual application.  Approval metadata such as
    ``approval_status``, ``approved_by`` and ``approved_at`` will be
    persisted on both the candidate and task.
    """
    try:
        task = TaskRun.objects.get(id=task_id)
    except TaskRun.DoesNotExist:
        return Response(
            {'error': {'message': 'Task not found', 'type': 'NotFound'}},
            status=status.HTTP_404_NOT_FOUND,
        )

    # Merge candidate_id from URL and request payload
    request_data = dict(request.data or {})
    if candidate_id:
        request_data.setdefault('candidate_id', str(candidate_id))
    serializer = ApprovePatchSerializer(data=request_data)
    serializer.is_valid(raise_exception=True)
    candidate_pk = serializer.validated_data.get('candidate_id') or candidate_id

    try:
        candidate = task.candidate_patches.get(id=candidate_pk)
    except CandidatePatch.DoesNotExist:
        return Response(
            {'error': {'message': 'Candidate patch not found', 'type': 'NotFound'}},
            status=status.HTTP_404_NOT_FOUND,
        )

    # Mark candidate as approved and update metadata
    candidate.approval_status = 'approved'
    candidate.approved_at = timezone.now()
    # Use API key owner or request user if available, else leave blank
    # Persist the authenticated user on the candidate if available.  Do not
    # assign a string to the ForeignKey; instead assign the actual user
    # instance.  Anonymous or API key requests leave this field null.
    approved_by = getattr(request, 'user', None)
    if approved_by and getattr(approved_by, 'is_authenticated', False):
        candidate.approved_by = approved_by
    candidate.status = 'selected'
    candidate.selected_at = timezone.now()
    # Determine effective apply mode.  For auto_apply we use the
    # ``apply_to_workspace`` mode.  Otherwise fall back to the candidate's
    # requested mode if provided, or ``manual_approval_required``.
    if serializer.validated_data.get('auto_apply'):
        candidate.apply_mode_effective = 'apply_to_workspace'
    else:
        candidate.apply_mode_effective = candidate.apply_mode_requested or 'manual_approval_required'
    candidate.save(update_fields=[
        'approval_status', 'approved_at', 'approved_by',
        'status', 'selected_at', 'apply_mode_effective', 'updated_at'
    ])

    # Update the parent task approval fields
    task.approval_status = 'approved'
    task.approved_at = candidate.approved_at
    # Assign the user instance or None directly to the task's FK field
    task.approved_by = candidate.approved_by
    task.effective_apply_mode = candidate.apply_mode_effective
    task.save(update_fields=['approval_status', 'approved_at', 'approved_by', 'effective_apply_mode', 'updated_at'])

    applied = False
    if serializer.validated_data.get('auto_apply'):
        # Determine workspace directory from the task.  We no longer accept
        # client‑supplied paths.
        workspace_path = TaskArtifactService.workspace_dir(task)
        # Apply the candidate patch
        applied = PatchGenerationService().apply_candidate_to_workspace(candidate, workspace_path)
        if not applied:
            return Response(
                {
                    'error': {
                        'message': 'Patch approval succeeded but apply failed',
                        'type': 'PatchApplyFailed',
                    }
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Optionally update task status to reflect applied state if still awaiting review
        if task.status == 'awaiting_review':
            task.status = 'applying_patch'
            task.current_stage = 'applying_patch'
            task.save(update_fields=['status', 'current_stage', 'updated_at'])

    response_serializer = CandidatePatchSerializer(candidate)
    return Response({
        'object': 'candidate_patch',
        'data': response_serializer.data,
        'applied': applied,
    })


@api_view(['POST'])
@permission_classes([CanApprovePatch])
def reject_patch(request, task_id, candidate_id=None):
    """
    Reject a candidate patch for a task.

    This endpoint sets the candidate's approval_status to ``rejected`` and
    records the rejection metadata.  Optionally a ``reason`` may be
    supplied in the request payload.  The parent task's approval fields
    will also be updated.
    """
    try:
        task = TaskRun.objects.get(id=task_id)
    except TaskRun.DoesNotExist:
        return Response(
            {'error': {'message': 'Task not found', 'type': 'NotFound'}},
            status=status.HTTP_404_NOT_FOUND,
        )

    # Resolve candidate ID from URL or payload
    request_data = dict(request.data or {})
    if candidate_id:
        request_data.setdefault('candidate_id', str(candidate_id))
    candidate_pk = request_data.get('candidate_id') or candidate_id
    if not candidate_pk:
        return Response(
            {
                'error': {
                    'message': 'Candidate ID is required',
                    'type': 'ValidationError',
                }
            },
            status=status.HTTP_400_BAD_REQUEST,
        )
    try:
        candidate = task.candidate_patches.get(id=candidate_pk)
    except CandidatePatch.DoesNotExist:
        return Response(
            {'error': {'message': 'Candidate patch not found', 'type': 'NotFound'}},
            status=status.HTTP_404_NOT_FOUND,
        )

    # Capture rejection reason if provided
    reason = request_data.get('reason') or ''
    candidate.approval_status = 'rejected'
    candidate.rejection_reason = reason
    candidate.rejected_at = timezone.now()
    # Set rejected_by as the authenticated user if available.  Do not
    # assign a string to the ForeignKey; instead assign the user instance.
    rejected_by = getattr(request, 'user', None)
    if rejected_by and getattr(rejected_by, 'is_authenticated', False):
        candidate.rejected_by = rejected_by
    # Update candidate status
    candidate.status = 'rejected'
    candidate.save(update_fields=[
        'approval_status', 'rejection_reason', 'rejected_at', 'rejected_by', 'status', 'updated_at'
    ])

    # Update task approval status only if no other candidates remain pending
    task.approval_status = 'rejected'
    task.rejection_reason = reason
    task.rejected_at = candidate.rejected_at
    task.rejected_by = candidate.rejected_by
    # When a task is rejected, mark it as failed if it was awaiting review
    if task.status == 'awaiting_review':
        task.status = 'failed'
        task.current_stage = 'failed'
        task.failure_reason = 'user_rejection'
    task.save(update_fields=['approval_status', 'rejection_reason', 'rejected_at', 'rejected_by', 'status', 'current_stage', 'failure_reason', 'updated_at'])

    response_serializer = CandidatePatchSerializer(candidate)
    return Response({
        'object': 'candidate_patch',
        'data': response_serializer.data,
        'rejected': True,
    })


@api_view(['GET'])
@permission_classes([CodeEditorApiKeyPermission])
def artifact_detail(request, task_id, artifact_id):
    try:
        artifact = Artifact.objects.get(id=artifact_id, task_id=task_id)
    except Artifact.DoesNotExist:
        return Response(
            {'error': {'message': 'Artifact not found', 'type': 'NotFound'}},
            status=status.HTTP_404_NOT_FOUND,
        )

    serializer = ArtifactSerializer(artifact)
    payload = {'object': 'artifact', 'data': serializer.data}
    include_content = str(request.query_params.get('include_content', '')).lower() in {'1', 'true', 'yes'}
    if include_content:
        payload['content'] = TaskArtifactService.read_content(artifact)
    return Response(payload)


@api_view(['GET'])
@permission_classes([CodeEditorApiKeyPermission])
def artifact_content(request, task_id, artifact_id):
    try:
        artifact = Artifact.objects.get(id=artifact_id, task_id=task_id)
    except Artifact.DoesNotExist:
        return Response(
            {'error': {'message': 'Artifact not found', 'type': 'NotFound'}},
            status=status.HTTP_404_NOT_FOUND,
        )

    return Response(
        {
            'object': 'artifact_content',
            'data': {
                'artifact_id': str(artifact.id),
                'content': TaskArtifactService.read_content(artifact),
            },
        }
    )


@api_view(['GET'])
@permission_classes([CodeEditorApiKeyPermission])
def task_result(request, task_id):
    try:
        task = TaskRun.objects.get(id=task_id)
    except TaskRun.DoesNotExist:
        return Response(
            {'error': {'message': 'Task not found', 'type': 'NotFound'}},
            status=status.HTTP_404_NOT_FOUND,
        )

    serializer = TaskSummarySerializer(task)
    return Response({'object': 'task_result', 'data': serializer.data})


@api_view(['POST'])
@permission_classes([CodeEditorApiKeyPermission])
def cancel_task(request, task_id):
    try:
        task = TaskRun.objects.get(id=task_id)
    except TaskRun.DoesNotExist:
        return Response(
            {'error': {'message': 'Task not found', 'type': 'NotFound'}},
            status=status.HTTP_404_NOT_FOUND,
        )

    serializer = CancelTaskSerializer(data=request.data or {})
    serializer.is_valid(raise_exception=True)

    if task.is_terminal:
        response_serializer = TaskRunSerializer(task)
        return Response({'object': 'task_run', 'data': response_serializer.data})

    task.cancellation_requested = True
    task.cancellation_reason = serializer.validated_data.get('reason', '')
    task.cancellation_requested_at = timezone.now()
    if task.status == 'queued':
        task.status = 'cancelled'
        task.current_stage = 'cancelled'
        task.cancelled_at = timezone.now()
        task.completed_at = timezone.now()
        task.result_summary = 'Task cancelled before execution started'
    else:
        task.status = 'cancel_requested'
        task.current_stage = 'cancel_requested'
    task.save(
        update_fields=[
            'cancellation_requested', 'cancellation_reason', 'cancellation_requested_at',
            'status', 'current_stage', 'cancelled_at', 'completed_at', 'result_summary',
            'updated_at',
        ]
    )

    response_serializer = TaskRunSerializer(task)
    return Response({'object': 'task_run', 'data': response_serializer.data})
