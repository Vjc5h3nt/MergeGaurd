"""Few-shot example retrieval from the feedback store.

Queries findings with ``thumbs_up >= 1`` that match the current diff's
category and file type, then formats them for injection into agent prompts.
"""

from __future__ import annotations

import logging
import sqlite3
from typing import Any

log = logging.getLogger(__name__)


def fetch_examples(
    conn: sqlite3.Connection,
    category_prefix: str,
    file_ext: str,
    limit: int = 3,
) -> list[dict[str, Any]]:
    """Return top positively-rated findings matching category and file extension.

    Falls back to category-only match when no extension-specific examples exist.
    Ranked by ``thumbs_up DESC, thumbs_down ASC``.
    """
    cols = "severity, category, message, file_ext, thumbs_up, thumbs_down"
    base_where = "thumbs_up >= 1"

    rows = conn.execute(
        f"SELECT {cols} FROM findings "
        f"WHERE category LIKE ? AND file_ext = ? AND {base_where} "
        "ORDER BY thumbs_up DESC, thumbs_down ASC LIMIT ?",
        (f"{category_prefix}%", file_ext, limit),
    ).fetchall()

    if not rows:
        rows = conn.execute(
            f"SELECT {cols} FROM findings "
            f"WHERE category LIKE ? AND {base_where} "
            "ORDER BY thumbs_up DESC, thumbs_down ASC LIMIT ?",
            (f"{category_prefix}%", limit),
        ).fetchall()

    col_names = ("severity", "category", "message", "file_ext", "thumbs_up", "thumbs_down")
    return [dict(zip(col_names, row)) for row in rows]


def format_examples_prompt(examples: list[dict[str, Any]]) -> str:
    """Render examples as a markdown block ready for prompt injection."""
    if not examples:
        return ""
    lines = ["## Real examples of issues confirmed by reviewers", ""]
    for ex in examples:
        lines.append(
            f"- **{ex['severity']}** `{ex['category']}` — {ex['message']}"
            f" *(👍 {ex['thumbs_up']})*"
        )
    lines.append("")
    return "\n".join(lines)


def get_examples_block(category_prefix: str, file_ext: str) -> str:
    """Convenience wrapper: open store, fetch, format, close. Returns empty on any error."""
    try:
        from mergeguard.feedback.store import get_db_path, open_db

        db_path = get_db_path()
        if not db_path.exists():
            return ""
        conn = open_db(db_path)
        try:
            examples = fetch_examples(conn, category_prefix, file_ext)
            return format_examples_prompt(examples)
        finally:
            conn.close()
    except Exception as exc:
        log.debug("Few-shot retrieval skipped: %s", exc)
        return ""
