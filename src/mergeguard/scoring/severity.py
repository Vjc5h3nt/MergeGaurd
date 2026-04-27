"""Severity model and rubric for MergeGuard findings."""

from __future__ import annotations

from enum import IntEnum


class Severity(IntEnum):
    CRITICAL = 5
    HIGH = 4
    MEDIUM = 3
    LOW = 2
    INFO = 1

    @classmethod
    def from_str(cls, value: str) -> "Severity":
        try:
            return cls[value.upper()]
        except KeyError:
            return cls.INFO


# Human-readable rubric used in agent system prompts
SEVERITY_RUBRIC = {
    Severity.CRITICAL: (
        "Direct exploitability with serious impact (RCE, data breach, hardcoded credentials). "
        "Merge MUST be blocked."
    ),
    Severity.HIGH: (
        "Likely exploitable or causes clear functional breakage. "
        "Merge should be blocked pending fix."
    ),
    Severity.MEDIUM: (
        "Exploitable under specific conditions, or degrades code quality significantly. "
        "Should be addressed before merge."
    ),
    Severity.LOW: (
        "Minor issue or improvement opportunity. Address if convenient, "
        "does not block merge."
    ),
    Severity.INFO: (
        "Informational observation with no direct risk. For developer awareness only."
    ),
}

# Weights for risk score calculation
SEVERITY_SCORE_WEIGHTS: dict[Severity, int] = {
    Severity.CRITICAL: 15,
    Severity.HIGH: 8,
    Severity.MEDIUM: 3,
    Severity.LOW: 1,
    Severity.INFO: 0,
}
