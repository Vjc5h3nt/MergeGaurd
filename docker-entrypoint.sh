#!/usr/bin/env bash
set -euo pipefail

# Resolve PR reference from GitHub Actions environment
OWNER="${REPO_OWNER:-}"
REPO="${REPO_NAME:-}"
PR="${PR_NUMBER:-}"
DRY_RUN_FLAG=""

if [[ "${DRY_RUN:-false}" == "true" ]]; then
  DRY_RUN_FLAG="--dry-run"
fi

if [[ -z "$OWNER" || -z "$REPO" || -z "$PR" ]]; then
  echo "ERROR: REPO_OWNER, REPO_NAME, and PR_NUMBER must be set." >&2
  exit 1
fi

exec mergeguard review \
  --pr "${OWNER}/${REPO}#${PR}" \
  ${DRY_RUN_FLAG}
