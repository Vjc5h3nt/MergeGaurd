"""Strands tool: dep_lookup — dependency graph queries and circular dep detection."""

from __future__ import annotations

import logging
from typing import Any

from strands import tool

log = logging.getLogger(__name__)


@tool
def dep_lookup(
    file_path: str,
    source: str,
    all_files_source: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Build the dependency graph for a file and detect circular imports.

    Args:
        file_path: File to analyze.
        source: Source code for file_path.
        all_files_source: Optional dict {file_path: source} for cross-file circular detection.

    Returns:
        Dict with imports, dependency edges, and any circular dependency chains.
    """
    from mergeguard.intelligence.dependency_graph import build_dependency_graph
    from mergeguard.intelligence.tree_sitter_loader import parse_file

    tree, language = parse_file(file_path, source)
    if tree is None or language is None:
        return {"error": f"Unsupported file: {file_path}"}

    known_files = set(all_files_source.keys()) if all_files_source else set()
    graph = build_dependency_graph(tree, source, file_path, language, known_files)

    circular = _detect_circular(graph.imports_by_file(), file_path) if all_files_source else []

    return {
        "file": file_path,
        "language": language,
        "imports": graph.imports_by_file().get(file_path, []),
        "dependency_graph": graph.to_dict(),
        "circular_dependencies": circular,
    }


def _detect_circular(
    imports_by_file: dict[str, list[str]],
    start_file: str,
) -> list[list[str]]:
    """Simple DFS cycle detection on the file import graph."""
    cycles: list[list[str]] = []
    visited: set[str] = set()
    path: list[str] = []

    def dfs(node: str) -> None:
        if node in path:
            cycle_start = path.index(node)
            cycles.append(path[cycle_start:] + [node])
            return
        if node in visited:
            return
        visited.add(node)
        path.append(node)
        for dep in imports_by_file.get(node, []):
            dfs(dep)
        path.pop()

    dfs(start_file)
    return cycles
