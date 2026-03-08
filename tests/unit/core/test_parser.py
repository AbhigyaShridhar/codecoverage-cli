"""
Unit tests for codecontext.core.parser — CodebaseParser and helpers.

All tests are pure-filesystem (tmp_path), no LLM calls.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from codecoverage.core.parser import CodebaseParser, extract_decorator_details


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _write(path: Path, content: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    return path


def _parse_one(tmp_path: Path, content: str) -> "FileInfo":
    src = tmp_path / "module.py"
    _write(src, content)
    parser = CodebaseParser(root=tmp_path, ignore_patterns=[])
    codebase = parser.parse()
    key = next(k for k in codebase.files if "module.py" in str(k))
    return codebase.files[key]


# ---------------------------------------------------------------------------
# CodebaseParser — basic parsing
# ---------------------------------------------------------------------------

class TestCodebaseParserBasics:

    def test_parse_empty_project(self, tmp_path):
        parser = CodebaseParser(root=tmp_path, ignore_patterns=[])
        codebase = parser.parse()
        assert codebase.total_files == 0
        assert codebase.total_functions == 0
        assert codebase.total_classes == 0

    def test_parse_single_function(self, tmp_path):
        _write(tmp_path / "foo.py", "def greet(name): return f'hi {name}'")
        parser = CodebaseParser(root=tmp_path, ignore_patterns=[])
        codebase = parser.parse()
        assert codebase.total_files == 1
        assert codebase.total_functions == 1

    def test_function_name_captured(self, tmp_path):
        fi = _parse_one(tmp_path, "def my_func(): pass")
        assert any(f.name == "my_func" for f in fi.functions)

    def test_multiple_functions(self, tmp_path):
        code = "def a(): pass\ndef b(): pass\ndef c(): pass\n"
        fi = _parse_one(tmp_path, code)
        names = {f.name for f in fi.functions}
        assert names == {"a", "b", "c"}

    def test_class_captured(self, tmp_path):
        code = "class MyClass:\n    def method(self): pass\n"
        fi = _parse_one(tmp_path, code)
        assert any(c.name == "MyClass" for c in fi.classes)

    def test_class_method_captured(self, tmp_path):
        code = "class Calc:\n    def add(self, a, b):\n        return a + b\n"
        fi = _parse_one(tmp_path, code)
        cls = next(c for c in fi.classes if c.name == "Calc")
        assert any(m.name == "add" for m in cls.methods)

    def test_counts_aggregate_across_files(self, tmp_path):
        _write(tmp_path / "a.py", "def f(): pass\n")
        _write(tmp_path / "b.py", "def g(): pass\ndef h(): pass\n")
        parser = CodebaseParser(root=tmp_path, ignore_patterns=[])
        codebase = parser.parse()
        assert codebase.total_files == 2
        assert codebase.total_functions == 3


class TestCodebaseParserIgnorePatterns:

    def test_ignores_venv_directory(self, tmp_path):
        _write(tmp_path / "venv" / "lib.py", "def hidden(): pass\n")
        _write(tmp_path / "src.py", "def visible(): pass\n")
        parser = CodebaseParser(root=tmp_path, ignore_patterns=["venv/"])
        codebase = parser.parse()
        assert codebase.total_files == 1

    def test_ignores_pyc_files(self, tmp_path):
        _write(tmp_path / "module.pyc", "garbage")
        _write(tmp_path / "module.py", "def f(): pass\n")
        parser = CodebaseParser(root=tmp_path, ignore_patterns=["*.pyc"])
        codebase = parser.parse()
        assert codebase.total_files == 1

    def test_ignores_multiple_patterns(self, tmp_path):
        _write(tmp_path / "env" / "pkg.py", "def hidden(): pass\n")
        _write(tmp_path / "build" / "out.py", "def hidden(): pass\n")
        _write(tmp_path / "app.py", "def visible(): pass\n")
        parser = CodebaseParser(root=tmp_path, ignore_patterns=["env/", "build/"])
        codebase = parser.parse()
        assert codebase.total_files == 1

    def test_syntax_error_file_skipped_gracefully(self, tmp_path):
        _write(tmp_path / "bad.py", "def broken(\n")
        _write(tmp_path / "good.py", "def fine(): pass\n")
        parser = CodebaseParser(root=tmp_path, ignore_patterns=[])
        codebase = parser.parse()
        # bad.py is skipped, good.py is parsed
        assert codebase.total_files == 1
        assert codebase.total_functions == 1


# ---------------------------------------------------------------------------
# extract_decorator_details
# ---------------------------------------------------------------------------

class TestExtractDecoratorDetails:

    def test_bare_decorator(self, tmp_path):
        fi = _parse_one(tmp_path, "@staticmethod\ndef f(): pass\n")
        fn = next(f for f in fi.functions if f.name == "f")
        details = fn.decorator_details
        assert any(d["name"] == "staticmethod" for d in details)

    def test_call_decorator_no_args(self, tmp_path):
        fi = _parse_one(tmp_path, "@property\ndef val(self): return 1\n")
        fn = next(f for f in fi.functions if f.name == "val")
        assert any(d["name"] == "property" for d in fn.decorator_details)

    def test_decorator_with_args(self, tmp_path):
        code = (
            "import pytest\n"
            "@pytest.mark.parametrize('x', [1, 2])\n"
            "def test_it(x): pass\n"
        )
        fi = _parse_one(tmp_path, code)
        fn = next(f for f in fi.functions if f.name == "test_it")
        details = fn.decorator_details
        assert len(details) >= 1
        names = [d["name"] for d in details]
        assert any("parametrize" in n for n in names)

    def test_decorator_with_keyword_args(self, tmp_path):
        code = (
            "@app.route('/path', methods=['GET', 'POST'])\n"
            "def view(): pass\n"
        )
        fi = _parse_one(tmp_path, code)
        fn = next(f for f in fi.functions if f.name == "view")
        details = fn.decorator_details
        assert len(details) >= 1

    def test_multiple_decorators(self, tmp_path):
        code = (
            "@login_required\n"
            "@permission_required('admin')\n"
            "def admin_view(): pass\n"
        )
        fi = _parse_one(tmp_path, code)
        fn = next(f for f in fi.functions if f.name == "admin_view")
        assert len(fn.decorator_details) == 2

    def test_no_decorators(self, tmp_path):
        fi = _parse_one(tmp_path, "def plain(): pass\n")
        fn = next(f for f in fi.functions if f.name == "plain")
        assert fn.decorator_details == []

    def test_extract_decorator_details_standalone(self):
        """extract_decorator_details helper works on a raw code string."""
        code = "@cached_property\ndef expensive(self): return 42\n"
        import ast
        tree = ast.parse(code)
        func_node = tree.body[0]
        details = extract_decorator_details(func_node)
        assert len(details) == 1
        assert details[0]["name"] == "cached_property"
