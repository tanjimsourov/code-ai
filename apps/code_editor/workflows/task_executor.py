"""Autonomous task executor for the code_editor application."""

from __future__ import annotations

import difflib
import json
import os
import shutil
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from django.utils import timezone

from ..models import (
    Artifact,
    CandidatePatch,
    CandidateScore,
    PlanNode,
    Repository,
    SelectedFile,
    TaskRun,
    TaskStep,
    TestRun,
    ValidationRun,
    WorkspaceSnapshot,
)
from ..services import ChatService, RetrievalService
from ..services.task_artifact_service import TaskArtifactService
from ..services.planning_service import PlanningService
from ..services.file_selection_service import FileSelectionService
from ..services.patch_generation_service import PatchGenerationService
from ..services.validation_service import ValidationService
from ..services.candidate_scoring_service import CandidateScoringService
from ..services.config import ConfigService
from ..services.bug_repair_service import BugRepairService


class TaskCancelled(Exception):
    pass


class TaskExecutor:
    """Coordinator for running a ``TaskRun`` through its lifecycle."""

    STORAGE_ROOT: str = os.getenv('CODE_EDITOR_TASK_STORAGE_ROOT', '/tmp/code_editor_tasks')

    def __init__(self, task: TaskRun) -> None:
        self.task = task
        self.task_dir = Path(self.STORAGE_ROOT) / str(task.id)
        self.workspace_dir = self.task_dir / 'workspace'
        self.task_dir.mkdir(parents=True, exist_ok=True)
        self.workspace_dir.mkdir(parents=True, exist_ok=True)

    @classmethod
    def from_id(cls, task_id: str) -> "TaskExecutor":
        task = TaskRun.objects.get(pk=task_id)
        return cls(task)

    def _refresh_task(self) -> TaskRun:
        self.task.refresh_from_db()
        return self.task

    def _heartbeat(self, stage: str = '') -> None:
        self.task.last_heartbeat_at = timezone.now()
        if stage:
            self.task.current_stage = stage
        self.task.save(update_fields=['last_heartbeat_at', 'current_stage', 'updated_at'])

    def _check_cancelled(self) -> None:
        self._refresh_task()
        if self.task.cancellation_requested or self.task.status == 'cancel_requested':
            raise TaskCancelled(self.task.cancellation_reason or 'Task was cancelled')

    def _create_step(self, name: str, status: str, summary: str = '') -> TaskStep:
        order = self.task.steps.count()
        step = TaskStep.objects.create(
            task=self.task,
            name=name,
            order=order,
            status=status,
            summary=summary,
            started_at=timezone.now(),
        )
        self.task.current_stage = name
        self.task.status = status
        self.task.save(update_fields=['current_stage', 'status', 'updated_at'])
        self._heartbeat(name)
        return step

    def _complete_step(self, step: TaskStep, status: str, summary: str = '') -> None:
        step.status = status
        if summary:
            step.summary = summary
        step.completed_at = timezone.now()
        step.save(update_fields=['status', 'summary', 'completed_at', 'updated_at'])

    def _add_log(self, step: TaskStep, message: str) -> None:
        current = step.logs or ''
        step.logs = current + message + '\n'
        step.save(update_fields=['logs', 'updated_at'])

    def _write_artifact(
        self,
        step: Optional[TaskStep],
        artifact_type: str,
        filename: str,
        content: str,
        description: Optional[str] = None,
        *,
        candidate_patch: Optional[CandidatePatch] = None,
        validation_run: Optional[ValidationRun] = None,
        test_run: Optional[TestRun] = None,
        workspace_snapshot: Optional[WorkspaceSnapshot] = None,
        metadata: Optional[dict[str, Any]] = None,
    ) -> Artifact:
        return TaskArtifactService.persist_text_artifact(
            task=self.task,
            step=step,
            candidate_patch=candidate_patch,
            validation_run=validation_run,
            test_run=test_run,
            workspace_snapshot=workspace_snapshot,
            artifact_type=artifact_type,
            relative_name=filename,
            content=content,
            description=description or f'{artifact_type} artifact {filename}',
            metadata=metadata or {},
        )

    def _copy_repository(self) -> Path:
        """Copy the task's repository into the workspace directory.

        For local repositories (``access_type == 'local'``) the path is
        derived from the URL, which should begin with ``file://``.  For
        remote repositories the ``storage_path`` field must be populated
        after a successful sync.  This method never clones a remote
        repository; upstream syncing should be performed by the
        RepositoryService or management commands prior to task execution.

        :raises FileNotFoundError: if the source path does not exist
        :raises ValueError: if a remote repository lacks a storage path
        :returns: The source repository path used for copying
        """
        repo: Repository = self.task.repository
        # Determine the source path based on access_type
        if repo.access_type == 'local':
            url = repo.url or ''
            if url.startswith('file://'):
                src_path = Path(url.replace('file://', ''))
            else:
                # Fall back to interpreting the URL as a raw path
                src_path = Path(url)
        else:
            if repo.storage_path:
                src_path = Path(repo.storage_path)
            else:
                raise ValueError('Remote repository has no storage_path; run sync before execution')
        if not src_path.exists():
            raise FileNotFoundError(f'Repository path {src_path} does not exist')
        # Remove any existing workspace and copy the repository into it
        if self.workspace_dir.exists():
            shutil.rmtree(self.workspace_dir)
        shutil.copytree(src_path, self.workspace_dir)
        return src_path

    def _create_workspace_snapshot(
        self,
        *,
        snapshot_type: str,
        candidate_patch: Optional[CandidatePatch] = None,
        metadata: Optional[dict[str, Any]] = None,
    ) -> WorkspaceSnapshot:
        snapshot = WorkspaceSnapshot.objects.create(
            task=self.task,
            candidate_patch=candidate_patch,
            snapshot_type=snapshot_type,
            status='created',
            root_path=str(self.workspace_dir),
            metadata=metadata or {},
        )
        Artifact.objects.create(
            task=self.task,
            workspace_snapshot=snapshot,
            candidate_patch=candidate_patch,
            artifact_type='snapshot',
            name=f'{snapshot_type}_snapshot',
            description=f'{snapshot_type} workspace snapshot',
            file_path=str(self.workspace_dir),
            content_type='inode/directory',
            metadata={'snapshot_type': snapshot_type},
        )
        return snapshot

    def _generate_diff(self) -> str:
        """Generate a unified diff between the original repository and the workspace.

        The diff includes modifications, new files and deletions.  Binary
        files and files exceeding a size threshold are identified rather than
        diffed.  Certain directories (e.g. .git, node_modules) are ignored.
        """
        # Determine the base path of the original repository.  For local
        # repositories the ``url`` field is expected to be a file:// URI.
        # For remote repositories, use the ``storage_path`` which points
        # to the cloned repository.  If the storage path is missing for a
        # remote repository, raise an error rather than silently using
        # the repository URL.
        repository = self.task.repository
        if repository.access_type == 'local':
            repo_path = Path(repository.url.replace('file://', ''))
        else:
            if not repository.storage_path:
                raise RuntimeError("Remote repository storage_path is not set; cannot generate diff")
            repo_path = Path(repository.storage_path)
        diff_lines: List[str] = []

        # Build sets of relative file paths for the repo and workspace
        def list_files(base: Path) -> set[str]:
            results: set[str] = set()
            for root, dirs, files in os.walk(base):
                # Skip ignored directories
                rel_root = Path(root).relative_to(base)
                ignored_prefixes = {'.git', '.hg', 'venv', 'env', 'node_modules', 'dist', 'build', '__pycache__'}
                parts = set(rel_root.parts)
                if parts & ignored_prefixes:
                    dirs[:] = []
                    continue
                for fname in files:
                    rel_path = (Path(root) / fname).relative_to(base)
                    # Skip large binary-like files based on extension
                    if rel_path.suffix.lower() in {'.png', '.jpg', '.jpeg', '.gif', '.svg', '.pyc', '.ico', '.zip', '.tar', '.gz', '.pdf', '.exe'}:
                        continue
                    results.add(str(rel_path))
            return results

        repo_files = list_files(repo_path)
        workspace_files = list_files(self.workspace_dir)
        all_paths = sorted(set(repo_files) | set(workspace_files))

        # Helper to determine if a file is binary or too large
        def is_binary_or_large(path: Path, max_size: int = 1024 * 1024) -> bool:
            try:
                if path.stat().st_size > max_size:
                    return True
                with open(path, 'rb') as f:
                    sample = f.read(1024)
                if b'\0' in sample:
                    return True
            except Exception:
                return True
            return False

        for rel in all_paths:
            rel_path = Path(rel)
            src_file = repo_path / rel_path
            dst_file = self.workspace_dir / rel_path
            src_exists = src_file.exists()
            dst_exists = dst_file.exists()

            if not src_exists and dst_exists:
                # New file added
                if is_binary_or_large(dst_file):
                    diff_lines.append(f"Binary or large file added: {rel}")
                    continue
                with open(dst_file, 'r', encoding='utf-8', errors='ignore') as f:
                    new_content = f.readlines()
                header = difflib.unified_diff([], new_content, fromfile='/dev/null', tofile=str(rel), lineterm='')
                diff_lines.extend(list(header))
                continue
            if src_exists and not dst_exists:
                # File deleted
                diff_lines.append(f"--- {rel}")
                diff_lines.append(f"+++ /dev/null")
                diff_lines.append(f"@@ deleted file {rel} @@")
                continue
            if src_exists and dst_exists:
                # Modified file or unchanged
                if is_binary_or_large(src_file) or is_binary_or_large(dst_file):
                    # Identify binary/large change if file sizes differ
                    if src_file.stat().st_size != dst_file.stat().st_size:
                        diff_lines.append(f"Binary or large file changed: {rel}")
                    continue
                try:
                    with open(src_file, 'r', encoding='utf-8', errors='ignore') as f1:
                        original = f1.readlines()
                    with open(dst_file, 'r', encoding='utf-8', errors='ignore') as f2:
                        modified = f2.readlines()
                except Exception:
                    continue
                if original != modified:
                    diff = difflib.unified_diff(
                        original,
                        modified,
                        fromfile=str(rel),
                        tofile=str(rel),
                        lineterm='',
                    )
                    diff_lines.extend(list(diff))
        return '\n'.join(diff_lines)

    def _generate_plan(self) -> str:
        """Generate execution plan using PlanningService."""
        planning_service = PlanningService()
        plan_nodes = planning_service.decompose_task(self.task)
        
        # Return the root plan description
        root_node = next((node for node in plan_nodes if node.node_key == 'root'), None)
        return root_node.description if root_node else "Plan could not be generated"

    def _search_context(self) -> List[Dict[str, Any]]:
        retrieval_service = RetrievalService()
        try:
            results = retrieval_service.search_chunks(
                query=self.task.instruction,
                repository_ids=[self.task.repository.id],
                limit=20,
                similarity_threshold=0.5,
                use_rerank=False,
            )
            return results or []
        except Exception:
            return []

    def _select_files(self, context: List[Dict[str, Any]]) -> List[SelectedFile]:
        """Select files using FileSelectionService."""
        file_selection_service = FileSelectionService()
        selected_files = file_selection_service.select_files(self.task, context)
        return selected_files

    def _generate_candidates(self, selected_files: List[SelectedFile]) -> List[CandidatePatch]:
        """Generate candidates using PatchGenerationService."""
        patch_service = PatchGenerationService()
        candidates = patch_service.generate_candidates(self.task, selected_files)
        return candidates

    def _apply_candidate(self, candidate: CandidatePatch) -> None:
        """Apply candidate using PatchGenerationService."""
        patch_service = PatchGenerationService()
        success = patch_service.apply_candidate_to_workspace(candidate, self.workspace_dir)
        if not success:
            raise Exception(f"Failed to apply candidate {candidate.candidate_key}")

    def _run_validation(self) -> tuple[int, str, int]:
        import io
        import unittest

        stream = io.StringIO()
        runner = unittest.TextTestRunner(stream=stream, verbosity=2)
        started = time.monotonic()
        try:
            suite = unittest.defaultTestLoader.discover(str(self.workspace_dir))
            result = runner.run(suite)
            exit_code = 0 if result.wasSuccessful() else 1
        except Exception as exc:
            exit_code = 1
            stream.write(f'Error running validation: {exc}\n')
        duration_ms = int((time.monotonic() - started) * 1000)
        return exit_code, stream.getvalue(), duration_ms

    def run_agent_loop(self) -> Dict[str, Any]:
        """Run a bounded synchronous agent loop for one task.

        The loop is intentionally synchronous-safe and bounded by
        ConfigService.get_agent_config().  Celery tasks can continue to invoke
        ``run()`` and are therefore preserved for async execution later.
        """
        if self.task.status not in ('queued', 'failed', 'cancel_requested'):
            return self.task.result_payload or {}

        agent_config = ConfigService.get_agent_config()
        max_iterations = int(agent_config.get('max_iterations', 3))
        max_repair_attempts = int(agent_config.get('max_repair_attempts', 2))
        auto_apply = bool(agent_config.get('auto_apply_patches', False))

        result_payload: Dict[str, Any] = {
            'iterations': 0,
            'repair_attempts': 0,
            'max_repair_attempts': max_repair_attempts,
            'auto_apply_patches': auto_apply,
            'candidate_count': 0,
            'selected_candidate_id': None,
            'needs_approval': not auto_apply,
        }

        self.task.started_at = timezone.now()
        # Initialise planning stage
        self.task.status = 'planning'
        self.task.current_stage = 'planning'
        self.task.error_message = ''
        self.task.failure_reason = ''
        self.task.save(update_fields=['started_at', 'status', 'current_stage', 'error_message', 'failure_reason', 'updated_at'])
        self._heartbeat('planning')

        current_step: Optional[TaskStep] = None
        try:
            self._check_cancelled()
            repository_path = self._copy_repository()
            # Use 'baseline' as the initial snapshot type.  The WorkspaceSnapshot
            # model defines the valid snapshot types as 'baseline', 'pre_apply',
            # 'post_apply' and 'rollback'.  Using an undefined value such as
            # 'initial' causes a validation error when the snapshot is saved.
            self._create_workspace_snapshot(snapshot_type='baseline', metadata={'repository_path': str(repository_path)})

            plan_step = self._create_step('planning', 'planning', summary='Planning task execution')
            current_step = plan_step
            plan_content = self._generate_plan()
            root_node = PlanNode.objects.create(
                task=self.task,
                node_key='root-plan',
                title='Root task plan',
                description=plan_content,
                action_type='plan',
                order=0,
                status='completed',
                metadata={'instruction': self.task.instruction, 'agent_config': agent_config},
            )
            self._write_artifact(plan_step, 'plan', 'plan.txt', plan_content, metadata={'plan_node_id': str(root_node.id)})
            self._add_log(plan_step, 'Generated bounded task plan')
            self._complete_step(plan_step, 'completed', summary='Planning completed')

            context_results: List[Dict[str, Any]] = []
            selected_files: List[SelectedFile] = []
            all_candidates: List[CandidatePatch] = []
            selected_candidate: Optional[CandidatePatch] = None
            validation_status = 'skipped'

            for iteration in range(1, max_iterations + 1):
                # Heartbeat and cancellation check at the start of each iteration
                self._check_cancelled()
                self._heartbeat(f'iteration_{iteration}')
                result_payload['iterations'] = iteration
                iter_step = self._create_step(
                    f'agent_iteration_{iteration}',
                    'generating_patch',
                    summary=f'Agent iteration {iteration} of {max_iterations}',
                )
                current_step = iter_step

                if not context_results:
                    context_results = self._search_context()
                    # Heartbeat after context retrieval
                    self._heartbeat(f'context_retrieved_{iteration}')
                    self._write_artifact(
                        iter_step,
                        'context',
                        f'context_iteration_{iteration}.json',
                        json.dumps({'results': context_results}, indent=2),
                        metadata={'iteration': iteration, 'result_count': len(context_results)},
                    )

                if not selected_files:
                    selected_files = self._select_files(context_results)
                    self._heartbeat(f'files_selected_{iteration}')
                    PlanNode.objects.create(
                        task=self.task,
                        parent=root_node,
                        node_key=f'iteration-{iteration}-selected-files',
                        title='Selected files',
                        description='Files selected for candidate patch generation',
                        action_type='selection',
                        order=iteration,
                        status='completed',
                        metadata={'files': [f.path for f in selected_files], 'count': len(selected_files)},
                    )
                    self._write_artifact(
                        iter_step,
                        'selection',
                        f'selected_files_iteration_{iteration}.json',
                        json.dumps({'files': [f.path for f in selected_files]}, indent=2),
                        metadata={'iteration': iteration, 'selected_count': len(selected_files)},
                    )

                candidates = self._generate_candidates(selected_files)
                # Heartbeat after candidate generation
                self._heartbeat(f'candidates_generated_{iteration}')
                all_candidates.extend(candidates)
                result_payload['candidate_count'] = len(all_candidates)
                self._add_log(iter_step, f'Generated {len(candidates)} candidate patch(es)')
                self._write_artifact(
                    iter_step,
                    'log',
                    f'candidates_iteration_{iteration}.json',
                    json.dumps({'candidates': [str(c.id) for c in candidates]}, indent=2),
                    metadata={'iteration': iteration, 'candidate_count': len(candidates)},
                )

                if not candidates:
                    # Mark iteration as failed when no candidates were produced
                    self._complete_step(iter_step, 'failed', summary='No candidate patches generated')
                    break

                selected_candidate = candidates[0]
                result_payload['selected_candidate_id'] = str(selected_candidate.id)
                result_payload['selected_candidate_key'] = selected_candidate.candidate_key

                if auto_apply:
                    try:
                        # Check for cancellation prior to applying the patch
                        self._check_cancelled()
                        apply_step = self._create_step(
                            'applying_patch',
                            'applying_patch',
                            summary=f'Applying {selected_candidate.candidate_key}',
                        )
                        current_step = apply_step
                        self._heartbeat('applying_patch')
                        self._apply_candidate(selected_candidate)
                        selected_candidate.status = 'applied'
                        selected_candidate.save(update_fields=['status', 'updated_at'])
                        self._complete_step(apply_step, 'completed', summary='Candidate applied')
                    except Exception as exc:
                        result_payload['apply_error'] = str(exc)
                        selected_candidate.status = 'failed'
                        selected_candidate.save(update_fields=['status', 'updated_at'])
                        self._complete_step(current_step, 'failed', summary='Candidate apply failed')
                        break

                    try:
                        # Check for cancellation prior to validation
                        self._check_cancelled()
                        validation_step = self._create_step(
                            'validating',
                            'validating',
                            summary=f'Validating {selected_candidate.candidate_key}',
                        )
                        current_step = validation_step
                        self._heartbeat('validating')
                        validation_service = ValidationService()
                        validation_run = validation_service.validate_candidate(self.task, selected_candidate, self.workspace_dir)
                        validation_status = validation_run.status
                        self._write_artifact(
                            validation_step,
                            'validation',
                            f'validation_{selected_candidate.candidate_key}.json',
                            validation_run.output or '',
                            candidate_patch=selected_candidate,
                            validation_run=validation_run,
                            metadata={'validation_status': validation_status, 'iteration': iteration},
                        )
                        self._complete_step(validation_step, validation_status, summary=f'Validation {validation_status}')
                    except Exception as exc:
                        validation_status = 'error'
                        result_payload['validation_error'] = str(exc)
                        self._complete_step(current_step, 'failed', summary='Validation failed to run')

                    if validation_status == 'passed':
                        self._complete_step(iter_step, 'completed', summary='Iteration completed with passing validation')
                        break

                    if result_payload['repair_attempts'] >= max_repair_attempts:
                        self._add_log(iter_step, 'Repair attempt limit reached; stopping loop')
                        self._complete_step(iter_step, 'failed', summary='Repair attempt limit reached')
                        break

                    # A bounded repair attempt is represented and counted even if a
                    # concrete repair implementation is not configured.
                    repair_step = self._create_step(
                        'repair_attempt',
                        'generating_patch',
                        summary=f'Repair attempt {result_payload["repair_attempts"] + 1} of {max_repair_attempts}',
                    )
                    current_step = repair_step
                    self._heartbeat('repair_attempt')
                    result_payload['repair_attempts'] += 1
                    try:
                        repair_service = BugRepairService()
                        # The repair service API varies across deployments.  Use a
                        # best-effort hook without making it mandatory for sync safety.
                        repair_hook = getattr(repair_service, 'repair_candidate', None)
                        if callable(repair_hook):
                            repair_hook(self.task, selected_candidate, self.workspace_dir)
                        self._complete_step(repair_step, 'completed', summary='Repair hook completed')
                    except Exception as exc:
                        self._add_log(repair_step, f'Repair hook failed: {exc}')
                        self._complete_step(repair_step, 'failed', summary='Repair hook failed')
                else:
                    # Review-only mode: stop after proposing a patch.
                    self._complete_step(iter_step, 'awaiting_review', summary='Candidate proposed for review')
                    break

            # If a candidate was selected, generate a unified diff capturing all changes
            if selected_candidate:
                diff = self._generate_diff()
                if diff:
                    self._write_artifact(
                        None,
                        'patch',
                        f'diff_{selected_candidate.candidate_key}.patch',
                        diff,
                        candidate_patch=selected_candidate,
                        metadata={'candidate_key': selected_candidate.candidate_key},
                    )

            # Determine the final status for the task based on outcomes
            final_status: str
            failure_reason: str = ''
            if not all_candidates:
                final_status = 'failed'
                failure_reason = 'patch_generation_failure'
            else:
                if auto_apply:
                    # In auto-apply mode, completion depends on validation status
                    if validation_status == 'passed':
                        final_status = 'completed'
                    elif validation_status == 'error':
                        final_status = 'validation_failed'
                        failure_reason = 'validation_failure'
                    elif validation_status == 'failed':
                        final_status = 'validation_failed'
                        failure_reason = 'validation_failure'
                    else:
                        # Unknown status
                        final_status = 'failed'
                        failure_reason = 'validation_failure'
                else:
                    # Review mode – waiting for manual approval
                    final_status = 'awaiting_review'

            # Set summary fields based on final_status
            if final_status == 'completed':
                summary = 'Task finished successfully'
                result_summary = f"Agent loop finished; validation={validation_status}"
            elif final_status == 'awaiting_review':
                summary = 'Patch proposed for review'
                result_summary = 'Patch proposed for review; approval required before applying'
            elif final_status == 'validation_failed':
                summary = 'Validation failed'
                result_summary = 'Task failed during validation'
            else:
                summary = 'Task failed'
                result_summary = 'Task failed'

            self.task.status = final_status
            self.task.current_stage = final_status
            self.task.summary = summary
            self.task.result_summary = result_summary
            self.task.result_payload = result_payload
            self.task.failure_reason = failure_reason
            self.task.completed_at = timezone.now()
            self.task.last_heartbeat_at = timezone.now()
            self.task.save(
                update_fields=[
                    'status',
                    'current_stage',
                    'summary',
                    'result_summary',
                    'result_payload',
                    'failure_reason',
                    'completed_at',
                    'last_heartbeat_at',
                    'updated_at',
                ]
            )
            self._write_artifact(
                None,
                'result',
                'result.json',
                json.dumps(self.task.result_payload, indent=2),
                description='Final task result payload',
                metadata={'status': self.task.status},
            )
            return result_payload

        except TaskCancelled as exc:
            self.task.status = 'cancelled'
            self.task.current_stage = 'cancelled'
            self.task.error_message = str(exc)
            self.task.result_summary = 'Task cancelled'
            self.task.cancelled_at = timezone.now()
            self.task.completed_at = timezone.now()
            self.task.last_heartbeat_at = timezone.now()
            self.task.result_payload = result_payload
            self.task.save(
                update_fields=[
                    'status', 'current_stage', 'error_message', 'result_summary', 'cancelled_at',
                    'completed_at', 'last_heartbeat_at', 'result_payload', 'updated_at',
                ]
            )
            if current_step and current_step.status not in {'completed', 'failed', 'cancelled'}:
                self._complete_step(current_step, 'cancelled', summary='Task cancelled during execution')
            return result_payload

        except Exception as exc:
            self.task.status = 'failed'
            self.task.current_stage = 'failed'
            self.task.error_message = str(exc)
            self.task.error_details = {'type': exc.__class__.__name__}
            self.task.result_summary = 'Task failed'
            self.task.result_payload = result_payload
            self.task.completed_at = timezone.now()
            self.task.last_heartbeat_at = timezone.now()
            self.task.save(
                update_fields=[
                    'status', 'current_stage', 'error_message', 'error_details', 'result_summary',
                    'result_payload', 'completed_at', 'last_heartbeat_at', 'updated_at',
                ]
            )
            if current_step and current_step.status not in {'completed', 'failed', 'cancelled'}:
                self._complete_step(current_step, 'failed', summary='Task failed during execution')
            return result_payload

    def run(self) -> None:
        """Backward-compatible entrypoint used by Celery and synchronous callers."""
        self.run_agent_loop()
