"""Regression detection agent — deterministic pre-checks + LLM behavioral analysis."""

from __future__ import annotations

import logging
import re
from typing import Any

from strands import Agent, tool

from mergeguard.agents.base import build_agent, dominant_file_ext, format_patch_context

log = logging.getLogger(__name__)

_SYSTEM_PROMPT = """\
You are the Regression Detection specialist in a multi-agent PR review system.

You will receive:
1. A diff of the PR changes.
2. A list of DETERMINISTIC findings already confirmed from static analysis — treat these as facts.
3. Optionally, call graph data showing which symbols call the changed functions.

Your job (LLM reasoning layer):
1. For each deterministic finding, verify the severity and add an explanation of the likely
   runtime impact on callers. Do NOT remove or downgrade deterministic findings.
2. Identify additional behavioral regressions not caught by static analysis:
   - Logic changes that alter control flow, exception propagation, or side effects.
   - Test coverage regressions: new logic paths without corresponding tests.
   - Removed/disabled assertions or tests.
3. Detect signature drift that static analysis may have missed (e.g., changed default values,
   return type narrowing, added required parameters).

IMPORTANT: Never flag a regression without a concrete, specific reason anchored in the diff.
Prefer false negatives over false positives.

Severity rules:
- HIGH: Public API removed/renamed with callers, or core logic fundamentally changed.
- MEDIUM: Behavioral change in internal function with callers, or test coverage dropped.
- LOW: Minor behavioral nuance that existing tests might not catch.
- INFO: Observation (e.g., test added but doesn't cover the new branch).

Return ALL findings (deterministic + LLM-discovered) as a JSON array inside ```json ... ```.
If none, return [].
"""

# Patterns for detecting function/class definitions in diff lines
_FUNC_DEF_PATTERNS = [
    re.compile(r"^(?P<sign>[-+])\s*(?:async\s+)?def\s+(?P<name>\w+)\s*\((?P<params>[^)]*)\)"),  # Python
    re.compile(r"^(?P<sign>[-+])\s*(?:export\s+)?(?:async\s+)?function\s+(?P<name>\w+)\s*\((?P<params>[^)]*)\)"),  # JS/TS
    re.compile(r"^(?P<sign>[-+])\s*func\s+(?:\(\w+\s+\*?\w+\)\s+)?(?P<name>\w+)\s*\((?P<params>[^)]*)\)"),  # Go
    re.compile(r"^(?P<sign>[-+])\s*(?:public|private|protected|static|\s)+\w[\w<>\[\]]*\s+(?P<name>\w+)\s*\((?P<params>[^)]*)\)"),  # Java
]
_CLASS_DEF_RE = re.compile(r"^(?P<sign>[-+])\s*class\s+(?P<name>\w+)")


