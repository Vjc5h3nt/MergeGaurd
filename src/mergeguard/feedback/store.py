"""SQLite feedback store — persists review findings and GitHub reaction tallies."""

from __future__ import annotations

import logging
import sqlite3
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

_DDL = """
CREATE TABLE IF NOT EXISTS reviews (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    owner        TEXT    NOT NULL,
    repo         TEXT    NOT NULL,
    pr_number    INTEGER NOT NULL,
    review_id    INTEGER,
    risk_bucket  TEXT    NOT NULL,
    risk_score   INTEGER NOT NULL,
    reviewed_at  TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);

CREATE TABLE IF NOT EXISTS findings (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    review_fk         INTEGER NOT NULL REFERENCES reviews(id),
    finding_idx       INTEGER NOT NULL,
    inline_comment_id INTEGER,
    severity          TEXT    NOT NULL,
    category          TEXT    NOT NULL,
    message           TEXT    NOT NULL,
    path              TEXT,
    file_ext          TEXT,
    thumbs_up         INTEGER NOT NULL DEFAULT 0,
    thumbs_down       INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_findings_category ON findings(category);
CREATE INDEX IF NOT EXISTS idx_findings_ext      ON findings(file_ext);
CREATE INDEX IF NOT EXISTS idx_findings_thumbs   ON findings(thumbs_up DESC);
CREATE INDEX IF NOT EXISTS idx_findings_comment  ON findings(inline_comment_id);
"""


def get_db_path() -> Path:
    from mergeguard.config import get_config

    cfg = get_config()
    if cfg.feedback_db_path:
        return Path(cfg.feedback_db_path)
    db_dir = cfg.cache_dir
    db_dir.mkdir(parents=True, exist_ok=True)
    return db_dir / "feedback.db"


def open_db(path: Path | None = None) -> sqlite3.Connection:
    """Open (or create) the feedback database and run DDL migrations."""
    p = path or get_db_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(p), check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript(_DDL)
    conn.commit()
    log.debug("Feedback DB opened: %s", p)
    return conn


def record_review(
    conn: sqlite3.Connection,
    owner: str,
    repo: str,
    pr_number: int,
    review_id: int | None,
    risk_bucket: str,
    risk_score: int,
) -> int:
    """Insert a review row and return its rowid."""
    cur = conn.execute(
        "INSERT INTO reviews (owner, repo, pr_number, review_id, risk_bucket, risk_score) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (owner, repo, pr_number, review_id, risk_bucket, risk_score),
    )
    conn.commit()
    return cur.lastrowid  # type: ignore[return-value]


def record_findings(
    conn: sqlite3.Connection,
    review_fk: int,
    findings: list[dict[str, Any]],
    inline_comment_ids: list[int | None],
) -> None:
    """Bulk-insert findings aligned by index with inline_comment_ids."""
    rows = []
    for idx, (f, cid) in enumerate(zip(findings, inline_comment_ids, strict=False)):
        path = f.get("path") or ""
        ext = path.rsplit(".", 1)[-1].lower() if "." in path else ""
        rows.append(
            (
                review_fk,
                idx,
                cid,
                f.get("severity", "INFO"),
                f.get("category", ""),
                f.get("message", ""),
                path,
                ext,
            )
        )
    conn.executemany(
        "INSERT INTO findings "
        "(review_fk, finding_idx, inline_comment_id, severity, category, "
        " message, path, file_ext) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        rows,
    )
    conn.commit()
    log.debug("Recorded %d findings (review_fk=%d)", len(rows), review_fk)


def update_reactions(
    conn: sqlite3.Connection,
    comment_id: int,
    thumbs_up: int,
    thumbs_down: int,
) -> None:
    """Update reaction tallies for a finding by its GitHub inline comment ID."""
    conn.execute(
        "UPDATE findings SET thumbs_up=?, thumbs_down=? WHERE inline_comment_id=?",
        (thumbs_up, thumbs_down, comment_id),
    )
    conn.commit()


def get_unsynced_comments(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    """Return findings that have an inline_comment_id (eligible for reaction sync)."""
    rows = conn.execute(
        """
        SELECT f.id, f.inline_comment_id, r.owner, r.repo
        FROM   findings f
        JOIN   reviews  r ON f.review_fk = r.id
        WHERE  f.inline_comment_id IS NOT NULL
        """
    ).fetchall()
    return [{"id": row[0], "comment_id": row[1], "owner": row[2], "repo": row[3]} for row in rows]
