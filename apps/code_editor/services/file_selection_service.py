"""File selection service for intelligent file and symbol selection."""

from typing import List, Dict, Any, Optional, Tuple
from pathlib import Path
from ..models import TaskRun, Repository, SelectedFile, IndexedFile, CodeChunk
from ..services import RetrievalService
from .symbol_analysis_service import SymbolAnalysisService


class FileSelectionService:
    """Service for intelligent file selection based on task context."""
    
    def __init__(self):
        self.retrieval_service = RetrievalService()
        self.symbol_service = SymbolAnalysisService()
    
    def select_files(self, task: TaskRun, context_results: List[Dict[str, Any]]) -> List[SelectedFile]:
        """Select relevant files for the task based on context and analysis."""
        
        # Start with retrieval-based selection
        retrieval_files = self._select_from_retrieval(task, context_results)
        
        # Enhance with symbol-aware selection
        symbol_files = self._select_from_symbols(task, context_results)
        
        # Enhance with repository-aware selection
        enhanced_files = self._enhance_with_repo_analysis(task, retrieval_files + symbol_files)
        
        # Rank and filter files
        ranked_files = self._rank_files(task, enhanced_files)
        
        return ranked_files
    
    def _select_from_retrieval(self, task: TaskRun, context_results: List[Dict[str, Any]]) -> List[SelectedFile]:
        """Select files based on retrieval results."""
        
        selected_files = []
        file_scores = {}
        
        # Aggregate scores by file path
        for result in context_results:
            file_path = result.get('file_path')
            if not file_path:
                continue
            
            score = result.get('similarity_score', 0.5)
            if file_path not in file_scores:
                file_scores[file_path] = {
                    'total_score': 0,
                    'chunk_count': 0,
                    'max_score': 0,
                    'evidence': []
                }
            
            file_scores[file_path]['total_score'] += score
            file_scores[file_path]['chunk_count'] += 1
            file_scores[file_path]['max_score'] = max(file_scores[file_path]['max_score'], score)
            file_scores[file_path]['evidence'].append({
                'chunk_id': result.get('chunk_id'),
                'score': score,
                'content_preview': result.get('content', '')[:200]
            })
        
        # Create SelectedFile objects
        for rank, (file_path, data) in enumerate(sorted(
            file_scores.items(), 
            key=lambda x: x[1]['max_score'], 
            reverse=True
        )):
            try:
                indexed_file = IndexedFile.objects.filter(
                    repository=task.repository,
                    file_path=file_path
                ).first()
                
                if indexed_file:
                    selected_file = SelectedFile.objects.create(
                        task=task,
                        repository=task.repository,
                        indexed_file=indexed_file,
                        path=file_path,
                        why_selected=f"Retrieved with {data['chunk_count']} chunks, max similarity {data['max_score']:.3f}",
                        selection_score=data['max_score'],
                        rank=rank,
                        evidence={
                            'source': 'retrieval',
                            'chunk_count': data['chunk_count'],
                            'total_score': data['total_score'],
                            'max_score': data['max_score'],
                            'chunks': data['evidence'][:5]  # Top 5 chunks
                        },
                        metadata={
                            'avg_chunk_score': data['total_score'] / data['chunk_count'],
                            'selection_method': 'retrieval_enhanced'
                        }
                    )
                    selected_files.append(selected_file)
                    
            except Exception:
                continue
        
        return selected_files
    
    def _select_from_symbols(self, task: TaskRun, context_results: List[Dict[str, Any]]) -> List[SelectedFile]:
        """Select files based on symbol analysis."""
        
        selected_files = []
        
        try:
            # Extract potential symbols from task instruction
            symbols = self._extract_symbols_from_instruction(task.instruction)
            
            if not symbols:
                return selected_files
            
            # Find files containing these symbols
            for symbol_name in symbols:
                related_symbols = self.symbol_service.find_related_symbols(task.repository, symbol_name)
                
                # Add files with symbol definitions
                for definition in related_symbols['definitions']:
                    file_path = definition['file']
                    if self._should_include_symbol_file(task, file_path, definition):
                        try:
                            indexed_file = IndexedFile.objects.filter(
                                repository=task.repository,
                                file_path=file_path
                            ).first()
                            
                            if indexed_file:
                                # Check if already selected
                                existing = SelectedFile.objects.filter(
                                    task=task,
                                    path=file_path
                                ).first()
                                
                                if not existing:
                                    selected_file = SelectedFile.objects.create(
                                        task=task,
                                        repository=task.repository,
                                        indexed_file=indexed_file,
                                        path=file_path,
                                        why_selected=f"Contains symbol '{symbol_name}' definition",
                                        selection_score=0.8,  # High score for symbol definitions
                                        rank=len(selected_files),
                                        evidence={
                                            'source': 'symbol_analysis',
                                            'symbol_name': symbol_name,
                                            'symbol_type': definition.get('type', 'unknown'),
                                            'line': definition.get('line', 0)
                                        },
                                        metadata={
                                            'selection_method': 'symbol_based',
                                            'symbol_name': symbol_name
                                        }
                                    )
                                    selected_files.append(selected_file)
                                    
                        except Exception:
                            continue
                
                # Add files with symbol usages (lower priority)
                for usage in related_symbols['usages'][:3]:  # Limit to top 3 usages
                    file_path = usage['file']
                    
                    # Skip if already selected
                    if SelectedFile.objects.filter(task=task, path=file_path).exists():
                        continue
                    
                    if self._should_include_symbol_file(task, file_path, usage):
                        try:
                            indexed_file = IndexedFile.objects.filter(
                                repository=task.repository,
                                file_path=file_path
                            ).first()
                            
                            if indexed_file:
                                selected_file = SelectedFile.objects.create(
                                    task=task,
                                    repository=task.repository,
                                    indexed_file=indexed_file,
                                    path=file_path,
                                    why_selected=f"Uses symbol '{symbol_name}'",
                                    selection_score=0.6,  # Medium score for symbol usages
                                    rank=len(selected_files),
                                    evidence={
                                        'source': 'symbol_analysis',
                                        'symbol_name': symbol_name,
                                        'usage_line': usage.get('line', 0)
                                    },
                                    metadata={
                                        'selection_method': 'symbol_usage',
                                        'symbol_name': symbol_name
                                    }
                                )
                                selected_files.append(selected_file)
                                
                        except Exception:
                            continue
            
        except Exception as exc:
            print(f"Error in symbol-based selection: {exc}")
        
        return selected_files
    
    def _extract_symbols_from_instruction(self, instruction: str) -> List[str]:
        """Extract potential symbol names from task instruction."""
        
        import re
        
        symbols = []
        
        # Look for common patterns
        patterns = [
            r'\b([A-Z][a-zA-Z0-9_]*)\b',  # CamelCase (classes)
            r'\b([a-z_][a-z0-9_]*_[a-z0-9_]*)\b',  # snake_case (functions/variables)
            r'\b([a-z][a-zA-Z0-9_]*)\s*\(',  # function calls
            r'function\s+([a-zA-Z_$][a-zA-Z0-9_$]*)',  # JS functions
            r'class\s+([A-Z][a-zA-Z0-9_]*)',  # classes
            r'def\s+([a-zA-Z_][a-zA-Z0-9_]*)',  # Python functions
        ]
        
        for pattern in patterns:
            matches = re.findall(pattern, instruction)
            symbols.extend(matches)
        
        # Filter common words
        common_words = {
            'the', 'and', 'for', 'with', 'that', 'this', 'from', 'have', 'are',
            'was', 'were', 'been', 'call', 'use', 'make', 'work', 'need', 'want',
            'get', 'set', 'add', 'remove', 'create', 'delete', 'update', 'test',
            'run', 'start', 'stop', 'open', 'close', 'read', 'write', 'file'
        }
        
        symbols = [s for s in symbols if s.lower() not in common_words and len(s) > 2]
        
        # Remove duplicates and return
        return list(set(symbols))
    
    def _should_include_symbol_file(self, task: TaskRun, file_path: str, symbol_info: Dict[str, Any]) -> bool:
        """Determine if a symbol file should be included."""
        
        # Exclude test files unless task is test-related
        if 'test' in file_path.lower() and task.task_type != 'test':
            return False
        
        # Exclude very large files
        try:
            indexed_file = IndexedFile.objects.filter(
                repository=task.repository,
                file_path=file_path
            ).first()
            
            if indexed_file and indexed_file.file_size > 1024 * 1024:  # 1MB
                return False
                
        except Exception:
            pass
        
        return True
    
    def _enhance_with_repo_analysis(self, task: TaskRun, base_files: List[SelectedFile]) -> List[SelectedFile]:
        """Enhance file selection with repository structure analysis."""
        
        # Get file paths from base selection
        base_paths = {f.path for f in base_files}
        
        # Add related files based on import relationships
        related_files = self._find_related_files(task, base_paths)
        
        # Add configuration and setup files if relevant
        config_files = self._find_config_files(task)
        
        # Combine and deduplicate
        all_paths = base_paths.union(related_files).union(config_files)
        
        # Create SelectedFile objects for new files
        new_files = []
        for file_path in all_paths - base_paths:
            if self._should_include_file(task, file_path):
                try:
                    indexed_file = IndexedFile.objects.filter(
                        repository=task.repository,
                        file_path=file_path
                    ).first()
                    
                    if indexed_file:
                        selected_file = SelectedFile.objects.create(
                            task=task,
                            repository=task.repository,
                            indexed_file=indexed_file,
                            path=file_path,
                            why_selected=self._get_selection_reason(file_path, related_files, config_files),
                            selection_score=0.3,  # Lower score for inferred files
                            rank=len(base_files) + len(new_files),
                            evidence={'source': 'repo_analysis'},
                            metadata={'selection_method': 'repo_enhanced'}
                        )
                        new_files.append(selected_file)
                        
                except Exception:
                    continue
        
        return base_files + new_files
    
    def _find_related_files(self, task: TaskRun, base_paths: set) -> set:
        """Find files related to base selection through imports/dependencies."""
        
        related_files = set()
        
        for file_path in base_paths:
            # Look for files that import this file
            importers = self._find_importers(task.repository, file_path)
            related_files.update(importers)
            
            # Look for files imported by this file
            imports = self._find_imports(task.repository, file_path)
            related_files.update(imports)
        
        return related_files
    
    def _find_importers(self, repository: Repository, file_path: str) -> set:
        """Find files that import the given file."""
        
        # This is a simplified implementation
        # In a real system, you'd parse AST or use language-specific tools
        
        file_stem = Path(file_path).stem
        
        # Look for potential import patterns
        import_patterns = [
            f"import {file_stem}",
            f"from {file_stem}",
            f"require('{file_stem}')",
            f"#include '{file_path}'"
        ]
        
        related_files = set()
        
        try:
            chunks = CodeChunk.objects.filter(
                indexed_file__repository=repository,
                content__contains=file_stem
            )
            
            for chunk in chunks:
                for pattern in import_patterns:
                    if pattern.lower() in chunk.content.lower():
                        related_files.add(chunk.indexed_file.file_path)
                        break
                        
        except Exception:
            pass
        
        return related_files
    
    def _find_imports(self, repository: Repository, file_path: str) -> set:
        """Find files imported by the given file."""
        
        # This would parse the file and extract imports
        # Simplified implementation for now
        
        imported_files = set()
        
        try:
            indexed_file = IndexedFile.objects.filter(
                repository=repository,
                file_path=file_path
            ).first()
            
            if indexed_file:
                chunks = indexed_file.chunks.all()
                for chunk in chunks:
                    # Simple regex-based import detection
                    # In production, use proper AST parsing
                    lines = chunk.content.split('\n')
                    for line in lines:
                        line = line.strip()
                        if line.startswith('import ') or line.startswith('from '):
                            # Extract module name and try to find corresponding file
                            module_name = self._extract_module_name(line)
                            if module_name:
                                potential_file = self._find_file_for_module(repository, module_name)
                                if potential_file:
                                    imported_files.add(potential_file)
                                    
        except Exception:
            pass
        
        return imported_files
    
    def _extract_module_name(self, import_line: str) -> Optional[str]:
        """Extract module name from import statement."""
        
        if import_line.startswith('import '):
            parts = import_line[7:].split()
            return parts[0].split('.')[0]
        elif import_line.startswith('from '):
            parts = import_line[5:].split()
            return parts[0].split('.')[0]
        
        return None
    
    def _find_file_for_module(self, repository: Repository, module_name: str) -> Optional[str]:
        """Find file corresponding to module name."""
        
        # Look for files with matching names
        possible_extensions = ['.py', '.js', '.ts', '.java', '.cpp', '.c', '.h']
        
        for ext in possible_extensions:
            file_path = f"{module_name}{ext}"
            if IndexedFile.objects.filter(repository=repository, file_path=file_path).exists():
                return file_path
        
        # Look in directories
        for ext in possible_extensions:
            file_path = f"{module_name}/__init__{ext}" if ext == '.py' else f"{module_name}/index{ext}"
            if IndexedFile.objects.filter(repository=repository, file_path=file_path).exists():
                return file_path
        
        return None
    
    def _find_config_files(self, task: TaskRun) -> set:
        """Find configuration files relevant to the task."""
        
        config_patterns = [
            'package.json', 'requirements.txt', 'pyproject.toml', 'Cargo.toml',
            'pom.xml', 'build.gradle', 'Makefile', 'CMakeLists.txt',
            '.env', 'config/', 'settings/', 'setup.py', 'setup.cfg'
        ]
        
        config_files = set()
        
        try:
            for pattern in config_patterns:
                files = IndexedFile.objects.filter(
                    repository=task.repository,
                    file_path__contains=pattern
                )
                
                for file in files:
                    if self._is_relevant_config(task.task_type, file.file_path):
                        config_files.add(file.file_path)
                        
        except Exception:
            pass
        
        return config_files
    
    def _is_relevant_config(self, task_type: str, file_path: str) -> bool:
        """Check if config file is relevant to task type."""
        
        if task_type in ['feature', 'bugfix', 'refactor']:
            # Most config files are relevant for code changes
            return True
        elif task_type == 'test':
            # Test-specific configs
            test_configs = ['pytest.ini', 'jest.config.js', 'test/', 'tests/']
            return any(config in file_path for config in test_configs)
        
        return False
    
    def _should_include_file(self, task: TaskRun, file_path: str) -> bool:
        """Determine if a file should be included in selection."""
        
        # Exclude certain file types
        excluded_extensions = ['.lock', '.log', '.tmp', '.cache']
        excluded_dirs = ['__pycache__', 'node_modules/.cache', '.git/']
        
        if any(file_path.endswith(ext) for ext in excluded_extensions):
            return False
        
        if any(excluded_dir in file_path for excluded_dir in excluded_dirs):
            return False
        
        # Exclude very large files (simplified check)
        try:
            indexed_file = IndexedFile.objects.filter(
                repository=task.repository,
                file_path=file_path
            ).first()
            
            if indexed_file and indexed_file.file_size > 1024 * 1024:  # 1MB
                return False
                
        except Exception:
            pass
        
        return True
    
    def _get_selection_reason(self, file_path: str, related_files: set, config_files: set) -> str:
        """Get reason for file selection."""
        
        if file_path in config_files:
            return "Configuration file relevant to task"
        elif file_path in related_files:
            return "Related to selected files through import dependencies"
        else:
            return "Repository analysis suggests relevance"
    
    def _rank_files(self, task: TaskRun, files: List[SelectedFile]) -> List[SelectedFile]:
        """Rank files by relevance and update ranks."""
        
        # Sort by selection score (descending)
        files.sort(key=lambda f: f.selection_score, reverse=True)
        
        # Update ranks
        for i, file in enumerate(files):
            file.rank = i
            file.save(update_fields=['rank'])
        
        return files
