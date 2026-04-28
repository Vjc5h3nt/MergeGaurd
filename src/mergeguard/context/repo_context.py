"""RepoContext — per-repository rules, docs, and conventions for a single review.

Loaded fresh at the start of every review via the installation's scoped token.
Threaded into each specialist agent's system prompt as an "## Repo conventions"
block so the review adapts to the target repo rather than using generic rules.
"""

from __future__ import annotations

import contextvars
import logging
from dataclasses import dataclass, field
from typing import Any

import yaml

log = logging.getLogger(__name__)


# Config file paths we probe, in priority order. First hit wins.
_CONFIG_CANDIDATES = [
    ".github/mergeguard.yml",
    ".github/mergeguard.yaml",
    ".mergeguard.yml",
    ".mergeguard.yaml",
]

# Doc paths that are auto-injected if present (truncated to ~6k chars each).
_DEFAULT_DOC_PATHS = [
    "docs/ARCHITECTURE.md",
    "docs/CODING_STANDARDS.md",
    "ARCHITECTURE.md",
    "CONTRIBUTING.md",
]

# Cap per-doc size to keep prompt budget bounded.
_MAX_DOC_CHARS = 6_000
_MAX_RULES_CHARS = 4_000


@dataclass
class RepoContext:
    """Context loaded from the target repo at review time.

    All fields are optional — missing files are silently skipped. A repo with
    no config at all produces an empty RepoContext and reviews proceed with
    defaults (same behaviour as before this module existed).
    """

    owner: str
    repo: str
    ref: str

    # From .github/mergeguard.yml
    custom_rules: str = ""              # free-form markdown block the user writes
    doc_paths: list[str] = field(default_factory=list)
    risk_thresholds: dict[str, int] = field(default_factory=dict)
    disabled_agents: list[str] = field(default_factory=list)
    per_agent_rules: dict[str, str] = field(default_factory=dict)  # e.g. {"security": "Never flag X"}

    # Fetched docs: {path: content}
    docs: dict[str, str] = field(default_factory=dict)

    # CODEOWNERS raw text (kept as plain string — agents can parse if useful)
    codeowners: str = ""

    # Whether we loaded ANY repo-specific signal. False → repo has no config.
    loaded: bool = False

    # --------- Prompt block builders ---------

    def has_content(self) -> bool:
        return bool(self.custom_rules or self.docs or self.codeowners or self.per_agent_rules)

    def prompt_block(self, agent_name: str = "") -> str:
        """Render a "## Repo conventions" block for prompt injection.

        Args:
            agent_name: optional specialist name ("code_quality", "security",
                "regression", "architecture"). If the repo config has
                ``rules.<agent_name>``, that block is appended too.
        """
        if not self.has_content():
            return ""

        lines: list[str] = ["", "## Repo conventions (from target repository)"]

        if self.custom_rules:
            lines.append("")
            lines.append("### Reviewer guidelines")
            lines.append(self.custom_rules.strip())

        if agent_name and self.per_agent_rules.get(agent_name):
            lines.append("")
            lines.append(f"### Rules specific to the {agent_name} review")
            lines.append(self.per_agent_rules[agent_name].strip())

        for path, body in self.docs.items():
            lines.append("")
            lines.append(f"### `{path}` (excerpt)")
            lines.append(body.strip())

        if self.codeowners:
            lines.append("")
            lines.append("### CODEOWNERS")
            lines.append("```")
            lines.append(self.codeowners.strip())
            lines.append("```")

        lines.append("")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Loader
# ---------------------------------------------------------------------------

