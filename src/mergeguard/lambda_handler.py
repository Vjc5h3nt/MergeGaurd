"""AWS Lambda handler — receives GitHub App webhook events and triggers the review."""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
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


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """Lambda entry point — handles GitHub webhooks and EventBridge scheduled sync."""

    # ── EventBridge scheduled feedback sync ───────────────────────────────────
    if event.get("action") == "feedback_sync":
        return _handle_feedback_sync()

    # ── GitHub webhook ─────────────────────────────────────────────────────────
    return _handle_github_webhook(event)


def _handle_github_webhook(event: dict[str, Any]) -> dict[str, Any]:
    """Validate and process a GitHub pull_request webhook event."""
    # API Gateway v2 HTTP API passes headers in event["headers"]
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

    if event_type != "pull_request":
        return {"statusCode": 200, "body": "Skipped non-PR event"}

    payload: dict[str, Any] = json.loads(body_str)
    action = payload.get("action", "")
    if action not in ("opened", "synchronize", "reopened", "labeled", "review_requested"):
        return {"statusCode": 200, "body": f"Skipped action: {action}"}

    if action == "labeled":
        label = payload.get("label", {}).get("name", "")
        if label != "ai-code-review":
            return {"statusCode": 200, "body": "Skipped — not ai-code-review label"}

    pr = payload.get("pull_request", {})
    repo_data = payload.get("repository", {})
    owner = repo_data.get("owner", {}).get("login", "")
    repo_name = repo_data.get("name", "")
    pr_number = pr.get("number", 0)
    installation_id = payload.get("installation", {}).get("id")

    if not owner or not repo_name or not pr_number:
        return {"statusCode": 400, "body": "Missing PR fields in payload"}

    # Get installation token and inject into env so all GitHub clients use the bot identity
    if installation_id:
        from mergeguard.integrations.github_app import get_installation_token
        import mergeguard.integrations.github as gh_module

        token = get_installation_token(
            int(os.environ["GITHUB_APP_ID"]),
            private_key,
            int(installation_id),
        )
        os.environ["GITHUB_TOKEN"] = token
        gh_module._client = None  # reset singleton to pick up new token
        log.info("Using GitHub App token for installation %s", installation_id)
    else:
        log.warning("No installation_id in payload — falling back to GITHUB_TOKEN env var")

    dry_run = os.getenv("DRY_RUN", "false").lower() == "true"

    try:
        from mergeguard.agents.orchestrator import review_pull_request

        result = review_pull_request(
            owner=owner,
            repo=repo_name,
            pr_number=pr_number,
            dry_run=dry_run,
        )
        log.info("Review complete: %s/%s#%d", owner, repo_name, pr_number)
        return {"statusCode": 200, "body": json.dumps({"pr": result["pr"]})}
    except Exception as exc:
        log.exception("Review failed for %s/%s#%d", owner, repo_name, pr_number)
        return {"statusCode": 500, "body": str(exc)}


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

        # Group by (owner, repo) to minimise token fetches
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
