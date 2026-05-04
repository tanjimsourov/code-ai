"""Patch generation service for creating multiple candidate solutions."""

from typing import List, Dict, Any, Optional
from pathlib import Path
import json
import difflib
from ..models import TaskRun, CandidatePatch, SelectedFile
from ..services import ChatService


class PatchGenerationService:
    """Service for generating multiple candidate patches for a task."""
    
    def __init__(self):
        self.chat_service = ChatService()
    
    def generate_candidates(self, task: TaskRun, selected_files: List[SelectedFile]) -> List[CandidatePatch]:
        """Generate multiple candidate patches for the task."""
        
        candidates = []
        
        # Strategy 1: Conservative approach - minimal changes
        conservative_candidate = self._generate_conservative_candidate(task, selected_files)
        if conservative_candidate:
            candidates.append(conservative_candidate)
        
        # Strategy 2: Comprehensive approach - full rewrite
        comprehensive_candidate = self._generate_comprehensive_candidate(task, selected_files)
        if comprehensive_candidate:
            candidates.append(comprehensive_candidate)
        
        # Strategy 3: Incremental approach - step-by-step changes
        incremental_candidate = self._generate_incremental_candidate(task, selected_files)
        if incremental_candidate:
            candidates.append(incremental_candidate)
        
        # Strategy 4: Alternative approach - different patterns
        if task.task_type in ['feature', 'refactor']:
            alternative_candidate = self._generate_alternative_candidate(task, selected_files)
            if alternative_candidate:
                candidates.append(alternative_candidate)
        
        return candidates
    
    def _generate_conservative_candidate(self, task: TaskRun, selected_files: List[SelectedFile]) -> Optional[CandidatePatch]:
        """Generate a conservative candidate with minimal changes."""
        
        system_prompt = (
            "You are a conservative software engineer. "
            "Make the minimal necessary changes to achieve the goal. "
            "Preserve existing patterns and avoid breaking changes. "
            "Focus on safety and stability."
        )
        
        return self._generate_patch_with_strategy(
            task, selected_files, 'conservative', system_prompt
        )
    
    def _generate_comprehensive_candidate(self, task: TaskRun, selected_files: List[SelectedFile]) -> Optional[CandidatePatch]:
        """Generate a comprehensive candidate that may involve larger changes."""
        
        system_prompt = (
            "You are an innovative software engineer. "
            "Create the best possible solution, even if it requires significant changes. "
            "Improve the code structure, patterns, and maintainability. "
            "Don't be afraid to refactor for better design."
        )
        
        return self._generate_patch_with_strategy(
            task, selected_files, 'comprehensive', system_prompt
        )
    
    def _generate_incremental_candidate(self, task: TaskRun, selected_files: List[SelectedFile]) -> Optional[CandidatePatch]:
        """Generate an incremental candidate with step-by-step changes."""
        
        system_prompt = (
            "You are a methodical software engineer. "
            "Break down the changes into clear, incremental steps. "
            "Each change should be independently verifiable. "
            "Focus on maintainability and clear progression."
        )
        
        return self._generate_patch_with_strategy(
            task, selected_files, 'incremental', system_prompt
        )
    
    def _generate_alternative_candidate(self, task: TaskRun, selected_files: List[SelectedFile]) -> Optional[CandidatePatch]:
        """Generate an alternative candidate using different patterns."""
        
        system_prompt = (
            "You are a creative software engineer. "
            "Propose an alternative approach to solve this problem. "
            "Consider different design patterns, algorithms, or architectures. "
            "Challenge assumptions and suggest innovative solutions."
        )
        
        return self._generate_patch_with_strategy(
            task, selected_files, 'alternative', system_prompt
        )
    
    def _generate_patch_with_strategy(
        self, 
        task: TaskRun, 
        selected_files: List[SelectedFile], 
        strategy: str, 
        system_prompt: str
    ) -> Optional[CandidatePatch]:
        """Generate a patch using a specific strategy."""
        
        try:
            # Prepare file context
            file_context = self._prepare_file_context(selected_files)
            
            # Generate patch using LLM
            patch_content = self._call_llm_for_patch(task, file_context, system_prompt, strategy)
            
            if not patch_content:
                return None
            
            # Parse patch content
            parsed_patch = self._parse_patch_response(patch_content)
            # Validate parsed patch
            if not parsed_patch or not parsed_patch.get('files'):
                return None

            files_dict = parsed_patch.get('files', {})
            changed_files = list(files_dict.keys())
            diff_lines: List[str] = []
            before_snippets: Dict[str, str] = {}
            after_snippets: Dict[str, str] = {}

            # Build original file map for diffing
            original_map: Dict[str, str] = {}
            for sel_file in selected_files:
                # Use full indexed file content if available
                if sel_file.indexed_file:
                    try:
                        content = '\n'.join(
                            chunk.content for chunk in sel_file.indexed_file.chunks.all().order_by('chunk_index')
                        )
                        original_map[sel_file.path] = content
                    except Exception:
                        pass

            # Compute unified diff and snippets for each changed file
            for file_path, new_content in files_dict.items():
                orig_content = original_map.get(file_path, '')
                # Ensure new content is string
                new_content_str = new_content if isinstance(new_content, str) else str(new_content)
                diff = difflib.unified_diff(
                    orig_content.splitlines(),
                    new_content_str.splitlines(),
                    fromfile=f"a/{file_path}",
                    tofile=f"b/{file_path}",
                    lineterm=''
                )
                diff_segment = list(diff)
                if diff_segment:
                    diff_lines.extend(diff_segment)
                # store first 3 lines of original/new for snippets
                before_snippets[file_path] = '\n'.join(orig_content.splitlines()[:3])
                after_snippets[file_path] = '\n'.join(new_content_str.splitlines()[:3])

            # Update parsed_patch with metadata
            parsed_patch['changed_files'] = changed_files
            parsed_patch['diff'] = '\n'.join(diff_lines)
            # Default status to proposed if not set
            parsed_patch.setdefault('status', 'proposed')
            parsed_patch['before_snippets'] = before_snippets
            parsed_patch['after_snippets'] = after_snippets

            # Create candidate patch record
            candidate = CandidatePatch.objects.create(
                task=task,
                candidate_key=f"{strategy}_candidate",
                status='generated',
                summary=f"Generated {strategy} candidate for {task.task_type}",
                patch_metadata={
                    'strategy': strategy,
                    'generation_method': 'llm_based',
                    'file_count': len(files_dict),
                    'changed_files': changed_files,
                },
                touched_files=changed_files
            )

            # Persist patch data as artifact with metadata
            from ..services.task_artifact_service import TaskArtifactService
            TaskArtifactService.persist_text_artifact(
                task=task,
                artifact_type='patch',
                relative_name=f"candidate_{candidate.candidate_key}.json",
                content=json.dumps(parsed_patch, indent=2),
                description=f"{strategy.title()} candidate patch",
                candidate_patch=candidate,
                metadata={'strategy': strategy, 'changed_files': changed_files}
            )

            return candidate
            
        except Exception as exc:
            print(f"Error generating {strategy} candidate: {exc}")
            return None
    
    def _prepare_file_context(self, selected_files: List[SelectedFile]) -> Dict[str, str]:
        """Prepare file context for LLM."""
        
        context = {}
        
        # Sort by rank and limit to top files to avoid context overflow
        top_files = sorted(selected_files, key=lambda f: f.rank)[:10]
        
        for selected_file in top_files:
            try:
                # Get file content
                if selected_file.indexed_file:
                    chunks = selected_file.indexed_file.chunks.all().order_by('chunk_index')
                    content = '\n'.join(chunk.content for chunk in chunks)
                    context[selected_file.path] = content
            except Exception:
                continue
        
        return context
    
    def _call_llm_for_patch(
        self, 
        task: TaskRun, 
        file_context: Dict[str, str], 
        system_prompt: str, 
        strategy: str
    ) -> Optional[str]:
        """Call LLM to generate patch."""
        
        # Construct user prompt
        user_prompt = self._build_user_prompt(task, file_context, strategy)
        
        messages = [
            {'role': 'system', 'content': system_prompt},
            {'role': 'user', 'content': user_prompt}
        ]
        
        try:
            response = self.chat_service.chat_completion(
                messages=messages,
                temperature=0.3 if strategy == 'conservative' else 0.7,
                max_tokens=4000
            )
            
            if isinstance(response, dict):
                choices = response.get('choices') or []
                if choices:
                    first_choice = choices[0] or {}
                    message = first_choice.get('message') or {}
                    return message.get('content', '') or ''
            
            return None
            
        except Exception as exc:
            print(f"LLM call failed for {strategy} candidate: {exc}")
            return None
    
    def _build_user_prompt(self, task: TaskRun, file_context: Dict[str, str], strategy: str) -> str:
        """Build user prompt for LLM."""
        
        prompt_parts = [
            f"Task: {task.instruction}",
            f"Task Type: {task.task_type}",
            f"Strategy: {strategy}",
            "",
            "Files to modify:",
        ]
        
        # Add file context
        for file_path, content in file_context.items():
            # Truncate very long files
            if len(content) > 2000:
                content = content[:1000] + "\n...[truncated]...\n" + content[-1000:]
            
            prompt_parts.extend([
                f"\n--- {file_path} ---",
                content,
                "---"
            ])
        
        prompt_parts.extend([
            "",
            "Please provide the modified file contents in the following JSON format:",
            "{",
            '  "files": {',
            '    "path/to/file1.py": "modified content...",',
            '    "path/to/file2.py": "modified content..."',
            "  },",
            '  "explanation": "Brief explanation of changes",',
            '  "risk_level": "low|medium|high"',
            "}",
            "",
            "Only modify files that need changes. Keep unchanged files out of the response."
        ])
        
        return '\n'.join(prompt_parts)
    
    def _parse_patch_response(self, response: str) -> Optional[Dict[str, Any]]:
        """Parse LLM response into structured patch."""
        
        try:
            # Try to extract JSON from response
            start_marker = "```json"
            end_marker = "```"
            
            start_idx = response.find(start_marker)
            if start_idx != -1:
                start_idx += len(start_marker)
                end_idx = response.find(end_marker, start_idx)
                if end_idx != -1:
                    json_str = response[start_idx:end_idx].strip()
                else:
                    json_str = response[start_idx:].strip()
            else:
                # Try to find JSON directly
                start_idx = response.find("{")
                end_idx = response.rfind("}") + 1
                if start_idx != -1 and end_idx > start_idx:
                    json_str = response[start_idx:end_idx]
                else:
                    return None
            
            # Parse JSON
            patch_data = json.loads(json_str)
            
            # Validate structure
            if not isinstance(patch_data, dict) or 'files' not in patch_data:
                return None
            
            files = patch_data['files']
            if not isinstance(files, dict):
                return None
            
            return patch_data
            
        except Exception as exc:
            print(f"Error parsing patch response: {exc}")
            return None
    
    def apply_candidate_to_workspace(self, candidate: CandidatePatch, workspace_dir: Path) -> bool:
        """Apply a candidate patch to the workspace safely using PatchService.

        Retrieves the patch artifact associated with the candidate, validates
        the patch, applies it to the provided ``workspace_dir`` via
        ``PatchService.apply_patch``, and updates the candidate status to
        ``applied`` if successful.  Returns ``True`` on success and ``False``
        on failure.
        """
        try:
            # Locate patch artifact for this candidate
            from ..services.task_artifact_service import TaskArtifactService
            from ..services.patch_service import PatchService
            artifacts = candidate.task.artifacts.filter(
                artifact_type='patch',
                candidate_patch=candidate
            )
            if not artifacts.exists():
                print(f"No patch artifact found for candidate {candidate.candidate_key}")
                return False
            artifact = artifacts.first()
            patch_json = TaskArtifactService.read_content(artifact)
            patch_data = json.loads(patch_json)
            # Apply patch to workspace
            PatchService.apply_patch(patch_data, workspace_dir)
            # Update status
            candidate.status = 'applied'
            candidate.save(update_fields=['status'])
            return True
        except Exception as exc:
            print(f"Error applying candidate {candidate.candidate_key}: {exc}")
            # Mark candidate as failed if apply fails
            try:
                candidate.status = 'failed'
                candidate.save(update_fields=['status'])
            except Exception:
                pass
            return False
