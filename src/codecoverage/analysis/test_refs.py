"""
Static test reference finder.

Given a source file and function name, finds the test functions
in the project that exercise it — pure static analysis, no LLM.

Strategy
--------
1. Use test_finder.find_test_files() to locate candidate test files via
   deterministic path-mirroring (e.g. tests/module/test_foo.py).
2. If that returns nothing (projects that organise tests by feature/flow
   rather than by source module), fall back to scanning every .py file
   inside known top-level test directories.
3. AST-parse each candidate and collect test functions whose source code
   contains a word-boundary match for the function name.
4. Return (rel_test_file, [test_func_names]) pairs.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path
from typing import Any, Dict, List, Set

from codecoverage.analysis.test_finder import find_test_files as _find_test_files

_TOP_LEVEL_TEST_DIRS = ("tests", "unit_tests", "test")
_IGNORE_DIRS = {"env", ".env", "venv", ".venv", "node_modules", "__pycache__", ".git"}


def find_test_refs(
    source_file: str,
    func_name: str,
    project_root: Path,
) -> List[Dict[str, Any]]:
    """
    Return test functions that reference *func_name* from *source_file*.

    Args:
        source_file:  Relative path to the source file (str).
        func_name:    Name of the function to search for.
        project_root: Absolute path to the project root.

    Returns:
        List of ``{"file": str, "tests": [str]}`` dicts, one per test file
        that contains at least one matching test function.  Empty if nothing
        found.
    """
    abs_source = project_root / source_file
    test_paths = _find_test_files(abs_source, project_root)

    # Fallback: scan all test files in known top-level test directories.
    # Handles projects that organise tests by feature rather than by source
    # module (e.g. unit_tests/tests/initiate_payment/test_gateway.py).
    if not test_paths:
        test_paths = _all_test_files(project_root)

    if not test_paths:
        return []

    pattern = re.compile(r"\b" + re.escape(func_name) + r"\b")
    refs: List[Dict[str, Any]] = []

    for test_path in test_paths:
        matching = _matching_tests(test_path, pattern)
        if matching:
            try:
                rel = str(test_path.relative_to(project_root))
            except ValueError:
                rel = str(test_path)
            refs.append({"file": rel, "tests": matching})

    return refs


def find_test_refs_for_label(
    source_file: str,
    label: str,
    project_root: Path,
) -> List[Dict[str, Any]]:
    """
    Like find_test_refs but uses the entry-point label (view class name or
    signal function name) rather than a specific method name.

    Used for flow/entry-point documentation.
    """
    return find_test_refs(source_file, label, project_root)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _all_test_files(project_root: Path) -> List[Path]:
    """
    Walk known top-level test directories and return .py files whose name
    starts with "test" or ends with "_test", skipping common non-source
    directories (env/, venv/, __pycache__/, etc.).
    """
    results: List[Path] = []
    for dir_name in _TOP_LEVEL_TEST_DIRS:
        test_root = project_root / dir_name
        if not test_root.is_dir():
            continue
        for path in test_root.rglob("*.py"):
            if any(part in _IGNORE_DIRS for part in path.parts):
                continue
            stem = path.stem
            if stem.startswith("test") or stem.endswith("_test"):
                results.append(path)
    return results


def _matching_tests(test_path: Path, pattern: re.Pattern) -> List[str]:
    """Return names of test functions in *test_path* that match *pattern*."""
    try:
        source = test_path.read_text(encoding="utf-8", errors="replace")
        tree = ast.parse(source, filename=str(test_path))
    except (SyntaxError, OSError):
        return []

    lines = source.splitlines()
    matches: List[str] = []

    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        name = node.name
        if not (name.startswith("test") or name.endswith("_test")):
            continue

        start = node.lineno - 1
        end = getattr(node, "end_lineno", node.lineno)
        func_source = "\n".join(lines[start:end])

        if pattern.search(func_source):
            matches.append(name)

    return matches
