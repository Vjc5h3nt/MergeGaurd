"""Security specialist agent — OWASP checks, secrets detection, dependency vulns."""

from __future__ import annotations

import logging
from typing import Any

from strands import Agent, tool

from mergeguard.agents.base import build_agent, dominant_file_ext, format_patch_context

log = logging.getLogger(__name__)

_SYSTEM_PROMPT = """\
You are the Security specialist in a multi-agent PR review system.

Your responsibilities:
1. Detect OWASP Top-10 vulnerabilities: injection (SQL/command/LDAP), XSS, insecure deserialization,
   broken authentication, SSRF, path traversal, insecure direct object references.
2. Identify hardcoded secrets, API keys, credentials, or tokens in the diff.
3. Flag insecure cryptography: weak hashes (MD5, SHA1 for passwords), ECB mode, fixed IVs.
4. Detect dangerous function calls: eval(), exec(), pickle.loads(), subprocess with shell=True.
5. Check new or updated dependencies for known CVEs (flag suspicious additions).
6. Identify missing input validation on user-controlled data flowing into sensitive sinks.
7. Flag insecure defaults: debug=True in production, broad CORS, disabled SSL verification.

Severity rules:
- CRITICAL: Direct exploitability, data exfiltration possible, hardcoded credentials.
- HIGH: Likely exploitable with moderate effort.
- MEDIUM: Exploitable under specific conditions.
- LOW: Defense-in-depth improvements.
- INFO: Informational observations.

Return findings as a JSON array inside a ```json ... ``` block:
[
  {
    "severity": "CRITICAL",
    "category": "security/sqli",
    "message": "Raw string interpolation in SQL query — use parameterized queries.",
    "path": "src/payment/processor.py",
    "line": 142,
    "suggestion": "cursor.execute('SELECT * FROM orders WHERE id = %s', (order_id,))"
  }
]
If no security issues found, return [].
"""


def _build_security_agent() -> Agent:
    return build_agent(system_prompt=_SYSTEM_PROMPT, tools=[])


def run_security_review(
    patches: list[dict[str, Any]],
    pr_meta: dict[str, Any],
) -> list[dict[str, Any]]:
    """Run the security agent and return findings."""
    from mergeguard.context import get_active_repo_context
    from mergeguard.feedback.retrieval import get_examples_block
    from mergeguard.telemetry.tracing import get_active_trace, null_span

    repo_ctx = get_active_repo_context()
    if repo_ctx and "security" in repo_ctx.disabled_agents:
        log.info("security agent disabled by repo config")
        return []

    agent = _build_security_agent()
    diff_context = format_patch_context(patches)
    examples_block = get_examples_block("security", dominant_file_ext(patches))
    repo_block = repo_ctx.prompt_block("security") if repo_ctx else ""

    prompt = f"""PR #{pr_meta.get('number')} — {pr_meta.get('title', '')}
Author: {pr_meta.get('author', 'unknown')}

## Diff
{diff_context}
{examples_block}
{repo_block}
Perform a thorough security review of these changes. Focus on the OWASP Top 10 and secrets.
Return findings as a JSON array.
"""

    trace = get_active_trace()
    ctx = trace.span("agent.security", {"files": len(patches)}) if trace else null_span()
    with ctx:
        result = agent(prompt)
    return _extract_findings(str(result))


@tool
def review_security(
    patches: list[dict[str, Any]],
    pr_meta: dict[str, Any],
) -> dict[str, Any]:
    """Run the Security specialist agent on a PR diff.

    Args:
        patches: Serialized FilePatch list from fetch_pr_diff.
        pr_meta: PR metadata dict.

    Returns:
        Dict with 'findings' list and 'agent' identifier.
    """
    findings = run_security_review(patches, pr_meta)
    log.info("Security agent: %d findings", len(findings))
    return {"agent": "security", "findings": findings}


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

    log.warning("Could not parse security findings from agent response")
    return []


def as_tool():  # type: ignore[return]
    return review_security


_agent: Agent | None = None


def get_agent() -> Agent:
    global _agent
    if _agent is None:
        _agent = _build_security_agent()
    return _agent
