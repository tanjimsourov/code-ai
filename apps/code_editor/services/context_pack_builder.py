"""Service for assembling structured context packs from repository data and retrieved content.

The ContextPackBuilderService orchestrates the production of a multi‑section
context document designed to fit within a given token budget.  It
incorporates repository maps, relevant code chunks, optional target
files and the user's instruction.  Each section is truncated based
on its relative importance to maximise useful information within the
available budget.  The context pack can then be injected into chat
and completion prompts to give models a richer awareness of the
project.
"""

from __future__ import annotations

from typing import Dict, Any, List, Optional
from ..models import Repository
from .code_map_service import CodeMapService
# Import TokenCounter from the utils package rather than from the services
# directory. The TokenCounter utility lives in ``code_editor/utils`` and
# is not part of the services package. Importing it relative to the
# services directory causes a ModuleNotFoundError at runtime. Use
# ``..utils.token_counter`` to resolve the correct module.
from ..utils.token_counter import TokenCounter


class ContextPackBuilderService:
    """Build structured context packs incorporating repository maps and chunks."""

    def __init__(self) -> None:
        self.code_map_service = CodeMapService()
        self.token_counter = TokenCounter()

    def build_context_pack(
        self,
        instruction: str,
        repositories: List[Repository],
        target_files: Optional[List[str]] = None,
        retrieved_chunks: Optional[List[Dict[str, Any]]] = None,
        token_budget: int = 2048,
    ) -> Dict[str, Any]:
        """Construct a context pack within a token budget.

        :param instruction: User instruction or query
        :param repositories: List of Repository instances
        :param target_files: Optional list of file paths to highlight
        :param retrieved_chunks: Optional list of chunks (as returned from
            RetrievalService.search_chunks) to include in the pack
        :param token_budget: Maximum number of tokens the context pack may
            consume.  This includes the instruction and all sections.
        :returns: A dictionary with structured sections: repo_map,
            selected_chunks, user_instruction and constraints.  If
            sections are truncated due to token limits, ellipses are
            inserted to indicate omitted content.
        """
        if retrieved_chunks is None:
            retrieved_chunks = []
        # Initialise context pack structure
        pack: Dict[str, Any] = {
            'user_instruction': instruction.strip(),
            'repo_map': [],
            'selected_chunks': [],
            'constraints': [
                'Respond using only the provided context and your knowledge.',
                'Do not make up files or code that are not present in the repository.',
                'Keep responses concise and focused on the user’s instruction.',
            ],
        }
        # Calculate tokens used by instruction and constraints upfront
        instruction_tokens = self.token_counter.count_tokens(pack['user_instruction'])
        constraint_tokens = self.token_counter.count_tokens('\n'.join(pack['constraints']))
        # Reserve space for instruction and constraints
        remaining_tokens = max(0, token_budget - instruction_tokens - constraint_tokens)
        # Function to serialise code chunks into a unified format
        def render_chunk(chunk: Dict[str, Any]) -> str:
            lines = [f"File: {chunk.get('file_path', 'unknown')}",
                    f"Lines: {chunk.get('start_line', '?')}‑{chunk.get('end_line', '?')}",
                    chunk.get('content', '').strip()]
            return '\n'.join(lines)
        # Add selected chunks first, as they are most relevant to the query
        for chunk in retrieved_chunks:
            chunk_text = render_chunk(chunk)
            chunk_tokens = self.token_counter.count_tokens(chunk_text)
            if chunk_tokens <= remaining_tokens:
                pack['selected_chunks'].append(chunk_text)
                remaining_tokens -= chunk_tokens
            else:
                # Truncate the chunk if possible
                # Approximate: include as many characters as tokens allow
                if remaining_tokens <= 0:
                    break
                approx_chars = remaining_tokens * 4  # assume 4 chars per token
                truncated = chunk_text[:approx_chars]
                # Indicate truncation
                truncated += '\n…'
                pack['selected_chunks'].append(truncated)
                remaining_tokens = 0
                break
        # Next, add repository maps for each repository, if space permits
        for repo in repositories:
            if remaining_tokens <= 0:
                break
            repo_map = self.code_map_service.generate_code_map(repo, target_files=target_files)
            # Serialise the repo_map into text; we produce a human readable form
            map_lines: List[str] = [f"Repository: {repo_map.get('repository_name', '')} (ID {repo_map.get('repository_id')})"]
            if repo_map.get('languages'):
                map_lines.append('Languages: ' + ', '.join(repo_map['languages']))
            # Important files summary
            important_files = repo_map.get('important_files', [])
            if important_files:
                map_lines.append('Important files:')
                for entry in important_files[:5]:
                    path = entry.get('file_path')
                    map_lines.append(f"  - {path}")
            # Dependencies summary
            dependencies = repo_map.get('dependencies', {})
            if dependencies:
                map_lines.append('Dependencies:')
                for dep_file, deps in dependencies.items():
                    if isinstance(deps, dict):
                        for section, names in deps.items():
                            map_lines.append(f"  - {dep_file} ({section}): {', '.join(names)}")
                    elif isinstance(deps, list):
                        map_lines.append(f"  - {dep_file}: {', '.join(deps)}")
            # Symbols summary
            symbols = repo_map.get('symbols', {})
            if symbols:
                sym_lines = []
                for kind, names in symbols.items():
                    if names:
                        sym_lines.append(f"{kind}: {', '.join(names)}")
                if sym_lines:
                    map_lines.append('Symbols: ' + ' | '.join(sym_lines))
            # File tree summary: present as indented listing
            tree_lines: List[str] = []
            def traverse(node: Dict[str, Any], prefix: str = '', depth: int = 0) -> None:
                nonlocal tree_lines
                if depth > 3 or not node:
                    return
                for name, child in list(node.items())[:10]:
                    line = prefix + name
                    tree_lines.append(line)
                    if isinstance(child, dict):
                        traverse(child, prefix + '  ', depth + 1)
            traverse(repo_map.get('file_tree', {}))
            if tree_lines:
                map_lines.append('File tree:')
                map_lines.extend('  ' + line for line in tree_lines[:20])
            repo_text = '\n'.join(map_lines)
            repo_tokens = self.token_counter.count_tokens(repo_text)
            if repo_tokens <= remaining_tokens:
                pack['repo_map'].append(repo_text)
                remaining_tokens -= repo_tokens
            else:
                # Truncate repo map text to fit remaining tokens
                if remaining_tokens <= 0:
                    break
                approx_chars = remaining_tokens * 4
                truncated = repo_text[:approx_chars]
                truncated += '\n…'
                pack['repo_map'].append(truncated)
                remaining_tokens = 0
                break
        # If there's remaining budget and target files specified, include their paths
        if target_files and remaining_tokens > 0:
            target_line = 'Target files: ' + ', '.join(target_files)
            target_tokens = self.token_counter.count_tokens(target_line)
            if target_tokens <= remaining_tokens:
                # Append to the last repo_map section if any, else as separate entry
                if pack['repo_map']:
                    pack['repo_map'][-1] += '\n' + target_line
                else:
                    pack['repo_map'].append(target_line)
                remaining_tokens -= target_tokens
        # The context pack is now constructed; any unused tokens remain for the model
        return pack

    def render_context_pack(self, context_pack: Dict[str, Any]) -> str:
        """Render a context pack dictionary into a plain text representation.

        Sections are separated by blank lines and labelled for clarity.  This
        method can be used to convert a structured pack into a message
        suitable for inclusion in a prompt.
        """
        sections: List[str] = []
        instr = context_pack.get('user_instruction')
        if instr:
            sections.append('Instruction:\n' + instr)
        repo_maps = context_pack.get('repo_map', [])
        if repo_maps:
            for idx, rmap in enumerate(repo_maps, 1):
                sections.append(f"Repository Map {idx}:\n{rmap}")
        selected_chunks = context_pack.get('selected_chunks', [])
        if selected_chunks:
            for idx, chunk in enumerate(selected_chunks, 1):
                sections.append(f"Relevant Chunk {idx}:\n{chunk}")
        constraints = context_pack.get('constraints', [])
        if constraints:
            sections.append('Constraints:\n' + '\n'.join(constraints))
        return '\n\n'.join(sections)