"""Unit tests for the per-installation rate limiter.

These tests mock boto3 — they verify our logic (key shape, conditional
expression, fail-open behaviour) without hitting DynamoDB.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from botocore.exceptions import ClientError

from mergeguard.limits import rate_limiter


def _mock_table(update_side_effect=None, get_item_return=None):
    """Build a mocked DynamoDB Table with configurable behaviour."""
    table = MagicMock()
    if update_side_effect is not None:
        table.update_item.side_effect = update_side_effect
    else:
        table.update_item.return_value = {"Attributes": {"count": 1}}
    table.get_item.return_value = get_item_return or {"Item": {"count": 0}}
    return table


def test_rate_key_shape():
    assert rate_limiter._rate_key(12345, "2026-04-29") == "ratelimit#12345#2026-04-29"


def test_check_and_increment_allowed_first_time():
    table = _mock_table()
    with patch.object(rate_limiter, "_table", return_value=table):
        allowed, count = rate_limiter.check_and_increment(12345, daily_limit=50)
    assert allowed is True
    assert count == 1
    # Verify it passes the daily limit as :limit in the conditional
    call = table.update_item.call_args
    assert call.kwargs["ExpressionAttributeValues"][":limit"] == 50
    assert call.kwargs["Key"]["review_id"].startswith("ratelimit#12345#")


def test_check_and_increment_rejects_when_condition_fails():
    cond_err = ClientError(
        {"Error": {"Code": "ConditionalCheckFailedException", "Message": "over"}},
        "UpdateItem",
    )
    table = _mock_table(
        update_side_effect=cond_err,
        get_item_return={"Item": {"count": 50}},
    )
    with patch.object(rate_limiter, "_table", return_value=table):
        allowed, count = rate_limiter.check_and_increment(12345, daily_limit=50)
    assert allowed is False
    assert count == 50


def test_fail_open_on_unexpected_client_error():
    other_err = ClientError(
        {"Error": {"Code": "ProvisionedThroughputExceededException", "Message": "x"}},
        "UpdateItem",
    )
    table = _mock_table(update_side_effect=other_err)
    with patch.object(rate_limiter, "_table", return_value=table):
        allowed, count = rate_limiter.check_and_increment(12345)
    assert allowed is True
    assert count == 0


def test_fail_open_on_unexpected_exception():
    table = _mock_table(update_side_effect=RuntimeError("boom"))
    with patch.object(rate_limiter, "_table", return_value=table):
        allowed, count = rate_limiter.check_and_increment(12345)
    assert allowed is True
    assert count == 0


def test_get_current_count_returns_zero_when_missing():
    table = _mock_table(get_item_return={})
    with patch.object(rate_limiter, "_table", return_value=table):
        assert rate_limiter.get_current_count(12345) == 0


def test_get_current_count_reads_count_field():
    table = _mock_table(get_item_return={"Item": {"count": 17}})
    with patch.object(rate_limiter, "_table", return_value=table):
        assert rate_limiter.get_current_count(12345) == 17


def test_get_current_count_fails_open_on_error():
    table = MagicMock()
    table.get_item.side_effect = RuntimeError("dynamo down")
    with patch.object(rate_limiter, "_table", return_value=table):
        assert rate_limiter.get_current_count(12345) == 0
