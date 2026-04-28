"""AWS Lambda handler — receives GitHub App webhook events and triggers the review."""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import time
from typing import Any

log = logging.getLogger(__name__)
log.setLevel(os.getenv("MERGEGUARD_LOG_LEVEL", "INFO"))

# Cache secrets across warm Lambda invocations
_private_key: str | None = None
_webhook_secret: str | None = None


def _load_secrets() -> tuple[str, str]:
    """Load GitHub App private key and webhook secret (cached after first call)."""
    global _private_key, _webhook_secret
    if _private_key and _webhook_secret:
        return _private_key, _webhook_secret

    from mergeguard.integrations.github_app import _load_private_key, _load_webhook_secret

    _private_key = _load_private_key()
    _webhook_secret = _load_webhook_secret()
    return _private_key, _webhook_secret


# ---------------------------------------------------------------------------
# DynamoDB review lock — prevents concurrent reviews on the same PR
# ---------------------------------------------------------------------------

def _lock_key(owner: str, repo: str, pr_number: int) -> str:
    return f"lock#{owner}/{repo}#{pr_number}"


def _acquire_lock(owner: str, repo: str, pr_number: int) -> bool:
    """Try to acquire an in-progress lock for this PR. Returns True if acquired."""
    import boto3
    from boto3.dynamodb.conditions import Attr

    table_name = os.getenv("MERGEGUARD_REVIEWS_TABLE", "mergeguard-reviews")
    table = boto3.resource("dynamodb", region_name=os.getenv("BEDROCK_REGION", "us-east-1")).Table(table_name)
    ttl = int(time.time()) + 900  # auto-expire after 15 min in case Lambda crashes
    try:
        table.put_item(
            Item={"review_id": _lock_key(owner, repo, pr_number), "status": "in_progress", "ttl": ttl},
            ConditionExpression=Attr("review_id").not_exists(),
        )
        return True
    except Exception:
        return False


def _release_lock(owner: str, repo: str, pr_number: int) -> None:
    import boto3
    table_name = os.getenv("MERGEGUARD_REVIEWS_TABLE", "mergeguard-reviews")
    table = boto3.resource("dynamodb", region_name=os.getenv("BEDROCK_REGION", "us-east-1")).Table(table_name)
    try:
        table.delete_item(Key={"review_id": _lock_key(owner, repo, pr_number)})
    except Exception as exc:
        log.warning("Failed to release lock: %s", exc)


# ---------------------------------------------------------------------------
# GitHub comment helpers
# ---------------------------------------------------------------------------

def _post_comment(owner: str, repo: str, pr_number: int, body: str) -> int | None:
    """Post a comment on the PR and return the comment ID."""
    import httpx
    token = os.environ.get("GITHUB_TOKEN", "")
    resp = httpx.post(
        f"https://api.github.com/repos/{owner}/{repo}/issues/{pr_number}/comments",
        headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"},
        json={"body": body},
        timeout=30,
    )
    if resp.status_code == 201:
        return resp.json().get("id")
    log.warning("Failed to post comment: %s", resp.text[:200])
    return None


def _update_comment(owner: str, repo: str, comment_id: int, body: str) -> None:
    """Edit an existing comment by ID."""
    import httpx
    token = os.environ.get("GITHUB_TOKEN", "")
    httpx.patch(
        f"https://api.github.com/repos/{owner}/{repo}/issues/comments/{comment_id}",
        headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"},
        json={"body": body},
        timeout=30,
    )


# ---------------------------------------------------------------------------
# Lambda entry point
# ---------------------------------------------------------------------------

def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """Lambda entry point — handles GitHub webhooks and EventBridge scheduled sync."""

    # ── EventBridge scheduled feedback sync ───────────────────────────────────
    if event.get("action") == "feedback_sync":
        return _handle_feedback_sync()

    # ── GitHub webhook ─────────────────────────────────────────────────────────
    return _handle_github_webhook(event)


