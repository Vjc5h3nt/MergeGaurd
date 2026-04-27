"""Orchestrator Agent — plans and dispatches all specialist sub-agents."""

from __future__ import annotations

import logging
from typing import Any

from strands import Agent

from mergeguard.agents.architecture import review_architecture
from mergeguard.agents.code_quality import review_code_quality
from mergeguard.agents.regression import detect_regressions
from mergeguard.agents.security import review_security
from mergeguard.integrations.bedrock import build_model
from mergeguard.tools.fetch_pr_diff import fetch_pr_diff
from mergeguard.tools.github_poster import post_github_review
from mergeguard.tools.impact_analyzer import analyze_impact
from mergeguard.tools.risk_scorer import calculate_risk_score

log = logging.getLogger(__name__)

_ORCHESTRATOR_PROMPT = """\
You are MergeGuard — an expert AI code review orchestrator.

Your goal is to produce a thorough, actionable, and precise review of a GitHub Pull Request.

## Workflow

1. Call `fetch_pr_diff` with the owner, repo, and pr_number to retrieve the PR diff and metadata.

2. Based on the changed files and diff size, dispatch specialist agents:
   - Always invoke `review_code_quality` and `review_security`.
   - Invoke `detect_regressions` if any existing functions/classes are modified (not just new files).
     This agent runs deterministic pre-checks (removed symbols, signature changes) BEFORE LLM reasoning
     — always invoke it when there are modified files, not just added ones.
   - Invoke `review_architecture` if the diff adds new imports, changes module structure,
     or restructures packages.

3. Collect all `findings` arrays from specialist results into a single flat list.

4. Call `analyze_impact` with the combined findings list and the patches from step 1.
   This annotates each finding with a blast-radius impact score (0.0–5.0) based on
   how many callers are transitively affected by each changed symbol.

5. Call `calculate_risk_score` with the impact-annotated findings list to get the
   risk score (0–100) and bucket (LOW/MEDIUM/HIGH/BLOCKING).

6. Write a concise 2-3 sentence walkthrough covering:
   - What the PR does (one sentence)
   - Any key concerns with impact context (e.g. "changes to X affect N callers")
   Keep it factual and brief — it appears as the "Walkthrough" section of the review.

7. Call `post_github_review` with owner, repo, pr_number, head_sha, risk_bucket,
   risk_score, summary, findings (impact-annotated), and patches (from step 1).
   Set dry_run=True if instructed.

## Rules
- Be precise. Only report findings with clear evidence from the diff.
- Never hallucinate file paths or line numbers.
- Format suggestions as runnable code snippets where possible.
- Deterministic findings from the regression agent (marked 'deterministic': true) are facts —
  do not remove or downgrade them in your summary.
- If findings list is empty, give an APPROVED review with a positive summary.
- Prominently surface BLOCKING and HIGH severity issues in the summary.
- Always run `analyze_impact` before `calculate_risk_score` — impact scores change the final risk bucket.
"""


def build_orchestrator() -> Agent:
    """Build and return the MergeGuard Orchestrator Strands Agent."""
    model = build_model()
    return Agent(
        model=model,
        system_prompt=_ORCHESTRATOR_PROMPT,
        tools=[
            fetch_pr_diff,
            review_code_quality,
            review_security,
            detect_regressions,
            review_architecture,
            analyze_impact,
            calculate_risk_score,
            post_github_review,
        ],
    )


def review_pull_request(
    owner: str,
    repo: str,
    pr_number: int,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Convenience function: run a full review and return structured results."""
    orchestrator = build_orchestrator()

    prompt = (
        f"Review GitHub PR: owner={owner} repo={repo} pr_number={pr_number} "
        f"dry_run={dry_run}"
    )

    log.info("Starting orchestrated review for %s/%s#%d", owner, repo, pr_number)
    result = orchestrator(prompt)

    return {
        "pr": f"{owner}/{repo}#{pr_number}",
        "result": str(result),
    }
