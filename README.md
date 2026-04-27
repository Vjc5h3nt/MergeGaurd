# MergeGuard

> AI PR Code Review Agent — powered by AWS Strands SDK + Amazon Bedrock

MergeGuard autonomously reviews GitHub Pull Requests: it fetches the diff, parses ASTs, builds call/dependency graphs, runs specialist AI agents (Code Quality, Security, Regression, Architecture), scores risk 0–100, and posts a structured review comment directly on the PR — all inside AWS, with no third-party AI services seeing your code.

---

## Architecture

```
GitHub PR Event
    → GitHub Actions workflow / AWS Lambda webhook
    → Diff Processor (unidiff)
    → Code Intelligence Layer (Tree-sitter AST + call/dep graphs)
    → Change Classifier (signature | logic | refactor | config | test | docs)
    → Impact Analyzer (BFS blast-radius on call graph)
    → Strands Orchestrator Agent
        ├── Code Quality Agent
        ├── Security Agent
        ├── Regression Agent  ← deterministic pre-checks + LLM
        └── Architecture Agent  ← import diff extraction
    → Risk Scorer (0–100, weighted dimensions)
    → GitHub Review Poster
        ├── Summary comment (Copilot-style: overview + changes + reviewed table + comments)
        ├── Inline comments per finding (HIGH/MEDIUM with fix suggestions)
        └── Check Run (branch protection gate)
```

---

## Quick Start

### Local

```bash
# Python 3.12 required
python3.12 -m venv .venv
pip install uv && uv pip install -e ".[dev]"

cp .env.example .env
# fill in GITHUB_TOKEN + AWS credentials (see .env.example)

# smoke test Bedrock connectivity
mergeguard smoke-test

# review a PR (dry run — prints without posting)
mergeguard review --pr owner/repo#123 --dry-run

# review and post live
mergeguard review --pr https://github.com/owner/repo/pull/5
```

### GitHub Actions

Add `.github/workflows/mergeguard-review.yml` to any repo:

```yaml
name: MergeGuard AI Review

on:
  pull_request:
    types: [opened, synchronize, reopened]

jobs:
  review:
    runs-on: ubuntu-latest
    permissions:
      contents: read
      pull-requests: write
      checks: write
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - run: pip install uv && uv pip install --system "mergeguard @ git+https://github.com/Vjc5h3nt/MergeGaurd.git@main"
      - name: Run MergeGuard Review
        env:
          GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}
          AWS_ACCESS_KEY_ID: ${{ secrets.AWS_ACCESS_KEY_ID }}
          AWS_SECRET_ACCESS_KEY: ${{ secrets.AWS_SECRET_ACCESS_KEY }}
          AWS_SESSION_TOKEN: ${{ secrets.AWS_SESSION_TOKEN }}
          BEDROCK_MODEL_ID: us.anthropic.claude-sonnet-4-5-20250929-v1:0
        run: mergeguard review --pr "${{ github.event.pull_request.html_url }}"
```

**Required GitHub secrets:** `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_SESSION_TOKEN` (or configure OIDC for permanent credentials — see below).

### AWS OIDC (permanent credentials — recommended for production)

Replace the static key secrets with an OIDC role:

```yaml
      - uses: aws-actions/configure-aws-credentials@v4
        with:
          role-to-assume: ${{ secrets.AWS_OIDC_ROLE_ARN }}
          aws-region: us-east-1
```

The role needs `bedrock:InvokeModel` on the Claude model ARN.

### Per-Repo Configuration

Create `.github/ai-reviewer.yml` in any reviewed repo to customise behaviour:

```yaml
trigger:
  on_review_request: true
  on_label: ai-code-review

analysis:
  risk_threshold_block: 75
  risk_threshold_warn: 50
  check_security: true
  check_test_coverage: true
  check_breaking_changes: true

output:
  post_inline_comments: true
  auto_approve_below_risk: 20
```

---

## Project Structure

