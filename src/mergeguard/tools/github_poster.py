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
    "HIGH": "Changes requested — resolve **HIGH** severity issues before merging.",
    "MEDIUM": "Review needed — consider addressing **MEDIUM** issues.",
    "LOW": "Looks good — low risk.",
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
    file_summaries: list[dict[str, Any]] | None = None,
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
        patches: Optional serialized FilePatch list from fetch_pr_diff.
        file_summaries: Optional list of {path, description} dicts with plain-English
            per-file change descriptions (e.g. "Introduces TTL-based cache with namespace support.").
            When provided, these replace the auto-generated Changes bullets.
        dry_run: If True, format and return the review body without posting.

    Returns:
        Dict with 'posted' bool, 'review_id' (if posted), 'body' (markdown).
    """
    body = _render_review_body(
        risk_score, risk_bucket, summary, findings, patches or [], file_summaries or []
    )

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

    # Inline comments posted individually — a bad line number won't block the rest.
    # IDs are tracked aligned by findings index for the feedback store.
    inline_comment_ids: list[int | None] = [None] * len(findings)
    for i, f in enumerate(findings):
        path = f.get("path")
        line = f.get("line")
        if not path or not line:
            continue
        try:
            resp = gh.create_review_comment(
                owner=owner,
                repo=repo,
                number=pr_number,
                commit_id=head_sha,
                path=path,
                line=int(line),
                side="RIGHT",
                body=_build_comment_body(f),
            )
            inline_comment_ids[i] = resp.get("id")
        except Exception as exc:
            log.warning("Skipped inline comment on %s:%s — %s", path, line, exc)

    _post_check_run(owner, repo, head_sha, risk_bucket, risk_score, summary)
    _record_to_store(
        owner=owner,
        repo=repo,
        pr_number=pr_number,
        review_id=review_id,
        risk_bucket=risk_bucket,
        risk_score=risk_score,
        findings=findings,
        inline_comment_ids=inline_comment_ids,
    )

    return {
        "posted": True,
        "review_id": review_id,
        "inline_comment_ids": inline_comment_ids,
        "body": body,
    }


# ---------------------------------------------------------------------------
# Renderer
# ---------------------------------------------------------------------------


def _render_review_body(
    risk_score: int,
    risk_bucket: str,
    summary: str,
    findings: list[dict[str, Any]],
    patches: list[dict[str, Any]],
    file_summaries: list[dict[str, Any]],
) -> str:
    emoji = _BUCKET_EMOJI.get(risk_bucket, "⚪")
    n_files = len(patches)

    sorted_findings = sorted(
        findings,
        key=lambda f: (_SEV_ORDER.get(f.get("severity", "INFO"), 5), -float(f.get("impact", 0))),
    )
    main_findings = [
        f for f in sorted_findings if f.get("severity") in ("CRITICAL", "HIGH", "MEDIUM")
    ]
    low_findings = [f for f in sorted_findings if f.get("severity") in ("LOW", "INFO")]
    n_total = len(sorted_findings)

    # Build a path→description lookup from file_summaries
    fs_map: dict[str, str] = {
        s["path"]: s["description"] for s in file_summaries if "path" in s and "description" in s
    }

    lines: list[str] = []

    # ── Header ───────────────────────────────────────────────────────────────
    lines += [
        f"## {emoji} MergeGuard &nbsp;·&nbsp; {risk_bucket} &nbsp;·&nbsp; `{risk_score}/100`",
        "",
    ]

    # ── Pull request overview ─────────────────────────────────────────────────
    lines += ["**Pull request overview**", "", summary, ""]

    # ── Changes — plain-English bullet per file ───────────────────────────────
    if patches:
        lines += ["**Changes**", ""]
        for p in patches:
            path = p.get("path", "")
            status = p.get("status", "modified")
            if path in fs_map:
                desc = fs_map[path]
            else:
                desc = _infer_change_description(path, status, sorted_findings)
            lines.append(f"- {desc}")
        lines += [""]

    # ── Reviewed changes table ────────────────────────────────────────────────
    verdict_line = _VERDICT.get(risk_bucket, "Review complete.")
    lines += [
        "**Reviewed changes**",
        "",
        f"MergeGuard reviewed {n_files} file{'s' if n_files != 1 else ''} "
        f"and generated {n_total} comment{'s' if n_total != 1 else ''}. "
        f"{verdict_line}",
        "",
    ]

    if patches:
        # Two even columns — File on left, Description on right
        lines += [
            "| File | Description |",
            "| :--- | :--- |",
        ]
        for p in patches:
            path = p.get("path", "")
            status = p.get("status", "modified")
            file_issues = [f for f in sorted_findings if f.get("path") == path]
            lines.append(f"| `{path}` | {_table_cell(path, status, file_issues)} |")
        lines += [""]

    # ── Comments grouped by file ──────────────────────────────────────────────
    if main_findings:
        lines += [f"**Comments ({len(main_findings)})**", ""]
        by_file: dict[str, list[dict[str, Any]]] = {}
        for f in main_findings:
            by_file.setdefault(f.get("path", "—"), []).append(f)

        for file_path, file_findings in by_file.items():
            n = len(file_findings)
            lines += [
                "<details open>",
                f"<summary>&bull; <code>{file_path}</code>"
                f" &nbsp; <em>{n} issue{'s' if n != 1 else ''}</em></summary>",
                "",
            ]
            for i, f in enumerate(file_findings):
                lines += _render_comment(f)
                if i < len(file_findings) - 1:
                    lines += ["---", ""]
            lines += ["</details>", ""]

    # ── Low-confidence — collapsed by default ─────────────────────────────────
    if low_findings:
        lines += [
            "<details>",
            f"<summary>&bull; Low confidence comments &nbsp;"
            f"<em>{len(low_findings)} suppressed</em></summary>",
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


def _infer_change_description(path: str, status: str, findings: list[dict[str, Any]]) -> str:
    """Fallback plain-English description when no file_summary is provided."""
    name = path.split("/")[-1]
    if status == "added":
        return f"Introduces `{name}`."
    if status == "removed":
        return f"Removes `{name}`."
    if status == "renamed":
        return f"Renames `{name}`."
    file_findings = [f for f in findings if f.get("path") == path]
    if file_findings:
        cats = list(dict.fromkeys(f.get("category", "").split("/")[-1] for f in file_findings))
        return f"Updates `{name}`. Areas reviewed: {', '.join(cats[:3])}."
    return f"Updates `{name}`."


def _table_cell(path: str, status: str, file_findings: list[dict[str, Any]]) -> str:
    """Content for the Reviewed changes table description cell."""
    if status == "removed":
        return "Deleted."
    if status == "renamed":
        return "Renamed."
    if not file_findings:
        return "No issues found."
    sevs = [f.get("severity", "INFO") for f in file_findings]
    top_sev = next((s for s in ("CRITICAL", "HIGH", "MEDIUM", "LOW") if s in sevs), "INFO")
    cats = list(dict.fromkeys(f.get("category", "") for f in file_findings))
    top_cats = ", ".join(f"`{c}`" for c in cats[:2])
    n = len(file_findings)
    more = f" +{len(cats) - 2} more" if len(cats) > 2 else ""
    return f"{n} issue{'s' if n != 1 else ''} &nbsp;·&nbsp; *{top_sev.lower()}* &nbsp;·&nbsp; {top_cats}{more}"


def _render_comment(f: dict[str, Any]) -> list[str]:
    """Render a single CRITICAL/HIGH/MEDIUM finding."""
    sev = f.get("severity", "INFO")
    cat = f.get("category", "")
    msg = f.get("message", "")
    path = f.get("path", "")
    line_no = f.get("line", "")
    suggestion = f.get("suggestion", "")
    impact = float(f.get("impact", 0))
    is_det = f.get("deterministic", False)

    loc = f"`{path}` line {line_no}" if line_no else (f"`{path}`" if path else "")

    meta: list[str] = []
    if is_det:
        meta.append("🔒 confirmed by static analysis")
    if impact >= 1:
        meta.append(f"⚡ blast radius {impact:.1f}/5")

    lines = [
        f"**{loc}** &nbsp; *{sev.lower()}* &nbsp; `{cat}`",
        "",
        msg,
    ]
    if meta:
        lines += ["", f"*{' &nbsp;·&nbsp; '.join(meta)}*"]

    if suggestion:
        # Indented child details inside the parent file details
        lines += [
            "",
            "<details>",
            "<summary>&nbsp;&nbsp;&nbsp;&bull; Suggested fix</summary>",
            "",
            f"```\n{suggestion}\n```",
            "",
            "</details>",
        ]

    lines.append("")
    return lines


def _render_low_confidence(f: dict[str, Any]) -> list[str]:
    """Render a LOW/INFO finding inside the collapsed low-confidence section."""
    sev = f.get("severity", "INFO")
    cat = f.get("category", "")
    msg = f.get("message", "")
    path = f.get("path", "")
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
            "<summary>&nbsp;&nbsp;&nbsp;&bull; Suggested fix</summary>",
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
# Inline comment body builder
# ---------------------------------------------------------------------------


def _build_comment_body(f: dict[str, Any]) -> str:
    """Build the body string for a single inline PR review comment."""
    sev = f.get("severity", "?")
    cat = f.get("category", "")
    msg = f.get("message", "")
    suggestion = f.get("suggestion", "")
    body = f"**{sev}** · {cat}\n\n{msg}"
    if suggestion:
        body += f"\n\n**Suggested fix:**\n```\n{suggestion}\n```"
    return body


# ---------------------------------------------------------------------------
# Feedback store write
# ---------------------------------------------------------------------------


def _record_to_store(
    owner: str,
    repo: str,
    pr_number: int,
    review_id: int | None,
    risk_bucket: str,
    risk_score: int,
    findings: list[dict[str, Any]],
    inline_comment_ids: list[int | None],
) -> None:
    """Write review + findings to the feedback store (non-fatal). Auto-routes to DynamoDB in Lambda."""
    import os

    try:
        if os.getenv("MERGEGUARD_STORE_BACKEND") == "dynamodb":
            from mergeguard.feedback.dynamodb_store import (
                record_findings_dynamo,
                record_review_dynamo,
            )

            rid = record_review_dynamo(owner, repo, pr_number, review_id, risk_bucket, risk_score)
            record_findings_dynamo(rid, findings, inline_comment_ids, owner, repo)
            log.debug("Feedback recorded to DynamoDB: %s", rid)
        else:
            from mergeguard.feedback.s3_sync import download_if_exists, upload
            from mergeguard.feedback.store import (
                get_db_path,
                open_db,
                record_findings,
                record_review,
            )

            db_path = get_db_path()
            download_if_exists(db_path)
            conn = open_db(db_path)
            fk = record_review(conn, owner, repo, pr_number, review_id, risk_bucket, risk_score)
            record_findings(conn, fk, findings, inline_comment_ids)
            conn.close()
            upload(db_path)
            log.debug("Feedback recorded to SQLite: review_fk=%d", fk)
    except Exception as exc:
        log.warning("Feedback store write failed (non-fatal): %s", exc)


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
