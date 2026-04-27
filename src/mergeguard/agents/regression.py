"""Regression detection agent — behavioral diff analysis + test coverage delta."""

from __future__ import annotations

import logging
from typing import Any

from strands import Agent, tool

from mergeguard.agents.base import build_agent, format_patch_context

log = logging.getLogger(__name__)

_SYSTEM_PROMPT = """\
You are the Regression Detection specialist in a multi-agent PR review system.

Your responsibilities:
1. Identify changed functions/methods and reason about whether their observable behavior
   could change for existing callers.
2. Detect renamed or removed public symbols (functions, classes, constants) that are used
   elsewhere — this is a definite breaking change.
3. Flag signature changes (added/removed/reordered parameters, changed return types).
4. Identify logic changes that could affect control flow, exception propagation, or side effects.
5. Detect test coverage regressions: new logic paths added without corresponding tests.
6. Flag removed tests or disabled assertions.

IMPORTANT: Never flag a regression without a concrete, specific reason anchored in the diff.
Prefer false negatives over false positives — only report when confident.

Severity rules:
- HIGH: Public API removed/renamed with active callers, or core logic fundamentally changed.
- MEDIUM: Behavioral change in internal function with many callers, or test coverage dropped.
- LOW: Minor behavioral nuance that existing tests might not catch.
- INFO: Observation (e.g., test added but doesn't cover the new branch).

Return findings as a JSON array inside a ```json ... ``` block. If no regressions, return [].
"""


def _build_regression_agent() -> Agent:
    return build_agent(system_prompt=_SYSTEM_PROMPT, tools=[])


def run_regression_review(
    patches: list[dict[str, Any]],
    pr_meta: dict[str, Any],
    symbol_graph: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Run the regression agent and return findings."""
    agent = _build_regression_agent()
    diff_context = format_patch_context(patches)

    symbol_context = ""
    if symbol_graph:
        symbol_context = f"\n## Symbol Graph (callers/callees)\n```json\n{symbol_graph}\n```\n"

    prompt = f"""PR #{pr_meta.get('number')} — {pr_meta.get('title', '')}

## Diff
{diff_context}
{symbol_context}
Analyze for regression risks. Only report issues with concrete evidence from the diff.
Return findings as a JSON array.
"""

    result = agent(prompt)
    return _extract_findings(str(result))


@tool
def detect_regressions(
    patches: list[dict[str, Any]],
    pr_meta: dict[str, Any],
    symbol_graph: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Run the Regression Detection agent on a PR diff.

    Args:
        patches: Serialized FilePatch list from fetch_pr_diff.
        pr_meta: PR metadata dict.
        symbol_graph: Optional call graph data from the Code Intelligence Layer.

    Returns:
        Dict with 'findings' list and 'agent' identifier.
    """
    findings = run_regression_review(patches, pr_meta, symbol_graph)
    log.info("Regression agent: %d findings", len(findings))
    return {"agent": "regression", "findings": findings}


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
    return detect_regressions
