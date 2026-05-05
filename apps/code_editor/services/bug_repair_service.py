"""Bug repair service with failing-test-first approach."""

import os
from typing import List, Dict, Any, Optional, Tuple
from pathlib import Path
import re
import json
from django.utils import timezone
from ..models import TaskRun, CandidatePatch, ValidationRun, TestRun
from ..services import ChatService
from ..services.validation_service import ValidationService
from ..services.patch_generation_service import PatchGenerationService


class BugRepairService:
    """Service for repairing bugs using failing-test-first approach."""
    
    def __init__(self):
        self.chat_service = ChatService()
        self.validation_service = ValidationService()
        self.patch_service = PatchGenerationService()
        # Use a sandboxed command runner for executing tests and custom scripts
        try:
            from .command_runner import CommandRunner  # local import to avoid circulars
            self.command_runner = CommandRunner(workspace_root=os.getenv('CODE_EDITOR_TASK_STORAGE_ROOT'))
        except Exception:
            # Fallback: no sandbox available; commands may be unsafe
            self.command_runner = None
    
    def repair_bug(self, task: TaskRun, workspace_dir: Path) -> Optional[CandidatePatch]:
        """Repair a bug using failing-test-first methodology."""
        
        try:
            # Step 1: Identify failing tests
            failing_tests = self._identify_failing_tests(task, workspace_dir)
            
            if not failing_tests:
                # No failing tests found, try to reproduce the bug
                failing_tests = self._reproduce_bug(task, workspace_dir)
            
            if not failing_tests:
                return None
            
            # Step 2: Analyze the failure
            failure_analysis = self._analyze_failure(task, failing_tests, workspace_dir)
            
            # Step 3: Generate targeted fix
            fix_candidate = self._generate_targeted_fix(task, failure_analysis, workspace_dir)
            
            if not fix_candidate:
                return None
            
            # Step 4: Validate the fix
            validation_result = self._validate_bug_fix(task, fix_candidate, workspace_dir)
            
            if validation_result['tests_passed']:
                return fix_candidate
            else:
                # Try iterative refinement
                return self._refine_fix(task, fix_candidate, validation_result, workspace_dir)
            
        except Exception as exc:
            print(f"Error in bug repair: {exc}")
            return None
    
    def _identify_failing_tests(self, task: TaskRun, workspace_dir: Path) -> List[Dict[str, Any]]:
        """Identify currently failing tests."""
        
        failing_tests = []
        
        try:
            # Run tests to find failures using allowed commands
            test_commands = [
                ['python', '-m', 'pytest', '--tb=short', '-v'],
                ['python', '-m', 'unittest', 'discover', '-v'],
                ['npm', 'test'],
                ['yarn', 'test']
            ]
            
            for cmd in test_commands:
                try:
                    if self.command_runner:
                        result = self.command_runner.run(cmd, cwd=workspace_dir)
                        exit_code = result.get('exit_code', -99)
                        output = result.get('output', '')
                        # Only consider this test framework if command executed (non negative allowed codes)
                        if exit_code == -3 or exit_code == -2:
                            # Command not allowed or missing; try next framework
                            continue
                        # If tests failed, parse failing tests
                        if exit_code != 0:
                            failures = self._parse_test_failures(output, cmd[0])
                            failing_tests.extend(failures)
                            break  # Use first test framework that provides results
                    else:
                        # Fallback to subprocess if sandbox unavailable
                        import subprocess
                        proc = subprocess.run(
                            cmd,
                            cwd=workspace_dir,
                            capture_output=True,
                            text=True,
                            timeout=60
                        )
                        if proc.returncode != 0:
                            failures = self._parse_test_failures(proc.stdout + proc.stderr, cmd[0])
                            failing_tests.extend(failures)
                            break
                except Exception:
                    continue
        except Exception as exc:
            print(f"Error identifying failing tests: {exc}")
        
        return failing_tests
    
    def _reproduce_bug(self, task: TaskRun, workspace_dir: Path) -> List[Dict[str, Any]]:
        """Try to reproduce the bug from the task description."""
        
        failing_tests = []
        
        try:
            # Generate a test case to reproduce the bug
            test_case = self._generate_reproduction_test(task, workspace_dir)
            
            if test_case:
                # Write the test case
                test_file = workspace_dir / 'bug_reproduction_test.py'
                with open(test_file, 'w', encoding='utf-8') as f:
                    f.write(test_case)
                
                # Run the test
                try:
                    if self.command_runner:
                        result = self.command_runner.run(['python', str(test_file)], cwd=workspace_dir)
                        exit_code = result.get('exit_code', -99)
                        output = result.get('output', '')
                        if exit_code != 0:
                            failing_tests.append({
                                'test_file': 'bug_reproduction_test.py',
                                'test_name': 'bug_reproduction',
                                'error': output,
                                'output': output
                            })
                    else:
                        import subprocess
                        proc = subprocess.run(
                            ['python', str(test_file)],
                            cwd=workspace_dir,
                            capture_output=True,
                            text=True,
                            timeout=30
                        )
                        if proc.returncode != 0:
                            failing_tests.append({
                                'test_file': 'bug_reproduction_test.py',
                                'test_name': 'bug_reproduction',
                                'error': proc.stderr,
                                'output': proc.stdout + proc.stderr
                            })
                except Exception:
                    failing_tests.append({
                        'test_file': 'bug_reproduction_test.py',
                        'test_name': 'bug_reproduction',
                        'error': 'Test execution error',
                        'output': 'Test execution failed'
                    })
        
        except Exception as exc:
            print(f"Error reproducing bug: {exc}")
        
        return failing_tests
    
    def _generate_reproduction_test(self, task: TaskRun, workspace_dir: Path) -> Optional[str]:
        """Generate a test case to reproduce the bug."""
        
        system_prompt = (
            "You are a QA engineer. Generate a Python test case that reproduces the bug described. "
            "The test should fail with the current code and pass when the bug is fixed. "
            "Use unittest framework. Focus on the core issue described."
        )
        
        user_prompt = f"""
Task: {task.instruction}
Task Type: {task.task_type}

Generate a test case that reproduces this issue. The test should:
1. Import the relevant modules
2. Set up the scenario described in the task
3. Assert the expected behavior (which should currently fail)
4. Be runnable as a standalone test

Return only the Python code for the test.
"""
        
        messages = [
            {'role': 'system', 'content': system_prompt},
            {'role': 'user', 'content': user_prompt}
        ]
        
        try:
            response = self.chat_service.chat_completion(
                messages=messages,
                temperature=0.1,
                max_tokens=1000
            )
            
            if isinstance(response, dict):
                choices = response.get('choices') or []
                if choices:
                    first_choice = choices[0] or {}
                    message = first_choice.get('message') or {}
                    content = message.get('content', '') or ''
                    
                    # Extract code from response
                    code_match = re.search(r'```python\n(.*?)\n```', content, re.DOTALL)
                    if code_match:
                        return code_match.group(1)
                    else:
                        # Return content as-is if no code blocks
                        return content
            
        except Exception as exc:
            print(f"Error generating reproduction test: {exc}")
        
        return None
    
    def _parse_test_failures(self, output: str, test_framework: str) -> List[Dict[str, Any]]:
        """Parse test output to extract failing test information."""
        
        failures = []
        
        try:
            if 'pytest' in test_framework:
                # Parse pytest output
                lines = output.split('\n')
                current_test = None
                error_lines = []
                
                for line in lines:
                    if 'FAILED' in line and '::' in line:
                        if current_test:
                            failures.append({
                                'test_file': current_test.split('::')[0],
                                'test_name': current_test.split('::')[-1],
                                'error': '\n'.join(error_lines),
                                'output': current_test
                            })
                        
                        current_test = line.split('FAILED')[1].strip()
                        error_lines = []
                    elif current_test and line.strip():
                        error_lines.append(line)
                
                # Add last failure
                if current_test:
                    failures.append({
                        'test_file': current_test.split('::')[0],
                        'test_name': current_test.split('::')[-1],
                        'error': '\n'.join(error_lines),
                        'output': current_test
                    })
            
            elif 'unittest' in test_framework:
                # Parse unittest output
                failure_match = re.search(r'FAIL: (.+)', output)
                if failure_match:
                    test_name = failure_match.group(1)
                    failures.append({
                        'test_file': test_name.split('(')[0].strip() if '(' in test_name else 'unknown',
                        'test_name': test_name,
                        'error': output,
                        'output': output
                    })
        
        except Exception as exc:
            print(f"Error parsing test failures: {exc}")
        
        return failures
    
    def _analyze_failure(self, task: TaskRun, failing_tests: List[Dict[str, Any]], workspace_dir: Path) -> Dict[str, Any]:
        """Analyze the test failure to understand the root cause."""
        
        analysis = {
            'error_type': 'unknown',
            'error_location': 'unknown',
            'root_cause': 'unknown',
            'suggested_fix': 'unknown',
            'affected_files': []
        }
        
        try:
            # Prepare failure context
            failure_context = self._prepare_failure_context(failing_tests, workspace_dir)
            
            # Use LLM to analyze the failure
            system_prompt = (
                "You are a senior software engineer debugging a test failure. "
                "Analyze the test failure and identify: "
                "1. The type of error (assertion, exception, etc.) "
                "2. The likely location of the bug "
                "3. The root cause "
                "4. A suggested approach to fix it "
                "5. Which files are likely affected"
            )
            
            user_prompt = f"""
Task: {task.instruction}

Failing Tests:
{json.dumps(failing_tests, indent=2)}

Code Context:
{json.dumps(failure_context, indent=2)}

Analyze this failure and provide a structured analysis.
"""
            
            messages = [
                {'role': 'system', 'content': system_prompt},
                {'role': 'user', 'content': user_prompt}
            ]
            
            response = self.chat_service.chat_completion(
                messages=messages,
                temperature=0.1,
                max_tokens=1500
            )
            
            if isinstance(response, dict):
                choices = response.get('choices') or []
                if choices:
                    first_choice = choices[0] or {}
                    message = first_choice.get('message') or {}
                    content = message.get('content', '') or ''
                    
                    # Parse the analysis
                    analysis = self._parse_failure_analysis(content)
        
        except Exception as exc:
            print(f"Error analyzing failure: {exc}")
        
        return analysis
    
    def _prepare_failure_context(self, failing_tests: List[Dict[str, Any]], workspace_dir: Path) -> Dict[str, Any]:
        """Prepare code context around the failure."""
        
        context = {}
        
        try:
            for test in failing_tests[:3]:  # Limit to top 3 failures
                test_file = test.get('test_file', '')
                if test_file:
                    full_path = workspace_dir / test_file
                    if full_path.exists():
                        try:
                            with open(full_path, 'r', encoding='utf-8') as f:
                                content = f.read()
                            
                            # Extract relevant parts (test method, imports, etc.)
                            context[test_file] = {
                                'content': content[:2000],  # Limit size
                                'error': test.get('error', '')[:500]
                            }
                        except Exception:
                            continue
        
        except Exception as exc:
            print(f"Error preparing failure context: {exc}")
        
        return context
    
    def _parse_failure_analysis(self, analysis_text: str) -> Dict[str, Any]:
        """Parse the LLM analysis into structured data."""
        
        analysis = {
            'error_type': 'unknown',
            'error_location': 'unknown',
            'root_cause': 'unknown',
            'suggested_fix': 'unknown',
            'affected_files': []
        }
        
        try:
            # Extract information using patterns
            patterns = {
                'error_type': r'Error Type:\s*(.+?)(?=\n|$)',
                'error_location': r'Error Location:\s*(.+?)(?=\n|$)',
                'root_cause': r'Root Cause:\s*(.+?)(?=\n|$)',
                'suggested_fix': r'Suggested Fix:\s*(.+?)(?=\n|$)',
                'affected_files': r'Affected Files:\s*(.+?)(?=\n|$)'
            }
            
            for key, pattern in patterns.items():
                match = re.search(pattern, analysis_text, re.IGNORECASE)
                if match:
                    value = match.group(1).strip()
                    if key == 'affected_files':
                        # Parse file list
                        files = [f.strip() for f in value.split(',')]
                        analysis[key] = [f for f in files if f]
                    else:
                        analysis[key] = value
        
        except Exception as exc:
            print(f"Error parsing failure analysis: {exc}")
        
        return analysis
    
    def _generate_targeted_fix(self, task: TaskRun, failure_analysis: Dict[str, Any], workspace_dir: Path) -> Optional[CandidatePatch]:
        """Generate a targeted fix based on the failure analysis."""
        
        try:
            # Get affected files
            affected_files = failure_analysis.get('affected_files', [])
            if not affected_files:
                return None
            
            # Read current file contents
            file_contents = {}
            for file_path in affected_files[:3]:  # Limit to 3 files
                full_path = workspace_dir / file_path
                if full_path.exists():
                    try:
                        with open(full_path, 'r', encoding='utf-8') as f:
                            file_contents[file_path] = f.read()
                    except Exception:
                        continue
            
            if not file_contents:
                return None
            
            # Generate fix using LLM
            system_prompt = (
                "You are a senior software engineer fixing a bug. "
                "Generate the minimal necessary changes to fix the issue. "
                "Focus on the root cause and make targeted changes only. "
                "Return the modified file contents in JSON format."
            )
            
            user_prompt = f"""
Task: {task.instruction}

Failure Analysis:
{json.dumps(failure_analysis, indent=2)}

Current File Contents:
{json.dumps(file_contents, indent=2)}

Generate the fix by modifying the affected files. Return JSON format:
{{
  "files": {{
    "path/to/file1.py": "modified content...",
    "path/to/file2.py": "modified content..."
  }},
  "explanation": "Brief explanation of the fix"
}}
"""
            
            messages = [
                {'role': 'system', 'content': system_prompt},
                {'role': 'user', 'content': user_prompt}
            ]
            
            response = self.chat_service.chat_completion(
                messages=messages,
                temperature=0.1,
                max_tokens=3000
            )
            
            if isinstance(response, dict):
                choices = response.get('choices') or []
                if choices:
                    first_choice = choices[0] or {}
                    message = first_choice.get('message') or {}
                    content = message.get('content', '') or ''
                    
                    # Parse the fix
                    fix_data = self._parse_fix_response(content)
                    
                    if fix_data and fix_data.get('files'):
                        # Create candidate patch
                        candidate = CandidatePatch.objects.create(
                            task=task,
                            candidate_key='bug_fix_candidate',
                            status='generated',
                            summary=f"Targeted bug fix based on failure analysis",
                            patch_metadata={
                                'strategy': 'bug_repair',
                                'generation_method': 'failure_analysis',
                                'error_type': failure_analysis.get('error_type'),
                                'root_cause': failure_analysis.get('root_cause')
                            },
                            touched_files=list(fix_data['files'].keys())
                        )
                        
                        # Store fix as artifact
                        from ..services.task_artifact_service import TaskArtifactService
                        TaskArtifactService.persist_text_artifact(
                            task=task,
                            artifact_type='patch',
                            relative_name=f"bug_fix_{candidate.candidate_key}.json",
                            content=json.dumps(fix_data, indent=2),
                            description="Bug fix generated from failure analysis",
                            candidate_patch=candidate,
                            metadata={'strategy': 'bug_repair'}
                        )
                        
                        return candidate
        
        except Exception as exc:
            print(f"Error generating targeted fix: {exc}")
        
        return None
    
    def _parse_fix_response(self, response: str) -> Optional[Dict[str, Any]]:
        """Parse the fix response from LLM."""
        
        try:
            # Extract JSON from response
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
            
            return json.loads(json_str)
            
        except Exception as exc:
            print(f"Error parsing fix response: {exc}")
            return None
    
    def _validate_bug_fix(self, task: TaskRun, candidate: CandidatePatch, workspace_dir: Path) -> Dict[str, Any]:
        """Validate that the bug fix works."""
        
        try:
            # Apply the fix
            success = self.patch_service.apply_candidate_to_workspace(candidate, workspace_dir)
            if not success:
                return {'tests_passed': False, 'error': 'Failed to apply fix'}
            
            # Run tests again
            validation_run = self.validation_service.validate_candidate(task, candidate, workspace_dir)
            
            # Check if tests pass now
            test_runs = validation_run.test_runs.all()
            tests_passed = all(run.status == 'passed' for run in test_runs)
            
            return {
                'tests_passed': tests_passed,
                'validation_status': validation_run.status,
                'test_results': [
                    {
                        'test_name': run.test_command,
                        'status': run.status,
                        'output': run.output[:500]  # Truncate
                    }
                    for run in test_runs
                ]
            }
            
        except Exception as exc:
            return {'tests_passed': False, 'error': str(exc)}
    
    def _refine_fix(self, task: TaskRun, candidate: CandidatePatch, validation_result: Dict[str, Any], workspace_dir: Path) -> Optional[CandidatePatch]:
        """Refine the fix based on validation results."""
        
        try:
            # Analyze what went wrong
            error_context = self._analyze_fix_failure(candidate, validation_result, workspace_dir)
            
            # Generate refined fix
            refined_candidate = self._generate_refined_fix(task, candidate, error_context, workspace_dir)
            
            if refined_candidate:
                # Validate the refined fix
                refined_validation = self._validate_bug_fix(task, refined_candidate, workspace_dir)
                
                if refined_validation['tests_passed']:
                    return refined_candidate
            
        except Exception as exc:
            print(f"Error refining fix: {exc}")
        
        return None
    
    def _analyze_fix_failure(self, candidate: CandidatePatch, validation_result: Dict[str, Any], workspace_dir: Path) -> Dict[str, Any]:
        """Analyze why the fix failed."""
        
        context = {
            'original_error': 'Unknown',
            'new_error': 'Unknown',
            'test_failures': []
        }
        
        try:
            # Get test failures
            test_results = validation_result.get('test_results', [])
            for result in test_results:
                if result['status'] == 'failed':
                    context['test_failures'].append({
                        'test': result['test_name'],
                        'error': result['output']
                    })
            
            # Get original patch content
            from ..services.task_artifact_service import TaskArtifactService
            artifacts = candidate.task.artifacts.filter(
                artifact_type='patch',
                candidate_patch=candidate
            )
            
            if artifacts.exists():
                artifact = artifacts.first()
                patch_content = TaskArtifactService.read_content(artifact)
                context['original_patch'] = json.loads(patch_content)
        
        except Exception as exc:
            print(f"Error analyzing fix failure: {exc}")
        
        return context
    
    def _generate_refined_fix(self, task: TaskRun, original_candidate: CandidatePatch, error_context: Dict[str, Any], workspace_dir: Path) -> Optional[CandidatePatch]:
        """Generate a refined fix based on error analysis."""
        
        try:
            # This would implement iterative refinement
            # For now, return None (could be extended later)
            return None
        
        except Exception as exc:
            print(f"Error generating refined fix: {exc}")
            return None
