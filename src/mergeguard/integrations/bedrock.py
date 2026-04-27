"""Bedrock model factory for the Strands SDK."""

from __future__ import annotations

import logging

log = logging.getLogger(__name__)


def build_model(model_id: str | None = None, region: str | None = None):  # type: ignore[return]
    """Return a Strands BedrockModel configured for MergeGuard.

    Falls back to config defaults when model_id / region are not supplied.
    """
    from strands.models import BedrockModel

    from mergeguard.config import get_config

    cfg = get_config()
    resolved_model = model_id or cfg.bedrock_model_id
    resolved_region = region or cfg.bedrock_region

    log.debug("Building BedrockModel: model=%s region=%s", resolved_model, resolved_region)

    return BedrockModel(
        model_id=resolved_model,
        region_name=resolved_region,
    )
