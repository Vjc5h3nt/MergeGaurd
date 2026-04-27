"""Unit tests for scoring/impact.py."""

import pytest
from mergeguard.scoring.impact import (
    compute_blast_radius,
    impact_score,
    annotate_findings_with_impact,
)


def test_blast_radius_direct():
    graph = {
        "foo": ["bar", "baz"],
        "bar": [],
        "baz": [],
    }
    result = compute_blast_radius(["foo"], graph)
    assert "bar" in result["foo"]
    assert "baz" in result["foo"]


def test_blast_radius_transitive():
    graph = {
        "foo": ["bar"],
        "bar": ["baz"],
        "baz": [],
    }
    result = compute_blast_radius(["foo"], graph, max_depth=2)
    assert "bar" in result["foo"]
    assert "baz" in result["foo"]


def test_blast_radius_depth_limit():
    graph = {
        "a": ["b"],
        "b": ["c"],
        "c": ["d"],
        "d": [],
    }
    # depth=1: only immediate callers
    result = compute_blast_radius(["a"], graph, max_depth=1)
    assert "b" in result["a"]
    assert "c" not in result["a"]


def test_blast_radius_no_callers():
    result = compute_blast_radius(["foo"], {}, max_depth=3)
    assert result["foo"] == set()


def test_impact_score_zero():
    assert impact_score(0) == 0.0


def test_impact_score_one():
    score = impact_score(1)
    assert 0 < score <= 5


def test_impact_score_max():
    assert impact_score(10000) == 5.0


def test_annotate_findings_with_impact():
    findings = [
        {"severity": "HIGH", "category": "quality/complexity", "path": "src/foo.py"}
    ]
    called_by = {"src/foo.py::my_func": ["src/bar.py::caller"]}
    symbol_to_file = {"my_func": "src/foo.py"}
    annotated = annotate_findings_with_impact(findings, called_by, symbol_to_file)
    assert len(annotated) == 1
    assert "impact" in annotated[0]
    assert 0.0 <= annotated[0]["impact"] <= 5.0
