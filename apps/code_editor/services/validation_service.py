"""Validation service for comprehensive candidate testing."""

from typing import List, Dict, Any, Optional, Tuple
from pathlib import Path
import subprocess
import time
import json
from django.utils import timezone
from ..models import TaskRun, CandidatePatch, ValidationRun, TestRun


class ValidationService:
    """Service for comprehensive validation of candidate patches."""
    
    def __init__(self):
        # Instantiate a sandboxed command runner for executing test and syntax commands
        try:
            from .command_runner import CommandRunner
            self.command_runner = CommandRunner()
        except Exception:
            self.command_runner = None
    
    def validate_candidate(self, task: TaskRun, candidate: CandidatePatch, workspace_dir: Path) -> ValidationRun:
        """Comprehensively validate a candidate patch."""
        
        # Create validation run
        validation_run = ValidationRun.objects.create(
            task=task,
            candidate_patch=candidate,
            stage_name='comprehensive_validation',
            validation_type='multi_stage',
            status='queued',
            command='comprehensive_validation_suite'
        )
        
        try:
            # Stage 1: Syntax validation
            syntax_result = self._validate_syntax(workspace_dir, validation_run)
            
            # Stage 2: Basic functionality tests
            if syntax_result['passed']:
                basic_test_result = self._run_basic_tests(workspace_dir, validation_run)
            else:
                basic_test_result = {'passed': False, 'reason': 'Syntax validation failed'}
            
            # Stage 3: Targeted tests (if available)
            if basic_test_result['passed']:
                targeted_result = self._run_targeted_tests(task, workspace_dir, validation_run)
            else:
                targeted_result = {'passed': False, 'reason': 'Basic tests failed'}
            
            # Stage 4: Regression tests (if available)
            if targeted_result['passed']:
                regression_result = self._run_regression_tests(workspace_dir, validation_run)
            else:
                regression_result = {'passed': False, 'reason': 'Targeted tests failed'}
            
            # Calculate overall result
            overall_passed = all([
                syntax_result['passed'],
                basic_test_result['passed'],
                targeted_result['passed'],
                regression_result['passed']
            ])
            
            # Update validation run
            validation_run.status = 'passed' if overall_passed else 'failed'
            validation_run.output = json.dumps({
                'syntax': syntax_result,
                'basic_tests': basic_test_result,
                'targeted_tests': targeted_result,
                'regression_tests': regression_result,
                'overall_passed': overall_passed
            }, indent=2)
            validation_run.completed_at = timezone.now()
            validation_run.save()
            
            return validation_run
            
        except Exception as exc:
            validation_run.status = 'error'
            validation_run.output = f"Validation error: {str(exc)}"
            validation_run.completed_at = timezone.now()
            validation_run.save()
            
            return validation_run
    
    def _validate_syntax(self, workspace_dir: Path, validation_run: ValidationRun) -> Dict[str, Any]:
        """Validate syntax of modified files."""
        
        result = {'passed': True, 'errors': [], 'files_checked': 0}
        
        try:
            # Get modified files from candidate
            modified_files = validation_run.candidate_patch.touched_files
            
            for file_path in modified_files:
                full_path = workspace_dir / file_path
                
                if not full_path.exists():
                    result['errors'].append(f"File not found: {file_path}")
                    result['passed'] = False
                    continue
                
                # Language-specific syntax checking
                language = self._detect_language(file_path)
                syntax_ok = self._check_file_syntax(full_path, language)
                
                if not syntax_ok:
                    result['errors'].append(f"Syntax error in {file_path}")
                    result['passed'] = False
                
                result['files_checked'] += 1
            
            return result
            
        except Exception as exc:
            return {'passed': False, 'errors': [str(exc)], 'files_checked': 0}
    
    def _detect_language(self, file_path: str) -> str:
        """Detect programming language from file extension."""
        
        ext = Path(file_path).suffix.lower()
        
        language_map = {
            '.py': 'python',
            '.js': 'javascript',
            '.ts': 'typescript',
            '.java': 'java',
            '.cpp': 'cpp',
            '.c': 'c',
            '.h': 'c',
            '.hpp': 'cpp',
            '.cs': 'csharp',
            '.go': 'go',
            '.rs': 'rust',
            '.php': 'php',
            '.rb': 'ruby'
        }
        
        return language_map.get(ext, 'unknown')
    
    def _check_file_syntax(self, file_path: Path, language: str) -> bool:
        """Check syntax of a single file."""
        
        try:
            if language == 'python':
                return self._check_python_syntax(file_path)
            elif language == 'javascript':
                return self._check_javascript_syntax(file_path)
            elif language == 'typescript':
                return self._check_typescript_syntax(file_path)
            else:
                # For unsupported languages, just check if file is readable
                with open(file_path, 'r', encoding='utf-8') as f:
                    f.read()
                return True
                
        except Exception:
            return False
    
    def _check_python_syntax(self, file_path: Path) -> bool:
        """Check Python syntax."""
        
        try:
            import ast
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
            ast.parse(content)
            return True
        except SyntaxError:
            return False
        except Exception:
            return False
    
    def _check_javascript_syntax(self, file_path: Path) -> bool:
        """Check JavaScript syntax (basic check)."""
        
        try:
            # Simple check - try to run through node
            if self.command_runner:
                res = self.command_runner.run(['node', '--check', str(file_path)], cwd=file_path.parent)
                exit_code = res.get('exit_code', -99)
                if exit_code == -3 or exit_code == -2:
                    # Not allowed or missing, fallback
                    return self._basic_brace_check(file_path)
                return exit_code == 0
            else:
                result = subprocess.run(
                    ['node', '--check', str(file_path)],
                    capture_output=True,
                    text=True,
                    timeout=10
                )
                return result.returncode == 0
        except Exception:
            # If node not available or error occurs, do basic check
            return self._basic_brace_check(file_path)
    
    def _check_typescript_syntax(self, file_path: Path) -> bool:
        """Check TypeScript syntax (basic check)."""
        
        try:
            # Try tsc if available
            if self.command_runner:
                res = self.command_runner.run(['tsc', '--noEmit', str(file_path)], cwd=file_path.parent)
                exit_code = res.get('exit_code', -99)
                if exit_code == -3 or exit_code == -2:
                    return self._basic_brace_check(file_path)
                return exit_code == 0
            else:
                result = subprocess.run(
                    ['tsc', '--noEmit', str(file_path)],
                    capture_output=True,
                    text=True,
                    timeout=30
                )
                return result.returncode == 0
        except Exception:
            # Fallback to basic JavaScript check
            return self._basic_brace_check(file_path)
    
    def _basic_brace_check(self, file_path: Path) -> bool:
        """Basic brace matching check."""
        
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
            
            # Simple brace counting
            brace_count = 0
            paren_count = 0
            bracket_count = 0
            
            for char in content:
                if char == '{':
                    brace_count += 1
                elif char == '}':
                    brace_count -= 1
                elif char == '(':
                    paren_count += 1
                elif char == ')':
                    paren_count -= 1
                elif char == '[':
                    bracket_count += 1
                elif char == ']':
                    bracket_count -= 1
            
            return brace_count >= 0 and paren_count >= 0 and bracket_count >= 0
            
        except Exception:
            return False
    
    def _run_basic_tests(self, workspace_dir: Path, validation_run: ValidationRun) -> Dict[str, Any]:
        """Run basic functionality tests."""
        
        test_run = TestRun.objects.create(
            task=validation_run.task,
            candidate_patch=validation_run.candidate_patch,
            validation_run=validation_run,
            run_type='targeted',
            status='running',
            test_command='basic_functionality_tests',
            started_at=timezone.now()
        )
        
        try:
            # Look for common test patterns
            test_commands = [
                ['python', '-m', 'pytest', '-v'],
                ['python', '-m', 'unittest', 'discover'],
                ['npm', 'test'],
                ['yarn', 'test'],
                ['make', 'test']
            ]
            
            for cmd in test_commands:
                if self._command_available(cmd[0], workspace_dir):
                    result = self._execute_test_command(cmd, workspace_dir)
                    
                    test_run.status = 'passed' if result['exit_code'] == 0 else 'failed'
                    test_run.exit_code = result['exit_code']
                    test_run.output = result['output']
                    test_run.duration_ms = result['duration_ms']
                    test_run.completed_at = timezone.now()
                    test_run.save()
                    
                    return {
                        'passed': result['exit_code'] == 0,
                        'command': ' '.join(cmd),
                        'exit_code': result['exit_code'],
                        'output': result['output']
                    }
            
            # No test framework found
            test_run.status = 'skipped'
            test_run.output = 'No test framework detected'
            test_run.completed_at = timezone.now()
            test_run.save()
            
            return {'passed': True, 'reason': 'No tests to run'}
            
        except Exception as exc:
            test_run.status = 'error'
            test_run.output = str(exc)
            test_run.completed_at = timezone.now()
            test_run.save()
            
            return {'passed': False, 'error': str(exc)}
    
    def _run_targeted_tests(self, task: TaskRun, workspace_dir: Path, validation_run: ValidationRun) -> Dict[str, Any]:
        """Run tests specifically related to the task."""
        
        test_run = TestRun.objects.create(
            task=task,
            candidate_patch=validation_run.candidate_patch,
            validation_run=validation_run,
            run_type='targeted',
            status='running',
            test_command='targeted_task_tests',
            started_at=timezone.now()
        )
        
        try:
            # Generate targeted tests based on task
            test_files = self._find_relevant_test_files(workspace_dir, task)
            
            if not test_files:
                test_run.status = 'skipped'
                test_run.output = 'No relevant test files found'
                test_run.completed_at = timezone.now()
                test_run.save()
                
                return {'passed': True, 'reason': 'No targeted tests available'}
            
            # Run specific test files
            if self._command_available('python', workspace_dir):
                cmd = ['python', '-m', 'pytest', '-v'] + test_files
                result = self._execute_test_command(cmd, workspace_dir)
                
                test_run.status = 'passed' if result['exit_code'] == 0 else 'failed'
                test_run.exit_code = result['exit_code']
                test_run.output = result['output']
                test_run.duration_ms = result['duration_ms']
                test_run.completed_at = timezone.now()
                test_run.save()
                
                return {
                    'passed': result['exit_code'] == 0,
                    'test_files': test_files,
                    'exit_code': result['exit_code'],
                    'output': result['output']
                }
            
            return {'passed': True, 'reason': 'Test runner not available'}
            
        except Exception as exc:
            test_run.status = 'error'
            test_run.output = str(exc)
            test_run.completed_at = timezone.now()
            test_run.save()
            
            return {'passed': False, 'error': str(exc)}
    
    def _run_regression_tests(self, workspace_dir: Path, validation_run: ValidationRun) -> Dict[str, Any]:
        """Run regression tests to ensure no breaking changes."""
        
        test_run = TestRun.objects.create(
            task=validation_run.task,
            candidate_patch=validation_run.candidate_patch,
            validation_run=validation_run,
            run_type='regression',
            status='running',
            test_command='regression_tests',
            started_at=timezone.now()
        )
        
        try:
            # Look for comprehensive test suites
            regression_commands = [
                ['python', '-m', 'pytest', '--tb=short'],
                ['python', '-m', 'unittest', 'discover', '-p', '*test*.py'],
                ['npm', 'run', 'test:coverage'],
                ['yarn', 'test:coverage']
            ]
            
            for cmd in regression_commands:
                if self._command_available(cmd[0], workspace_dir):
                    result = self._execute_test_command(cmd, workspace_dir)
                    
                    test_run.status = 'passed' if result['exit_code'] == 0 else 'failed'
                    test_run.exit_code = result['exit_code']
                    test_run.output = result['output']
                    test_run.duration_ms = result['duration_ms']
                    test_run.completed_at = timezone.now()
                    test_run.save()
                    
                    return {
                        'passed': result['exit_code'] == 0,
                        'command': ' '.join(cmd),
                        'exit_code': result['exit_code'],
                        'output': result['output']
                    }
            
            # No regression tests found
            test_run.status = 'skipped'
            test_run.output = 'No regression test suite detected'
            test_run.completed_at = timezone.now()
            test_run.save()
            
            return {'passed': True, 'reason': 'No regression tests available'}
            
        except Exception as exc:
            test_run.status = 'error'
            test_run.output = str(exc)
            test_run.completed_at = timezone.now()
            test_run.save()
            
            return {'passed': False, 'error': str(exc)}
    
    def _command_available(self, command: str, workspace_dir: Optional[Path] = None) -> bool:
        """Check if a command is allowed and present in the system.

        When sandboxing is enabled, only commands in the allowed list will
        be considered available.  We attempt to run ``command --version`` via
        the sandboxed runner; if it returns a negative exit code related to
        missing or not allowed commands, availability is False.  Otherwise
        True.

        Parameters
        ----------
        command: str
            The command name (e.g., ``python``).
        workspace_dir: Optional[Path]
            The working directory to execute the command in.  If not provided
            defaults to the current working directory.
        """
        if workspace_dir is None:
            workspace_dir = Path.cwd()
        # Use CommandRunner when available
        if self.command_runner:
            result = self.command_runner.run([command, '--version'], cwd=workspace_dir)
            exit_code = result.get('exit_code', -99)
            # Only exit code zero counts as available
            return exit_code == 0
        # Fallback: call subprocess.run
        try:
            subprocess.run([command, '--version'], capture_output=True, timeout=5)
            return True
        except Exception:
            return False
    
    def _execute_test_command(self, cmd: List[str], workspace_dir: Path) -> Dict[str, Any]:
        """Execute a test command and return results."""
        
        started = time.monotonic()
        # Prefer sandboxed command execution
        if self.command_runner:
            res = self.command_runner.run(cmd, cwd=workspace_dir)
            # Normalise keys
            exit_code = res.get('exit_code', -99)
            output = res.get('output', '')
            duration_ms = res.get('duration_ms', int((time.monotonic() - started) * 1000))
            return {
                'exit_code': exit_code,
                'output': output,
                'duration_ms': duration_ms
            }
        # Fallback: raw subprocess
        try:
            result = subprocess.run(
                cmd,
                cwd=workspace_dir,
                capture_output=True,
                text=True,
                timeout=300  # 5 minute timeout
            )
            duration_ms = int((time.monotonic() - started) * 1000)
            return {
                'exit_code': result.returncode,
                'output': result.stdout + result.stderr,
                'duration_ms': duration_ms
            }
        except subprocess.TimeoutExpired:
            duration_ms = int((time.monotonic() - started) * 1000)
            return {
                'exit_code': -1,
                'output': 'Test execution timed out',
                'duration_ms': duration_ms
            }
        except Exception as exc:
            duration_ms = int((time.monotonic() - started) * 1000)
            return {
                'exit_code': -2,
                'output': f'Test execution error: {str(exc)}',
                'duration_ms': duration_ms
            }
    
    def _find_relevant_test_files(self, workspace_dir: Path, task: TaskRun) -> List[str]:
        """Find test files relevant to the task."""
        test_files: List[str] = []
        # ``touched_files`` is stored as a JSON array for each candidate.  The
        # values_list call yields each JSON list, which may contain multiple
        # paths.  Flatten the lists into a single iterable of strings.
        modified_files_qs = task.candidate_patches.filter(status='applied').values_list('touched_files', flat=True)
        all_modified_paths: List[str] = []
        for item in modified_files_qs:
            # Each item may be a list or a string.  If it's a list, extend the
            # accumulator; otherwise append the string.
            if isinstance(item, list):
                all_modified_paths.extend(item)
            elif isinstance(item, str):
                all_modified_paths.append(item)

        # Look for test files that might test the modified functionality
        for modified_path in all_modified_paths:
            try:
                file_stem = Path(modified_path).stem
            except Exception:
                continue

            # Common test file patterns in various languages/frameworks
            test_patterns = [
                f"test_{file_stem}.py",
                f"{file_stem}_test.py",
                f"tests/test_{file_stem}.py",
                f"tests/{file_stem}_test.py",
                f"{file_stem}.test.js",
                f"{file_stem}.spec.js",
                f"test/{file_stem}.js",
                f"tests/{file_stem}.js",
            ]

            for pattern in test_patterns:
                test_path = workspace_dir / pattern
                if test_path.exists():
                    test_files.append(pattern)

        # Remove duplicates while preserving order
        seen: set[str] = set()
        unique_files: List[str] = []
        for path in test_files:
            if path not in seen:
                seen.add(path)
                unique_files.append(path)
        return unique_files
