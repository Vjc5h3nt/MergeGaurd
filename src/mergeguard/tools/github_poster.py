"""Strands tool: post_github_review — posts the final review comment to a GitHub PR."""

from __future__ import annotations

import logging
from typing import Any

from strands import tool

from mergeguard.integrations.github import get_github_client

log = logging.getLogger(__name__)

# Map risk bucket to GitHub review event
_EVENT_MAP = {
    "BLOCKING": "REQUEST_CHANGES",
    "HIGH": "REQUEST_CHANGES",
    "MEDIUM": "COMMENT",
    "LOW": "COMMENT",
}


@tool
def post_github_review(
    owner: str,
    repo: str,
    pr_number: int,
    head_sha: str,
    risk_bucket: str,
    risk_score: int,
    summary: str,
    findings: list[dict[str, Any]],
    dry_run: bool = False,
) -> dict[str, Any]:
    """Post a structured code review comment to a GitHub Pull Request.

    Args:
        owner: GitHub repository owner.
        repo: Repository name.
        pr_number: Pull request number.
        head_sha: The head commit SHA (required for inline comments).
        risk_bucket: One of LOW | MEDIUM | HIGH | BLOCKING.
        risk_score: Numeric risk score 0–100.
        summary: Markdown summary of the review.
        findings: List of finding dicts with keys:
            - severity (str): CRITICAL | HIGH | MEDIUM | LOW | INFO
            - category (str): e.g. security/sqli, quality/complexity
            - message (str): human-readable description
            - path (str, optional): file path
            - line (int, optional): target line number
            - suggestion (str, optional): suggested fix
        dry_run: If True, format and return the review body without posting.

    Returns:
        Dict with 'posted' bool, 'review_id' (if posted), 'body' (markdown).
    """
    body = _render_review_body(risk_score, risk_bucket, summary, findings)

    if dry_run:
        log.info("Dry run — review body formatted but not posted.")
        return {"posted": False, "review_id": None, "body": body}

    event = _EVENT_MAP.get(risk_bucket, "COMMENT")
    gh = get_github_client()

    # Post the main review body without inline comments (avoids 422 from
    # line numbers that don't sit on the diff).
    review = gh.create_review(
        owner=owner,
        repo=repo,
        number=pr_number,
        body=body,
        event=event,
        comments=None,
        commit_id=head_sha,
    )

    review_id = review.get("id")
    log.info(
        "Posted review #%s on %s/%s#%d (event=%s)",
        review_id,
        owner,
        repo,
        pr_number,
        event,
    )

    # Post inline comments individually so a single bad line number
    # doesn't block the rest.
    inline_comments = _build_inline_comments(findings)
    for comment in inline_comments:
        try:
            gh.create_review_comment(
                owner=owner,
                repo=repo,
                number=pr_number,
                commit_id=head_sha,
                path=comment["path"],
                line=comment["line"],
                side=comment.get("side", "RIGHT"),
                body=comment["body"],
            )
        except Exception as exc:
            log.warning("Skipped inline comment on %s:%s — %s", comment["path"], comment["line"], exc)

    # Also create / update a Check Run for branch protection
    _post_check_run(owner, repo, head_sha, risk_bucket, risk_score, body)

    return {
        "posted": True,
        "review_id": review_id,
        "body": body,
    }


