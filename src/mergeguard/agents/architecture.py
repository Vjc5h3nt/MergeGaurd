"""Architecture compliance agent — layer boundary violations, circular deps, design patterns."""

from __future__ import annotations

import logging
import re
from typing import Any

from strands import Agent, tool

from mergeguard.agents.base import build_agent, dominant_file_ext, format_patch_context

log = logging.getLogger(__name__)

_SYSTEM_PROMPT = """\
You are the Architecture Compliance specialist in a multi-agent PR review system.

You will receive:
1. A diff of the PR changes.
2. A structured import diff showing exactly which imports were added and removed per file.
3. Optionally, a dependency graph showing module-level relationships.

Your responsibilities:
1. Detect layer boundary violations using the import diff:
   - e.g. a presentation/API layer importing directly from a data/infrastructure layer,
   - a utility/helper module importing from business logic,
   - a domain model importing from HTTP/framework concerns.
2. Identify circular dependencies introduced by the new imports.
3. Flag files placed in incorrect modules/packages based on their content and imports.
4. Detect violations of established design patterns visible in the diff:
   - Service class directly constructing repositories (should use DI).
   - Domain model with HTTP concerns (status codes, request/response objects).
   - Controller/handler importing database models directly.
5. Flag new public APIs that don't follow naming conventions or are missing validation.
6. Detect overly tight coupling: concrete class instantiation where interfaces should be used.

Use the import diff to anchor every finding — only report what is directly evidenced.

Return findings as a JSON array inside ```json ... ```. If none, return [].
"""

# Import statement patterns per language
_IMPORT_PATTERNS = [
    re.compile(r"^(?P<sign>[+-])\s*(?:from\s+(?P<from>[\w.]+)\s+)?import\s+(?P<what>.+)$"),   # Python
    re.compile(r"^(?P<sign>[+-])\s*import\s+(?:\{[^}]+\}|[\w*]+)\s+from\s+['\"](?P<from>[^'\"]+)['\"]"),  # JS/TS
    re.compile(r"^(?P<sign>[+-])\s*import\s+\"(?P<from>[^\"]+)\""),  # Go
    re.compile(r"^(?P<sign>[+-])\s*import\s+(?P<from>[\w.]+);"),  # Java
]


def _extract_import_diff(patches: list[dict[str, Any]]) -> dict[str, Any]:
    """Extract structured import changes from the diff.

    Returns:
        {
          "added_imports": { "file.py": ["from foo import bar", ...] },
          "removed_imports": { "file.py": ["import baz", ...] },
          "new_dependencies": ["module_a -> module_b", ...],   # inferred edges
        }
    """
    added_imports: dict[str, list[str]] = {}
    removed_imports: dict[str, list[str]] = {}

    for patch in patches:
        path = patch.get("path", "")
        for hunk in patch.get("hunks", []):
            for line in hunk.get("added", []):
                for pat in _IMPORT_PATTERNS:
                    m = pat.match(line)
                    if m:
                        added_imports.setdefault(path, []).append(line.lstrip("+").strip())
                        break
            for line in hunk.get("removed", []):
                for pat in _IMPORT_PATTERNS:
                    m = pat.match(line)
                    if m:
                        removed_imports.setdefault(path, []).append(line.lstrip("-").strip())
                        break

    # Build simple dependency edges from new imports
    new_deps: list[str] = []
    for file_path, imports in added_imports.items():
        # Derive module name from file path
        module = _path_to_module(file_path)
        for imp in imports:
            dep = _import_to_module(imp)
            if dep and dep != module:
                new_deps.append(f"{module} → {dep}")

    return {
        "added_imports": added_imports,
        "removed_imports": removed_imports,
        "new_dependencies": new_deps,
    }


def _path_to_module(path: str) -> str:
    """Convert a file path to a rough module name."""
    return path.replace("/", ".").replace("\\", ".").removesuffix(".py").removesuffix(".ts").removesuffix(".js")


def _import_to_module(imp: str) -> str | None:
    """Extract the module being imported from an import statement."""
    # Python: from foo.bar import baz  OR  import foo.bar
    m = re.match(r"from\s+([\w.]+)\s+import", imp)
    if m:
        return m.group(1)
    m = re.match(r"import\s+([\w.]+)", imp)
    if m:
        return m.group(1)
    # JS/TS: import ... from './foo/bar'
    m = re.search(r"from\s+['\"]([^'\"]+)['\"]", imp)
    if m:
        return m.group(1).lstrip("./").replace("/", ".")
    return None


def _build_architecture_agent() -> Agent:
    return build_agent(system_prompt=_SYSTEM_PROMPT, tools=[], tier="fast")


def run_architecture_review(
    patches: list[dict[str, Any]],
    pr_meta: dict[str, Any],
    dep_graph: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Run the architecture agent and return findings."""
    import json

    from mergeguard.feedback.retrieval import get_examples_block
    from mergeguard.telemetry.tracing import get_active_trace, null_span

    agent = _build_architecture_agent()
    diff_context = format_patch_context(patches)
    import_diff = _extract_import_diff(patches)
    examples_block = get_examples_block("architecture", dominant_file_ext(patches))

    import_context = (
        "\n## Import Changes (structured)\n"
        f"```json\n{json.dumps(import_diff, indent=2)}\n```\n"
    )

    dep_context = ""
    if dep_graph:
        dep_context = (
            f"\n## Full Dependency Graph\n"
            f"```json\n{json.dumps(dep_graph, indent=2)}\n```\n"
        )

    prompt = f"""PR #{pr_meta.get('number')} — {pr_meta.get('title', '')}

## Diff
{diff_context}
{import_context}
{dep_context}
{examples_block}
Review for architectural violations, layer boundary breaches, circular dependencies,
and design pattern issues. Use the import changes as your primary evidence.
Return findings as a JSON array.
"""

    trace = get_active_trace()
    ctx = trace.span("agent.architecture", {"files": len(patches)}) if trace else null_span()
    with ctx:
        result = agent(prompt)
    return _extract_findings(str(result))


@tool
def review_architecture(
    patches: list[dict[str, Any]],
    pr_meta: dict[str, Any],
    dep_graph: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Run the Architecture Compliance agent on a PR diff.

    Uses structured import diff extraction to ground architectural findings
    in concrete evidence from the changed files.

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
