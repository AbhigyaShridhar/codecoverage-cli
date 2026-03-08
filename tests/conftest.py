"""
Shared pytest fixtures for the codecontext test suite.
"""
from __future__ import annotations

from pathlib import Path
import pytest


@pytest.fixture
def tmp_project(tmp_path: Path) -> Path:
    """
    A temporary directory that looks like a minimal Python project:
      tmp_project/
        .codecoverage.toml
        src/
          calculator.py    — a simple module with a few functions
        tests/
          test_calculator.py  — matching test file
    """
    toml = tmp_path / ".codecoverage.toml"
    toml.write_text(
        "[project]\nname = 'test-project'\n\n"
        "[parsing]\nignore_patterns = ['venv/']\n\n"
        "[llm]\nmodel = 'claude-sonnet-4-6'\ntemperature = 0.0\n\n"
        "[generation]\nmax_retries = 3\n"
    )

    src = tmp_path / "src"
    src.mkdir()
    (src / "__init__.py").write_text("")
    (src / "calculator.py").write_text(
        '''\
def add(a: int, b: int) -> int:
    """Return the sum of two integers."""
    return a + b


def divide(a: float, b: float) -> float:
    """Return a divided by b. Raises ZeroDivisionError when b is zero."""
    if b == 0:
        raise ZeroDivisionError("Cannot divide by zero")
    return a / b


class Calculator:
    """Simple stateful calculator."""

    def __init__(self) -> None:
        self.history: list = []

    def add(self, a: int, b: int) -> int:
        result = a + b
        self.history.append(result)
        return result
'''
    )

    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    (tests_dir / "__init__.py").write_text("")
    (tests_dir / "test_calculator.py").write_text(
        '''\
import pytest
from src.calculator import add, divide


def test_add_positive():
    assert add(1, 2) == 3


def test_divide_by_zero():
    with pytest.raises(ZeroDivisionError):
        divide(1, 0)
'''
    )

    return tmp_path


@pytest.fixture
def tmp_project_no_tests(tmp_path: Path) -> Path:
    """A temporary project directory with source files but no test files."""
    (tmp_path / "module.py").write_text(
        "def hello(name: str) -> str:\n    return f'Hello, {name}'\n"
    )
    (tmp_path / ".codecoverage.toml").write_text(
        "[project]\nname = 'no-tests'\n\n"
        "[parsing]\nignore_patterns = []\n\n"
        "[llm]\nmodel = 'claude-sonnet-4-6'\ntemperature = 0.0\n\n"
        "[generation]\nmax_retries = 3\n"
    )
    return tmp_path