def _render_review_body(
    risk_score: int,
    risk_bucket: str,
    summary: str,
    findings: list[dict[str, Any]],
) -> str:
    from mergeguard.scoring.pr_score import compute_pr_score, render_score_table

    bucket_emoji = {
        "BLOCKING": "🔴",
        "HIGH": "🟠",
        "MEDIUM": "🟡",
        "LOW": "🟢",
    }.get(risk_bucket, "⚪")

    verdict_map = {
        "BLOCKING": "🔴 **CHANGES REQUESTED** — Resolve BLOCKING issues before merging.",
        "HIGH": "🟠 **CHANGES REQUESTED** — Resolve HIGH severity issues before merging.",
        "MEDIUM": "🟡 **REVIEW NEEDED** — Consider addressing MEDIUM issues.",
        "LOW": "🟢 **APPROVED** — Low risk. Nice work!",
    }

    lines: list[str] = [
        f"## {bucket_emoji} MergeGuard AI Review — Risk Score: `{risk_score}/100` ({risk_bucket})",
        "",
        "> " + verdict_map.get(risk_bucket, "ℹ️ COMMENT"),
        "",
        "---",
        "",
        "### Summary",
        summary,
        "",
    ]

    # Per-dimension score breakdown + per-file table
    if findings:
        pr_score = compute_pr_score(findings)
        lines.append("### Risk Breakdown")
        lines.append("")
        lines.append(render_score_table(pr_score, findings))
        lines.append("")

    # Findings table — sorted by severity then impact
    _SEV_ORDER = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3, "INFO": 4}
    sorted_findings = sorted(
        findings,
        key=lambda f: (_SEV_ORDER.get(f.get("severity", "INFO"), 5), -float(f.get("impact", 0))),
    )

    if sorted_findings:
        lines.append("### Findings")
        lines.append("")
        lines.append("| Severity | Impact | Category | Location | Message |")
        lines.append("|----------|--------|----------|----------|---------|")
        for f in sorted_findings:
            path = f.get("path", "—")
            line_no = f.get("line", "")
            loc = f"`{path}:{line_no}`" if line_no else f"`{path}`"
            impact = f.get("impact", 0)
            impact_str = f"{'⚡' * min(int(impact), 3)} {impact:.1f}" if impact else "—"
            det_badge = " 🔒" if f.get("deterministic") else ""
            lines.append(
                f"| **{f.get('severity','?')}**{det_badge} | {impact_str} "
                f"| {f.get('category','?')} | {loc} | {f.get('message','')} |"
            )
        lines.append("")
        lines.append("> 🔒 = confirmed by static analysis &nbsp;|&nbsp; ⚡ = blast-radius impact level")
        lines.append("")

        # Collapsible details per finding
        for f in sorted_findings:
            sev = f.get("severity", "INFO")
            cat = f.get("category", "")
            msg = f.get("message", "")
            impact = f.get("impact", 0)
            det = " · 🔒 static" if f.get("deterministic") else ""
            impact_label = f" · ⚡ impact {impact:.1f}/5" if impact else ""

            lines.append(
                f"<details><summary><b>{sev}</b> — {cat}{det}{impact_label} — "
                f"{msg[:80]}{'…' if len(msg) > 80 else ''}</summary>"
            )
            lines.append("")
            if path := f.get("path"):
                ln = f.get("line", "")
                lines.append(f"**File:** `{path}`" + (f" line {ln}" if ln else ""))
                lines.append("")
            lines.append(msg)
            lines.append("")
            if suggestion := f.get("suggestion"):
                lines.append("**Suggested fix:**")
                lines.append(f"```\n{suggestion}\n```")
            lines.append("")
            lines.append("</details>")
            lines.append("")

    lines.append("---")
    lines.append(
        "*Generated by [MergeGuard](https://github.com/Vjc5h3nt/MergeGaurd) — "
        "AI PR Review powered by [AWS Strands SDK](https://github.com/strands-agents/sdk-python) "
        "+ Amazon Bedrock*"
    )

    return "\n".join(lines)


def _build_inline_comments(findings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Convert findings with file + line into GitHub inline review comment dicts."""
    comments: list[dict[str, Any]] = []
    for f in findings:
        path = f.get("path")
        line = f.get("line")
        if not path or not line:
            continue
        body_parts = [f"**{f.get('severity','?')}** — {f.get('category','')}",
                      "", f.get("message", "")]
        if suggestion := f.get("suggestion"):
            body_parts += ["", "**Suggested fix:**", f"```\n{suggestion}\n```"]
        comments.append({
            "path": path,
            "line": int(line),
            "side": "RIGHT",
            "body": "\n".join(body_parts),
        })
    return comments


def _post_check_run(
    owner: str,
    repo: str,
    head_sha: str,
    risk_bucket: str,
    risk_score: int,
    summary: str,
) -> None:
    conclusion_map = {
        "BLOCKING": "action_required",
        "HIGH": "action_required",
        "MEDIUM": "neutral",
        "LOW": "success",
    }
    conclusion = conclusion_map.get(risk_bucket, "neutral")
    gh = get_github_client()
    try:
        gh.create_check_run(
            owner=owner,
            repo=repo,
            name="MergeGuard AI Review",
            head_sha=head_sha,
            status="completed",
            conclusion=conclusion,
            title=f"Risk Score: {risk_score}/100 — {risk_bucket}",
            summary=summary[:65535],  # GitHub limit
        )
    except Exception as exc:
        log.warning("Failed to create check run: %s", exc)
