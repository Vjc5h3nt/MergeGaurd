"""GitHub REST client — wraps httpx with auth, rate-limit handling, and ETag caching."""

from __future__ import annotations

import hashlib
import json
import logging
import time
from typing import Any

import httpx

log = logging.getLogger(__name__)

_GITHUB_API = "https://api.github.com"


class GitHubClient:
    """Thin async-capable GitHub REST client."""

    def __init__(self, token: str, base_url: str = _GITHUB_API) -> None:
        if not token:
            raise ValueError("GITHUB_TOKEN is required")
        self._base = base_url.rstrip("/")
        self._headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        self._etag_cache: dict[str, tuple[str, Any]] = {}  # url -> (etag, body)

    # ------------------------------------------------------------------
    # Low-level helpers
    # ------------------------------------------------------------------

    def _get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        url = f"{self._base}/{path.lstrip('/')}"
        headers = dict(self._headers)
        etag_key = url + json.dumps(params or {}, sort_keys=True)
        etag_hash = hashlib.md5(etag_key.encode()).hexdigest()  # noqa: S324

        if etag_hash in self._etag_cache:
            cached_etag, cached_body = self._etag_cache[etag_hash]
            headers["If-None-Match"] = cached_etag

        with httpx.Client(timeout=30) as client:
            resp = client.get(url, headers=headers, params=params)

        if resp.status_code == 304:
            log.debug("ETag cache hit: %s", url)
            return self._etag_cache[etag_hash][1]

        self._handle_rate_limit(resp)
        resp.raise_for_status()

        body = resp.json()
        if etag := resp.headers.get("ETag"):
            self._etag_cache[etag_hash] = (etag, body)

        return body

    def _post(self, path: str, payload: dict[str, Any]) -> Any:
        url = f"{self._base}/{path.lstrip('/')}"
        with httpx.Client(timeout=30) as client:
            resp = client.post(url, headers=self._headers, json=payload)
        self._handle_rate_limit(resp)
        resp.raise_for_status()
        return resp.json()

    def _put(self, path: str, payload: dict[str, Any]) -> Any:
        url = f"{self._base}/{path.lstrip('/')}"
        with httpx.Client(timeout=30) as client:
            resp = client.put(url, headers=self._headers, json=payload)
        self._handle_rate_limit(resp)
        resp.raise_for_status()
        return resp.json()

    @staticmethod
    def _handle_rate_limit(resp: httpx.Response) -> None:
        if resp.status_code == 429 or (
            resp.status_code == 403 and "rate limit" in resp.text.lower()
        ):
            reset_at = int(resp.headers.get("X-RateLimit-Reset", time.time() + 60))
            wait = max(0, reset_at - int(time.time())) + 1
            log.warning("Rate limited. Sleeping %ds.", wait)
            time.sleep(wait)

    # ------------------------------------------------------------------
    # PR methods
    # ------------------------------------------------------------------

    def get_pull_request(self, owner: str, repo: str, number: int) -> dict[str, Any]:
        return self._get(f"/repos/{owner}/{repo}/pulls/{number}")  # type: ignore[return-value]

    def get_pr_files(self, owner: str, repo: str, number: int) -> list[dict[str, Any]]:
        """Paginate all changed files for a PR."""
        results: list[dict[str, Any]] = []
        page = 1
        while True:
            page_data = self._get(
                f"/repos/{owner}/{repo}/pulls/{number}/files",
                params={"per_page": 100, "page": page},
            )
            if not page_data:
                break
            results.extend(page_data)
            if len(page_data) < 100:
                break
            page += 1
        return results

    def get_pr_diff(self, owner: str, repo: str, number: int) -> str:
        """Fetch the raw unified diff for a PR."""
        url = f"{self._base}/repos/{owner}/{repo}/pulls/{number}"
        headers = dict(self._headers)
        headers["Accept"] = "application/vnd.github.v3.diff"
        with httpx.Client(timeout=60) as client:
            resp = client.get(url, headers=headers)
        self._handle_rate_limit(resp)
        resp.raise_for_status()
        return resp.text

    def get_file_content(self, owner: str, repo: str, path: str, ref: str) -> str:
        """Fetch raw file content at a given ref (SHA or branch)."""
        import base64

        data = self._get(
            f"/repos/{owner}/{repo}/contents/{path}",
            params={"ref": ref},
        )
        if isinstance(data, dict) and data.get("encoding") == "base64":
            return base64.b64decode(data["content"]).decode("utf-8", errors="replace")
        return ""

    def get_repo_structure(self, owner: str, repo: str, ref: str) -> list[dict[str, Any]]:
        """Return the flat tree of all files at a given ref (recursive)."""
        data = self._get(
            f"/repos/{owner}/{repo}/git/trees/{ref}",
            params={"recursive": "1"},
        )
        return data.get("tree", [])  # type: ignore[return-value]

    # ------------------------------------------------------------------
    # Review / Check-run posting
    # ------------------------------------------------------------------

    def create_review(
        self,
        owner: str,
        repo: str,
        number: int,
        body: str,
        event: str,  # APPROVE | REQUEST_CHANGES | COMMENT
        comments: list[dict[str, Any]] | None = None,
        commit_id: str | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "body": body,
            "event": event,
        }
        if commit_id:
            payload["commit_id"] = commit_id
        if comments:
            payload["comments"] = comments
        return self._post(  # type: ignore[return-value]
            f"/repos/{owner}/{repo}/pulls/{number}/reviews", payload
        )

    def create_review_comment(
        self,
        owner: str,
        repo: str,
        number: int,
        commit_id: str,
        path: str,
        line: int,
        side: str,
        body: str,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "body": body,
            "commit_id": commit_id,
            "path": path,
            "line": line,
            "side": side,
        }
        return self._post(  # type: ignore[return-value]
            f"/repos/{owner}/{repo}/pulls/{number}/comments", payload
        )

    def create_check_run(
        self,
        owner: str,
        repo: str,
        name: str,
        head_sha: str,
        status: str,  # queued | in_progress | completed
        conclusion: str | None = None,  # success | failure | neutral | action_required
        title: str = "",
        summary: str = "",
        details_url: str = "",
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "name": name,
            "head_sha": head_sha,
            "status": status,
        }
        if conclusion:
            payload["conclusion"] = conclusion
            payload["completed_at"] = _now_iso()
        if title or summary:
            payload["output"] = {"title": title, "summary": summary}
        if details_url:
            payload["details_url"] = details_url
        return self._post(f"/repos/{owner}/{repo}/check-runs", payload)  # type: ignore[return-value]

    def update_check_run(
        self,
        owner: str,
        repo: str,
        check_run_id: int,
        status: str,
        conclusion: str | None = None,
        title: str = "",
        summary: str = "",
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {"status": status}
        if conclusion:
            payload["conclusion"] = conclusion
            payload["completed_at"] = _now_iso()
        if title or summary:
            payload["output"] = {"title": title, "summary": summary}
        return self._put(  # type: ignore[return-value]
            f"/repos/{owner}/{repo}/check-runs/{check_run_id}", payload
        )


def _now_iso() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()


_client: GitHubClient | None = None


def get_github_client() -> GitHubClient:
    global _client
    if _client is None:
        from mergeguard.config import get_config

        _client = GitHubClient(token=get_config().github_token)
    return _client
