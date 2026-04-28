"""Bedrock model factory for the Strands SDK."""

from __future__ import annotations

import logging

log = logging.getLogger(__name__)


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

    log.debug("Building BedrockModel: model=%s region=%s tier=%s", resolved_model, resolved_region, tier)

    return BedrockModel(
        model_id=resolved_model,
        region_name=resolved_region,
    )
