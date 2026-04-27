"""Unit tests for regression agent deterministic pre-checks."""

import pytest
from mergeguard.agents.regression import _deterministic_regression_checks, _normalize_params


def _patch(path, removed, added):
    return {
        "path": path,
        "is_deleted_file": False,
        "hunks": [{"removed": removed, "added": added}],
    }


def test_detects_removed_public_function():
    patches = [_patch("src/api.py", ["-def process_payment(amount, user_id):"], [])]
    findings = _deterministic_regression_checks(patches)
    assert any(f["category"] == "regression/removed-symbol" for f in findings)
    assert any("process_payment" in f["message"] for f in findings)


def test_ignores_removed_private_function():
    patches = [_patch("src/api.py", ["-def _internal_helper(x):"], [])]
    findings = _deterministic_regression_checks(patches)
    assert not any(f["category"] == "regression/removed-symbol" for f in findings)


def test_detects_signature_change():
    patches = [_patch(
        "src/api.py",
        ["-def charge(self, user_id, amount):"],
        ["+def charge(self, user_id, amount, currency):"],
    )]
    findings = _deterministic_regression_checks(patches)
    assert any(f["category"] == "regression/signature-change" for f in findings)
    assert any("charge" in f["message"] for f in findings)


def test_no_finding_when_params_unchanged():
    patches = [_patch(
        "src/api.py",
        ["-def charge(self, user_id: str, amount: float) -> bool:"],
        ["+def charge(self, user_id: str, amount: float) -> None:"],
    )]
    # Return type changes don't affect params — no signature-change finding
    findings = _deterministic_regression_checks(patches)
    assert not any(f["category"] == "regression/signature-change" for f in findings)


def test_detects_possible_rename():
    patches = [_patch(
        "src/utils.py",
        ["-def validate_input(data):"],
        ["+def validate_request(data):"],
    )]
    findings = _deterministic_regression_checks(patches)
    assert any(f["category"] == "regression/possible-rename" for f in findings)


def test_deleted_file_skipped():
    patches = [{
        "path": "src/old.py",
        "is_deleted_file": True,
        "hunks": [{"removed": ["-def foo():"], "added": []}],
    }]
    findings = _deterministic_regression_checks(patches)
    assert findings == []


def test_normalize_params_strips_types_and_defaults():
    assert _normalize_params("user_id: str, amount: float = 0.0") == "user_id, amount"
    assert _normalize_params("self, x: int") == "x"
    assert _normalize_params("*args, **kwargs") == ""


def test_high_severity_on_removed_symbol():
    patches = [_patch("src/payments.py", ["-def process(order):"], [])]
    findings = _deterministic_regression_checks(patches)
    removed = [f for f in findings if f["category"] == "regression/removed-symbol"]
    assert all(f["severity"] == "HIGH" for f in removed)


def test_deterministic_flag_set():
    patches = [_patch("src/api.py", ["-def send(msg):"], [])]
    findings = _deterministic_regression_checks(patches)
    assert all(f.get("deterministic") is True for f in findings)
