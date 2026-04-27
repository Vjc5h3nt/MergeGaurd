"""Unit tests for tools/risk_scorer.py."""

import pytest
from mergeguard.tools.risk_scorer import (
    _category_to_dimension,
    _score_to_bucket,
    compute_blast_radius_impact,
)


def test_score_to_bucket_blocking():
    assert _score_to_bucket(80) == "BLOCKING"
    assert _score_to_bucket(75) == "BLOCKING"


def test_score_to_bucket_high():
    assert _score_to_bucket(74) == "HIGH"
    assert _score_to_bucket(50) == "HIGH"


def test_score_to_bucket_medium():
    assert _score_to_bucket(49) == "MEDIUM"
    assert _score_to_bucket(25) == "MEDIUM"


def test_score_to_bucket_low():
    assert _score_to_bucket(24) == "LOW"
    assert _score_to_bucket(0) == "LOW"


def test_category_to_dimension_security():
    assert _category_to_dimension("security/sqli") == "security"
    assert _category_to_dimension("security/xss") == "security"


def test_category_to_dimension_complexity():
    assert _category_to_dimension("quality/complexity") == "complexity"
    assert _category_to_dimension("complexity/cyclomatic") == "complexity"


def test_category_to_dimension_architecture():
    assert _category_to_dimension("architecture/layer") == "architecture"
    assert _category_to_dimension("arch/boundary") == "architecture"


def test_category_to_dimension_unknown():
    assert _category_to_dimension("unknown/foo") == "complexity"


def test_blast_radius_impact_zero():
    assert compute_blast_radius_impact(0) == 0.0


def test_blast_radius_impact_small():
    score = compute_blast_radius_impact(1)
    assert 0 < score <= 5


def test_blast_radius_impact_large():
    score = compute_blast_radius_impact(1000)
    assert score == 5.0
