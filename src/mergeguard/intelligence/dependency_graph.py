"""Dependency graph — per-language import edges."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

log = logging.getLogger(__name__)


@dataclass
class ImportEdge:
    source_file: str  # file that contains the import
    imported_name: str  # name being imported
    module_path: str  # resolved module / package path
    is_external: bool  # True if from a third-party package


@dataclass
class DependencyGraph:
    edges: list[ImportEdge] = field(default_factory=list)

    def imports_by_file(self) -> dict[str, list[str]]:
        """Returns {file: [module_paths imported]}."""
        result: dict[str, list[str]] = {}
        for e in self.edges:
            result.setdefault(e.source_file, []).append(e.module_path)
        return result

    def import_map(self) -> dict[str, str]:
        """Returns {imported_name: source_file} for intra-repo imports only."""
        return {e.imported_name: e.module_path for e in self.edges if not e.is_external}

    def to_dict(self) -> dict[str, Any]:
        return {
            "imports_by_file": self.imports_by_file(),
            "edges": [
                {
                    "source_file": e.source_file,
                    "imported_name": e.imported_name,
                    "module_path": e.module_path,
                    "is_external": e.is_external,
                }
                for e in self.edges
            ],
        }


def build_dependency_graph(
    tree: Any,
    source: str,
    file_path: str,
    language: str,
    known_files: set[str] | None = None,
) -> DependencyGraph:
    """Extract import/dependency edges for a single file.

    Args:
        tree: tree-sitter Tree.
        source: Raw source text.
        file_path: Path of file being analyzed.
        language: Language name.
        known_files: Set of all files in the repo (for is_external detection).
    """
    graph = DependencyGraph()
    kf = known_files or set()

    if language == "python":
        _extract_python_imports(tree, source, file_path, graph, kf)
    elif language in ("typescript", "javascript"):
        _extract_js_imports(tree, source, file_path, graph, kf)
    elif language == "go":
        _extract_go_imports(tree, source, file_path, graph, kf)
    elif language == "java":
        _extract_java_imports(tree, source, file_path, graph, kf)
    else:
        log.debug("Dependency extraction not implemented for %s", language)

    return graph


def _is_external(module: str, known_files: set[str]) -> bool:
    """Heuristic: external if module path doesn't resolve to a known repo file."""
    # Relative imports are always internal
    if module.startswith("."):
        return False
    # Check if any known file matches this module as a path component
    module_as_path = module.replace(".", "/")
    return not any(module_as_path in f for f in known_files)


def _extract_python_imports(
    tree: Any,
    source: str,
    file_path: str,
    graph: DependencyGraph,
    known_files: set[str],
) -> None:
    def walk(node: Any) -> None:
        if node.type == "import_statement":
            for child in node.children:
                if child.type == "dotted_name":
                    module = child.text.decode("utf-8")
                    graph.edges.append(
                        ImportEdge(
                            source_file=file_path,
                            imported_name=module.split(".")[-1],
                            module_path=module,
                            is_external=_is_external(module, known_files),
                        )
                    )
        elif node.type == "import_from_statement":
            module_node = node.child_by_field_name("module_name")
            module = module_node.text.decode("utf-8") if module_node else ""
            for child in node.children:
                if child.type == "dotted_name" and child != module_node:
                    name = child.text.decode("utf-8")
                    graph.edges.append(
                        ImportEdge(
                            source_file=file_path,
                            imported_name=name,
                            module_path=module,
                            is_external=_is_external(module, known_files),
                        )
                    )
        for child in node.children:
            walk(child)

    walk(tree.root_node)


def _extract_js_imports(
    tree: Any,
    source: str,
    file_path: str,
    graph: DependencyGraph,
    known_files: set[str],
) -> None:
    def walk(node: Any) -> None:
        if node.type == "import_statement":
            # import { X } from 'module'
            source_node = node.child_by_field_name("source")
            if source_node:
                module = source_node.text.decode("utf-8").strip("'\"")
                is_ext = not module.startswith(".")
                graph.edges.append(
                    ImportEdge(
                        source_file=file_path,
                        imported_name=module.split("/")[-1],
                        module_path=module,
                        is_external=is_ext,
                    )
                )
        for child in node.children:
            walk(child)

    walk(tree.root_node)


def _extract_go_imports(
    tree: Any,
    source: str,
    file_path: str,
    graph: DependencyGraph,
    known_files: set[str],
) -> None:
    def walk(node: Any) -> None:
        if node.type == "import_spec":
            for child in node.children:
                if child.type == "interpreted_string_literal":
                    module = child.text.decode("utf-8").strip('"')
                    is_ext = "/" in module and not module.startswith("./")
                    graph.edges.append(
                        ImportEdge(
                            source_file=file_path,
                            imported_name=module.split("/")[-1],
                            module_path=module,
                            is_external=is_ext,
                        )
                    )
        for child in node.children:
            walk(child)

    walk(tree.root_node)


def _extract_java_imports(
    tree: Any,
    source: str,
    file_path: str,
    graph: DependencyGraph,
    known_files: set[str],
) -> None:
    def walk(node: Any) -> None:
        if node.type == "import_declaration":
            for child in node.children:
                if child.type == "scoped_identifier":
                    module = child.text.decode("utf-8")
                    is_ext = not any(p in module for p in ("com.", "org.", "net."))
                    graph.edges.append(
                        ImportEdge(
                            source_file=file_path,
                            imported_name=module.split(".")[-1],
                            module_path=module,
                            is_external=is_ext,
                        )
                    )
        for child in node.children:
            walk(child)

    walk(tree.root_node)
