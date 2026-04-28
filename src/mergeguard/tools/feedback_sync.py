"""Poll GitHub reactions on inline PR review comments and sync to the feedback store."""

from __future__ import annotations

import logging
from typing import Any

log = logging.getLogger(__name__)


def sync_reactions(conn: Any, gh: Any) -> int:
    """Fetch reactions for all stored inline comment IDs and update the DB.

    Args:
        conn: Open SQLite connection from ``feedback.store.open_db()``.
        gh:   ``GitHubClient`` instance.

    Returns:
        Number of findings updated.
    """
    from mergeguard.feedback.store import get_unsynced_comments, update_reactions

    rows = get_unsynced_comments(conn)
    if not rows:
        log.info("No inline comments to sync.")
        return 0

    updated = 0
    for row in rows:
        comment_id = row["comment_id"]
        owner = row["owner"]
        repo = row["repo"]
        try:
            reactions: list[dict[str, Any]] = gh.get_reactions(owner, repo, comment_id)
            thumbs_up = sum(1 for r in reactions if r.get("content") == "+1")
            thumbs_down = sum(1 for r in reactions if r.get("content") == "-1")
            update_reactions(conn, comment_id, thumbs_up, thumbs_down)
            updated += 1
            log.debug("Comment %d: +%d / -%d reactions", comment_id, thumbs_up, thumbs_down)
        except Exception as exc:
            log.warning("Failed to fetch reactions for comment %d: %s", comment_id, exc)

    log.info("Synced reactions for %d/%d comments.", updated, len(rows))
    return updated