def _handle_github_webhook(event: dict[str, Any]) -> dict[str, Any]:
    """Validate and process a GitHub webhook event."""
    headers = {k.lower(): v for k, v in (event.get("headers") or {}).items()}
    body_str = event.get("body") or "{}"

    # Validate HMAC signature
    private_key, webhook_secret = _load_secrets()
    if webhook_secret:
        signature = headers.get("x-hub-signature-256", "")
        if not _verify_signature(webhook_secret, body_str, signature):
            log.warning("Invalid webhook signature — rejecting request")
            return {"statusCode": 401, "body": "Unauthorized"}

    event_type = headers.get("x-github-event", "")
    log.info("GitHub event: %s", event_type)

    payload: dict[str, Any] = json.loads(body_str)

    if event_type == "issue_comment":
        return _handle_issue_comment(payload, private_key)

    if event_type != "pull_request":
        return {"statusCode": 200, "body": "Skipped non-PR event"}

    action = payload.get("action", "")
    if action not in ("review_requested", "labeled"):
        return {"statusCode": 200, "body": f"Skipped action: {action}"}

    if action == "labeled":
        label = payload.get("label", {}).get("name", "")
        if label != "ai-code-review":
            return {"statusCode": 200, "body": "Skipped — not ai-code-review label"}

    if action == "review_requested":
        requested = payload.get("requested_reviewer", {})
        if requested.get("type") != "Bot" and "mergegaurd" not in requested.get("login", "").lower():
            return {"statusCode": 200, "body": "Skipped — review not requested from mergegaurd-ai"}

    pr = payload.get("pull_request", {})
    repo_data = payload.get("repository", {})
    owner = repo_data.get("owner", {}).get("login", "")
    repo_name = repo_data.get("name", "")
    pr_number = pr.get("number", 0)
    installation_id = payload.get("installation", {}).get("id")

    if not owner or not repo_name or not pr_number:
        return {"statusCode": 400, "body": "Missing PR fields in payload"}

    return _run_review(owner, repo_name, pr_number, installation_id, private_key)


def _handle_issue_comment(payload: dict[str, Any], private_key: str) -> dict[str, Any]:
    """Trigger a review when someone comments /mergeguard review on a PR."""
    comment_body = payload.get("comment", {}).get("body", "").strip()
    first_line = comment_body.splitlines()[0].strip().lower() if comment_body else ""
    if first_line not in ("/mergeguard review", "/mergegaurd review"):
        return {"statusCode": 200, "body": "Skipped — not a /mergeguard review command"}

    # Only works on PRs, not plain issues
    if "pull_request" not in payload.get("issue", {}):
        return {"statusCode": 200, "body": "Skipped — comment is not on a PR"}

    repo_data = payload.get("repository", {})
    owner = repo_data.get("owner", {}).get("login", "")
    repo_name = repo_data.get("name", "")
    pr_number = payload.get("issue", {}).get("number", 0)
    installation_id = payload.get("installation", {}).get("id")

    return _run_review(owner, repo_name, pr_number, installation_id, private_key)


