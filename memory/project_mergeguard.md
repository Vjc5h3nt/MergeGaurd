---
name: MergeGuard project context
description: Full current state of MergeGuard — build status, architecture, live deployment, pending work
type: project
---

MergeGuard is an AI PR Code Review Agent shipped as a GitHub Action and AWS Lambda function.

**Stack:** Python 3.12, AWS Strands SDK (`strands-agents`), Amazon Bedrock (`us.anthropic.claude-sonnet-4-5-20250929-v1:0`), Tree-sitter, unidiff, networkx, httpx, pydantic, typer, rich.

**Key constraint:** Python must be 3.12 — `tree-sitter-languages` has no 3.13/3.14 wheel.

**AWS:** Account `381492050009`, SSO-assumed role, default profile. Bedrock region `us-east-1`. SSO credentials are temporary (~8h) — to refresh: `aws sso login`. For permanent GitHub Actions auth, OIDC setup is pending (Phase 4).

---

## Build Status (2026-04-28)

- **Phase 0** ✅ Bootstrap — pyproject.toml, CLI (`mergeguard review`, `smoke-test`), config, CI workflow
- **Phase 1** ✅ Diff MVP — GitHub REST client, diff parser, Strands orchestrator + 4 specialist agents, risk scorer, GitHub poster, action.yml, Dockerfile, Lambda handler
- **Phase 2** ✅ Code Intelligence — tree-sitter loader (Py/TS/JS/Go/Java), symbol extractor, call graph, dependency graph, change classifier, graph cache, ast_query/callgraph_query/dep_lookup Strands tools
- **Phase 3** ✅ Impact + Regression:
  - `tools/impact_analyzer.py` — BFS blast-radius wired into orchestrator; annotates each finding with `impact` score (0–5)
  - `agents/regression.py` — deterministic pre-checks (removed symbols, signature changes, renames) before LLM; `🔒` badge on confirmed findings
  - `agents/architecture.py` — structured import diff extraction; passes new dependency edges to the agent
  - `agents/orchestrator.py` — calls `analyze_impact` after specialists, passes `patches` + `file_summaries` to poster
  - `tools/github_poster.py` — Copilot-style review format (see below)
- **Phase 4** 🔜 OTel tracing, feedback loop, few-shot retrieval, model cost routing

**Tests:** 68 unit tests, all passing.

---

## Live Deployment

- **MergeGuard source repo:** https://github.com/Vjc5h3nt/MergeGaurd (main branch)
- **Test target repo:** https://github.com/Vjc5h3nt/IT-Query-Agent-RAG
- **Active test PR:** https://github.com/Vjc5h3nt/IT-Query-Agent-RAG/pull/1 (branch: `test/mergeguard-review`)
- Workflow file in target repo: `.github/workflows/mergeguard-review.yml`
- AWS secrets set on target repo: `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_SESSION_TOKEN`, `AWS_REGION`

---

## Review Output Format (current — Copilot-inspired)

Structure of the GitHub review comment:
1. **Header** — `🟢 MergeGuard · LOW · 12/100`
2. **Pull request overview** — 2-3 sentence walkthrough (LLM-generated)
3. **Changes** — plain-English bullet per file (LLM-generated via `file_summaries` param)
4. **Reviewed changes** — 50/50 table: file | severity + categories
5. **Comments (N)** — HIGH/MEDIUM grouped by file, each file collapsible open; each comment shows `loc · *severity* · category`, meta badges, suggestion in nested `<details>`
6. **Low confidence comments (N suppressed)** — collapsed root, file children, comment grandchildren (no suggested fix shown)
7. **Footer** — MergeGuard + Bedrock branding

MergeGuard-specific elements: `🔒` (deterministic/static), `⚡ blast radius N/5` (BFS impact).
Inline comments: brief one-liner for all; suggested fix only for HIGH/MEDIUM, not LOW/INFO.

**Known pending UX issue:** Last attempted change (tree-structure for low-confidence + brief inline messages) was reverted at user request — format was worse. Need to revisit low-confidence section structure carefully next session.

---

## Key File Locations

- Orchestrator: `src/mergeguard/agents/orchestrator.py`
- GitHub poster (review format): `src/mergeguard/tools/github_poster.py`
- Regression deterministic checks: `src/mergeguard/agents/regression.py` → `_deterministic_regression_checks()`
- Impact analyzer: `src/mergeguard/tools/impact_analyzer.py`
- GitHub Actions workflow (target repo): cloned at `/var/folders/ty/mgr98n8s5p5ds0ms146m83sr0000gn/T/tmp.3QMYqzzbKa/` (temp dir — re-clone if needed)

**Why:** Keep code inside AWS — no third-party AI services see repo content. SSO credentials rotate; for production use OIDC.
