"""Unit tests for diff/hunk_mapper.py."""

import pytest
from mergeguard.diff.hunk_mapper import LineRange, changed_ranges, hunk_to_target_range
from mergeguard.diff.parser import Hunk, FilePatch


def _make_hunk(target_start: int, target_length: int) -> Hunk:
    return Hunk(
        source_start=target_start,
        source_length=target_length,
        target_start=target_start,
        target_length=target_length,
        added_lines=[(target_start, "+line\n")],
        removed_lines=[],
        context_lines=[],
    )


def _make_patch(hunks: list[Hunk]) -> FilePatch:
    return FilePatch(
        path="src/test.py",
        source_path="src/test.py",
        is_new_file=False,
        is_deleted_file=False,
        is_renamed=False,
        hunks=hunks,
    )


def test_hunk_to_target_range_basic():
    hunk = _make_hunk(target_start=20, target_length=5)
    r = hunk_to_target_range(hunk, context_lines=0)
    assert r.start == 20
    assert r.end == 24  # 20 + 5 - 1


def test_hunk_to_target_range_with_context():
    hunk = _make_hunk(target_start=20, target_length=5)
    r = hunk_to_target_range(hunk, context_lines=3)
    assert r.start == 17
    assert r.end == 27


def test_changed_ranges_single_hunk():
    patch = _make_patch([_make_hunk(10, 3)])
    ranges = changed_ranges(patch, context_lines=0)
    assert len(ranges) == 1
    assert ranges[0].start == 10


def test_changed_ranges_merges_overlapping():
    hunks = [_make_hunk(10, 3), _make_hunk(12, 3)]  # overlapping
    patch = _make_patch(hunks)
    ranges = changed_ranges(patch, context_lines=0)
    assert len(ranges) == 1  # merged into one


def test_changed_ranges_keeps_separate():
    hunks = [_make_hunk(10, 2), _make_hunk(50, 2)]  # far apart
    patch = _make_patch(hunks)
    ranges = changed_ranges(patch, context_lines=0)
    assert len(ranges) == 2


def test_changed_ranges_empty_patch():
    patch = _make_patch([])
    ranges = changed_ranges(patch)
    assert ranges == []
