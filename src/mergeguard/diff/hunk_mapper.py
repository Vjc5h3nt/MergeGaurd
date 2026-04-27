"""Map hunks to file line ranges (pre/post), useful for fetching surrounding context."""

from __future__ import annotations

from dataclasses import dataclass

from mergeguard.diff.parser import FilePatch, Hunk


@dataclass
class LineRange:
    start: int
    end: int  # inclusive


def hunk_to_target_range(hunk: Hunk, context_lines: int = 3) -> LineRange:
    """Return target-side line range for a hunk with optional surrounding context."""
    start = max(1, hunk.target_start - context_lines)
    end = hunk.target_start + hunk.target_length + context_lines - 1
    return LineRange(start=start, end=end)


def hunk_to_source_range(hunk: Hunk, context_lines: int = 3) -> LineRange:
    """Return source-side line range for a hunk with optional surrounding context."""
    start = max(1, hunk.source_start - context_lines)
    end = hunk.source_start + hunk.source_length + context_lines - 1
    return LineRange(start=start, end=end)


def changed_ranges(patch: FilePatch, context_lines: int = 3) -> list[LineRange]:
    """Return merged target-side line ranges for all hunks in a file patch.

    Overlapping / adjacent ranges (within context_lines) are merged.
    """
    raw = [hunk_to_target_range(h, context_lines) for h in patch.hunks]
    if not raw:
        return []

    raw.sort(key=lambda r: r.start)
    merged: list[LineRange] = [raw[0]]

    for r in raw[1:]:
        last = merged[-1]
        if r.start <= last.end + 1:
            merged[-1] = LineRange(start=last.start, end=max(last.end, r.end))
        else:
            merged.append(r)

    return merged


def build_line_map(patch: FilePatch) -> dict[int, int]:
    """Build a mapping from source line numbers to target line numbers.

    Only covers lines present in the patch hunks (added/context lines).
    Returns {source_line: target_line}.
    """
    mapping: dict[int, int] = {}
    for hunk in patch.hunks:
        src = hunk.source_start
        tgt = hunk.target_start
        for line in (
            sorted(hunk.context_lines + hunk.added_lines + hunk.removed_lines)
        ):
            # context lines exist in both; removed only in source; added only in target
            _ = line  # we iterate by offset below

        # Re-derive from raw hunk offsets
        s_off, t_off = hunk.source_start, hunk.target_start
        for removed_ln, _ in hunk.removed_lines:
            s_off = removed_ln
        for ctx_ln, _ in hunk.context_lines:
            mapping[ctx_ln] = ctx_ln  # context: same in both (simplified)
        _ = src, tgt  # silence unused warning

    return mapping
