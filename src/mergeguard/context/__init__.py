"""Per-repository context — rules, docs, and conventions loaded at review time."""

from mergeguard.context.repo_context import (
    RepoContext,
    get_active_repo_context,
    load_repo_context,
    reset_active_repo_context,
    set_active_repo_context,
)

__all__ = [
    "RepoContext",
    "load_repo_context",
    "get_active_repo_context",
    "set_active_repo_context",
    "reset_active_repo_context",
]
