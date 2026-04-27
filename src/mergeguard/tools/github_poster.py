"""Strands tool: post_github_review — posts the final review comment to a GitHub PR."""

from __future__ import annotations

import logging
from typing import Any

from strands import tool

from mergeguard.integrations.github import get_github_client

log = logging.getLogger(__name__)

_EVENT_MAP = {
    "BLOCKING": "REQUEST_CHANGES",
    "HIGH": "REQUEST_CHANGES",
    "MEDIUM": "COMMENT",
    "LOW": "COMMENT",
}

_SEV_ORDER = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3, "INFO": 4}

# GitHub Alert type per severity — renders as coloured callout boxes
_ALERT_TYPE = {
    "CRITICAL": "CAUTION",
    "HIGH": "CAUTION",
    "MEDIUM": "WARNING",
    "LOW": "NOTE",
    "INFO": "NOTE",
}

_BUCKET_EMOJI = {
    "BLOCKING": "🔴",
    "HIGH": "🟠",
    "MEDIUM": "🟡",
    "LOW": "🟢",
}

_VERDICT = {
    "BLOCKING": "Changes requested — resolve **BLOCKING** issues before merging.",
    "HIGH":     "Changes requested — resolve **HIGH** severity issues before merging.",
    "MEDIUM":   "Review needed — consider addressing **MEDIUM** issues.",
    "LOW":      "Looks good — low risk.",
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
    patches: list[dict[str, Any]] | None = None,
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
        summary: 2-3 sentence walkthrough of what the PR does and key concerns.
        findings: List of finding dicts (severity, category, message, path, line, suggestion).
        patches: Optional serialized FilePatch list from fetch_pr_diff (used for Changes table).
        dry_run: If True, format and return the review body without posting.

    Returns:
        Dict with 'posted' bool, 'review_id' (if posted), 'body' (markdown).
    """
    body = _render_review_body(risk_score, risk_bucket, summary, findings, patches or [])

    if dry_run:
        log.info("Dry run — review body formatted but not posted.")
        return {"posted": False, "review_id": None, "body": body}

    event = _EVENT_MAP.get(risk_bucket, "COMMENT")
    gh = get_github_client()

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
    log.info("Posted review #%s on %s/%s#%d (event=%s)", review_id, owner, repo, pr_number, event)

    # Inline comments posted individually — a bad line number won't block the rest
    for comment in _build_inline_comments(findings):
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

    _post_check_run(owner, repo, head_sha, risk_bucket, risk_score, summary)

    return {"posted": True, "review_id": review_id, "body": body}


# ---------------------------------------------------------------------------
# Renderer
# ---------------------------------------------------------------------------

def _render_review_body(
    risk_score: int,
    risk_bucket: str,
    summary: str,
    findings: list[dict[str, Any]],
    patches: list[dict[str, Any]],
) -> str:
    emoji = _BUCKET_EMOJI.get(risk_bucket, "⚪")
    n_files = len(patches)

    sorted_findings = sorted(
        findings,
        key=lambda f: (_SEV_ORDER.get(f.get("severity", "INFO"), 5), -float(f.get("impact", 0))),
    )
    main_findings    = [f for f in sorted_findings if f.get("severity") in ("CRITICAL", "HIGH", "MEDIUM")]
    low_findings     = [f for f in sorted_findings if f.get("severity") in ("LOW", "INFO")]
    n_main           = len(main_findings)
    n_low            = len(low_findings)
    n_total          = len(sorted_findings)

    lines: list[str] = []

    # ── Header ───────────────────────────────────────────────────────────────
    lines += [
        f"## {emoji} MergeGuard &nbsp;·&nbsp; {risk_bucket} &nbsp;·&nbsp; `{risk_score}/100`",
        "",
    ]

    # ── Pull request overview ─────────────────────────────────────────────────
    lines += [
        "**Pull request overview**",
        "",
        summary,
        "",
    ]

    # ── Changes bullet list ───────────────────────────────────────────────────
    if patches:
        lines += ["**Changes**", ""]
        for p in patches:
            path = p.get("path", "")
            desc = _patch_description(p, sorted_findings)
            lines.append(f"- `{path}` — {desc}")
        lines += [""]

    # ── Reviewed changes table ────────────────────────────────────────────────
    verdict_line = _VERDICT.get(risk_bucket, "Review complete.")
    reviewed_str = (
        f"MergeGuard reviewed {n_files} file{'s' if n_files != 1 else ''} "
        f"and generated {n_total} comment{'s' if n_total != 1 else ''}. "
        f"{verdict_line}"
    )
    lines += ["**Reviewed changes**", "", reviewed_str, ""]

    if patches:
        lines += ["| File | Description |", "|------|-------------|"]
        for p in patches:
            path     = p.get("path", "")
            added    = p.get("additions", len(p.get("added_lines", [])))
            removed  = p.get("deletions",  len(p.get("removed_lines", [])))
            status   = p.get("status", "modified")
            diff_str = {"added": "New file", "removed": "Deleted", "renamed": "Renamed"}.get(
                status, f"+{added} −{removed}"
            )
            file_issues = [f for f in sorted_findings if f.get("path") == path]
            n_fi = len(file_issues)
            issue_str = f" · {n_fi} issue{'s' if n_fi != 1 else ''}" if file_issues else ""
            desc = _file_table_description(p, file_issues)
            lines.append(f"| `{path}` | {diff_str}{issue_str} — {desc} |")
        lines += [""]

    # ── Main comments grouped by file ────────────────────────────────────────
    if main_findings:
        lines += [f"**Comments ({n_main})**", ""]
        by_file: dict[str, list[dict[str, Any]]] = {}
        for f in main_findings:
            by_file.setdefault(f.get("path", "—"), []).append(f)

        for file_path, file_findings in by_file.items():
            lines += [
                f"<details open>",
                f"<summary>&#9660; <code>{file_path}</code> &nbsp; "
                f"<em>{len(file_findings)} issue{'s' if len(file_findings) != 1 else ''}</em></summary>",
                "",
            ]
            for i, f in enumerate(file_findings):
                lines += _render_comment(f)
                if i < len(file_findings) - 1:
                    lines.append("---")
                    lines.append("")
            lines += ["</details>", ""]

    # ── Low-confidence section — collapsed by default ─────────────────────────
    if low_findings:
        lines += [
            f"<details>",
            f"<summary>&#9658; Low confidence comments ({n_low} suppressed)</summary>",
            "",
        ]
        for f in low_findings:
            lines += _render_low_confidence(f)
        lines += ["</details>", ""]

    # ── Footer ────────────────────────────────────────────────────────────────
    lines += [
        "---",
        "*[MergeGuard](https://github.com/Vjc5h3nt/MergeGaurd) &nbsp;·&nbsp; "
        "AWS Strands SDK + Amazon Bedrock &nbsp;·&nbsp; "
        "🔒 static analysis &nbsp;·&nbsp; ⚡ blast-radius impact scoring*",
    ]

    return "\n".join(lines)


def _patch_description(patch: dict[str, Any], findings: list[dict[str, Any]]) -> str:
    """One-line Changes bullet description."""
    path   = patch.get("path", "")
    status = patch.get("status", "modified")
    added  = patch.get("additions", len(patch.get("added_lines", [])))
    removed = patch.get("deletions", len(patch.get("removed_lines", [])))

    if status == "added":
        return f"New file (+{added} lines)."
    if status == "removed":
        return f"Deleted (−{removed} lines)."
    if status == "renamed":
        return "Renamed."

    file_findings = [f for f in findings if f.get("path") == path]
    if file_findings:
        cats = list(dict.fromkeys(f.get("category", "").split("/")[0] for f in file_findings))
        return f"Modified (+{added} −{removed}). Areas flagged: {', '.join(cats)}."
    return f"Modified (+{added} −{removed} lines)."


def _file_table_description(patch: dict[str, Any], file_findings: list[dict[str, Any]]) -> str:
    """Short description for the Reviewed changes table cell."""
    if not file_findings:
        return "No issues found."
    sevs = [f.get("severity", "INFO") for f in file_findings]
    cats = list(dict.fromkeys(f.get("category", "") for f in file_findings))
    top = ", ".join(f"`{c}`" for c in cats[:3])
    top_sev = next((s for s in ("CRITICAL", "HIGH", "MEDIUM") if s in sevs), sevs[0])
    return f"Highest severity: *{top_sev.lower()}*. Categories: {top}."


def _render_comment(f: dict[str, Any]) -> list[str]:
    """Render a single CRITICAL/HIGH/MEDIUM finding — clean, no alert boxes."""
    sev      = f.get("severity", "INFO")
    cat      = f.get("category", "")
    msg      = f.get("message", "")
    path     = f.get("path", "")
    line_no  = f.get("line", "")
    suggestion = f.get("suggestion", "")
    impact   = float(f.get("impact", 0))
    is_det   = f.get("deterministic", False)

    loc = f"`{path}` line {line_no}" if line_no else (f"`{path}`" if path else "")

    # MergeGuard-specific badges (minimal, only when meaningful)
    meta: list[str] = []
    if is_det:
        meta.append("🔒 confirmed by static analysis")
    if impact >= 1:
        meta.append(f"⚡ blast radius {impact:.1f}/5")
    meta_str = f"\n\n_{' · '.join(meta)}_" if meta else ""

    lines = [
        f"**{loc}** &nbsp; *{sev.lower()}* &nbsp; `{cat}`",
        "",
        msg,
    ]

    if meta_str:
        lines += [meta_str.strip(), ""]

    if suggestion:
        lines += [
            "",
            "<details>",
            "<summary>&#9658; Suggested fix</summary>",
            "",
            f"```\n{suggestion}\n```",
            "",
            "</details>",
        ]

    lines.append("")
    return lines


def _render_low_confidence(f: dict[str, Any]) -> list[str]:
    """Render a LOW/INFO finding — compact, inside the collapsed section."""
    sev     = f.get("severity", "INFO")
    cat     = f.get("category", "")
    msg     = f.get("message", "")
    path    = f.get("path", "")
    line_no = f.get("line", "")
    suggestion = f.get("suggestion", "")

    loc = f"`{path}` line {line_no}" if line_no else (f"`{path}`" if path else "")

    lines = [
        f"**{loc}** &nbsp; *{sev.lower()}* &nbsp; `{cat}`",
        "",
        msg,
        "",
    ]
    if suggestion:
        lines += [
            "<details>",
            "<summary>&#9658; Suggested fix</summary>",
            "",
            f"```\n{suggestion}\n```",
            "",
            "</details>",
            "",
        ]
    lines += ["---", ""]
    return lines


def _count_by_severity(findings: list[dict[str, Any]]) -> dict[str, int]:
    order = ["CRITICAL", "HIGH", "MEDIUM", "LOW", "INFO"]
    counts: dict[str, int] = {k: 0 for k in order}
    for f in findings:
        sev = f.get("severity", "INFO").upper()
        if sev in counts:
            counts[sev] += 1
    return {k: v for k, v in counts.items() if v > 0}


# ---------------------------------------------------------------------------
# Inline comment builder
# ---------------------------------------------------------------------------

def _build_inline_comments(findings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    comments = []
    for f in findings:
        path = f.get("path")
        line = f.get("line")
        if not path or not line:
            continue
        sev = f.get("severity", "?")
        cat = f.get("category", "")
        msg = f.get("message", "")
        suggestion = f.get("suggestion", "")
        body = f"**{sev}** · {cat}\n\n{msg}"
        if suggestion:
            body += f"\n\n**Suggested fix:**\n```\n{suggestion}\n```"
        comments.append({"path": path, "line": int(line), "side": "RIGHT", "body": body})
    return comments


# ---------------------------------------------------------------------------
# Check Run
# ---------------------------------------------------------------------------

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
    gh = get_github_client()
    try:
        gh.create_check_run(
            owner=owner,
            repo=repo,
            name="MergeGuard AI Review",
            head_sha=head_sha,
            status="completed",
            conclusion=conclusion_map.get(risk_bucket, "neutral"),
            title=f"Risk Score: {risk_score}/100 — {risk_bucket}",
            summary=summary[:65535],
        )
    except Exception as exc:
        log.warning("Failed to create check run: %s", exc)
