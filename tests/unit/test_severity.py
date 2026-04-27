"""Unit tests for scoring/severity.py."""

import pytest
from mergeguard.scoring.severity import Severity, SEVERITY_SCORE_WEIGHTS


def test_severity_ordering():
    assert Severity.CRITICAL > Severity.HIGH > Severity.MEDIUM > Severity.LOW > Severity.INFO


def test_from_str_valid():
    assert Severity.from_str("critical") == Severity.CRITICAL
    assert Severity.from_str("HIGH") == Severity.HIGH
    assert Severity.from_str("medium") == Severity.MEDIUM


def test_from_str_invalid():
    assert Severity.from_str("garbage") == Severity.INFO


def test_score_weights_order():
    assert (
        SEVERITY_SCORE_WEIGHTS[Severity.CRITICAL]
        > SEVERITY_SCORE_WEIGHTS[Severity.HIGH]
        > SEVERITY_SCORE_WEIGHTS[Severity.MEDIUM]
        > SEVERITY_SCORE_WEIGHTS[Severity.LOW]
    )


def test_info_weight_is_zero():
    assert SEVERITY_SCORE_WEIGHTS[Severity.INFO] == 0
