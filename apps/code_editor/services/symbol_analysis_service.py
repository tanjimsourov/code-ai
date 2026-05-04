"""Symbol analysis service for repository-aware code understanding."""

from typing import List, Dict, Any, Optional, Set, Tuple
from pathlib import Path
import re
import ast
import json
from ..models import Repository, IndexedFile, CodeChunk


class SymbolAnalysisService:
    """Service for analyzing symbols in code repositories."""
    
    def __init__(self):
        pass
    
    def analyze_repository_symbols(self, repository: Repository) -> Dict[str, Any]:
        """Analyze all symbols in a repository."""
        
        symbols = {
            'functions': {},
            'classes': {},
            'variables': {},
            'imports': {},
            'exports': {},
            'dependencies': {}
        }
        
        try:
            indexed_files = repository.indexed_files.all()
            
            for indexed_file in indexed_files:
                file_symbols = self._analyze_file_symbols(indexed_file)
                
                # Merge file symbols into repository symbols
                for symbol_type, symbol_dict in file_symbols.items():
                    if symbol_type in symbols:
                        symbols[symbol_type].update(symbol_dict)
            
            # Build dependency graph
            symbols['dependencies'] = self._build_dependency_graph(symbols)
            
            return symbols
            
        except Exception as exc:
            print(f"Error analyzing repository symbols: {exc}")
            return symbols
    
    def _analyze_file_symbols(self, indexed_file: IndexedFile) -> Dict[str, Any]:
        """Analyze symbols in a single file."""
        
        symbols = {
            'functions': {},
            'classes': {},
            'variables': {},
            'imports': {},
            'exports': {}
        }
        
        try:
            language = self._detect_file_language(indexed_file.file_path)
            
            if language == 'python':
                symbols = self._analyze_python_symbols(indexed_file)
            elif language in ['javascript', 'typescript']:
                symbols = self._analyze_js_symbols(indexed_file)
            elif language == 'java':
                symbols = self._analyze_java_symbols(indexed_file)
            else:
                # Generic analysis for other languages
                symbols = self._analyze_generic_symbols(indexed_file)
                
        except Exception as exc:
            print(f"Error analyzing symbols in {indexed_file.file_path}: {exc}")
        
        return symbols
    
    def _detect_file_language(self, file_path: str) -> str:
        """Detect programming language from file path."""
        
        ext = Path(file_path).suffix.lower()
        
        language_map = {
            '.py': 'python',
            '.js': 'javascript',
            '.ts': 'typescript',
            '.jsx': 'javascript',
            '.tsx': 'typescript',
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
    
    def _analyze_python_symbols(self, indexed_file: IndexedFile) -> Dict[str, Any]:
        """Analyze Python symbols using AST."""
        
        symbols = {
            'functions': {},
            'classes': {},
            'variables': {},
            'imports': {},
            'exports': {}
        }
        
        try:
            # Get file content
            chunks = indexed_file.chunks.all().order_by('chunk_index')
            content = '\n'.join(chunk.content for chunk in chunks)
            
            # Parse AST
            tree = ast.parse(content)
            
            # Walk through AST nodes
            for node in ast.walk(tree):
                if isinstance(node, ast.FunctionDef):
                    symbols['functions'][node.name] = {
                        'file': indexed_file.file_path,
                        'line': node.lineno,
                        'type': 'function',
                        'args': [arg.arg for arg in node.args.args],
                        'decorators': [d.id if isinstance(d, ast.Name) else str(d) for d in node.decorator_list]
                    }
                elif isinstance(node, ast.AsyncFunctionDef):
                    symbols['functions'][node.name] = {
                        'file': indexed_file.file_path,
                        'line': node.lineno,
                        'type': 'async_function',
                        'args': [arg.arg for arg in node.args.args],
                        'decorators': [d.id if isinstance(d, ast.Name) else str(d) for d in node.decorator_list]
                    }
                elif isinstance(node, ast.ClassDef):
                    symbols['classes'][node.name] = {
                        'file': indexed_file.file_path,
                        'line': node.lineno,
                        'type': 'class',
                        'bases': [self._get_node_name(base) for base in node.bases],
                        'methods': [],
                        'decorators': [d.id if isinstance(d, ast.Name) else str(d) for d in node.decorator_list]
                    }
                    
                    # Find methods
                    for item in node.body:
                        if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                            symbols['classes'][node.name]['methods'].append(item.name)
                
                elif isinstance(node, ast.Import):
                    for alias in node.names:
                        symbols['imports'][alias.name] = {
                            'file': indexed_file.file_path,
                            'line': node.lineno,
                            'alias': alias.asname,
                            'type': 'import'
                        }
                elif isinstance(node, ast.ImportFrom):
                    module = node.module or ''
                    for alias in node.names:
                        full_name = f"{module}.{alias.name}" if module else alias.name
                        symbols['imports'][full_name] = {
                            'file': indexed_file.file_path,
                            'line': node.lineno,
                            'module': module,
                            'alias': alias.asname,
                            'type': 'from_import'
                        }
                elif isinstance(node, ast.Assign):
                    for target in node.targets:
                        if isinstance(target, ast.Name):
                            symbols['variables'][target.id] = {
                                'file': indexed_file.file_path,
                                'line': node.lineno,
                                'type': 'variable'
                            }
            
            # Find exports (public symbols)
            symbols['exports'] = self._find_python_exports(content, indexed_file.file_path)
            
        except SyntaxError:
            # Fallback to regex-based parsing
            symbols = self._analyze_python_regex(indexed_file)
        except Exception as exc:
            print(f"Error in Python AST analysis: {exc}")
        
        return symbols
    
    def _get_node_name(self, node) -> str:
        """Get name from AST node."""
        
        if isinstance(node, ast.Name):
            return node.id
        elif isinstance(node, ast.Attribute):
            return f"{self._get_node_name(node.value)}.{node.attr}"
        else:
            return str(node)
    
    def _find_python_exports(self, content: str, file_path: str) -> Dict[str, Any]:
        """Find public exports in Python file."""
        
        exports = {}
        
        # Look for __all__ definition
        all_match = re.search(r'__all__\s*=\s*\[(.*?)\]', content, re.DOTALL)
        if all_match:
            all_content = all_match.group(1)
            # Extract quoted names
            names = re.findall(r'["\']([^"\']+)["\']', all_content)
            for name in names:
                exports[name] = {
                    'file': file_path,
                    'type': 'explicit_export'
                }
        
        # If no __all__, assume public symbols (not starting with _)
        if not exports:
            public_symbols = re.findall(r'^(def|class)\s+([a-zA-Z][a-zA-Z0-9_]*)', content, re.MULTILINE)
            for _, name in public_symbols:
                if not name.startswith('_'):
                    exports[name] = {
                        'file': file_path,
                        'type': 'implicit_export'
                    }
        
        return exports
    
    def _analyze_python_regex(self, indexed_file: IndexedFile) -> Dict[str, Any]:
        """Fallback regex-based Python analysis."""
        
        symbols = {
            'functions': {},
            'classes': {},
            'variables': {},
            'imports': {},
            'exports': {}
        }
        
        try:
            chunks = indexed_file.chunks.all().order_by('chunk_index')
            content = '\n'.join(chunk.content for chunk in chunks)
            
            # Function definitions
            func_matches = re.finditer(r'^(async\s+)?def\s+([a-zA-Z_][a-zA-Z0-9_]*)\s*\(', content, re.MULTILINE)
            for match in func_matches:
                func_name = match.group(2)
                is_async = bool(match.group(1))
                symbols['functions'][func_name] = {
                    'file': indexed_file.file_path,
                    'line': content[:match.start()].count('\n') + 1,
                    'type': 'async_function' if is_async else 'function'
                }
            
            # Class definitions
            class_matches = re.finditer(r'^class\s+([a-zA-Z_][a-zA-Z0-9_]*)\s*(\((.*?)\))?:', content, re.MULTILINE)
            for match in class_matches:
                class_name = match.group(1)
                bases = match.group(3).split(',') if match.group(3) else []
                symbols['classes'][class_name] = {
                    'file': indexed_file.file_path,
                    'line': content[:match.start()].count('\n') + 1,
                    'type': 'class',
                    'bases': [b.strip() for b in bases]
                }
            
            # Import statements
            import_matches = re.finditer(r'^(import|from)\s+(.+)', content, re.MULTILINE)
            for match in import_matches:
                import_stmt = match.group(0)
                symbols['imports'][import_stmt] = {
                    'file': indexed_file.file_path,
                    'line': content[:match.start()].count('\n') + 1,
                    'type': 'import'
                }
            
        except Exception as exc:
            print(f"Error in Python regex analysis: {exc}")
        
        return symbols
    
    def _analyze_js_symbols(self, indexed_file: IndexedFile) -> Dict[str, Any]:
        """Analyze JavaScript/TypeScript symbols."""
        
        symbols = {
            'functions': {},
            'classes': {},
            'variables': {},
            'imports': {},
            'exports': {}
        }
        
        try:
            chunks = indexed_file.chunks.all().order_by('chunk_index')
            content = '\n'.join(chunk.content for chunk in chunks)
            
            # Function definitions
            func_patterns = [
                r'function\s+([a-zA-Z_$][a-zA-Z0-9_$]*)\s*\(',
                r'const\s+([a-zA-Z_$][a-zA-Z0-9_$]*)\s*=\s*(?:async\s+)?\(',
                r'let\s+([a-zA-Z_$][a-zA-Z0-9_$]*)\s*=\s*(?:async\s+)?\(',
                r'var\s+([a-zA-Z_$][a-zA-Z0-9_$]*)\s*=\s*(?:async\s+)?\(',
                r'([a-zA-Z_$][a-zA-Z0-9_$]*)\s*:\s*(?:async\s+)?function'
            ]
            
            for pattern in func_patterns:
                matches = re.finditer(pattern, content)
                for match in matches:
                    func_name = match.group(1)
                    symbols['functions'][func_name] = {
                        'file': indexed_file.file_path,
                        'line': content[:match.start()].count('\n') + 1,
                        'type': 'function'
                    }
            
            # Class definitions
            class_matches = re.finditer(r'class\s+([a-zA-Z_$][a-zA-Z0-9_$]*)\s*(?:extends\s+([a-zA-Z_$][a-zA-Z0-9_$]*))?', content)
            for match in class_matches:
                class_name = match.group(1)
                extends = match.group(2) if match.group(2) else None
                symbols['classes'][class_name] = {
                    'file': indexed_file.file_path,
                    'line': content[:match.start()].count('\n') + 1,
                    'type': 'class',
                    'extends': extends
                }
            
            # Import statements
            import_patterns = [
                r'import\s+(?:.*\s+from\s+)?[\'"]([^\'"]+)[\'"]',
                r'require\([\'"]([^\'"]+)[\'"]\)'
            ]
            
            for pattern in import_patterns:
                matches = re.finditer(pattern, content)
                for match in matches:
                    import_path = match.group(1)
                    symbols['imports'][import_path] = {
                        'file': indexed_file.file_path,
                        'line': content[:match.start()].count('\n') + 1,
                        'type': 'import'
                    }
            
            # Export statements
            export_patterns = [
                r'export\s+(?:default\s+)?(?:function|class|const|let|var)\s+([a-zA-Z_$][a-zA-Z0-9_$]*)',
                r'export\s*\{([^}]+)\}',
                r'module\.exports\s*=\s*([a-zA-Z_$][a-zA-Z0-9_$]*)'
            ]
            
            for pattern in export_patterns:
                matches = re.finditer(pattern, content)
                for match in matches:
                    export_name = match.group(1) if match.groups() else 'default'
                    symbols['exports'][export_name] = {
                        'file': indexed_file.file_path,
                        'line': content[:match.start()].count('\n') + 1,
                        'type': 'export'
                    }
            
        except Exception as exc:
            print(f"Error in JS/TS analysis: {exc}")
        
        return symbols
    
    def _analyze_java_symbols(self, indexed_file: IndexedFile) -> Dict[str, Any]:
        """Analyze Java symbols."""
        
        symbols = {
            'functions': {},  # Methods in Java
            'classes': {},
            'variables': {},
            'imports': {},
            'exports': {}  # Public classes/methods
        }
        
        try:
            chunks = indexed_file.chunks.all().order_by('chunk_index')
            content = '\n'.join(chunk.content for chunk in chunks)
            
            # Class definitions
            class_matches = re.finditer(r'(?:public\s+|private\s+|protected\s+)?(?:abstract\s+|final\s+)?class\s+([a-zA-Z_][a-zA-Z0-9_]*)\s*(?:extends\s+([a-zA-Z_][a-zA-Z0-9_]*))?\s*(?:implements\s+([^{]+))?', content)
            for match in class_matches:
                class_name = match.group(1)
                extends = match.group(2)
                implements = match.group(3)
                symbols['classes'][class_name] = {
                    'file': indexed_file.file_path,
                    'line': content[:match.start()].count('\n') + 1,
                    'type': 'class',
                    'extends': extends,
                    'implements': [i.strip() for i in implements.split(',')] if implements else []
                }
            
            # Method definitions
            method_matches = re.finditer(r'(?:public\s+|private\s+|protected\s+)?(?:static\s+)?(?:final\s+)?(?:abstract\s+)?(?:\w+\s+)?([a-zA-Z_][a-zA-Z0-9_]*)\s*\([^)]*\)\s*(?:throws\s+[^{]+)?\s*(?:\{|;)', content)
            for match in method_matches:
                method_name = match.group(1)
                # Skip constructors and common keywords
                if method_name not in ['class', 'interface', 'if', 'while', 'for', 'switch']:
                    symbols['functions'][method_name] = {
                        'file': indexed_file.file_path,
                        'line': content[:match.start()].count('\n') + 1,
                        'type': 'method'
                    }
            
            # Import statements
            import_matches = re.finditer(r'import\s+(?:static\s+)?([^;]+);', content)
            for match in import_matches:
                import_path = match.group(1).strip()
                symbols['imports'][import_path] = {
                    'file': indexed_file.file_path,
                    'line': content[:match.start()].count('\n') + 1,
                    'type': 'import'
                }
            
        except Exception as exc:
            print(f"Error in Java analysis: {exc}")
        
        return symbols
    
    def _analyze_generic_symbols(self, indexed_file: IndexedFile) -> Dict[str, Any]:
        """Generic symbol analysis for unknown languages."""
        
        symbols = {
            'functions': {},
            'classes': {},
            'variables': {},
            'imports': {},
            'exports': {}
        }
        
        try:
            chunks = indexed_file.chunks.all().order_by('chunk_index')
            content = '\n'.join(chunk.content for chunk in chunks)
            
            # Very basic pattern matching
            lines = content.split('\n')
            
            for i, line in enumerate(lines, 1):
                line = line.strip()
                
                # Look for function-like patterns
                if re.match(r'^(function|def|func)\s+\w+', line):
                    match = re.match(r'^(function|def|func)\s+(\w+)', line)
                    if match:
                        func_name = match.group(2)
                        symbols['functions'][func_name] = {
                            'file': indexed_file.file_path,
                            'line': i,
                            'type': 'function'
                        }
                
                # Look for class-like patterns
                if re.match(r'^(class|struct)\s+\w+', line):
                    match = re.match(r'^(class|struct)\s+(\w+)', line)
                    if match:
                        class_name = match.group(2)
                        symbols['classes'][class_name] = {
                            'file': indexed_file.file_path,
                            'line': i,
                            'type': 'class'
                        }
                
                # Look for import-like patterns
                if re.match(r'^(import|include|require)\s+', line):
                    import_stmt = line
                    symbols['imports'][import_stmt] = {
                        'file': indexed_file.file_path,
                        'line': i,
                        'type': 'import'
                    }
            
        except Exception as exc:
            print(f"Error in generic analysis: {exc}")
        
        return symbols
    
    def _build_dependency_graph(self, symbols: Dict[str, Any]) -> Dict[str, List[str]]:
        """Build dependency graph from symbols and imports."""
        
        dependencies = {}
        
        # For each file, find what it imports
        import_map = {}
        for import_name, import_info in symbols['imports'].items():
            file_path = import_info['file']
            if file_path not in import_map:
                import_map[file_path] = []
            import_map[file_path].append(import_name)
        
        # For each file, find what it exports
        export_map = {}
        for export_name, export_info in symbols['exports'].items():
            file_path = export_info['file']
            if file_path not in export_map:
                export_map[file_path] = []
            export_map[file_path].append(export_name)
        
        # Build dependency relationships
        for file_path, imports in import_map.items():
            dependencies[file_path] = []
            
            for import_name in imports:
                # Try to find which file provides this import
                for other_file, exports in export_map.items():
                    if other_file != file_path:
                        for export in exports:
                            if export in import_name or import_name in export:
                                if other_file not in dependencies[file_path]:
                                    dependencies[file_path].append(other_file)
        
        return dependencies
    
    def find_related_symbols(self, repository: Repository, symbol_name: str) -> Dict[str, Any]:
        """Find symbols related to a given symbol."""
        
        related = {
            'definitions': [],
            'usages': [],
            'dependents': [],
            'dependencies': []
        }
        
        try:
            # Analyze repository symbols
            repo_symbols = self.analyze_repository_symbols(repository)
            
            # Find definitions
            for symbol_type in ['functions', 'classes', 'variables']:
                if symbol_name in repo_symbols[symbol_type]:
                    related['definitions'].append(repo_symbols[symbol_type][symbol_name])
            
            # Find usages (simple string search for now)
            indexed_files = repository.indexed_files.all()
            for indexed_file in indexed_files:
                chunks = indexed_file.chunks.all()
                for chunk in chunks:
                    if symbol_name in chunk.content:
                        related['usages'].append({
                            'file': indexed_file.file_path,
                            'chunk_id': chunk.id,
                            'line': chunk.content[:chunk.content.find(symbol_name)].count('\n') + 1
                        })
            
            # Find dependencies and dependents
            dependencies = repo_symbols.get('dependencies', {})
            for file_path, deps in dependencies.items():
                if symbol_name in file_path:  # If symbol is in this file
                    related['dependencies'] = deps
                elif any(symbol_name in dep for dep in deps):  # If symbol is a dependency
                    related['dependents'].append(file_path)
            
        except Exception as exc:
            print(f"Error finding related symbols: {exc}")
        
        return related
    
    def get_symbol_context(self, repository: Repository, symbol_name: str, context_size: int = 5) -> List[Dict[str, Any]]:
        """Get context around a symbol usage."""
        
        context_chunks = []
        
        try:
            related_symbols = self.find_related_symbols(repository, symbol_name)
            
            # Get context for definitions
            for definition in related_symbols['definitions']:
                file_path = definition['file']
                line_num = definition.get('line', 1)
                
                indexed_file = repository.indexed_files.filter(file_path=file_path).first()
                if indexed_file:
                    chunks = indexed_file.chunks.all().order_by('chunk_index')
                    
                    # Find chunks around the line
                    current_line = 0
                    for chunk in chunks:
                        chunk_lines = chunk.content.split('\n')
                        chunk_start_line = current_line + 1
                        chunk_end_line = current_line + len(chunk_lines)
                        
                        if chunk_start_line <= line_num <= chunk_end_line:
                            context_chunks.append({
                                'file_path': file_path,
                                'chunk_id': chunk.id,
                                'content': chunk.content,
                                'type': 'definition',
                                'symbol_line': line_num - chunk_start_line + 1
                            })
                            break
                        
                        current_line = chunk_end_line
            
            # Get context for usages
            for usage in related_symbols['usages'][:context_size]:
                file_path = usage['file']
                chunk_id = usage['chunk_id']
                
                try:
                    chunk = CodeChunk.objects.get(id=chunk_id)
                    context_chunks.append({
                        'file_path': file_path,
                        'chunk_id': chunk_id,
                        'content': chunk.content,
                        'type': 'usage',
                        'symbol_line': usage['line']
                    })
                except CodeChunk.DoesNotExist:
                    continue
            
        except Exception as exc:
            print(f"Error getting symbol context: {exc}")
        
        return context_chunks
