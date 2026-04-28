"""Strands tool: ast_query — query the symbol graph for a given file/symbol."""

from __future__ import annotations

import logging
from typing import Any

from strands import tool

log = logging.getLogger(__name__)


@tool
def ast_query(
    file_path: str,
    source: str,
    query_type: str = "symbols",
) -> dict[str, Any]:
    """Parse a source file and return AST-derived data.

    Args:
        file_path: Path of the file (used for language detection).
        source: Raw source code string.
        query_type: One of 'symbols' | 'call_graph' | 'dependency_graph'.

    Returns:
        Dict with requested AST data.
    """
    from mergeguard.intelligence.call_graph_builder import build_call_graph
    from mergeguard.intelligence.dependency_graph import build_dependency_graph
    from mergeguard.intelligence.symbol_extractor import extract_symbols, symbols_to_dict
    from mergeguard.intelligence.tree_sitter_loader import parse_file

    tree, language = parse_file(file_path, source)
    if tree is None or language is None:
        return {"error": f"Unsupported file: {file_path}", "file": file_path}

    if query_type == "symbols":
        symbols = extract_symbols(tree, source, file_path, language)
        return {
            "file": file_path,
            "language": language,
            "symbols": symbols_to_dict(symbols),
        }

    if query_type == "call_graph":
        graph = build_call_graph(tree, source, file_path, language)
        return {
            "file": file_path,
            "language": language,
            "call_graph": graph.to_dict(),
        }

    if query_type == "dependency_graph":
        dep_graph = build_dependency_graph(tree, source, file_path, language)
        return {
            "file": file_path,
            "language": language,
            "dependency_graph": dep_graph.to_dict(),
        }

    return {"error": f"Unknown query_type: {query_type}"}
