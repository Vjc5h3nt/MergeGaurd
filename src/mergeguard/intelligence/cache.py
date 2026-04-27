"""Per-PR + per-commit symbol graph cache (file-system backed)."""

from __future__ import annotations

import hashlib
import json
import logging
import os
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

_DEFAULT_CACHE_DIR = Path(os.getenv("MERGEGUARD_CACHE_DIR", "/tmp/mergeguard-cache"))


def _cache_key(repo: str, sha: str, key_suffix: str = "") -> str:
    raw = f"{repo}:{sha}:{key_suffix}"
    return hashlib.sha256(raw.encode()).hexdigest()[:24]


def _cache_path(cache_dir: Path, cache_key: str) -> Path:
    return cache_dir / f"{cache_key}.json"


def cache_get(
    repo: str,
    sha: str,
    key_suffix: str = "symbols",
    cache_dir: Path | None = None,
) -> Any | None:
    """Load cached data for (repo, sha). Returns None on miss."""
    d = cache_dir or _DEFAULT_CACHE_DIR
    path = _cache_path(d, _cache_key(repo, sha, key_suffix))
    if not path.exists():
        return None
    try:
        with open(path) as f:
            log.debug("Cache hit: %s", path)
            return json.load(f)
    except (json.JSONDecodeError, OSError) as exc:
        log.warning("Cache read error: %s", exc)
        return None


def cache_set(
    repo: str,
    sha: str,
    data: Any,
    key_suffix: str = "symbols",
    cache_dir: Path | None = None,
) -> None:
    """Store data for (repo, sha) in the cache."""
    d = cache_dir or _DEFAULT_CACHE_DIR
    d.mkdir(parents=True, exist_ok=True)
    path = _cache_path(d, _cache_key(repo, sha, key_suffix))
    try:
        with open(path, "w") as f:
            json.dump(data, f)
        log.debug("Cached: %s", path)
    except OSError as exc:
        log.warning("Cache write error: %s", exc)


def cache_invalidate(
    repo: str,
    sha: str,
    key_suffix: str = "symbols",
    cache_dir: Path | None = None,
) -> None:
    d = cache_dir or _DEFAULT_CACHE_DIR
    path = _cache_path(d, _cache_key(repo, sha, key_suffix))
    if path.exists():
        path.unlink()
        log.debug("Cache invalidated: %s", path)
