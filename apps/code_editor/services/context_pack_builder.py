"""Build structured context packs for chat and completion requests."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from ..models import Repository
from ..utils.token_counter import TokenCounter
from .code_map_service import CodeMapService


class ContextPackBuilderService:
    """Build compact context packs within a token budget."""

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
        if retrieved_chunks is None:
            retrieved_chunks = []

        pack: Dict[str, Any] = {
            "user_instruction": instruction.strip(),
            "repo_map": [],
            "selected_chunks": [],
            "constraints": [
                "Use the provided repository context.",
                "Do not invent missing files or code.",
                "Keep the answer focused on the instruction.",
            ],
        }

        instruction_tokens = self.token_counter.count_tokens(pack["user_instruction"])
        constraint_tokens = min(
            self.token_counter.count_tokens("\n".join(pack["constraints"])),
            max(4, token_budget // 6),
        )
        remaining_tokens = max(0, token_budget - instruction_tokens - constraint_tokens)

        for chunk in retrieved_chunks:
            if remaining_tokens <= 0:
                break
            chunk_text = self._render_chunk(chunk)
            chunk_tokens = self.token_counter.count_tokens(chunk_text)
            if chunk_tokens <= remaining_tokens:
                pack["selected_chunks"].append(chunk_text)
                remaining_tokens -= chunk_tokens
                continue
            approx_chars = max(32, remaining_tokens * 4)
            pack["selected_chunks"].append(chunk_text[:approx_chars] + "\n...")
            remaining_tokens = 0
            break

        for repo in repositories:
            if remaining_tokens <= 0:
                break
            repo_text = self._render_repo_map(repo, target_files=target_files)
            repo_tokens = self.token_counter.count_tokens(repo_text)
            if repo_tokens <= remaining_tokens:
                pack["repo_map"].append(repo_text)
                remaining_tokens -= repo_tokens
                continue
            approx_chars = max(32, remaining_tokens * 4)
            pack["repo_map"].append(repo_text[:approx_chars] + "\n...")
            remaining_tokens = 0
            break

        if not pack["selected_chunks"] and retrieved_chunks:
            fallback = self._render_chunk(retrieved_chunks[0])
            pack["selected_chunks"].append(fallback[: max(16, token_budget)])
        if not pack["repo_map"] and repositories:
            fallback = self._render_repo_map(repositories[0], target_files=target_files)
            pack["repo_map"].append(fallback[: max(16, token_budget)])

        return self._trim_to_budget(pack, token_budget)

    def _render_chunk(self, chunk: Dict[str, Any]) -> str:
        lines = [
            f"File: {chunk.get('file_path', 'unknown')}",
            f"Lines: {chunk.get('start_line', '?')}-{chunk.get('end_line', '?')}",
            str(chunk.get("content", "")).strip(),
        ]
        return "\n".join(lines)

    def _render_repo_map(self, repo: Repository, target_files: Optional[List[str]] = None) -> str:
        repo_map = self.code_map_service.generate_code_map(repo, target_files=target_files)
        map_lines: List[str] = [
            f"Repository: {repo_map.get('repository_name', '')} (ID {repo_map.get('repository_id')})"
        ]
        languages = repo_map.get("languages") or []
        if languages:
            map_lines.append("Languages: " + ", ".join(languages))
        important_files = repo_map.get("important_files") or []
        if important_files:
            map_lines.append("Important files:")
            for entry in important_files[:5]:
                map_lines.append(f"  - {entry.get('file_path')}")
        symbols = repo_map.get("symbols") or {}
        if symbols:
            symbol_parts = []
            for kind, names in symbols.items():
                if names:
                    symbol_parts.append(f"{kind}: {', '.join(names)}")
            if symbol_parts:
                map_lines.append("Symbols: " + " | ".join(symbol_parts))
        tree_lines: List[str] = []

        def traverse(node: Dict[str, Any], prefix: str = "", depth: int = 0) -> None:
            if depth > 3 or not node:
                return
            for name, child in list(node.items())[:10]:
                tree_lines.append(prefix + name)
                if isinstance(child, dict):
                    traverse(child, prefix + "  ", depth + 1)

        traverse(repo_map.get("file_tree", {}))
        if tree_lines:
            map_lines.append("File tree:")
            map_lines.extend("  " + line for line in tree_lines[:20])
        if target_files:
            map_lines.append("Target files: " + ", ".join(target_files))
        return "\n".join(map_lines)

    def _trim_to_budget(self, pack: Dict[str, Any], token_budget: int) -> Dict[str, Any]:
        for _ in range(256):
            if self.token_counter.count_tokens(self.render_context_pack(pack)) <= token_budget:
                break
            if len(pack["constraints"]) > 1:
                pack["constraints"].pop()
                continue
            if pack["repo_map"]:
                last = pack["repo_map"][-1]
                if len(last) > 18:
                    pack["repo_map"][-1] = last[: max(8, len(last) - 24)].rstrip() + "..."
                    continue
                if len(pack["repo_map"]) > 1:
                    pack["repo_map"].pop()
                    continue
                compact = last[:4]
                if last != compact:
                    pack["repo_map"][-1] = compact
                    continue
                pack["repo_map"][-1] = "R"
                continue
            if pack["selected_chunks"]:
                last = pack["selected_chunks"][-1]
                if len(last) > 18:
                    pack["selected_chunks"][-1] = last[: max(8, len(last) - 24)].rstrip() + "..."
                    continue
                if len(pack["selected_chunks"]) > 1:
                    pack["selected_chunks"].pop()
                    continue
                compact = last[:4]
                if last != compact:
                    pack["selected_chunks"][-1] = compact
                    continue
                pack["selected_chunks"][-1] = "C"
                continue
            break
        return pack

    def render_context_pack(self, context_pack: Dict[str, Any]) -> str:
        sections: List[str] = []
        instr = context_pack.get("user_instruction")
        if instr:
            sections.append(instr)
        for idx, repo_map in enumerate(context_pack.get("repo_map", []), 1):
            sections.append(f"R{idx}:\n{repo_map}")
        for idx, chunk in enumerate(context_pack.get("selected_chunks", []), 1):
            sections.append(f"C{idx}:\n{chunk}")
        constraints = context_pack.get("constraints", [])
        if constraints:
            sections.append("Rule:\n" + "\n".join(constraints[:1]))
        return "\n\n".join(sections)
