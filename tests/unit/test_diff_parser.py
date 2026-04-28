"""Unit tests for diff/parser.py."""

from mergeguard.diff.parser import parse_diff

SIMPLE_DIFF = """\
diff --git a/src/foo.py b/src/foo.py
index abc1234..def5678 100644
--- a/src/foo.py
+++ b/src/foo.py
@@ -10,3 +10,4 @@ def existing():
     x = 1
-    return x
+    y = x + 1
+    return y
     # end
"""

NEW_FILE_DIFF = """\
diff --git a/src/new_file.py b/src/new_file.py
new file mode 100644
index 000..abc
--- /dev/null
+++ b/src/new_file.py
@@ -0,0 +1,3 @@
+def hello():
+    return "world"
+
"""

DELETED_FILE_DIFF = """\
diff --git a/src/old.py b/src/old.py
deleted file mode 100644
index abc..000
--- a/src/old.py
+++ /dev/null
@@ -1,2 +0,0 @@
-def goodbye():
-    pass
"""


def test_parse_simple_diff():
    patches = parse_diff(SIMPLE_DIFF)
    assert len(patches) == 1
    patch = patches[0]
    assert patch.path == "src/foo.py"
    assert not patch.is_new_file
    assert not patch.is_deleted_file
    assert len(patch.hunks) == 1


def test_parse_simple_diff_lines():
    patches = parse_diff(SIMPLE_DIFF)
    hunk = patches[0].hunks[0]
    # One removed line (-return x) and two added lines (+y = x+1, +return y)
    assert len(hunk.removed_lines) == 1
    assert len(hunk.added_lines) == 2


def test_parse_new_file():
    patches = parse_diff(NEW_FILE_DIFF)
    assert len(patches) == 1
    assert patches[0].is_new_file
    assert patches[0].path == "src/new_file.py"


def test_parse_deleted_file():
    patches = parse_diff(DELETED_FILE_DIFF)
    assert len(patches) == 1
    assert patches[0].is_deleted_file


def test_parse_empty_diff():
    patches = parse_diff("")
    assert patches == []


def test_added_line_numbers():
    patches = parse_diff(SIMPLE_DIFF)
    added = patches[0].added_line_numbers
    assert len(added) == 2
    # Both added lines should be >= hunk target_start
    assert all(ln >= 10 for ln in added)


def test_removed_line_numbers():
    patches = parse_diff(SIMPLE_DIFF)
    removed = patches[0].removed_line_numbers
    assert len(removed) == 1


def test_parse_invalid_diff():
    patches = parse_diff("this is not a diff")
    assert patches == []
