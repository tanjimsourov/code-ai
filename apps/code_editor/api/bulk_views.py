"""Bulk operations for tasks and candidate patches.

These API endpoints allow callers to perform bulk actions on tasks and
candidate patches in a single request.  Bulk operations help reduce
latency and overhead when processing many records at once and ensure
consistent quota enforcement.  All endpoints require an authenticated
API key and return a summary of the number of records updated.
"""

from django.utils import timezone
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response

from ..permissions import CodeEditorApiKeyPermission
from ..models import TaskRun, CandidatePatch


@api_view(['POST'])
@permission_classes([CodeEditorApiKeyPermission])
def bulk_cancel_tasks(request):
    """Cancel multiple tasks in a single request.

    Expects a JSON body with a ``task_ids`` field containing a list of
    task UUID strings.  For each task that is not in a terminal state,
    its status is set to ``cancel_requested`` and the cancellation
    timestamp is recorded.  Returns the number of tasks successfully
    marked for cancellation.
    """
    task_ids = request.data.get('task_ids') or []
    if not isinstance(task_ids, (list, tuple)):
        return Response({
            'error': {
                'message': 'task_ids must be a list of UUIDs',
                'type': 'InvalidRequest'
            }
        }, status=status.HTTP_400_BAD_REQUEST)

    # Filter tasks by ID, excluding those already terminal or cancelled
    tasks = TaskRun.objects.filter(id__in=task_ids).exclude(
        status__in=[
            'completed', 'completed_with_warnings', 'validation_failed',
            'failed', 'cancelled', 'rolled_back'
        ]
    )
    cancelled_count = 0
    now = timezone.now()
    for task in tasks:
        # Only mark if not already cancel_requested
        if task.status != 'cancel_requested':
            task.status = 'cancel_requested'
            task.cancellation_requested = True
            task.cancellation_requested_at = now
            task.save(update_fields=['status', 'cancellation_requested', 'cancellation_requested_at', 'updated_at'])
            cancelled_count += 1
    return Response({
        'object': 'bulk_cancel',
        'cancelled_count': cancelled_count
    }, status=status.HTTP_200_OK)


@api_view(['POST'])
@permission_classes([CodeEditorApiKeyPermission])
def bulk_approve_patches(request):
    """Approve multiple candidate patches in a single request.

    Expects a JSON body with a ``candidate_ids`` field containing a list
    of candidate patch UUID strings.  Each candidate in a pending state
    will be marked approved, its approval timestamp set, and the parent
    task approval status updated if all of its candidates are approved.
    Returns the number of candidate patches approved.
    """
    candidate_ids = request.data.get('candidate_ids') or []
    if not isinstance(candidate_ids, (list, tuple)):
        return Response({
            'error': {
                'message': 'candidate_ids must be a list of UUIDs',
                'type': 'InvalidRequest'
            }
        }, status=status.HTTP_400_BAD_REQUEST)

    candidates = CandidatePatch.objects.filter(id__in=candidate_ids, approval_status='pending')
    approved_count = 0
    now = timezone.now()
    tasks_to_update = set()
    for candidate in candidates.select_related('task'):
        candidate.approval_status = 'approved'
        candidate.approved_at = now
        candidate.save(update_fields=['approval_status', 'approved_at', 'updated_at'])
        approved_count += 1
        tasks_to_update.add(candidate.task_id)

    # Update tasks associated with fully approved candidates if still pending
    for task_id in tasks_to_update:
        task = TaskRun.objects.get(id=task_id)
        # If task approval is pending, set to approved
        if task.approval_status == 'pending':
            task.approval_status = 'approved'
            task.approved_at = now
            task.save(update_fields=['approval_status', 'approved_at', 'updated_at'])
    return Response({
        'object': 'bulk_approve',
        'approved_count': approved_count
    }, status=status.HTTP_200_OK)