"""Optional S3 sync for the feedback SQLite database.

Set ``MERGEGUARD_FEEDBACK_BUCKET`` to enable.  When unset all functions
are no-ops — the DB is ephemeral for that run but the reviewer still works.

S3 key: ``feedback/feedback.db``  (single store shared across all repos,
enabling cross-repo few-shot learning).
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

log = logging.getLogger(__name__)

_S3_KEY = "feedback/feedback.db"


def _bucket() -> str:
    return os.getenv("MERGEGUARD_FEEDBACK_BUCKET", "")


def download_if_exists(db_path: Path) -> None:
    """Pull the feedback DB from S3 before the run.

    Silently skips if ``MERGEGUARD_FEEDBACK_BUCKET`` is not set or the
    object does not exist yet (first run).
    """
    bucket = _bucket()
    if not bucket:
        return
    import boto3
    import botocore.exceptions  # boto3 is already a project dep

    s3 = boto3.client("s3")
    try:
        s3.download_file(bucket, _S3_KEY, str(db_path))
        log.info("Feedback DB downloaded from s3://%s/%s", bucket, _S3_KEY)
    except botocore.exceptions.ClientError as exc:
        code = exc.response["Error"]["Code"]
        if code in ("404", "NoSuchKey"):
            log.info("No existing feedback DB in S3 — starting fresh.")
        else:
            log.warning("S3 download failed (non-fatal): %s", exc)
    except Exception as exc:
        log.warning("S3 download failed (non-fatal): %s", exc)


def upload(db_path: Path) -> None:
    """Push the feedback DB to S3 after the run."""
    bucket = _bucket()
    if not bucket:
        return
    if not db_path.exists():
        log.debug("No feedback DB to upload (file not found).")
        return
    import boto3

    s3 = boto3.client("s3")
    try:
        s3.upload_file(str(db_path), bucket, _S3_KEY)
        log.info("Feedback DB uploaded to s3://%s/%s", bucket, _S3_KEY)
    except Exception as exc:
        log.warning("S3 upload failed (non-fatal): %s", exc)
