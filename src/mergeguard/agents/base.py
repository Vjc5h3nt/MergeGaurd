"""Shared helpers for all MergeGuard Strands agents."""

from __future__ import annotations

import logging
from typing import Any

log = logging.getLogger(__name__)


def build_agent(
    system_prompt: str,
    tools: list[Any],
    model_id: str | None = None,
    region: str | None = None,
    tier: str = "capable",
):  # type: ignore[return]
    """Factory: build a Strands Agent with a BedrockModel.

    Args:
        tier: ``"capable"`` (Sonnet) or ``"fast"`` (Haiku).
    """
    from strands import Agent

    from mergeguard.integrations.bedrock import build_model

    model = build_model(model_id=model_id, region=region, tier=tier)
    return Agent(model=model, system_prompt=system_prompt, tools=tools)


def dominant_file_ext(patches: list[dict[str, Any]]) -> str:
    """Return the most common file extension across changed files."""
    from collections import Counter

    exts = [p["path"].rsplit(".", 1)[-1].lower() for p in patches if "." in p.get("path", "")]
    return Counter(exts).most_common(1)[0][0] if exts else ""


def format_patch_context(patches: list[dict[str, Any]], max_files: int = 20) -> str:
    """Render serialized FilePatch dicts into a compact diff context string."""
    lines: list[str] = []
    for p in patches[:max_files]:
        lines.append(f"### {p['path']}")
        if p.get("is_new_file"):
            lines.append("*(new file)*")
        elif p.get("is_deleted_file"):
            lines.append("*(deleted)*")
        elif p.get("is_renamed"):
            lines.append(f"*(renamed from {p['source_path']})*")

        for h in p.get("hunks", []):
            lines.append(
                f"@@ -{h['source_start']},{h['source_length']} "
                f"+{h['target_start']},{h['target_length']} @@"
                + (f" {h['section_header']}" if h.get("section_header") else "")
            )
            for ln, content in h.get("removed", []):
                lines.append(f"- [{ln}] {content.rstrip()}")
            for ln, content in h.get("added", []):
                lines.append(f"+ [{ln}] {content.rstrip()}")
        lines.append("")

    if len(patches) > max_files:
        lines.append(
            f"*… and {len(patches) - max_files} more files (truncated for context budget)*"
        )
    return "\n".join(lines)
