"""Code Quality specialist agent — lint, style, complexity, dead code, duplication."""

from __future__ import annotations

import logging
from typing import Any

from strands import Agent, tool

from mergeguard.agents.base import build_agent, format_patch_context
from mergeguard.integrations.bedrock import build_model

log = logging.getLogger(__name__)

_SYSTEM_PROMPT = """\
You are the Code Quality specialist in a multi-agent PR review system.

Your responsibilities:
1. Identify style and convention violations (naming, formatting, idiomatic patterns).
2. Detect complexity issues: deeply nested logic, long functions, high cyclomatic complexity.
3. Flag dead code, unused imports, unreachable branches.
4. Spot code duplication that should be refactored.
5. Check for missing or misleading docstrings/comments on public APIs.
6. Identify missing or inadequate error handling.

You receive a diff context. For each issue found, return a finding with:
- severity: HIGH | MEDIUM | LOW | INFO
- category: quality/<sub-type>  e.g. quality/complexity, quality/naming, quality/dead-code
- message: concise description of the problem
- path: file path (if applicable)
- line: target line number (if applicable)
- suggestion: a specific fix (optional, include a code snippet when helpful)

Be precise and actionable. Do not flag style issues in files the PR did not touch.
Return findings as a JSON array inside a ```json ... ``` block. If no issues, return [].
"""


def _build_code_quality_agent() -> Agent:
    return build_agent(system_prompt=_SYSTEM_PROMPT, tools=[])


def run_code_quality_review(
    patches: list[dict[str, Any]],
    pr_meta: dict[str, Any],
) -> list[dict[str, Any]]:
    """Run the code quality agent and return a list of findings."""
    agent = _build_code_quality_agent()
    diff_context = format_patch_context(patches)

    prompt = f"""PR #{pr_meta.get('number')} — {pr_meta.get('title', '')}
Author: {pr_meta.get('author', 'unknown')}
Changed files: {pr_meta.get('changed_files', '?')} | +{pr_meta.get('additions', 0)} -{pr_meta.get('deletions', 0)}

## Diff
{diff_context}

Review the above changes for code quality issues. Return findings as a JSON array.
"""

    result = agent(prompt)
    return _extract_findings(str(result))


@tool
def review_code_quality(
    patches: list[dict[str, Any]],
    pr_meta: dict[str, Any],
) -> dict[str, Any]:
    """Run the Code Quality specialist agent on a PR diff.

    Args:
        patches: Serialized FilePatch list from fetch_pr_diff.
        pr_meta: PR metadata dict (number, title, author, additions, deletions).

    Returns:
        Dict with 'findings' list and 'agent' identifier.
    """
    findings = run_code_quality_review(patches, pr_meta)
    log.info("Code Quality agent: %d findings", len(findings))
    return {"agent": "code_quality", "findings": findings}


def _extract_findings(text: str) -> list[dict[str, Any]]:
    """Extract JSON findings array from agent response text."""
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

    # Fallback: try raw JSON array
    match2 = re.search(r"\[.*\]", text, re.DOTALL)
    if match2:
        try:
            result = json.loads(match2.group(0))
            if isinstance(result, list):
                return result
        except json.JSONDecodeError:
            pass

    log.warning("Could not parse findings from agent response")
    return []


# Expose as Strands agent-as-tool
def as_tool():  # type: ignore[return]
    return review_code_quality


# Keep a module-level agent instance for direct reuse
_agent: Agent | None = None


def get_agent() -> Agent:
    global _agent
    if _agent is None:
        _agent = _build_code_quality_agent()
    return _agent
