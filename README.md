# MergeGuard

> AI PR Code Review Agent — powered by AWS Strands SDK + Amazon Bedrock

MergeGuard autonomously reviews GitHub Pull Requests: it fetches the diff, parses ASTs, builds call/dependency graphs, runs specialist AI agents (Code Quality, Security, Regression, Architecture), scores risk 0–100, and posts a structured review comment directly on the PR.

---

## Architecture

```
GitHub PR Event
    → GitHub Action / Lambda webhook
    → Diff Processor (unidiff)
    → Code Intelligence Layer (Tree-sitter AST + call/dep graphs)
    → Change Classifier (signature | logic | refactor | config | test)
    → Strands Orchestrator Agent
        ├── Code Quality Agent
        ├── Security Agent
        ├── Regression Agent
        └── Architecture Agent
    → Risk Scorer (0–100, bucket: LOW/MEDIUM/HIGH/BLOCKING)
    → GitHub Review Poster (inline comments + summary + Check Run)
```

---

## Quick Start

### Local Development

```bash
# Python 3.12 required (tree-sitter-languages constraint)
python3.12 -m venv .venv
pip install uv
uv pip install -e ".[dev]"

# Set credentials
cp .env.example .env
# edit .env with GITHUB_TOKEN + AWS credentials

# Review a PR
mergeguard review --pr owner/repo#123 --dry-run

# Run tests
pytest tests/unit/
```

### GitHub Action

Add to `.github/workflows/review.yml`:

```yaml
on:
  pull_request:
    types: [opened, synchronize, review_requested]

jobs:
  ai-review:
    runs-on: ubuntu-latest
    permissions:
      pull-requests: write
      id-token: write  # for OIDC Bedrock auth
    steps:
      - uses: actions/checkout@v4
      - name: Configure AWS credentials
        uses: aws-actions/configure-aws-credentials@v4
        with:
          role-to-assume: ${{ secrets.AWS_OIDC_ROLE_ARN }}
          aws-region: us-east-1
      - uses: ./  # or: your-org/mergeguard@v1
        with:
          risk-threshold-block: "75"
```

### Per-Repo Configuration

Create `.github/ai-reviewer.yml`:

```yaml
trigger:
  on_review_request: true
  on_label: ai-code-review

analysis:
  risk_threshold_block: 75
  risk_threshold_warn: 50
  check_security: true
  check_test_coverage: true

output:
  post_inline_comments: true
  auto_approve_below_risk: 20
```

---

## Project Structure

```
src/mergeguard/
├── cli.py                  # mergeguard review / smoke-test
├── config.py               # env + .github/ai-reviewer.yml loader
├── lambda_handler.py       # AWS Lambda entry point
├── diff/
│   ├── parser.py           # unidiff → FilePatch objects
│   └── hunk_mapper.py      # hunk → line ranges
├── intelligence/
│   ├── tree_sitter_loader.py   # Language registry (Py/TS/JS/Go/Java)
│   ├── symbol_extractor.py     # AST → Symbol objects
│   ├── call_graph_builder.py   # intra-file call edges
│   ├── dependency_graph.py     # import edges
│   ├── change_classifier.py    # signature|logic|refactor|config
│   └── cache.py                # (repo, sha) → symbol graph cache
├── scoring/
│   ├── severity.py         # 0–5 severity model
│   ├── impact.py           # BFS blast-radius scorer
│   └── pr_score.py         # PR-level risk aggregation
├── agents/
│   ├── orchestrator.py     # Strands Orchestrator Agent
│   ├── code_quality.py     # lint, complexity, dead code
│   ├── security.py         # OWASP, secrets, CVEs
│   ├── regression.py       # behavioral diff, test coverage delta
│   └── architecture.py     # layer boundaries, circular deps
├── tools/                  # Strands @tool functions
│   ├── fetch_pr_diff.py
│   ├── ast_query.py
│   ├── callgraph_query.py
│   ├── dep_lookup.py
│   ├── risk_scorer.py
│   └── github_poster.py
├── integrations/
│   ├── github.py           # REST client with ETag caching
│   └── bedrock.py          # BedrockModel factory
└── telemetry/
    └── tracing.py          # OTel / ReviewTrace
```

---

## Risk Score

| Dimension | Weight | Max |
|-----------|--------|-----|
| Security Findings | 30% | 30 |
| Code Complexity | 20% | 20 |
| Test Coverage Delta | 20% | 20 |
| Architectural Violations | 15% | 15 |
| Breaking Change Risk | 15% | 15 |

| Bucket | Score Range | GitHub Action |
|--------|------------|---------------|
| LOW | 0–24 | Approve |
| MEDIUM | 25–49 | Comment |
| HIGH | 50–74 | Request Changes |
| BLOCKING | 75–100 | Block merge (Check Run fails) |

---

## Sample Review Output

```
## 🟠 AI Code Review — Risk Score: 62/100

### Summary
This PR modifies the payment processing module and adds a new webhook handler.
3 issues found: 1 HIGH, 1 MEDIUM, 1 LOW.

### Findings

| Severity | Category | File | Message |
|----------|----------|------|---------|
| **HIGH** | security/sqli | `src/payment/processor.py:L142` | Raw string interpolation in SQL query |
| **MEDIUM** | test/coverage | `src/webhook/handler.py` | New `WebhookHandler.process()` has 0 test coverage |
| **LOW** | quality/complexity | `src/payment/validator.py:L23` | Cyclomatic complexity: 4 → 11 |

### Verdict: 🟠 CHANGES REQUESTED — Resolve HIGH severity issues before merging.
```

---

## Phased Roadmap

- **Phase 0** ✅ Bootstrap — scaffold, deps, CLI, CI
- **Phase 1** ✅ Diff MVP — GitHub I/O, Strands agents, Action/Dockerfile
- **Phase 2** ✅ Code Intelligence — Tree-sitter AST, call/dep graphs, classifier
- **Phase 3** 🔜 Impact + Regression — BFS blast radius, regression agent, architecture agent
- **Phase 4** 🔜 Scale + Learning — OTel tracing, feedback loop, few-shot retrieval

---

## Requirements

- Python 3.12 (tree-sitter-languages constraint)
- AWS credentials with Bedrock access (`anthropic.claude-sonnet-4-5-v1:0`)
- GitHub token with `pull_requests: write` and `checks: write`
