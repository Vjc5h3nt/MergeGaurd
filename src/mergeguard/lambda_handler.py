"""AWS Lambda handler — receives GitHub webhook events and triggers the review."""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
from typing import Any

log = logging.getLogger(__name__)
log.setLevel(os.getenv("MERGEGUARD_LOG_LEVEL", "INFO"))


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """Lambda entry point for GitHub webhook events via API Gateway."""
    # Validate HMAC signature
    secret = os.getenv("GITHUB_WEBHOOK_SECRET", "")
    if secret:
        signature = event.get("headers", {}).get("X-Hub-Signature-256", "")
        body = event.get("body", "")
        if not _verify_signature(secret, body, signature):
            log.warning("Invalid webhook signature")
            return {"statusCode": 401, "body": "Unauthorized"}

    body_str = event.get("body", "{}")
    payload: dict[str, Any] = json.loads(body_str) if body_str else {}

    event_type = event.get("headers", {}).get("X-GitHub-Event", "")
    log.info("Received GitHub event: %s", event_type)

    # Only handle pull_request events
    if event_type != "pull_request":
        return {"statusCode": 200, "body": "Skipped non-PR event"}

    action = payload.get("action", "")
    if action not in ("opened", "synchronize", "labeled", "review_requested"):
        return {"statusCode": 200, "body": f"Skipped action: {action}"}

    # Check label trigger
    if action == "labeled":
        label = payload.get("label", {}).get("name", "")
        if label != "ai-code-review":
            return {"statusCode": 200, "body": "Skipped non-review label"}

    pr = payload.get("pull_request", {})
    repo = payload.get("repository", {})

    owner = repo.get("owner", {}).get("login", "")
    repo_name = repo.get("name", "")
    pr_number = pr.get("number", 0)

    if not owner or not repo_name or not pr_number:
        return {"statusCode": 400, "body": "Missing PR fields in payload"}

    # Trigger review
    from mergeguard.agents.orchestrator import review_pull_request

    dry_run = os.getenv("DRY_RUN", "false").lower() == "true"

    try:
        result = review_pull_request(
            owner=owner,
            repo=repo_name,
            pr_number=pr_number,
            dry_run=dry_run,
        )
        return {"statusCode": 200, "body": json.dumps(result)}
    except Exception as exc:
        log.exception("Review failed for %s/%s#%d", owner, repo_name, pr_number)
        return {"statusCode": 500, "body": str(exc)}


def _verify_signature(secret: str, body: str, signature: str) -> bool:
    """Verify GitHub HMAC-SHA256 webhook signature."""
    if not signature.startswith("sha256="):
        return False
    expected = "sha256=" + hmac.new(
        secret.encode(), body.encode(), hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(expected, signature)
