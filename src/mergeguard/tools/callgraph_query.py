"""Strands tool: callgraph_query — BFS blast-radius lookup on the call graph."""

from __future__ import annotations

import logging
from typing import Any

from strands import tool

log = logging.getLogger(__name__)


@tool
def callgraph_query(
    changed_symbols: list[str],
    called_by_graph: dict[str, list[str]],
    max_depth: int = 3,
) -> dict[str, Any]:
    """Compute the blast radius of changed symbols via BFS on the call graph.

    Args:
        changed_symbols: List of fully-qualified symbol names that changed.
        called_by_graph: Maps symbol -> list of callers (from build_call_graph).
        max_depth: BFS depth limit (default 3).

    Returns:
        Dict with per-symbol blast radius sets and impact scores.
    """
    from mergeguard.scoring.impact import compute_blast_radius, impact_score

    blast_radius = compute_blast_radius(changed_symbols, called_by_graph, max_depth)

    result: dict[str, Any] = {}
    for sym, callers in blast_radius.items():
        result[sym] = {
            "callers": sorted(callers),
            "blast_radius_count": len(callers),
            "impact_score": impact_score(len(callers)),
        }

    return {
        "blast_radius": result,
        "total_impacted": len({c for callers in blast_radius.values() for c in callers}),
    }