def _run_review(
    owner: str,
    repo: str,
    pr_number: int,
    installation_id: Any,
    private_key: str,
) -> dict[str, Any]:
    """Authenticate, acquire lock, post status, run review, release lock."""

    # ── Auth ──────────────────────────────────────────────────────────────────
    if installation_id:
        from mergeguard.integrations.github_app import get_installation_token
        import mergeguard.integrations.github as gh_module

        token = get_installation_token(
            int(os.environ["GITHUB_APP_ID"]),
            private_key,
            int(installation_id),
        )
        os.environ["GITHUB_TOKEN"] = token
        gh_module._client = None
        log.info("Using GitHub App token for installation %s", installation_id)
    else:
        log.warning("No installation_id — falling back to GITHUB_TOKEN env var")

    # ── Rate limit — reject if installation is over daily quota ──────────────
    if installation_id:
        from mergeguard.limits import check_and_increment

        daily_limit = int(os.getenv("MERGEGUARD_DAILY_LIMIT_PER_INSTALL", "50"))
        allowed, count = check_and_increment(int(installation_id), daily_limit=daily_limit)
        if not allowed:
            msg = (
                f"⏸️ **MergeGuard daily review limit reached** "
                f"({count}/{daily_limit} reviews today for this installation).\n\n"
                "The counter resets at 00:00 UTC. Contact the MergeGuard maintainers "
                "if you need a higher limit."
            )
            _post_comment(owner, repo, pr_number, msg)
            log.warning(
                "Rate limit hit for installation %s: %d/%d",
                installation_id, count, daily_limit,
            )
            return {"statusCode": 429, "body": f"Rate limit: {count}/{daily_limit}"}
        log.info("Rate limit check passed: %d/%d for installation %s",
                 count, daily_limit, installation_id)

    # ── Lock — reject if already running ─────────────────────────────────────
    if not _acquire_lock(owner, repo, pr_number):
        msg = (
            "⏳ **MergeGuard review already in progress** for this PR.\n\n"
            "Please wait for the current review to complete before requesting another."
        )
        _post_comment(owner, repo, pr_number, msg)
        log.info("Review already in progress for %s/%s#%d — rejected", owner, repo, pr_number)
        return {"statusCode": 200, "body": "Review already in progress"}

    # ── Acknowledge — post "running" comment ──────────────────────────────────
    status_comment_id = _post_comment(
        owner, repo, pr_number,
        "🔍 **MergeGuard review started**\n\n"
        "Running code quality, security, regression, and architecture checks...\n\n"
        "_Results will appear as a full review comment when complete (~3–5 min)._"
    )
    log.info("Starting review for %s/%s#%d", owner, repo, pr_number)

    try:
        from mergeguard.agents.orchestrator import review_pull_request
        result = review_pull_request(owner=owner, repo=repo, pr_number=pr_number, dry_run=False)
        log.info("Review complete: %s/%s#%d", owner, repo, pr_number)

        # Update the status comment to show completion
        if status_comment_id:
            _update_comment(owner, repo, status_comment_id,
                "✅ **MergeGuard review complete** — see the review comment above.")

        return {"statusCode": 200, "body": json.dumps({"pr": result["pr"]})}

    except Exception as exc:
        log.exception("Review failed for %s/%s#%d", owner, repo, pr_number)
        if status_comment_id:
            _update_comment(owner, repo, status_comment_id,
                f"❌ **MergeGuard review failed**\n\n```\n{str(exc)[:300]}\n```")
        return {"statusCode": 500, "body": str(exc)}

    finally:
        _release_lock(owner, repo, pr_number)


# ---------------------------------------------------------------------------
# Feedback sync
# ---------------------------------------------------------------------------

def _handle_feedback_sync() -> dict[str, Any]:
    """Poll GitHub reactions on all stored inline comments and update DynamoDB."""
    log.info("Starting feedback sync")
    private_key, _ = _load_secrets()
    app_id = int(os.environ.get("GITHUB_APP_ID", "0"))

    try:
        from mergeguard.feedback.dynamodb_store import (
            get_all_findings_with_comments,
            update_reactions_dynamo,
        )
        from mergeguard.integrations.github import GitHubClient
        from mergeguard.integrations.github_app import (
            get_installation_token,
            get_repo_installation_id,
        )

        findings = get_all_findings_with_comments()
        if not findings:
            log.info("No findings with comments to sync")
            return {"statusCode": 200, "body": "No comments to sync"}

        by_repo: dict[tuple[str, str], list[dict[str, Any]]] = {}
        for f in findings:
            key = (f["owner"], f["repo"])
            by_repo.setdefault(key, []).append(f)

        updated = 0
        for (owner, repo), items in by_repo.items():
            try:
                inst_id = get_repo_installation_id(app_id, private_key, owner, repo)
                token = get_installation_token(app_id, private_key, inst_id)
                gh = GitHubClient(token)
                for item in items:
                    try:
                        reactions = gh.get_reactions(owner, repo, int(item["inline_comment_id"]))
                        thumbs_up = sum(1 for r in reactions if r.get("content") == "+1")
                        thumbs_down = sum(1 for r in reactions if r.get("content") == "-1")
                        update_reactions_dynamo(
                            item["review_id"],
                            int(item["finding_idx"]),
                            thumbs_up,
                            thumbs_down,
                        )
                        updated += 1
                    except Exception as exc:
                        log.warning("Reaction fetch failed for comment %s: %s", item["inline_comment_id"], exc)
            except Exception as exc:
                log.warning("Skipped %s/%s: %s", owner, repo, exc)

        log.info("Feedback sync complete: %d updated", updated)
        return {"statusCode": 200, "body": json.dumps({"updated": updated})}

    except Exception as exc:
        log.exception("Feedback sync failed")
        return {"statusCode": 500, "body": str(exc)}


def _verify_signature(secret: str, body: str, signature: str) -> bool:
    if not signature.startswith("sha256="):
        return False
    expected = "sha256=" + hmac.new(
        secret.encode(), body.encode(), hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(expected, signature)
