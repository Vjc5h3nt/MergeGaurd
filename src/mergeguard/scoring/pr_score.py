"""PR-level risk score aggregation and markdown summary table."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from mergeguard.scoring.severity import Severity


@dataclass
class PRScore:
    score: int
    bucket: str  # LOW | MEDIUM | HIGH | BLOCKING
    breakdown: dict[str, float] = field(default_factory=dict)
    finding_count: int = 0
    per_file: dict[str, int] = field(default_factory=dict)


_BUCKET_THRESHOLDS = [
    (75, "BLOCKING"),
    (50, "HIGH"),
    (25, "MEDIUM"),
    (0, "LOW"),
]

_DIMENSION_WEIGHTS = {
    "security": 0.30,
    "complexity": 0.20,
    "test_coverage": 0.20,
    "architecture": 0.15,
    "breaking_change": 0.15,
}


def compute_pr_score(findings: list[dict[str, Any]]) -> PRScore:
    """Compute a PRScore from a flat list of findings."""
    dimension_scores: dict[str, float] = {k: 0.0 for k in _DIMENSION_WEIGHTS}
    per_file: dict[str, float] = {}

    for f in findings:
        sev = Severity.from_str(f.get("severity", "INFO"))
        category = f.get("category", "")
        impact = float(f.get("impact", 0))

        from mergeguard.tools.risk_scorer import _category_to_dimension  # noqa: PLC0415

        dim = _category_to_dimension(category)
        base = sev.value * 3  # scale 0-15
        impact_mult = 1.0 + impact / 5.0
        fs = base * impact_mult

        dimension_scores[dim] = min(100, dimension_scores[dim] + fs)

        path = f.get("path", "")
        if path:
            per_file[path] = per_file.get(path, 0.0) + fs

    raw = sum(dimension_scores[d] * w for d, w in _DIMENSION_WEIGHTS.items())
    score = min(100, int(raw))

    bucket = "LOW"
    for threshold, b in _BUCKET_THRESHOLDS:
        if score >= threshold:
            bucket = b
            break

    return PRScore(
        score=score,
        bucket=bucket,
        breakdown={k: round(v, 1) for k, v in dimension_scores.items()},
        finding_count=len(findings),
        per_file={k: min(100, int(v)) for k, v in per_file.items()},
    )


def render_score_table(pr_score: PRScore, findings: list[dict[str, Any]]) -> str:
    """Render a markdown summary table for the GitHub review comment."""
    lines = [
        "| Dimension | Score |",
        "|-----------|-------|",
    ]
    for dim, val in pr_score.breakdown.items():
        bar = "█" * int(val / 10)
        lines.append(f"| {dim.replace('_', ' ').title()} | {val:.0f}/100 {bar} |")

    lines.append("")
    lines.append("**Files with highest risk:**")
    lines.append("")
    lines.append("| File | Score |")
    lines.append("|------|-------|")

    top_files = sorted(pr_score.per_file.items(), key=lambda x: x[1], reverse=True)[:5]
    for path, score in top_files:
        lines.append(f"| `{path}` | {score} |")

    return "\n".join(lines)
