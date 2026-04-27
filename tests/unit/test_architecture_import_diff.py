"""Unit tests for architecture agent import diff extraction."""

import pytest
from mergeguard.agents.architecture import _extract_import_diff


def _patch(path, added, removed=None):
    return {
        "path": path,
        "hunks": [{"added": added, "removed": removed or []}],
    }


def test_extracts_added_python_imports():
    patches = [_patch("src/api/views.py", ["+from app.database import db"])]
    result = _extract_import_diff(patches)
    assert "src/api/views.py" in result["added_imports"]
    assert any("database" in imp for imp in result["added_imports"]["src/api/views.py"])


def test_extracts_removed_python_imports():
    patches = [_patch("src/api/views.py", [], ["-import os"])]
    result = _extract_import_diff(patches)
    assert "src/api/views.py" in result["removed_imports"]


def test_builds_new_dependency_edges():
    patches = [_patch("src/web/handler.py", ["+from src.infra.db import session"])]
    result = _extract_import_diff(patches)
    assert len(result["new_dependencies"]) > 0
    assert any("→" in dep for dep in result["new_dependencies"])


def test_no_imports_returns_empty():
    patches = [_patch("src/utils.py", ["+x = 1", "+y = x + 2"])]
    result = _extract_import_diff(patches)
    assert result["added_imports"] == {}
    assert result["removed_imports"] == {}
    assert result["new_dependencies"] == []


def test_extracts_js_imports():
    patches = [_patch("src/app.ts", ["+import { db } from '../infra/database'"])]
    result = _extract_import_diff(patches)
    assert "src/app.ts" in result["added_imports"]
