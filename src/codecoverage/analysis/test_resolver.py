"""
Resolves where a generated test file should be written, based on the
existing test layout in the project.

Detection order:
  1. Find all project-owned test files (excluding venv, env, etc.)
  2. Identify the dominant test root (unit_tests/tests/, tests/, etc.)
  3. Mirror the source file's parent directory name under that root
  4. Fall back to <source_dir>/tests/test_<name>.py if no pattern found
"""

from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Optional


_IGNORE_DIRS = {
    "venv", "env", ".venv", "ENV", "node_modules", ".git",
    "__pycache__", ".pytest_cache", ".mypy_cache",
    "dist", "build", "migrations", "static", "site-packages",
}

_TEST_ROOT_NAMES = {"tests", "test", "unit_tests", "specs", "spec"}


def resolve_test_output_path(
    source_file: Path,
    project_root: Path,
    function_name: str = "",
) -> Path:
    """
    Return the Path where a generated test for *source_file* should be written.

    Args:
        source_file:   Absolute path to the source file being tested.
        project_root:  Absolute project root.
        function_name: Name of the function being tested (unused for path,
                       kept for future per-function file naming).

    Returns:
        Absolute path for the test file (parent dirs may not exist yet).
    """
    project_test_files = _find_project_test_files(project_root)

    if not project_test_files:
        return _fallback_path(source_file)

    test_root = _detect_test_root(project_test_files, project_root)

    if test_root is None:
        return _fallback_path(source_file)

    return _build_output_path(source_file, project_root, test_root)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _find_project_test_files(project_root: Path) -> list[Path]:
    """Return all test files under project_root, excluding venv/env dirs."""
    results = []
    for pattern in ("**/test_*.py", "**/*_test.py"):
        for p in project_root.glob(pattern):
            if not any(part in _IGNORE_DIRS for part in p.parts):
                results.append(p)
    return results


def _detect_test_root(test_files: list[Path], project_root: Path) -> Optional[Path]:
    """
    Walk up each test file's ancestry looking for a directory whose name is
    in _TEST_ROOT_NAMES.  Return the most frequently occurring such directory.
    """
    candidates: Counter = Counter()

    for tf in test_files:
        for parent in tf.parents:
            if parent == project_root or not str(parent).startswith(str(project_root)):
                break
            if parent.name.lower() in _TEST_ROOT_NAMES:
                candidates[parent] += 1
                break  # use the closest ancestor match per file

    if not candidates:
        return None

    return candidates.most_common(1)[0][0]


def _build_output_path(
    source_file: Path,
    project_root: Path,
    test_root: Path,
) -> Path:
    """
    Map source_file → test_root/<subdir>/test_<stem>.py.

    The subdir is the immediate parent directory of the source file,
    relative to the project root — e.g. for:
      project/payments/gateway/views.py  →  test_root/gateway/test_views.py
    """
    try:
        source_rel = source_file.relative_to(project_root)
    except ValueError:
        source_rel = Path(source_file.name)

    # Use the parent dir of the source file as the subdir name.
    # Strip top-level app directory to keep paths readable.
    parts = source_rel.parent.parts
    subdir = Path(*parts) if parts else Path(".")

    test_filename = f"test_{source_file.stem}.py"
    return test_root / subdir / test_filename


def _fallback_path(source_file: Path) -> Path:
    """No existing test layout found — put tests next to the source."""
    return source_file.parent / "tests" / f"test_{source_file.stem}.py"
