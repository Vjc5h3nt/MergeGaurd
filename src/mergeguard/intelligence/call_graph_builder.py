"""Call graph builder — intra-file call edges via Tree-sitter, cross-file via import map."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

log = logging.getLogger(__name__)


@dataclass
class CallEdge:
    caller: str   # fully-qualified: file::ClassName::method_name
    callee: str   # may be unresolved if cross-file


@dataclass
class CallGraph:
    edges: list[CallEdge] = field(default_factory=list)

    def calls(self) -> dict[str, list[str]]:
        """Returns {caller: [callees]}."""
        result: dict[str, list[str]] = {}
        for e in self.edges:
            result.setdefault(e.caller, []).append(e.callee)
        return result

    def called_by(self) -> dict[str, list[str]]:
        """Returns {callee: [callers]} — used for blast-radius BFS."""
        result: dict[str, list[str]] = {}
        for e in self.edges:
            result.setdefault(e.callee, []).append(e.caller)
        return result

    def to_dict(self) -> dict[str, Any]:
        return {
            "calls": self.calls(),
            "called_by": self.called_by(),
        }


def build_call_graph(
    tree: Any,
    source: str,
    file_path: str,
    language: str,
    import_map: dict[str, str] | None = None,
) -> CallGraph:
    """Build an intra-file call graph from a parsed AST.

    Args:
        tree: tree-sitter Tree object.
        source: Raw source text.
        file_path: Path of the file being analyzed.
        language: Language name.
        import_map: Optional {imported_name: source_file} for cross-file resolution.

    Returns:
        CallGraph with edges found in this file.
    """
    graph = CallGraph()

    if language == "python":
        _extract_python_calls(tree, source, file_path, graph, import_map or {})
    elif language in ("typescript", "javascript"):
        _extract_js_calls(tree, source, file_path, graph, import_map or {})
    elif language == "go":
        _extract_go_calls(tree, source, file_path, graph, import_map or {})
    else:
        log.debug("Call graph extraction not implemented for %s", language)

    return graph


def _current_function(node: Any, source_lines: list[str]) -> str | None:
    """Walk up the AST to find the enclosing function/method name."""
    parent = node.parent
    func_types = {
        "function_definition", "function_declaration",
        "method_definition", "method_declaration",
        "async_function_def",
    }
    while parent is not None:
        if parent.type in func_types:
            for child in parent.children:
                if child.type == "identifier":
                    return child.text.decode("utf-8")
        parent = parent.parent
    return None


def _extract_python_calls(
    tree: Any,
    source: str,
    file_path: str,
    graph: CallGraph,
    import_map: dict[str, str],
) -> None:
    source_lines = source.splitlines()

    def walk(node: Any) -> None:
        if node.type == "call":
            # Extract callee name
            func_node = None
            for child in node.children:
                if child.type in ("identifier", "attribute"):
                    func_node = child
                    break
            if func_node:
                callee_name = func_node.text.decode("utf-8")
                caller = _current_function(node, source_lines) or "<module>"
                caller_fq = f"{file_path}::{caller}"
                # Attempt cross-file resolution
                base = callee_name.split(".")[0]
                callee_file = import_map.get(base, "")
                callee_fq = (
                    f"{callee_file}::{callee_name}" if callee_file else callee_name
                )
                graph.edges.append(CallEdge(caller=caller_fq, callee=callee_fq))
        for child in node.children:
            walk(child)

    walk(tree.root_node)


def _extract_js_calls(
    tree: Any,
    source: str,
    file_path: str,
    graph: CallGraph,
    import_map: dict[str, str],
) -> None:
    source_lines = source.splitlines()

    def walk(node: Any) -> None:
        if node.type == "call_expression":
            func_node = node.child_by_field_name("function")
            if func_node:
                callee_name = func_node.text.decode("utf-8")
                caller = _current_function(node, source_lines) or "<module>"
                caller_fq = f"{file_path}::{caller}"
                base = callee_name.split(".")[0]
                callee_file = import_map.get(base, "")
                callee_fq = (
                    f"{callee_file}::{callee_name}" if callee_file else callee_name
                )
                graph.edges.append(CallEdge(caller=caller_fq, callee=callee_fq))
        for child in node.children:
            walk(child)

    walk(tree.root_node)


def _extract_go_calls(
    tree: Any,
    source: str,
    file_path: str,
    graph: CallGraph,
    import_map: dict[str, str],
) -> None:
    source_lines = source.splitlines()

    def walk(node: Any) -> None:
        if node.type == "call_expression":
            func_node = node.child_by_field_name("function")
            if func_node:
                callee_name = func_node.text.decode("utf-8")
                caller = _current_function(node, source_lines) or "<package>"
                caller_fq = f"{file_path}::{caller}"
                graph.edges.append(CallEdge(caller=caller_fq, callee=callee_name))
        for child in node.children:
            walk(child)

    walk(tree.root_node)
