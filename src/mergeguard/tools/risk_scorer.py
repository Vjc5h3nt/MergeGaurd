"""Strands tool: calculate_risk_score — aggregates findings into a weighted PR risk score."""

from __future__ import annotations

import logging
import math
from typing import Any

from strands import tool

log = logging.getLogger(__name__)

# Severity weights
_SEVERITY_WEIGHTS = {
    "CRITICAL": 15,
    "HIGH": 8,
    "MEDIUM": 3,
    "LOW": 1,
    "INFO": 0,
}

# Dimension weights (as fractions, must sum to 1.0)
_DIMENSION_WEIGHTS = {
    "security": 0.30,
    "complexity": 0.20,
    "test_coverage": 0.20,
    "architecture": 0.15,
    "breaking_change": 0.15,
}

_BUCKET_THRESHOLDS = [
    (75, "BLOCKING"),
    (50, "HIGH"),
    (25, "MEDIUM"),
    (0, "LOW"),
]


@tool
def calculate_risk_score(findings: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate specialist findings into a weighted risk score (0–100) and bucket.

    Args:
        findings: List of finding dicts from specialist agents. Each dict must have:
            - severity (str): CRITICAL | HIGH | MEDIUM | LOW | INFO
            - category (str): dot-separated, first segment is dimension
                              e.g. "security/sqli", "complexity/cognitive"
            - impact (float, optional): 0–5 blast-radius impact score

    Returns:
        Dict with:
        - score (int): 0–100
        - bucket (str): LOW | MEDIUM | HIGH | BLOCKING
        - breakdown (dict): per-dimension sub-scores
        - finding_count (int)
    """
    if not findings:
        return {"score": 0, "bucket": "LOW", "breakdown": {}, "finding_count": 0}

    dimension_scores: dict[str, float] = {k: 0.0 for k in _DIMENSION_WEIGHTS}

    for f in findings:
        sev = f.get("severity", "INFO").upper()
        category = f.get("category", "")
        impact = float(f.get("impact", 0))

        base_weight = _SEVERITY_WEIGHTS.get(sev, 0)
        impact_multiplier = 1.0 + impact / 5.0
        finding_score = base_weight * impact_multiplier

        # Map category prefix to dimension
        dim = _category_to_dimension(category)
        if dim in dimension_scores:
            dimension_scores[dim] = min(
                100, dimension_scores[dim] + finding_score
            )

    # Weighted sum capped at 100
    raw_score = sum(
        dimension_scores[dim] * weight
        for dim, weight in _DIMENSION_WEIGHTS.items()
    )
    score = min(100, int(raw_score))
    bucket = _score_to_bucket(score)

    log.info("Risk score: %d (%s) | findings: %d", score, bucket, len(findings))

    return {
        "score": score,
        "bucket": bucket,
        "breakdown": {k: round(v, 1) for k, v in dimension_scores.items()},
        "finding_count": len(findings),
    }


def compute_blast_radius_impact(blast_radius: int) -> float:
    """Convert BFS blast-radius count to an impact score 0–5."""
    return min(5.0, math.log2(blast_radius + 1))


def _category_to_dimension(category: str) -> str:
    prefix = category.split("/")[0].lower()
    mapping = {
        "security": "security",
        "complexity": "complexity",
        "quality": "complexity",
        "test": "test_coverage",
        "coverage": "test_coverage",
        "architecture": "architecture",
        "arch": "architecture",
        "breaking": "breaking_change",
        "regression": "breaking_change",
        "api": "breaking_change",
    }
    return mapping.get(prefix, "complexity")


def _score_to_bucket(score: int) -> str:
    for threshold, bucket in _BUCKET_THRESHOLDS:
        if score >= threshold:
            return bucket
    return "LOW"
