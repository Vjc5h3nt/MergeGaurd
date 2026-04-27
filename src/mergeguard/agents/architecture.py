"""Architecture compliance agent — layer boundary violations, circular deps, design patterns."""

from __future__ import annotations

import logging
from typing import Any

from strands import Agent, tool

from mergeguard.agents.base import build_agent, format_patch_context

log = logging.getLogger(__name__)

_SYSTEM_PROMPT = """\
You are the Architecture Compliance specialist in a multi-agent PR review system.

Your responsibilities:
1. Detect layer boundary violations: e.g. presentation layer importing from data layer directly,
   or a utility module importing from business logic.
2. Identify circular dependencies introduced by the PR.
3. Flag files placed in incorrect modules/packages based on their content.
4. Detect violations of established design patterns: e.g. a service class directly constructing
   repositories instead of using DI, a domain model with HTTP concerns.
5. Identify overly tight coupling: new direct instantiation of concrete classes where
   interfaces/abstractions should be used.
6. Flag new public APIs that don't follow the project's versioning or naming conventions.

You receive the diff and optionally a dependency graph. Reason about the structural impact.

Return findings as a JSON array inside a ```json ... ``` block.
If no architectural issues found, return [].
"""


def _build_architecture_agent() -> Agent:
    return build_agent(system_prompt=_SYSTEM_PROMPT, tools=[])


def run_architecture_review(
    patches: list[dict[str, Any]],
    pr_meta: dict[str, Any],
    dep_graph: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Run the architecture agent and return findings."""
    agent = _build_architecture_agent()
    diff_context = format_patch_context(patches)

    dep_context = ""
    if dep_graph:
        dep_context = f"\n## Dependency Graph\n```json\n{dep_graph}\n```\n"

    prompt = f"""PR #{pr_meta.get('number')} — {pr_meta.get('title', '')}

## Diff
{diff_context}
{dep_context}
Review for architectural violations, layer boundary breaches, and design pattern issues.
Return findings as a JSON array.
"""

    result = agent(prompt)
    return _extract_findings(str(result))


@tool
def review_architecture(
    patches: list[dict[str, Any]],
    pr_meta: dict[str, Any],
    dep_graph: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Run the Architecture Compliance agent on a PR diff.

    Args:
        patches: Serialized FilePatch list from fetch_pr_diff.
        pr_meta: PR metadata dict.
        dep_graph: Optional dependency graph from Code Intelligence Layer.

    Returns:
        Dict with 'findings' list and 'agent' identifier.
    """
    findings = run_architecture_review(patches, pr_meta, dep_graph)
    log.info("Architecture agent: %d findings", len(findings))
    return {"agent": "architecture", "findings": findings}


def _extract_findings(text: str) -> list[dict[str, Any]]:
    import json
    import re

    match = re.search(r"```json\s*(.*?)\s*```", text, re.DOTALL)
    if match:
        try:
            result = json.loads(match.group(1))
            if isinstance(result, list):
                return result
        except json.JSONDecodeError:
            pass

    match2 = re.search(r"\[.*\]", text, re.DOTALL)
    if match2:
        try:
            result = json.loads(match2.group(0))
            if isinstance(result, list):
                return result
        except json.JSONDecodeError:
            pass

    return []


def as_tool():  # type: ignore[return]
    return review_architecture
