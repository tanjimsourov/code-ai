"""Service for generating a concise map of a repository's structure and key components.

This service inspects an indexed repository and produces a high‑level summary
that includes important files, a truncated file tree, detected languages,
top‑level symbols and dependency/configuration files.  The goal is to
provide models with enough situational awareness to answer questions about
projects without overloading the context window.

The resulting map is intended for human and model consumption and should
remain stable across invocations.  Only a limited number of files and
directories are included to avoid runaway output.  Symbol extraction uses
the existing ``SymbolAnalysisService`` when available.  Parsing of
dependency files is best‑effort and will fall back to including a short
snippet of the file when structured extraction fails.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Dict, Any, List, Optional, Set

from ..models import Repository, IndexedFile, CodeChunk
from .symbol_analysis_service import SymbolAnalysisService


class CodeMapService:
    """Generate a high‑level code map for one or more repositories.

    The code map summarises key attributes of a repository such as the
    languages used, important configuration or dependency files, a
    truncated file tree and top‑level symbols detected.  To keep output
    bounded, the tree is truncated after a given depth and number of
    entries.  Only files that are indexed via the ingestion pipeline are
    considered.  Symbol analysis leverages the existing
    ``SymbolAnalysisService`` for supported languages.
    """

    # Known configuration and dependency files that provide insight into a project
    IMPORTANT_FILENAMES: Set[str] = {
        'README', 'README.md', 'LICENSE', 'LICENSE.txt', 'requirements.txt',
        'requirements.in', 'requirements-dev.txt', 'package.json',
        'pyproject.toml', 'setup.py', 'settings.py', '.env', '.gitignore',
        'docker-compose.yml', 'Dockerfile', 'Makefile'
    }

    def __init__(self) -> None:
        self.symbol_service = SymbolAnalysisService()

    def generate_code_map(
        self,
        repository: Repository,
        target_files: Optional[List[str]] = None,
        max_depth: int = 2,
        max_entries: int = 100,
    ) -> Dict[str, Any]:
        """Generate a map of the given repository.

        :param repository: Repository instance to summarise
        :param target_files: Optional specific file paths to highlight in the
            map.  If provided, these will always be included in the tree.
        :param max_depth: Maximum directory depth to descend when building
            the file tree.  A depth of 0 includes only the top‑level files.
        :param max_entries: Maximum number of entries (files or directories)
            to include in the tree.  Once this limit is reached, traversal
            stops and remaining items are summarised in a "…" entry.
        :returns: A dictionary describing the repository's structure.
        """
        repo_map: Dict[str, Any] = {
            'repository_id': repository.id,
            'repository_name': repository.name,
            'languages': [],
            'important_files': [],
            'file_tree': {},
            'symbols': {},
            'dependencies': {},
        }

        try:
            # Collect all indexed files for this repository
            indexed_files = list(repository.indexed_files.all())
            # Determine languages used
            languages = sorted({f.language or 'unknown' for f in indexed_files})
            repo_map['languages'] = languages

            # Identify important files
            important_entries = []
            for f in indexed_files:
                base = os.path.basename(f.file_path)
                if base in self.IMPORTANT_FILENAMES:
                    snippet = self._read_file_snippet(f)
                    important_entries.append({
                        'file_path': f.file_path,
                        'snippet': snippet,
                    })
            repo_map['important_files'] = important_entries

            # Build truncated file tree
            tree = {}
            # If target_files provided, ensure they are included even if deeper
            include_paths: Set[str] = set(target_files or [])
            # Sort file paths to ensure deterministic order
            file_paths = sorted([f.file_path for f in indexed_files])
            entries_count = 0
            for path in file_paths:
                parts = path.split('/')
                # Only include deeper levels up to max_depth
                node = tree
                for depth, part in enumerate(parts):
                    if depth > max_depth:
                        break
                    # Determine if we should include this entry
                    if entries_count >= max_entries and path not in include_paths:
                        # Stop adding new entries
                        break
                    if part not in node:
                        node[part] = {}
                        entries_count += 1
                    node = node[part]
            repo_map['file_tree'] = tree

            # Symbol analysis (functions, classes, etc.)
            try:
                symbols = self.symbol_service.analyze_repository_symbols(repository)
                # Summarise symbols: only include names, not full metadata, to keep map concise
                summarised = {}
                for sym_type, sym_dict in symbols.items():
                    if isinstance(sym_dict, dict):
                        # Keep up to 10 symbol names per type
                        summarised[sym_type] = list(sym_dict.keys())[:10]
                repo_map['symbols'] = summarised
            except Exception:
                # If symbol analysis fails, leave symbols empty
                repo_map['symbols'] = {}

            # Dependency file parsing
            dependencies: Dict[str, Any] = {}
            for entry in important_entries:
                fname = os.path.basename(entry['file_path'])
                content = entry['snippet']
                if fname == 'requirements.txt' or fname.endswith('requirements.in'):
                    deps = self._parse_requirements(content)
                    if deps:
                        dependencies[entry['file_path']] = deps
                elif fname == 'package.json':
                    deps = self._parse_package_json(content)
                    if deps:
                        dependencies[entry['file_path']] = deps
                elif fname == 'pyproject.toml':
                    deps = self._parse_pyproject_toml(content)
                    if deps:
                        dependencies[entry['file_path']] = deps
            repo_map['dependencies'] = dependencies
        except Exception:
            # If any unexpected error occurs, return what we have
            pass
        return repo_map

    def _read_file_snippet(self, indexed_file: IndexedFile, max_chars: int = 500) -> str:
        """Read a short snippet from the beginning of an indexed file.

        The snippet concatenates the contents of the first few chunks until
        ``max_chars`` characters have been collected.  If no chunks are
        present, returns an empty string.
        """
        try:
            chunks = list(indexed_file.chunks.all().order_by('chunk_index'))
            content_parts: List[str] = []
            total = 0
            for chunk in chunks:
                part = chunk.content
                if not part:
                    continue
                remaining = max_chars - total
                content_parts.append(part[:remaining])
                total += len(part[:remaining])
                if total >= max_chars:
                    break
            return ''.join(content_parts)
        except Exception:
            return ''

    def _parse_requirements(self, text: str) -> List[str]:
        """Parse a requirements.txt style snippet into a list of dependencies."""
        deps = []
        for line in text.splitlines():
            line = line.strip()
            # Ignore comments and empty lines
            if not line or line.startswith('#'):
                continue
            # Only take the package name (before any version specifiers)
            pkg = line.split('==')[0].split('>')[0].split('<')[0].split('~=')[0]
            if pkg:
                deps.append(pkg)
        return deps[:20]

    def _parse_package_json(self, text: str) -> Dict[str, List[str]]:
        """Parse dependencies from a package.json snippet."""
        try:
            # Attempt to parse as JSON; text may be truncated
            data = json.loads(text)
        except Exception:
            return {}
        deps: Dict[str, List[str]] = {}
        for section in ['dependencies', 'devDependencies', 'peerDependencies']:
            section_data = data.get(section)
            if isinstance(section_data, dict):
                deps[section] = list(section_data.keys())[:20]
        return deps

    def _parse_pyproject_toml(self, text: str) -> Dict[str, List[str]]:
        """Attempt to parse dependencies from a pyproject.toml snippet.

        Since we avoid external dependencies such as ``toml``, we use a very
        simple heuristic that looks for lines under a ``[tool.poetry.dependencies]``
        section or a ``[project.dependencies]`` section.  Only lines that
        resemble ``name = "version"`` are captured.  Parsing stops when
        another section header is encountered.
        """
        deps: Dict[str, List[str]] = {}
        current_section: Optional[str] = None
        for line in text.splitlines():
            stripped = line.strip()
            # Detect section headers
            if stripped.startswith('[') and stripped.endswith(']'):
                section_name = stripped.strip('[]').strip()
                if section_name in {'tool.poetry.dependencies', 'project.dependencies'}:
                    current_section = section_name
                    deps[current_section] = []
                else:
                    current_section = None
                continue
            if current_section and '=' in stripped:
                # Attempt to extract key before '='
                key = stripped.split('=')[0].strip().strip('"').strip("'")
                if key and key not in deps[current_section]:
                    deps[current_section].append(key)
            # Stop after collecting too many entries
            if current_section and len(deps[current_section]) >= 20:
                break
        return deps