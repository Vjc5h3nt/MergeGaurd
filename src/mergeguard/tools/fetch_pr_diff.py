"""Strands tool: fetch_pr_diff — retrieves PR diff and file metadata from GitHub."""

from __future__ import annotations

import logging
from typing import Any

from strands import tool

from mergeguard.diff.parser import FilePatch, parse_diff
from mergeguard.integrations.github import get_github_client

log = logging.getLogger(__name__)


@tool
def fetch_pr_diff(owner: str, repo: str, pr_number: int) -> dict[str, Any]:
    """Fetch the unified diff and changed-file metadata for a GitHub Pull Request.

    Args:
        owner: GitHub repository owner (user or org).
        repo: Repository name.
        pr_number: Pull request number.

    Returns:
        A dict with keys:
        - pr: basic PR metadata (title, author, base_sha, head_sha)
        - files: list of changed file objects (path, status, additions, deletions)
        - patches: parsed FilePatch objects serialized as dicts
        - raw_diff: the full unified diff string
    """
    gh = get_github_client()

    log.info("Fetching PR %s/%s#%d", owner, repo, pr_number)
    pr_data = gh.get_pull_request(owner, repo, pr_number)
    raw_diff = gh.get_pr_diff(owner, repo, pr_number)
    files = gh.get_pr_files(owner, repo, pr_number)

    patches = parse_diff(raw_diff)
    patches_serialized = [_serialize_patch(p) for p in patches]

    return {
        "pr": {
            "number": pr_data["number"],
            "title": pr_data["title"],
            "author": pr_data["user"]["login"],
            "base_sha": pr_data["base"]["sha"],
            "head_sha": pr_data["head"]["sha"],
            "base_ref": pr_data["base"]["ref"],
            "head_ref": pr_data["head"]["ref"],
            "additions": pr_data["additions"],
            "deletions": pr_data["deletions"],
            "changed_files": pr_data["changed_files"],
        },
        "files": [
            {
                "path": f["filename"],
                "status": f["status"],  # added | modified | removed | renamed
                "additions": f["additions"],
                "deletions": f["deletions"],
                "patch": f.get("patch", ""),
            }
            for f in files
        ],
        "patches": patches_serialized,
        "raw_diff": raw_diff,
    }


def _serialize_patch(p: FilePatch) -> dict[str, Any]:
    return {
        "path": p.path,
        "source_path": p.source_path,
        "is_new_file": p.is_new_file,
        "is_deleted_file": p.is_deleted_file,
        "is_renamed": p.is_renamed,
        "added_lines": p.added_line_numbers,
        "removed_lines": p.removed_line_numbers,
        "hunks": [
            {
                "source_start": h.source_start,
                "source_length": h.source_length,
                "target_start": h.target_start,
                "target_length": h.target_length,
                "added": h.added_lines,
                "removed": h.removed_lines,
                "section_header": h.section_header,
            }
            for h in p.hunks
        ],
    }
