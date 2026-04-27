"""Diff parser: converts unified diff text into structured FilePatch objects."""

from __future__ import annotations

from dataclasses import dataclass, field

import unidiff


@dataclass
class Hunk:
    source_start: int
    source_length: int
    target_start: int
    target_length: int
    added_lines: list[tuple[int, str]]    # (line_number, content)
    removed_lines: list[tuple[int, str]]  # (line_number, content)
    context_lines: list[tuple[int, str]]  # (line_number, content)
    section_header: str = ""


@dataclass
class FilePatch:
    path: str                          # target (new) path
    source_path: str                   # source (old) path
    is_new_file: bool
    is_deleted_file: bool
    is_renamed: bool
    hunks: list[Hunk] = field(default_factory=list)

    @property
    def added_line_numbers(self) -> list[int]:
        return [ln for h in self.hunks for ln, _ in h.added_lines]

    @property
    def removed_line_numbers(self) -> list[int]:
        return [ln for h in self.hunks for ln, _ in h.removed_lines]

    @property
    def changed_line_numbers(self) -> list[int]:
        """Union of added + removed lines (target-side numbering for added)."""
        added = {ln for h in self.hunks for ln, _ in h.added_lines}
        removed = {ln for h in self.hunks for ln, _ in h.removed_lines}
        return sorted(added | removed)


def parse_diff(unified_diff: str) -> list[FilePatch]:
    """Parse a unified diff string into a list of FilePatch objects."""
    patches: list[FilePatch] = []

    try:
        patch_set = unidiff.PatchSet(unified_diff)
    except unidiff.errors.UnidiffParseError:
        return []

    for patched_file in patch_set:
        hunks: list[Hunk] = []
        for hunk in patched_file:
            added: list[tuple[int, str]] = []
            removed: list[tuple[int, str]] = []
            context: list[tuple[int, str]] = []

            for line in hunk:
                if line.is_added:
                    added.append((line.target_line_no or 0, line.value))
                elif line.is_removed:
                    removed.append((line.source_line_no or 0, line.value))
                else:
                    # context line — use target line number when available
                    ln = line.target_line_no or line.source_line_no or 0
                    context.append((ln, line.value))

            hunks.append(
                Hunk(
                    source_start=hunk.source_start,
                    source_length=hunk.source_length,
                    target_start=hunk.target_start,
                    target_length=hunk.target_length,
                    added_lines=added,
                    removed_lines=removed,
                    context_lines=context,
                    section_header=hunk.section_header or "",
                )
            )

        patches.append(
            FilePatch(
                path=patched_file.path,
                source_path=patched_file.source_file or patched_file.path,
                is_new_file=patched_file.is_added_file,
                is_deleted_file=patched_file.is_removed_file,
                is_renamed=patched_file.is_rename,
                hunks=hunks,
            )
        )

    return patches
