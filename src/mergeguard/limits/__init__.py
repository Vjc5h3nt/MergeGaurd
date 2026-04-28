"""Per-installation rate limiting for MergeGuard public GitHub App."""

from mergeguard.limits.rate_limiter import check_and_increment, get_current_count

__all__ = ["check_and_increment", "get_current_count"]