def _deterministic_regression_checks(patches: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Scan the diff for definitive regression signals without LLM.

    Detects:
    - Removed public functions/classes (symbol present only in removed lines)
    - Renamed functions (removed A, added B in same hunk)
    - Signature changes (same function name, different parameter list)

    Returns a list of HIGH/MEDIUM severity findings with concrete evidence.
    """
    findings: list[dict[str, Any]] = []

    for patch in patches:
        path = patch.get("path", "")
        if patch.get("is_deleted_file"):
            continue  # whole file deleted is expected

        for hunk in patch.get("hunks", []):
            removed_lines: list[str] = hunk.get("removed", [])
            added_lines: list[str] = hunk.get("added", [])

            removed_syms = _extract_symbols(removed_lines, path)
            added_syms = _extract_symbols(added_lines, path)

            removed_names = {s["name"] for s in removed_syms}
            added_names = {s["name"] for s in added_syms}

            # 1. Removed symbols (not present in added lines at all)
            for sym in removed_syms:
                name = sym["name"]
                if name not in added_names and _is_public(name):
                    findings.append({
                        "severity": "HIGH",
                        "category": "regression/removed-symbol",
                        "message": (
                            f"`{name}` was removed from `{path}`. "
                            "Any callers of this symbol will break at runtime."
                        ),
                        "path": path,
                        "line": sym.get("line"),
                        "suggestion": (
                            f"If `{name}` is no longer needed, ensure all call sites are updated. "
                            "If it was renamed, add a deprecation alias."
                        ),
                        "deterministic": True,
                    })

            # 2. Signature changes (same name, different params)
            for rem_sym in removed_syms:
                name = rem_sym["name"]
                for add_sym in added_syms:
                    if add_sym["name"] == name and rem_sym["params"] != add_sym["params"]:
                        findings.append({
                            "severity": "HIGH",
                            "category": "regression/signature-change",
                            "message": (
                                f"`{name}` signature changed in `{path}`: "
                                f"`({rem_sym['params']})` → `({add_sym['params']})`. "
                                "Existing callers may break."
                            ),
                            "path": path,
                            "line": add_sym.get("line"),
                            "suggestion": (
                                "Add a compatibility shim or update all call sites. "
                                "Consider bumping the API version if this is a public interface."
                            ),
                            "deterministic": True,
                        })

            # 3. Possible rename: removed X, added Y (same hunk, same kind)
            only_removed = removed_names - added_names
            only_added = added_names - removed_names
            if len(only_removed) == 1 and len(only_added) == 1:
                old_name = next(iter(only_removed))
                new_name = next(iter(only_added))
                if _is_public(old_name):
                    findings.append({
                        "severity": "MEDIUM",
                        "category": "regression/possible-rename",
                        "message": (
                            f"`{old_name}` may have been renamed to `{new_name}` in `{path}`. "
                            "Callers of `{old_name}` will break."
                        ),
                        "path": path,
                        "suggestion": (
                            f"Add `{old_name} = {new_name}` as a deprecation alias, "
                            "or update all call sites."
                        ),
                        "deterministic": True,
                    })

    return findings


def _extract_symbols(lines: list[str], path: str) -> list[dict[str, Any]]:
    symbols = []
    for i, line in enumerate(lines):
        for pattern in _FUNC_DEF_PATTERNS:
            m = pattern.match(line)
            if m:
                symbols.append({
                    "name": m.group("name"),
                    "params": _normalize_params(m.group("params")),
                    "line": i + 1,
                    "kind": "function",
                })
                break
        else:
            m = _CLASS_DEF_RE.match(line)
            if m:
                symbols.append({
                    "name": m.group("name"),
                    "params": "",
                    "line": i + 1,
                    "kind": "class",
                })
    return symbols


def _normalize_params(params: str) -> str:
    """Strip type annotations and default values for comparison."""
    parts = []
    for p in params.split(","):
        p = p.strip()
        p = re.sub(r":.*", "", p)   # remove type annotation
        p = re.sub(r"=.*", "", p)   # remove default value
        p = p.strip().lstrip("*")   # strip */**/self/cls markers
        if p and p not in {"self", "cls", "args", "kwargs"}:
            parts.append(p)
    return ", ".join(parts)


def _is_public(name: str) -> bool:
    return not name.startswith("_")


def _build_regression_agent() -> Agent:
    return build_agent(system_prompt=_SYSTEM_PROMPT, tools=[], tier="fast")


def run_regression_review(
    patches: list[dict[str, Any]],
    pr_meta: dict[str, Any],
    symbol_graph: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Run deterministic pre-checks then LLM reasoning. Return merged findings."""
    # --- Deterministic layer (no LLM) ---
    deterministic = _deterministic_regression_checks(patches)
    log.info("Regression deterministic pre-checks: %d findings", len(deterministic))

    # --- LLM layer ---
    import json

    from mergeguard.feedback.retrieval import get_examples_block
    from mergeguard.telemetry.tracing import get_active_trace, null_span

    agent = _build_regression_agent()
    diff_context = format_patch_context(patches)
    examples_block = get_examples_block("regression", dominant_file_ext(patches))

    det_context = ""
    if deterministic:
        det_context = (
            "\n## Deterministic Findings (confirmed by static analysis — treat as facts)\n"
            f"```json\n{json.dumps(deterministic, indent=2)}\n```\n"
        )

    symbol_context = ""
    if symbol_graph:
        symbol_context = (
            f"\n## Call Graph (callers/callees)\n"
            f"```json\n{json.dumps(symbol_graph, indent=2)}\n```\n"
        )

    prompt = f"""PR #{pr_meta.get('number')} — {pr_meta.get('title', '')}

## Diff
{diff_context}
{det_context}
{symbol_context}
{examples_block}
Analyze for regression risks. Return ALL findings (include the deterministic ones above plus
any additional ones you discover) as a single JSON array.
"""

    trace = get_active_trace()
    ctx = trace.span("agent.regression", {"files": len(patches)}) if trace else null_span()
    with ctx:
        result = agent(prompt)
    llm_findings = _extract_findings(str(result))

    # Merge: LLM findings take precedence (they may have richer explanations),
    # but ensure all deterministic findings are present.
    det_keys = {(f.get("category"), f.get("path"), f.get("line")) for f in deterministic}
    llm_keys = {(f.get("category"), f.get("path"), f.get("line")) for f in llm_findings}
    missed_det = [f for f in deterministic if (f["category"], f.get("path"), f.get("line")) not in llm_keys]

    return llm_findings + missed_det


@tool
def detect_regressions(
    patches: list[dict[str, Any]],
    pr_meta: dict[str, Any],
    symbol_graph: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Run the Regression Detection agent on a PR diff.

    Combines deterministic static analysis (removed/renamed symbols, signature changes)
    with LLM behavioral reasoning for comprehensive regression detection.

    Args:
        patches: Serialized FilePatch list from fetch_pr_diff.
        pr_meta: PR metadata dict.
        symbol_graph: Optional call graph data from the Code Intelligence Layer.

    Returns:
        Dict with 'findings' list and 'agent' identifier.
    """
    findings = run_regression_review(patches, pr_meta, symbol_graph)
    log.info("Regression agent: %d findings total", len(findings))
    return {"agent": "regression", "findings": findings}


def _extract_findings(text: str) -> list[dict[str, Any]]:
    import json

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
