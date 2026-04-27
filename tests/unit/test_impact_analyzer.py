"""Unit tests for tools/impact_analyzer.py."""

import pytest
from mergeguard.tools.impact_analyzer import _build_called_by_graph, _build_symbol_to_file


def _patch(path, added, removed=None):
    return {
        "path": path,
        "hunks": [{"added": added, "removed": removed or []}],
    }


def test_symbol_to_file_extracts_added_functions():
    patches = [_patch("src/api.py", ["+def process_payment(amount):"])]
    s2f = _build_symbol_to_file(patches)
    assert "src/api.py::process_payment" in s2f
    assert s2f["src/api.py::process_payment"] == "src/api.py"


def test_symbol_to_file_extracts_removed_functions():
    patches = [_patch("src/api.py", [], ["-def old_process(amount):"])]
    s2f = _build_symbol_to_file(patches)
    assert "src/api.py::old_process" in s2f


def test_symbol_to_file_extracts_classes():
    patches = [_patch("src/models.py", ["+class PaymentProcessor:"])]
    s2f = _build_symbol_to_file(patches)
    assert "src/models.py::PaymentProcessor" in s2f


def test_called_by_graph_infers_edges():
    patches = [_patch("src/api.py", [
        "+def handle_request(req):",
        "+    result = process_payment(req.amount)",
        "+    return result",
    ])]
    cbg = _build_called_by_graph(patches)
    # process_payment should have handle_request as a caller
    callers = cbg.get("src/api.py::process_payment", [])
    assert "src/api.py::handle_request" in callers


def test_called_by_graph_ignores_builtins():
    patches = [_patch("src/api.py", [
        "+def my_func(x):",
        "+    return str(len(x))",
    ])]
    cbg = _build_called_by_graph(patches)
    # builtins str/len should NOT appear
    assert "src/api.py::str" not in cbg
    assert "src/api.py::len" not in cbg


def test_empty_patches_return_empty_graph():
    assert _build_called_by_graph([]) == {}
    assert _build_symbol_to_file([]) == {}
