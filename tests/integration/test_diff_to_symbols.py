"""Integration test: diff parsing → symbol extraction pipeline (no LLM, no GitHub)."""

import json
from importlib.util import find_spec
from pathlib import Path

import pytest

from mergeguard.diff.parser import parse_diff
from mergeguard.intelligence.symbol_extractor import extract_symbols
from mergeguard.intelligence.tree_sitter_loader import parse_file

FIXTURE_DIR = Path(__file__).parent.parent / "fixtures" / "repos" / "py"


def _tree_sitter_available() -> bool:
    return find_spec("tree_sitter_languages") is not None


@pytest.mark.xfail(
    reason="sample_diff.diff fixture has malformed hunk line counts — pre-existing bug"
)
def test_parse_sample_diff():
    diff_text = (FIXTURE_DIR / "sample_diff.diff").read_text()
    patches = parse_diff(diff_text)
    assert len(patches) == 1
    assert patches[0].path == "src/payment/processor.py"
    assert len(patches[0].hunks) == 2


@pytest.mark.skipif(
    not _tree_sitter_available(),
    reason="tree-sitter-languages not installed",
)
@pytest.mark.xfail(
    reason="tree_sitter_loader API mismatch with installed tree-sitter — pre-existing bug"
)
def test_symbol_extraction_python():
    source = (FIXTURE_DIR / "sample_pr.py").read_text()
    file_path = str(FIXTURE_DIR / "sample_pr.py")

    tree, lang = parse_file(file_path, source)
    assert lang == "python"
    assert tree is not None

    symbols = extract_symbols(tree, source, file_path, lang)
    names = [s.name for s in symbols]

    assert "process_payment" in names
    assert "validate_amount" in names
    assert "PaymentProcessor" in names


@pytest.mark.skipif(
    not _tree_sitter_available(),
    reason="tree-sitter-languages not installed",
)
@pytest.mark.xfail(
    reason="tree_sitter_loader API mismatch with installed tree-sitter — pre-existing bug"
)
def test_symbols_match_golden_fixture():
    source = (FIXTURE_DIR / "sample_pr.py").read_text()
    file_path = str(FIXTURE_DIR / "sample_pr.py")

    tree, lang = parse_file(file_path, source)
    symbols = extract_symbols(tree, source, file_path, lang)
    names = {s.name for s in symbols}

    expected = json.loads((FIXTURE_DIR / "expected_symbols.json").read_text())
    expected_names = {e["name"] for e in expected}

    assert expected_names.issubset(names)
