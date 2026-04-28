"""Bedrock model factory for the Strands SDK."""

from __future__ import annotations

import json
import logging
import os

log = logging.getLogger(__name__)


def _load_bedrock_credentials() -> dict | None:
    """Load explicit Bedrock credentials from Secrets Manager if configured.

    To rotate keys: update the secret 'mergeguard/bedrock-credentials' with
    new values — no code or Lambda redeployment needed.

    Returns a dict with boto3 session kwargs, or None to use the default
    IAM role credentials.
    """
    secret_name = os.getenv("BEDROCK_CREDS_SECRET", "mergeguard/bedrock-credentials")
    if not secret_name:
        return None

    try:
        import boto3

        sm = boto3.client("secretsmanager", region_name=os.getenv("AWS_REGION", "us-east-1"))
        resp = sm.get_secret_value(SecretId=secret_name)
        creds = json.loads(resp["SecretString"])
        log.debug("Loaded Bedrock credentials from secret: %s", secret_name)
        return {
            "aws_access_key_id": creds["aws_access_key_id"],
            "aws_secret_access_key": creds["aws_secret_access_key"],
            "aws_session_token": creds.get("aws_session_token"),
        }
    except Exception as exc:
        log.warning(
            "Could not load Bedrock credentials from secret '%s': %s — falling back to IAM role",
            secret_name,
            exc,
        )
        return None


def build_model(  # type: ignore[return]
    model_id: str | None = None,
    region: str | None = None,
    tier: str = "capable",
):
    """Return a Strands BedrockModel configured for MergeGuard.

    Args:
        model_id: Explicit model ID — overrides tier and config defaults.
        region: AWS region — overrides config default.
        tier: ``"capable"`` (Sonnet, default) or ``"fast"`` (Haiku).
            Used when model_id is not supplied.
    """
    import boto3
    from strands.models import BedrockModel

    from mergeguard.config import get_config

    cfg = get_config()
    if model_id:
        resolved_model = model_id
    elif tier == "fast":
        resolved_model = cfg.bedrock_model_haiku_id
    else:
        resolved_model = cfg.bedrock_model_id
    resolved_region = region or cfg.bedrock_region

    log.debug(
        "Building BedrockModel: model=%s region=%s tier=%s", resolved_model, resolved_region, tier
    )

    # Use explicit credentials from Secrets Manager if available,
    # otherwise fall back to the Lambda's IAM role.
    creds = _load_bedrock_credentials()
    if creds:
        session = boto3.Session(
            aws_access_key_id=creds["aws_access_key_id"],
            aws_secret_access_key=creds["aws_secret_access_key"],
            aws_session_token=creds.get("aws_session_token"),
            region_name=resolved_region,
        )
        return BedrockModel(model_id=resolved_model, boto_session=session)

    return BedrockModel(model_id=resolved_model, region_name=resolved_region)