def load_repo_context(owner: str, repo: str, ref: str) -> RepoContext:
    """Load per-repo context using the current GitHubClient singleton.

    The singleton must already be authed with the installation token
    (done by lambda_handler._run_review).

    Args:
        owner: Repository owner.
        repo: Repository name.
        ref: Commit SHA or branch to read files from (usually PR head_sha so
            rules added in the PR itself take effect for that review).
    """
    from mergeguard.integrations.github import get_github_client

    ctx = RepoContext(owner=owner, repo=repo, ref=ref)
    gh = get_github_client()

    # 1. Try each candidate config path — first hit wins
    raw_config: dict[str, Any] | None = None
    for path in _CONFIG_CANDIDATES:
        try:
            text = gh.get_file_content(owner, repo, path, ref)
            if not text:
                continue
            data = yaml.safe_load(text)
            if isinstance(data, dict):
                raw_config = data
                log.info("Loaded repo config: %s/%s:%s", owner, repo, path)
                break
        except Exception as exc:
            log.debug("No config at %s: %s", path, exc)

    if raw_config:
        ctx.loaded = True
        ctx.custom_rules = _truncate(_as_str(raw_config.get("rules")), _MAX_RULES_CHARS)
        ctx.doc_paths = _as_list(raw_config.get("context_docs"))
        ctx.risk_thresholds = _as_int_dict(raw_config.get("risk_thresholds"))
        ctx.disabled_agents = _as_list(raw_config.get("disable"))
        ctx.per_agent_rules = {
            k: _truncate(_as_str(v), _MAX_RULES_CHARS)
            for k, v in (raw_config.get("per_agent_rules") or {}).items()
            if isinstance(k, str)
        }

    # 2. Fetch docs — explicitly listed paths, plus defaults if present
    paths_to_try = list(dict.fromkeys(ctx.doc_paths + _DEFAULT_DOC_PATHS))
    for path in paths_to_try:
        try:
            body = gh.get_file_content(owner, repo, path, ref)
            if body:
                ctx.docs[path] = _truncate(body, _MAX_DOC_CHARS)
                ctx.loaded = True
                log.debug("Loaded context doc: %s", path)
        except Exception:
            continue

    # 3. CODEOWNERS — try the three standard locations
    for path in (".github/CODEOWNERS", "CODEOWNERS", "docs/CODEOWNERS"):
        try:
            body = gh.get_file_content(owner, repo, path, ref)
            if body:
                ctx.codeowners = _truncate(body, _MAX_RULES_CHARS)
                ctx.loaded = True
                break
        except Exception:
            continue

    log.info(
        "RepoContext loaded: %s/%s (rules=%s, docs=%d, codeowners=%s)",
        owner, repo, bool(ctx.custom_rules), len(ctx.docs), bool(ctx.codeowners),
    )
    return ctx


# ---------------------------------------------------------------------------
# YAML coercion helpers — user input is untrusted shape-wise
# ---------------------------------------------------------------------------

def _as_str(v: Any) -> str:
    if v is None:
        return ""
    if isinstance(v, str):
        return v
    if isinstance(v, list):
        return "\n".join(_as_str(x) for x in v)
    return str(v)


def _as_list(v: Any) -> list[str]:
    if not v:
        return []
    if isinstance(v, str):
        return [v]
    if isinstance(v, list):
        return [str(x) for x in v if x]
    return []


def _as_int_dict(v: Any) -> dict[str, int]:
    if not isinstance(v, dict):
        return {}
    out: dict[str, int] = {}
    for k, val in v.items():
        try:
            out[str(k)] = int(val)
        except (TypeError, ValueError):
            continue
    return out


def _truncate(s: str, limit: int) -> str:
    if len(s) <= limit:
        return s
    return s[:limit] + "\n\n_[truncated]_"


# ---------------------------------------------------------------------------
# Active-context propagation
# ---------------------------------------------------------------------------
# Strands @tool functions receive only JSON-serializable args from the
# orchestrator LLM, so we can't pass a RepoContext object through tool calls.
# Instead we stash it on a ContextVar inside review_pull_request() — specialist
# agents read it at the point they build their prompt. Same pattern as
# telemetry.tracing._active_trace.

_active_repo_context: contextvars.ContextVar["RepoContext | None"] = contextvars.ContextVar(
    "mergeguard_active_repo_context", default=None
)


def set_active_repo_context(ctx: "RepoContext") -> contextvars.Token:  # type: ignore[type-arg]
    return _active_repo_context.set(ctx)


def get_active_repo_context() -> "RepoContext | None":
    return _active_repo_context.get()


def reset_active_repo_context(token: "contextvars.Token") -> None:  # type: ignore[type-arg]
    _active_repo_context.reset(token)
