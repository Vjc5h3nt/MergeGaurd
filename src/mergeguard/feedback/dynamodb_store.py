"""DynamoDB-backed feedback store — used when running in AWS Lambda."""

from __future__ import annotations

import logging
import os
import uuid
from datetime import UTC, datetime
from typing import Any

log = logging.getLogger(__name__)


def _reviews_table():
    import boto3

    dynamodb = boto3.resource("dynamodb", region_name=os.getenv("AWS_REGION", "us-east-1"))
    return dynamodb.Table(os.getenv("MERGEGUARD_REVIEWS_TABLE", "mergeguard-reviews"))


def _findings_table():
    import boto3

    dynamodb = boto3.resource("dynamodb", region_name=os.getenv("AWS_REGION", "us-east-1"))
    return dynamodb.Table(os.getenv("MERGEGUARD_FINDINGS_TABLE", "mergeguard-findings"))


def record_review_dynamo(
    owner: str,
    repo: str,
    pr_number: int,
    github_review_id: int | None,
    risk_bucket: str,
    risk_score: int,
) -> str:
    """Insert a review record. Returns the generated review UUID."""
    review_id = str(uuid.uuid4())
    _reviews_table().put_item(
        Item={
            "review_id": review_id,
            "owner": owner,
            "repo": repo,
            "pr_number": pr_number,
            "github_review_id": github_review_id,
            "risk_bucket": risk_bucket,
            "risk_score": risk_score,
            "reviewed_at": datetime.now(UTC).isoformat(),
        }
    )
    log.debug("Recorded review %s for %s/%s#%d", review_id, owner, repo, pr_number)
    return review_id


def record_findings_dynamo(
    review_id: str,
    findings: list[dict[str, Any]],
    inline_comment_ids: list[int | None],
    owner: str,
    repo: str,
) -> None:
    """Bulk-insert findings aligned by index with inline_comment_ids."""
    table = _findings_table()
    with table.batch_writer() as batch:
        for idx, (f, cid) in enumerate(zip(findings, inline_comment_ids, strict=False)):
            path = f.get("path") or ""
            ext = path.rsplit(".", 1)[-1].lower() if "." in path else ""
            item: dict[str, Any] = {
                "review_id": review_id,
                "finding_idx": idx,
                "severity": f.get("severity", "INFO"),
                "category": f.get("category", ""),
                "message": f.get("message", ""),
                "path": path,
                "file_ext": ext,
                "owner": owner,
                "repo": repo,
                "thumbs_up": 0,
                "thumbs_down": 0,
            }
            if cid is not None:
                item["inline_comment_id"] = cid
            batch.put_item(Item=item)
    log.debug("Recorded %d findings for review %s", len(findings), review_id)


def update_reactions_dynamo(
    review_id: str,
    finding_idx: int,
    thumbs_up: int,
    thumbs_down: int,
) -> None:
    _findings_table().update_item(
        Key={"review_id": review_id, "finding_idx": finding_idx},
        UpdateExpression="SET thumbs_up = :u, thumbs_down = :d",
        ExpressionAttributeValues={":u": thumbs_up, ":d": thumbs_down},
    )


def fetch_examples_dynamo(
    category_prefix: str,
    file_ext: str,
    limit: int = 3,
) -> list[dict[str, Any]]:
    """Scan for positively-rated findings matching category and file extension."""
    from boto3.dynamodb.conditions import Attr

    table = _findings_table()
    resp = table.scan(
        FilterExpression=(Attr("category").begins_with(category_prefix) & Attr("thumbs_up").gte(1)),
        ProjectionExpression=("severity, category, message, file_ext, thumbs_up, thumbs_down"),
    )
    items: list[dict[str, Any]] = resp.get("Items", [])
    # Prefer matching extension, fall back to any
    ext_match = [i for i in items if i.get("file_ext") == file_ext]
    ranked = sorted(
        ext_match or items,
        key=lambda x: (-int(x.get("thumbs_up", 0)), int(x.get("thumbs_down", 0))),
    )
    return ranked[:limit]


def get_all_findings_with_comments() -> list[dict[str, Any]]:
    """Return all findings that have an inline_comment_id (for reaction sync)."""
    from boto3.dynamodb.conditions import Attr

    table = _findings_table()
    resp = table.scan(
        FilterExpression=Attr("inline_comment_id").exists(),
        ProjectionExpression=("review_id, finding_idx, inline_comment_id, #o, repo"),
        ExpressionAttributeNames={"#o": "owner"},
    )
    return resp.get("Items", [])
