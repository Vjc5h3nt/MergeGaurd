"""DynamoDB-backed per-installation daily rate limiter.

Uses a single counter row per (installation_id, UTC date) in the shared
`mergeguard-reviews` table. Keys are namespaced with `ratelimit#` to avoid
collision with review locks (`lock#...`) and review records (UUIDs).

The module is fail-open: any infrastructure error results in the review being
allowed through, so DynamoDB outages don't block legitimate PR reviews.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone

log = logging.getLogger(__name__)


def _rate_key(installation_id: int, date_str: str) -> str:
    return f"ratelimit#{installation_id}#{date_str}"


def _today_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _ttl_epoch() -> int:
    """Epoch seconds for tomorrow 00:00 UTC + 86400s (~2 days from now)."""
    now = datetime.now(timezone.utc)
    tomorrow_midnight = (now + timedelta(days=1)).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    return int(tomorrow_midnight.timestamp()) + 86400


def _table():
    import boto3

    table_name = os.getenv("MERGEGUARD_REVIEWS_TABLE", "mergeguard-reviews")
    return boto3.resource(
        "dynamodb", region_name=os.getenv("BEDROCK_REGION", "us-east-1")
    ).Table(table_name)


def check_and_increment(installation_id: int, daily_limit: int = 50) -> tuple[bool, int]:
    """Atomically increment today's review counter for this installation.

    Returns (allowed, current_count):
      - allowed=True if the new count is <= daily_limit
      - allowed=False if already at/over the limit (count is NOT incremented)
      - current_count is the post-increment value (or the current value if rejected)

    Fails open: on any DynamoDB error, returns (True, 0) so infrastructure
    issues don't block legitimate reviews.
    """
    date_str = _today_utc()
    key = _rate_key(installation_id, date_str)

    try:
        from botocore.exceptions import ClientError

        table = _table()
        try:
            resp = table.update_item(
                Key={"review_id": key},
                UpdateExpression="ADD #c :one SET #ttl = :ttl, installation_id = :iid, #d = :date",
                ConditionExpression="attribute_not_exists(#c) OR #c < :limit",
                ExpressionAttributeNames={"#c": "count", "#ttl": "ttl", "#d": "date"},
                ExpressionAttributeValues={
                    ":one": 1,
                    ":limit": daily_limit,
                    ":ttl": _ttl_epoch(),
                    ":iid": installation_id,
                    ":date": date_str,
                },
                ReturnValues="UPDATED_NEW",
            )
            new_count = int(resp.get("Attributes", {}).get("count", 1))
            return True, new_count
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") == "ConditionalCheckFailedException":
                current = get_current_count(installation_id)
                return False, current
            log.warning("Rate limiter DynamoDB error (fail-open): %s", exc)
            return True, 0
    except Exception as exc:
        log.warning("Rate limiter unexpected error (fail-open): %s", exc)
        return True, 0


def get_current_count(installation_id: int) -> int:
    """Return today's count without incrementing. Returns 0 on error or no entry."""
    key = _rate_key(installation_id, _today_utc())
    try:
        table = _table()
        resp = table.get_item(Key={"review_id": key})
        item = resp.get("Item")
        if not item:
            return 0
        return int(item.get("count", 0))
    except Exception as exc:
        log.warning("Rate limiter get_current_count error: %s", exc)
        return 0
