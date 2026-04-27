---
name: Review format feedback
description: What worked and what didn't when iterating on the GitHub review comment format
type: feedback
---

Do not use colored GitHub Alert boxes (`[!CAUTION]`, `[!WARNING]`, `[!NOTE]`) in the review comment — user found them visually noisy.

**Why:** User prefers clean professional formatting. *italic* severity and `inline code` category is the right style.

**How to apply:** Use plain markdown + `<details>`/`<summary>` for collapsing. Never use `> [!WARNING]` style blocks in the review body.

---

Do not use triangle or arrow HTML entities (`&#9660;`, `&#9658;`) as expand/collapse icons in `<summary>` tags.

**Why:** User explicitly rejected these. They look cluttered.

**How to apply:** Use plain text in `<summary>` tags, or `&bull;` minimally. No decorative arrow icons.

---

Do not use `•` dots (bullet symbols) heavily throughout the comment as section markers.

**Why:** User said "you are using them frequently" — overuse makes it look noisy.

**How to apply:** Use sparingly or not at all. Plain headings and `<details>` are sufficient.

---

Do not show `+N −N` line counts anywhere in the review comment.

**Why:** User explicitly asked to remove these — they add noise without value.

**How to apply:** Never include `+37 −0` or similar diff stats in the Changes list or Reviewed changes table.

---

The last attempted change (2026-04-28) that added tree-structure to low-confidence section + brief inline messages was reverted — user said "it's worst".

**Why:** Making comment messages too brief lost important context. The nested `<details open>` per comment inside file groups was likely the issue.

**How to apply:** Keep the current format (comments as full text under file group, suggestion in nested details). If revisiting low-confidence tree structure, test carefully before deploying — do not make all comments into `<details>` with just the first sentence as summary.

---

The Copilot-inspired format (overview → changes → reviewed changes table → comments by file) is well received.

**Why:** User provided the Copilot format as the reference and asked to follow it with "our touch".

**How to apply:** Keep this overall structure. MergeGuard additions: risk score in header, `🔒` static badge, `⚡ blast radius` score. These are positively received.
