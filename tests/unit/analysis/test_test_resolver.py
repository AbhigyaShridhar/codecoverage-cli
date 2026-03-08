"""
Unit tests for codecontext.analysis.test_resolver.

Tests the automatic test output path detection logic — no LLM calls.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from codecoverage.analysis.test_resolver import (
    resolve_test_output_path,
    _find_project_test_files,
    _detect_test_root,
    _build_output_path,
    _fallback_path,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _touch(path: Path, content: str = "# test\n") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    return path


# ---------------------------------------------------------------------------
# _find_project_test_files
# ---------------------------------------------------------------------------

class TestFindProjectTestFiles:

    def test_finds_test_prefix_files(self, tmp_path):
        _touch(tmp_path / "tests" / "test_foo.py")
        results = _find_project_test_files(tmp_path)
        assert any("test_foo.py" in str(p) for p in results)

    def test_finds_test_suffix_files(self, tmp_path):
        _touch(tmp_path / "tests" / "foo_test.py")
        results = _find_project_test_files(tmp_path)
        assert any("foo_test.py" in str(p) for p in results)

    def test_excludes_venv(self, tmp_path):
        _touch(tmp_path / "venv" / "lib" / "test_something.py")
        _touch(tmp_path / "tests" / "test_real.py")
        results = _find_project_test_files(tmp_path)
        # Check that the venv-nested file is absent and the real one is present.
        # Use parts-level check to avoid false match from "venv" in the test name
        # appearing in the tmp_path directory itself.
        venv_file = (tmp_path / "venv" / "lib" / "test_something.py").resolve()
        assert venv_file not in [r.resolve() for r in results]
        assert any("test_real.py" in str(p) for p in results)

    def test_excludes_site_packages(self, tmp_path):
        _touch(tmp_path / "site-packages" / "test_pkg.py")
        results = _find_project_test_files(tmp_path)
        assert not any("site-packages" in str(p) for p in results)

    def test_empty_project_returns_empty(self, tmp_path):
        (tmp_path / "module.py").write_text("def f(): pass\n")
        results = _find_project_test_files(tmp_path)
        assert results == []

    def test_finds_nested_test_files(self, tmp_path):
        _touch(tmp_path / "unit_tests" / "tests" / "payments" / "test_gateway.py")
        results = _find_project_test_files(tmp_path)
        assert any("test_gateway.py" in str(p) for p in results)


# ---------------------------------------------------------------------------
# _detect_test_root
# ---------------------------------------------------------------------------

class TestDetectTestRoot:

    def test_detects_tests_dir(self, tmp_path):
        files = [_touch(tmp_path / "tests" / f"test_{i}.py") for i in range(3)]
        root = _detect_test_root(files, tmp_path)
        assert root is not None
        assert root.name == "tests"

    def test_detects_unit_tests_dir(self, tmp_path):
        files = [
            _touch(tmp_path / "unit_tests" / "tests" / f"test_{i}.py")
            for i in range(3)
        ]
        root = _detect_test_root(files, tmp_path)
        assert root is not None
        # Closest ancestor named in _TEST_ROOT_NAMES is "tests"
        assert root.name == "tests"

    def test_picks_most_common_root(self, tmp_path):
        # 3 files under tests/, 1 under spec/
        for i in range(3):
            _touch(tmp_path / "tests" / f"test_{i}.py")
        _touch(tmp_path / "spec" / "test_other.py")
        files = _find_project_test_files(tmp_path)
        root = _detect_test_root(files, tmp_path)
        assert root is not None
        assert root.name == "tests"

    def test_returns_none_for_empty_list(self, tmp_path):
        root = _detect_test_root([], tmp_path)
        assert root is None

    def test_returns_none_when_no_named_root(self, tmp_path):
        # Test file is directly under tmp_path — no ancestor named tests/etc.
        files = [_touch(tmp_path / "test_foo.py")]
        root = _detect_test_root(files, tmp_path)
        assert root is None


# ---------------------------------------------------------------------------
# _build_output_path
# ---------------------------------------------------------------------------

class TestBuildOutputPath:

    def test_simple_source_mirrors_to_test_root(self, tmp_path):
        test_root = tmp_path / "tests"
        source = tmp_path / "payments" / "gateway.py"
        result = _build_output_path(source, tmp_path, test_root)
        assert result == test_root / "payments" / "test_gateway.py"

    def test_nested_source_mirrors_full_path(self, tmp_path):
        test_root = tmp_path / "unit_tests" / "tests"
        source = tmp_path / "payments" / "interface_layer" / "views.py"
        result = _build_output_path(source, tmp_path, test_root)
        assert result == test_root / "payments" / "interface_layer" / "test_views.py"

    def test_top_level_source_maps_to_test_root_directly(self, tmp_path):
        test_root = tmp_path / "tests"
        source = tmp_path / "utils.py"
        result = _build_output_path(source, tmp_path, test_root)
        assert result == test_root / "test_utils.py"

    def test_output_filename_has_test_prefix(self, tmp_path):
        test_root = tmp_path / "tests"
        source = tmp_path / "module.py"
        result = _build_output_path(source, tmp_path, test_root)
        assert result.name == "test_module.py"


# ---------------------------------------------------------------------------
# _fallback_path
# ---------------------------------------------------------------------------

class TestFallbackPath:

    def test_places_test_next_to_source(self, tmp_path):
        source = tmp_path / "src" / "payments" / "gateway.py"
        result = _fallback_path(source)
        assert result == source.parent / "tests" / "test_gateway.py"


# ---------------------------------------------------------------------------
# resolve_test_output_path — end-to-end
# ---------------------------------------------------------------------------

class TestResolveTestOutputPath:

    def test_returns_fallback_when_no_existing_tests(self, tmp_path):
        source = tmp_path / "src" / "module.py"
        source.parent.mkdir(parents=True)
        source.write_text("def f(): pass\n")
        result = resolve_test_output_path(source, tmp_path)
        # Falls back to <source_dir>/tests/test_module.py
        assert result == source.parent / "tests" / "test_module.py"

    def test_detects_tests_root_and_mirrors_path(self, tmp_path):
        # Create an existing test file to establish the test root
        _touch(tmp_path / "tests" / "test_existing.py")
        source = tmp_path / "payments" / "gateway.py"
        source.parent.mkdir(parents=True)
        source.write_text("def process(): pass\n")
        result = resolve_test_output_path(source, tmp_path)
        assert result == tmp_path / "tests" / "payments" / "test_gateway.py"

    def test_detects_unit_tests_root(self, tmp_path):
        for i in range(2):
            _touch(tmp_path / "unit_tests" / "tests" / f"test_{i}.py")
        source = tmp_path / "src" / "core.py"
        source.parent.mkdir(parents=True)
        source.write_text("def run(): pass\n")
        result = resolve_test_output_path(source, tmp_path)
        expected_root = tmp_path / "unit_tests" / "tests"
        assert result.is_relative_to(expected_root)
        assert result.name == "test_core.py"

    def test_function_name_arg_does_not_change_path(self, tmp_path):
        _touch(tmp_path / "tests" / "test_existing.py")
        source = tmp_path / "mod.py"
        source.write_text("def f(): pass\n")
        result_with = resolve_test_output_path(source, tmp_path, function_name="f")
        result_without = resolve_test_output_path(source, tmp_path)
        assert result_with == result_without
