"""Change classifier — diffs symbol graphs pre/post to classify change type."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import Enum
from typing import Any

from mergeguard.intelligence.symbol_extractor import Symbol

log = logging.getLogger(__name__)


class ChangeClass(str, Enum):
    SIGNATURE = "signature"       # public API / signature changed
    LOGIC = "logic"               # function body changed, signature same
    REFACTOR = "refactor"         # pure rename / move / structural
    CONFIG = "config"             # config / env / infra files changed
    DOCS = "docs"                 # only docs / comments changed
    TEST = "test"                 # only test files changed
    NEW_FILE = "new_file"         # net-new file
    DELETED = "deleted"           # file removed
    UNKNOWN = "unknown"


@dataclass
class SymbolDelta:
    name: str
    file: str
    change_class: ChangeClass
    old_signature: str | None = None
    new_signature: str | None = None
    old_hash: str | None = None
    new_hash: str | None = None


def classify_changes(
    base_symbols: list[Symbol],
    head_symbols: list[Symbol],
    changed_files: list[dict[str, Any]],  # from fetch_pr_diff "files"
) -> list[SymbolDelta]:
    """Compare symbol lists between base and head commits to classify each change.

    Args:
        base_symbols: Symbols extracted from the base (pre-merge) version.
        head_symbols: Symbols extracted from the head (post-merge) version.
        changed_files: File list from fetch_pr_diff (with 'status' field).

    Returns:
        List of SymbolDelta objects, one per changed/added/removed symbol.
    """
    deltas: list[SymbolDelta] = []

    # Build lookup: (file, name) -> symbol
    base_map = {(s.file, s.name): s for s in base_symbols}
    head_map = {(s.file, s.name): s for s in head_symbols}

    # Changed file metadata
    file_status: dict[str, str] = {f["path"]: f["status"] for f in changed_files}

    # New or deleted files
    for path, status in file_status.items():
        if status == "added":
            deltas.append(
                SymbolDelta(
                    name="*",
                    file=path,
                    change_class=ChangeClass.NEW_FILE,
                )
            )
        elif status == "removed":
            deltas.append(
                SymbolDelta(
                    name="*",
                    file=path,
                    change_class=ChangeClass.DELETED,
                )
            )

    # Removed symbols (present in base, not in head)
    for key, sym in base_map.items():
        if key not in head_map:
            deltas.append(
                SymbolDelta(
                    name=sym.name,
                    file=sym.file,
                    change_class=ChangeClass.SIGNATURE,  # removal = breaking
                    old_signature=sym.signature,
                    old_hash=sym.signature_hash,
                )
            )

    # Added symbols (in head, not in base)
    for key, sym in head_map.items():
        if key not in base_map:
            deltas.append(
                SymbolDelta(
                    name=sym.name,
                    file=sym.file,
                    change_class=ChangeClass.NEW_FILE,
                    new_signature=sym.signature,
                    new_hash=sym.signature_hash,
                )
            )

    # Modified symbols (in both — compare hashes)
    for key in base_map.keys() & head_map.keys():
        base_sym = base_map[key]
        head_sym = head_map[key]

        if base_sym.signature_hash != head_sym.signature_hash:
            # Signature line changed
            change_class = ChangeClass.SIGNATURE
        elif _is_pure_rename(base_sym, head_sym):
            change_class = ChangeClass.REFACTOR
        else:
            # Body changed but signature same
            change_class = ChangeClass.LOGIC

        if change_class != ChangeClass.REFACTOR or (
            base_sym.signature_hash != head_sym.signature_hash
        ):
            deltas.append(
                SymbolDelta(
                    name=base_sym.name,
                    file=base_sym.file,
                    change_class=change_class,
                    old_signature=base_sym.signature,
                    new_signature=head_sym.signature,
                    old_hash=base_sym.signature_hash,
                    new_hash=head_sym.signature_hash,
                )
            )

    # Annotate config / docs / test file changes
    for path, status in file_status.items():
        if status in ("modified", "added") and _is_config_file(path):
            deltas.append(
                SymbolDelta(name="*", file=path, change_class=ChangeClass.CONFIG)
            )
        elif _is_test_file(path):
            deltas.append(
                SymbolDelta(name="*", file=path, change_class=ChangeClass.TEST)
            )
        elif _is_docs_file(path):
            deltas.append(
                SymbolDelta(name="*", file=path, change_class=ChangeClass.DOCS)
            )

    return deltas


def _is_pure_rename(a: Symbol, b: Symbol) -> bool:
    return a.signature_hash == b.signature_hash and a.file != b.file


def _is_config_file(path: str) -> bool:
    config_extensions = {
        ".yml", ".yaml", ".json", ".toml", ".ini", ".cfg",
        ".env", ".dockerfile", "Dockerfile",
    }
    return any(path.endswith(ext) for ext in config_extensions) or "config" in path.lower()


def _is_test_file(path: str) -> bool:
    return (
        "/test" in path
        or "/tests/" in path
        or path.startswith("test_")
        or "_test.go" in path
        or "spec." in path
    )


def _is_docs_file(path: str) -> bool:
    return path.endswith(".md") or "/docs/" in path or path.endswith(".rst")


def summarize_classification(deltas: list[SymbolDelta]) -> dict[str, list[str]]:
    """Group SymbolDelta names by change class for a quick summary."""
    summary: dict[str, list[str]] = {}
    for d in deltas:
        key = d.change_class.value
        summary.setdefault(key, []).append(f"{d.file}::{d.name}")
    return summary
