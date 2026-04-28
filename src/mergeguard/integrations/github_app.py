"""GitHub App authentication — JWT → installation token flow.

Produces short-lived installation tokens that allow the bot to post reviews
as ``mergeguard-ai[bot]`` instead of a personal account.
"""

from __future__ import annotations

import logging
import os
import time
from typing import Any

import httpx

log = logging.getLogger(__name__)

_GITHUB_API = "https://api.github.com"


def _load_private_key() -> str:
    """Load the GitHub App private key from Secrets Manager or env var."""
    # 1. Direct env var (local dev / GitHub Actions)
    key = os.getenv("GITHUB_APP_PRIVATE_KEY", "")
    if key:
        return key

    # 2. Secrets Manager (Lambda)
    import boto3

    sm = boto3.client("secretsmanager", region_name=os.getenv("AWS_REGION", "us-east-1"))
    resp = sm.get_secret_value(SecretId="mergeguard/github-app-private-key")
    return resp["SecretString"]


def _load_webhook_secret() -> str:
    """Load the webhook signing secret from Secrets Manager or env var."""
    secret = os.getenv("GITHUB_WEBHOOK_SECRET", "")
    if secret:
        return secret

    import boto3

    sm = boto3.client("secretsmanager", region_name=os.getenv("AWS_REGION", "us-east-1"))
    resp = sm.get_secret_value(SecretId="mergeguard/webhook-secret")
    return resp["SecretString"]


def generate_app_jwt(app_id: int, private_key: str) -> str:
    """Generate a signed JWT for authenticating as the GitHub App itself."""
    import jwt  # PyJWT

    now = int(time.time())
    payload = {
        "iat": now - 60,   # issued 60s ago (handles clock skew)
        "exp": now + 540,  # expires in 9 min (max 10)
        "iss": str(app_id),
    }
    return jwt.encode(payload, private_key, algorithm="RS256")


def get_installation_token(app_id: int, private_key: str, installation_id: int) -> str:
    """Exchange a GitHub App JWT for a short-lived installation access token."""
    app_jwt = generate_app_jwt(app_id, private_key)
    resp = httpx.post(
        f"{_GITHUB_API}/app/installations/{installation_id}/access_tokens",
        headers={
            "Authorization": f"Bearer {app_jwt}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        },
        timeout=30,
    )
    resp.raise_for_status()
    token: str = resp.json()["token"]
    log.debug("Got installation token for installation %d", installation_id)
    return token


def get_repo_installation_id(app_id: int, private_key: str, owner: str, repo: str) -> int:
    """Look up the installation ID for a given repo (used by feedback sync)."""
    app_jwt = generate_app_jwt(app_id, private_key)
    resp = httpx.get(
        f"{_GITHUB_API}/repos/{owner}/{repo}/installation",
        headers={
            "Authorization": f"Bearer {app_jwt}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        },
        timeout=30,
    )
    resp.raise_for_status()
    return int(resp.json()["id"])
