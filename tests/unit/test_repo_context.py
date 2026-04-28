"""Unit tests for RepoContext — prompt rendering and YAML coercion."""

from __future__ import annotations

from mergeguard.context.repo_context import (
    RepoContext,
    _as_int_dict,
    _as_list,
    _as_str,
    _truncate,
)


def test_empty_context_renders_empty_block():
    ctx = RepoContext(owner="o", repo="r", ref="abc")
    assert ctx.prompt_block() == ""
    assert ctx.prompt_block("security") == ""
    assert ctx.has_content() is False


def test_custom_rules_rendered():
    ctx = RepoContext(owner="o", repo="r", ref="abc", custom_rules="No exec() calls.")
    block = ctx.prompt_block()
    assert "Repo conventions" in block
    assert "No exec() calls" in block
    assert "Reviewer guidelines" in block


def test_per_agent_rules_only_shown_for_matching_agent():
    ctx = RepoContext(
        owner="o",
        repo="r",
        ref="abc",
        per_agent_rules={"security": "Ignore test fixtures."},
    )
    assert "Ignore test fixtures" in ctx.prompt_block("security")
    assert "Ignore test fixtures" not in ctx.prompt_block("code_quality")


def test_docs_rendered_with_path_header():
    ctx = RepoContext(
        owner="o",
        repo="r",
        ref="abc",
        docs={"docs/ARCHITECTURE.md": "Services must not import from db/."},
    )
    block = ctx.prompt_block()
    assert "`docs/ARCHITECTURE.md`" in block
    assert "Services must not import" in block


def test_codeowners_wrapped_in_code_fence():
    ctx = RepoContext(
        owner="o",
        repo="r",
        ref="abc",
        codeowners="*.py @python-team\n/infra @devops",
    )
    block = ctx.prompt_block()
    assert "CODEOWNERS" in block
    assert "```" in block
    assert "@python-team" in block


def test_combined_block_order_is_stable():
    ctx = RepoContext(
        owner="o",
        repo="r",
        ref="abc",
        custom_rules="rule-1",
        per_agent_rules={"code_quality": "cq-rule"},
        docs={"ARCHITECTURE.md": "arch-body"},
        codeowners="*.py @team",
    )
    block = ctx.prompt_block("code_quality")
    idx_rules = block.index("rule-1")
    idx_per = block.index("cq-rule")
    idx_doc = block.index("arch-body")
    idx_co = block.index("@team")
    assert idx_rules < idx_per < idx_doc < idx_co


def test_as_str_coerces_lists():
    assert _as_str(["a", "b"]) == "a\nb"
    assert _as_str(None) == ""
    assert _as_str("x") == "x"


def test_as_list_coerces_scalars():
    assert _as_list("x") == ["x"]
    assert _as_list(None) == []
    assert _as_list(["a", "b"]) == ["a", "b"]


def test_as_int_dict_skips_non_numeric():
    d = _as_int_dict({"block": 90, "warn": "50", "bad": "xx"})
    assert d == {"block": 90, "warn": 50}


def test_truncate_adds_marker_when_over_limit():
    out = _truncate("x" * 100, limit=10)
    assert out.startswith("x" * 10)
    assert "truncated" in out


def test_truncate_leaves_short_strings_alone():
    assert _truncate("short", limit=100) == "short"
