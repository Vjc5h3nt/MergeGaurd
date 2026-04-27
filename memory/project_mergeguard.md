---
name: MergeGuard project context
description: Core facts about MergeGuard — AI PR Code Review Agent built on AWS Strands SDK + Bedrock
type: project
---

MergeGuard is an AI PR Code Review Agent shipped as a GitHub Action and AWS Lambda function.

**Stack:** Python 3.12, AWS Strands SDK (`strands-agents`), Amazon Bedrock (Claude Sonnet 4.5), Tree-sitter, unidiff, networkx, httpx, pydantic, typer, rich.

**Key constraint:** Python must be 3.12 (not 3.14) — `tree-sitter-languages` has no 3.14 wheel.

**Build status (2026-04-27):**
- Phase 0 (Bootstrap): COMPLETE — pyproject.toml, CLI, config, CI workflow, project structure
- Phase 1 (Diff MVP): COMPLETE — GitHub client, diff parser, Strands orchestrator + 4 specialist agents, risk scorer, GitHub poster, action.yml, Dockerfile, Lambda handler
- Phase 2 (Code Intelligence): COMPLETE — tree-sitter loader, symbol extractor, call graph, dependency graph, change classifier, cache, ast_query/callgraph_query/dep_lookup tools
- Phase 3 (Impact + Regression): PENDING
- Phase 4 (Scale + Learning): PENDING

**Why:** Automate PR reviews — catch security vulns, regressions, architectural violations — while keeping code inside AWS (no 3rd-party AI services see the code).

**How to apply:** When continuing this project, start from Phase 3: scoring/impact.py BFS blast radius wiring into the orchestrator, regression agent with deterministic pre-checks, architecture agent with dep_lookup integration.
