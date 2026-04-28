"""Unit tests for intelligence/change_classifier.py."""

from mergeguard.intelligence.change_classifier import (
    ChangeClass,
    _is_config_file,
    _is_docs_file,
    _is_test_file,
    classify_changes,
    summarize_classification,
)
from mergeguard.intelligence.symbol_extractor import Symbol


def _sym(
    name: str, file: str = "src/foo.py", sig: str = "def foo():", sig_hash: str = "abc"
) -> Symbol:
    return Symbol(
        name=name,
        kind="function",
        file=file,
        start_line=1,
        end_line=5,
        signature=sig,
        signature_hash=sig_hash,
        language="python",
    )


def test_removed_symbol_is_signature():
    base = [_sym("foo")]
    head: list[Symbol] = []
    deltas = classify_changes(base, head, [{"path": "src/foo.py", "status": "modified"}])
    assert any(d.change_class == ChangeClass.SIGNATURE for d in deltas)


def test_added_symbol_is_new_file():
    base: list[Symbol] = []
    head = [_sym("bar")]
    deltas = classify_changes(base, head, [{"path": "src/foo.py", "status": "added"}])
    assert any(d.change_class == ChangeClass.NEW_FILE for d in deltas)


def test_signature_changed():
    base = [_sym("foo", sig="def foo():", sig_hash="aaa")]
    head = [_sym("foo", sig="def foo(x: int):", sig_hash="bbb")]
    deltas = classify_changes(base, head, [{"path": "src/foo.py", "status": "modified"}])
    sig_deltas = [d for d in deltas if d.name == "foo"]
    assert sig_deltas
    assert sig_deltas[0].change_class == ChangeClass.SIGNATURE


def test_logic_changed_same_signature():
    base = [_sym("foo", sig="def foo():", sig_hash="aaa")]
    head = [_sym("foo", sig="def foo():", sig_hash="aaa")]
    # Same signature hash but file modified — no delta in symbols but...
    # change_classifier won't emit a delta for identical symbols:
    deltas = classify_changes(base, head, [{"path": "src/foo.py", "status": "modified"}])
    # change_classifier emits no delta for completely unchanged symbols;
    # the assertion below guards against a SIGNATURE delta for an unchanged sig.
    assert not any(d.change_class == ChangeClass.SIGNATURE and d.name == "foo" for d in deltas)


def test_new_file_status():
    deltas = classify_changes([], [], [{"path": "src/brand_new.py", "status": "added"}])
    assert any(d.change_class == ChangeClass.NEW_FILE for d in deltas)


def test_deleted_file_status():
    deltas = classify_changes([], [], [{"path": "src/old.py", "status": "removed"}])
    assert any(d.change_class == ChangeClass.DELETED for d in deltas)


def test_is_config_file():
    assert _is_config_file("config.yml")
    assert _is_config_file(".env")
    assert _is_config_file("Dockerfile")
    assert not _is_config_file("src/foo.py")


def test_is_test_file():
    assert _is_test_file("tests/test_foo.py")
    assert _is_test_file("src/foo_test.go")
    assert not _is_test_file("src/foo.py")


def test_is_docs_file():
    assert _is_docs_file("README.md")
    assert _is_docs_file("docs/architecture.md")
    assert not _is_docs_file("src/foo.py")


def test_summarize_classification():
    base = [_sym("foo", sig_hash="aaa")]
    head: list[Symbol] = []
    deltas = classify_changes(base, head, [{"path": "src/foo.py", "status": "modified"}])
    summary = summarize_classification(deltas)
    assert isinstance(summary, dict)
    assert len(summary) > 0
