"""Symbol extractor — walks a tree-sitter AST and emits Symbol objects."""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass
from typing import Any

log = logging.getLogger(__name__)


@dataclass
class Symbol:
    name: str
    kind: str  # function | class | method | variable | constant
    file: str
    start_line: int
    end_line: int
    signature: str  # text of the definition line (for hashing / change detection)
    signature_hash: str
    language: str
    parent: str | None = None  # enclosing class name for methods


def _make_hash(signature: str) -> str:
    return hashlib.sha256(signature.encode()).hexdigest()[:16]


# Tree-sitter node type -> Symbol kind mappings per language
_NODE_KIND_MAP: dict[str, dict[str, str]] = {
    "python": {
        "function_definition": "function",
        "async_function_def": "function",
        "class_definition": "class",
    },
    "typescript": {
        "function_declaration": "function",
        "method_definition": "method",
        "class_declaration": "class",
        "arrow_function": "function",
        "interface_declaration": "class",
    },
    "javascript": {
        "function_declaration": "function",
        "method_definition": "method",
        "class_declaration": "class",
        "arrow_function": "function",
    },
    "go": {
        "function_declaration": "function",
        "method_declaration": "method",
        "type_declaration": "class",
    },
    "java": {
        "method_declaration": "method",
        "class_declaration": "class",
        "interface_declaration": "class",
        "constructor_declaration": "method",
    },
}

# Node field containing the identifier for each language/type
_NAME_FIELD = "name"


def extract_symbols(
    tree: Any,
    source: str,
    file_path: str,
    language: str,
) -> list[Symbol]:
    """Extract all top-level and class-member symbols from a parsed AST."""
    symbols: list[Symbol] = []
    source_lines = source.splitlines()

    node_map = _NODE_KIND_MAP.get(language, {})
    if not node_map:
        return []

    def walk(node: Any, parent_class: str | None = None) -> None:
        node_type = node.type
        kind = node_map.get(node_type)

        if kind:
            name = _extract_name(node, language)
            if name:
                start = node.start_point[0]  # 0-indexed
                end = node.end_point[0]
                # Signature = first line of the definition
                sig = source_lines[start].strip() if start < len(source_lines) else ""
                symbols.append(
                    Symbol(
                        name=name,
                        kind=kind,
                        file=file_path,
                        start_line=start + 1,  # 1-indexed for humans
                        end_line=end + 1,
                        signature=sig,
                        signature_hash=_make_hash(sig),
                        language=language,
                        parent=parent_class if kind == "method" else None,
                    )
                )
                # Track class name for child methods
                new_parent = name if kind == "class" else parent_class
                for child in node.children:
                    walk(child, parent_class=new_parent)
                return

        for child in node.children:
            walk(child, parent_class=parent_class)

    walk(tree.root_node)
    return symbols


def _extract_name(node: Any, language: str) -> str | None:
    """Extract the identifier name from a definition node."""
    # The canonical way: look up the "name" field on the node.
    named = node.child_by_field_name(_NAME_FIELD)
    if named is not None and named.text:
        return named.text.decode("utf-8")
    # Fallback: first identifier-ish child (some grammars don't use fields).
    for child in node.children:
        if child.type in ("identifier", "type_identifier", "property_identifier"):
            return child.text.decode("utf-8")
    return None


def symbols_to_dict(symbols: list[Symbol]) -> list[dict[str, Any]]:
    return [
        {
            "name": s.name,
            "kind": s.kind,
            "file": s.file,
            "start_line": s.start_line,
            "end_line": s.end_line,
            "signature": s.signature,
            "signature_hash": s.signature_hash,
            "language": s.language,
            "parent": s.parent,
        }
        for s in symbols
    ]
