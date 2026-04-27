"""BFS blast-radius impact calculator on the call graph."""

from __future__ import annotations

import logging
import math
from typing import Any

log = logging.getLogger(__name__)


def compute_blast_radius(
    changed_symbols: list[str],
    called_by_graph: dict[str, list[str]],
    max_depth: int = 3,
) -> dict[str, set[str]]:
    """BFS from each changed symbol upward through the `called_by` graph.

    Args:
        changed_symbols: Symbol names that were modified in the PR.
        called_by_graph: Maps symbol -> list of symbols that call it.
        max_depth: Maximum BFS depth (default 3, per PRD).

    Returns:
        Dict mapping each changed symbol to its blast-radius set
        (all transitively impacted callers, excluding the symbol itself).
    """
    result: dict[str, set[str]] = {}

    for symbol in changed_symbols:
        visited: set[str] = set()
        queue = [(symbol, 0)]

        while queue:
            current, depth = queue.pop(0)
            if depth >= max_depth:
                continue
            callers = called_by_graph.get(current, [])
            for caller in callers:
                if caller not in visited and caller != symbol:
                    visited.add(caller)
                    queue.append((caller, depth + 1))

        result[symbol] = visited

    return result


def impact_score(blast_radius_count: int) -> float:
    """Convert blast-radius size to a 0–5 impact score (log scale, per PRD)."""
    return min(5.0, math.log2(blast_radius_count + 1))


def annotate_findings_with_impact(
    findings: list[dict[str, Any]],
    called_by_graph: dict[str, list[str]],
    symbol_to_file: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    """Add `impact` field to each finding based on blast-radius of the affected symbol."""
    annotated = []
    for f in findings:
        path = f.get("path", "")
        # Try to match finding file path to a known symbol
        blast = 0
        if symbol_to_file:
            for sym, sym_file in symbol_to_file.items():
                if sym_file == path:
                    radius = compute_blast_radius([sym], called_by_graph)
                    blast = max(blast, len(radius.get(sym, set())))

        annotated.append({**f, "impact": impact_score(blast)})
    return annotated