```
src/mergeguard/
├── cli.py                    # mergeguard review / smoke-test
├── config.py                 # env + .github/ai-reviewer.yml loader
├── lambda_handler.py         # AWS Lambda webhook entry point
├── diff/
│   ├── parser.py             # unidiff → FilePatch objects
│   └── hunk_mapper.py        # hunk → pre/post line ranges
├── intelligence/
│   ├── tree_sitter_loader.py # Language registry (Py/TS/JS/Go/Java)
│   ├── symbol_extractor.py   # AST → Symbol objects with signature hashes
│   ├── call_graph_builder.py # intra-file call edges + cross-file via import map
│   ├── dependency_graph.py   # import edges per language
│   ├── change_classifier.py  # signature|logic|refactor|config|test|docs
│   └── cache.py              # (repo, sha) → symbol graph file-system cache
├── scoring/
│   ├── severity.py           # CRITICAL/HIGH/MEDIUM/LOW/INFO model
│   ├── impact.py             # BFS blast-radius scorer (0–5 scale)
│   └── pr_score.py           # PR-level weighted risk aggregation + markdown table
├── agents/
│   ├── orchestrator.py       # Strands Orchestrator — dispatches specialists
│   ├── code_quality.py       # lint, complexity, dead code, duplication
│   ├── security.py           # OWASP, secrets, dependency vulns
│   ├── regression.py         # deterministic pre-checks + LLM behavioral analysis
│   └── architecture.py       # layer violations, circular deps, import diff
├── tools/                    # Strands @tool functions
│   ├── fetch_pr_diff.py      # GitHub PR diff + metadata
│   ├── impact_analyzer.py    # BFS blast-radius annotation on findings
│   ├── ast_query.py          # symbol graph queries
│   ├── callgraph_query.py    # call graph BFS lookup
│   ├── dep_lookup.py         # dependency graph + circular dep detection
│   ├── risk_scorer.py        # weighted 0–100 risk score
│   └── github_poster.py      # review comment + inline comments + Check Run
├── integrations/
│   ├── github.py             # REST client with ETag caching + rate-limit handling
│   └── bedrock.py            # Strands BedrockModel factory
└── telemetry/
    └── tracing.py            # OTel tracing via Strands hooks
```

---

## Review Output Format

The review comment follows a **Copilot-inspired structure** with MergeGuard's own additions:

```
## 🟢 MergeGuard · LOW · 12/100

**Pull request overview**
Brief walkthrough of what the PR does and key concerns.

**Changes**
- Introduces a TTL-based in-memory cache with `get()`, `set()`, and `invalidate()`.
- Adds a `GET /metrics` endpoint returning cache stats and vector store counts.

**Reviewed changes**
MergeGuard reviewed 4 files and generated 9 comments. Looks good — low risk.

| File                   | Description                                          |
| :---                   | :---                                                 |
| `backend/app/cache.py` | 7 issues · high · `quality/thread-safety`, `security/...` |

**Comments (9)**
  backend/app/cache.py — 7 issues   [expandable]
    line 5 · high · quality/thread-safety — Global `_store` is not thread-safe.
      🔒 confirmed by static analysis · ⚡ blast radius 1.2/5
      [Suggested fix — collapsible]

  Low confidence comments — 10 suppressed   [collapsed]
    backend/app/cache.py — 3 issues   [collapsed]
      line 18 · low · quality/error-handling
```

**MergeGuard-specific elements:**
- `🔒` — finding confirmed by deterministic static analysis (not LLM guess)
- `⚡ blast radius N/5` — how many callers are transitively affected
- HIGH/MEDIUM shown expanded; LOW/INFO collapsed and grouped by file
- Inline comments on code lines: brief one-liner only; fix suggestions for HIGH/MEDIUM only

---

## Risk Score

| Dimension | Weight |
|-----------|--------|
| Security | 30% |
| Code Complexity | 20% |
| Test Coverage | 20% |
| Architecture | 15% |
| Breaking Changes | 15% |

| Bucket | Score | Review event |
|--------|-------|-------------|
| LOW | 0–24 | Comment |
| MEDIUM | 25–49 | Comment |
| HIGH | 50–74 | Request changes |
| BLOCKING | 75–100 | Request changes + Check Run fails |

---

## Phased Roadmap

- **Phase 0** ✅ Bootstrap — scaffold, deps, CLI, CI workflow
- **Phase 1** ✅ Diff MVP — GitHub client, Strands orchestrator + 4 specialist agents, GitHub poster, Action/Dockerfile, Lambda handler
- **Phase 2** ✅ Code Intelligence — Tree-sitter AST (Py/TS/JS/Go/Java), symbol extractor, call graph, dependency graph, change classifier, graph cache
- **Phase 3** ✅ Impact + Regression — BFS blast-radius wired into orchestrator, deterministic regression pre-checks (removed symbols, signature changes, renames), architecture agent with import diff extraction, richer review rendering
- **Phase 4** 🔜 Scale + Learning — OTel tracing, 👍/👎 feedback capture, few-shot retrieval, model cost routing (Haiku for triage)

---

## Requirements

- Python 3.12 (`tree-sitter-languages` has no 3.13+ wheel)
- AWS credentials with Bedrock access — model: `us.anthropic.claude-sonnet-4-5-20250929-v1:0`
- GitHub token: `pull_requests: write`, `contents: read`, `checks: write`

---

## Live Deployment

| Resource | URL |
|----------|-----|
| MergeGuard source | https://github.com/Vjc5h3nt/MergeGaurd |
| Test repo (reviews active) | https://github.com/Vjc5h3nt/IT-Query-Agent-RAG |
| Active test PR | https://github.com/Vjc5h3nt/IT-Query-Agent-RAG/pull/1 |
