"""Strands tool: analyze_impact — BFS blast-radius annotation on findings."""

from __future__ import annotations

import logging
import re
from typing import Any

from strands import tool

from mergeguard.scoring.impact import (
    annotate_findings_with_impact,
    compute_blast_radius,
    impact_score,
)

log = logging.getLogger(__name__)


@tool
def analyze_impact(
    findings: list[dict[str, Any]],
    patches: list[dict[str, Any]],
) -> dict[str, Any]:
    """Annotate each finding with a blast-radius impact score.

    Builds a lightweight called_by graph from the diff (function calls visible
    in added/removed lines) then runs BFS from each changed symbol to find
    transitive callers. Each finding gets an 'impact' field (0.0–5.0).

    Args:
        findings: Flat list of findings from all specialist agents.
        patches:  Serialized FilePatch list from fetch_pr_diff.

    Returns:
        Dict with 'findings' (annotated) and 'impact_summary' stats.
    """
    called_by_graph = _build_called_by_graph(patches)
    symbol_to_file = _build_symbol_to_file(patches)

    annotated = annotate_findings_with_impact(findings, called_by_graph, symbol_to_file)

    # Also compute per-symbol blast radius for the summary
    changed_symbols = list(symbol_to_file.keys())
    blast_map = compute_blast_radius(changed_symbols, called_by_graph)
    blast_summary = {
        sym: {"callers_affected": len(radius), "impact_score": round(impact_score(len(radius)), 2)}
        for sym, radius in blast_map.items()
        if radius  # only include symbols with actual blast radius
    }

    log.info(
        "Impact analysis: %d findings annotated, %d symbols with blast radius",
        len(annotated),
        len(blast_summary),
    )

    return {
        "findings": annotated,
        "impact_summary": blast_summary,
        "total_changed_symbols": len(changed_symbols),
    }


def _build_called_by_graph(patches: list[dict[str, Any]]) -> dict[str, list[str]]:
    """Extract a called_by graph from function call patterns in the diff.

    Strategy: scan added lines for `something(` patterns adjacent to function
    definitions to infer caller→callee edges, then invert to called_by.
    This is best-effort for diff context — the full CIL graph is richer.
    """
    calls: dict[str, list[str]] = {}
    current_function: str | None = None

    func_def_re = re.compile(
        r"^\+\s*(?:def|async def|function|func|public|private|protected|static)?\s*"
        r"(?:def |async def |function |func )?(\w+)\s*\("
    )
    call_re = re.compile(r"\b(\w+)\s*\(")

    for patch in patches:
        file_path = patch.get("path", "")
        for hunk in patch.get("hunks", []):
            for line in hunk.get("added", []):
                # Detect function definition
                m = func_def_re.match(line)
                if m:
                    current_function = f"{file_path}::{m.group(1)}"
                    calls.setdefault(current_function, [])
                    continue
                # Detect calls within the current function
                if current_function:
                    for callee in call_re.findall(line):
                        if callee not in {
                            "if",
                            "for",
                            "while",
                            "return",
                            "print",
                            "len",
                            "str",
                            "int",
                            "list",
                            "dict",
                            "set",
                            "bool",
                        }:
                            full_callee = f"{file_path}::{callee}"
                            calls.setdefault(current_function, []).append(full_callee)

    # Invert to called_by
    called_by: dict[str, list[str]] = {}
    for caller, callees in calls.items():
        for callee in callees:
            called_by.setdefault(callee, []).append(caller)

    return called_by


def _build_symbol_to_file(patches: list[dict[str, Any]]) -> dict[str, str]:
    """Map changed symbol names to their file path."""
    symbol_to_file: dict[str, str] = {}

    func_def_re = re.compile(r"^[-+]\s*(?:async def |def |function |func |class )(\w+)\s*[\(:]")

    for patch in patches:
        file_path = patch.get("path", "")
        for hunk in patch.get("hunks", []):
            for line in hunk.get("removed", []) + hunk.get("added", []):
                m = func_def_re.match(line)
                if m:
                    symbol_to_file[f"{file_path}::{m.group(1)}"] = file_path

    return symbol_to_file
