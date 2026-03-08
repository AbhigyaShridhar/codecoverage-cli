"""
Module-level test file discovery and style extraction.

Given a source file (e.g. payments/gateway.py), finds the test file(s)
that exercise it and extracts enough style information for the agent to
replicate the project's test conventions exactly.

Design
------
Discovery uses deterministic lookups in priority order — no file-system
walks that could be slow on large projects.  The caller gets back a list
of (Path, TestFileContext) pairs ordered by relevance; the agent uses
the first match as the authoritative style reference.

Conventions searched (in order):
  1. Same package dir        →  test_<stem>.py, <stem>_test.py
  2. tests/ subpackage       →  tests/test_<stem>.py
  3. Django-style            →  tests.py or test.py in the same package
  4. Top-level mirrors       →  {tests,unit_tests,test}/<rel_path>/test_<stem>.py
  4c. Nested subdirs         →  {tests,unit_tests,test}/{unit,integration,...}/<rel_path>/test_<stem>.py
  5. Top-level flat          →  {tests,unit_tests,test}/test_<stem>.py
  6. src-stripped mirror     →  same as 4/4c but with the leading "src/" segment removed
  7. doubly-stripped mirror  →  same as 4/4c but with "src/<pkg>/" stripped (e.g. src/pkg/sub/ → tests/sub/)
"""

import ast
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class TestFileContext:
    """
    Extracted style information from a single test file.

    The agent consumes this verbatim: it tells the agent *exactly* what
    imports to use, what base class to inherit, how fixtures are written,
    and provides concrete function examples to imitate.
    """

    # Location
    test_file: Path

    # Raw source (truncated for very large files)
    source_code: str

    # Structural info
    imports: List[str]          = field(default_factory=list)
    base_classes: List[str]     = field(default_factory=list)

    # Detected conventions
    framework: str      = "pytest"    # "pytest" | "unittest" | "custom"
    fixture_style: str  = "none"      # "pytest_fixture" | "setUp" | "custom" | "none"
    mock_style: str     = "none"      # "unittest.mock" | "pytest_mock" | "custom" | "none"

    # Concrete code examples (ready to paste and adapt)
    example_functions: List[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------

_TOP_LEVEL_TEST_DIRS = ("tests", "unit_tests", "test")

# Common first-level subdirectories inside top-level test directories.
# e.g. tests/unit/, tests/integration/, unit_tests/tests/
_TEST_SUBDIRS = ("unit", "integration", "functional", "e2e", "tests")


def find_test_files(source_file: Path, project_root: Path) -> List[Path]:
    """
    Return test files that correspond to *source_file*, ordered by relevance.

    The first item in the list is the most specific match (same package).
    All paths in the return value are guaranteed to exist.

    Args:
        source_file:  Absolute (or resolvable) path to the source .py file.
        project_root: Absolute path to the project root directory.

    Returns:
        List of existing test file paths; empty list if none found.
    """
    source_file  = source_file.resolve()
    project_root = project_root.resolve()
    stem         = source_file.stem          # e.g. "gateway" from "gateway.py"
    same_dir     = source_file.parent

    seen: List[Path] = []

    def _add(p: Path) -> None:
        p = p.resolve()
        if p.exists() and p not in seen:
            seen.append(p)

    # ------------------------------------------------------------------
    # 1. Same package directory
    # ------------------------------------------------------------------
    _add(same_dir / f"test_{stem}.py")
    _add(same_dir / f"{stem}_test.py")

    # ------------------------------------------------------------------
    # 2. tests/ subpackage of the same directory
    # ------------------------------------------------------------------
    _add(same_dir / "tests" / f"test_{stem}.py")
    _add(same_dir / "tests" / f"{stem}_test.py")

    # ------------------------------------------------------------------
    # 3. Django-style: monolithic tests.py / test.py in the same package
    # ------------------------------------------------------------------
    _add(same_dir / "tests.py")
    _add(same_dir / "test.py")

    # ------------------------------------------------------------------
    # 4 & 5. Top-level test directories
    # ------------------------------------------------------------------
    try:
        rel = source_file.relative_to(project_root)
    except ValueError:
        rel = None

    # If the project uses a src/ layout, build a version of rel without
    # the leading "src" segment for mirror lookups (e.g. src/payments/gateway.py
    # → payments/gateway.py inside tests/).
    rel_stripped: Optional[Path] = None
    if rel is not None and rel.parts and rel.parts[0] == "src":
        rel_stripped = Path(*rel.parts[1:])

    # Some projects further strip the top-level package name so that
    # src/<pkg>/analysis/foo.py maps to tests/unit/analysis/test_foo.py
    # (not tests/unit/<pkg>/analysis/test_foo.py).
    rel_double_stripped: Optional[Path] = None
    if rel_stripped is not None and len(rel_stripped.parts) > 2:
        rel_double_stripped = Path(*rel_stripped.parts[1:])

    for tests_dir_name in _TOP_LEVEL_TEST_DIRS:
        tests_root = project_root / tests_dir_name
        if not tests_root.is_dir():
            continue

        # 4a. Mirror full relative path
        if rel is not None:
            mirrored = tests_root / rel.parent
            _add(mirrored / f"test_{stem}.py")
            _add(mirrored / f"{stem}_test.py")

        # 4b. Mirror src-stripped path (e.g. src/pkg/foo.py → tests/pkg/test_foo.py)
        if rel_stripped is not None:
            mirrored = tests_root / rel_stripped.parent
            _add(mirrored / f"test_{stem}.py")
            _add(mirrored / f"{stem}_test.py")

        # 4b2. Mirror doubly-stripped path (src/pkg/sub/foo.py → tests/sub/test_foo.py)
        if rel_double_stripped is not None:
            mirrored = tests_root / rel_double_stripped.parent
            _add(mirrored / f"test_{stem}.py")
            _add(mirrored / f"{stem}_test.py")

        # 4c. Nested subdirectory mirrors: tests/unit/<rel>/test_<stem>.py
        #     Handles projects that split tests into unit/, integration/, etc.
        for subdir in _TEST_SUBDIRS:
            nested_root = tests_root / subdir
            if not nested_root.is_dir():
                continue
            if rel is not None:
                _add(nested_root / rel.parent / f"test_{stem}.py")
                _add(nested_root / rel.parent / f"{stem}_test.py")
            if rel_stripped is not None:
                _add(nested_root / rel_stripped.parent / f"test_{stem}.py")
                _add(nested_root / rel_stripped.parent / f"{stem}_test.py")
            if rel_double_stripped is not None:
                _add(nested_root / rel_double_stripped.parent / f"test_{stem}.py")
                _add(nested_root / rel_double_stripped.parent / f"{stem}_test.py")
            # Flat inside the subdir
            _add(nested_root / f"test_{stem}.py")
            _add(nested_root / f"{stem}_test.py")

        # 5. Flat fallback: just tests/test_<stem>.py
        _add(tests_root / f"test_{stem}.py")
        _add(tests_root / f"{stem}_test.py")

    return seen


# ---------------------------------------------------------------------------
# Style extraction
# ---------------------------------------------------------------------------

_MAX_SOURCE_CHARS = 5000   # chars kept from the raw source for agent context
_MAX_EXAMPLES     = 3      # representative test functions to extract
_MIN_FUNC_LINES   = 3      # skip trivial one-liners
_MAX_FUNC_LINES   = 40     # skip monster tests that obscure the pattern


def extract_test_context(test_file: Path) -> TestFileContext:
    """
    Parse *test_file* and extract style metadata for the agent.

    On any parse error an empty-but-valid context is returned so callers
    never need to handle exceptions.

    Args:
        test_file: Path to an existing test file.

    Returns:
        TestFileContext populated with framework, fixture, mock, and example info.
    """
    try:
        source = test_file.read_text(encoding="utf-8", errors="replace")
        tree   = ast.parse(source, filename=str(test_file))
    except (SyntaxError, OSError):
        return TestFileContext(test_file=test_file, source_code="")

    imports      = _extract_imports(tree)
    base_classes = _extract_base_classes(tree)
    framework    = _detect_framework(imports, base_classes, source)
    fixture_style = _detect_fixture_style(tree, source)
    mock_style    = _detect_mock_style(imports, source)
    examples      = _extract_examples(tree, source)

    # Truncate raw source for the agent context window
    if len(source) > _MAX_SOURCE_CHARS:
        truncated = source[:_MAX_SOURCE_CHARS]
        truncated += f"\n# ... ({len(source) - _MAX_SOURCE_CHARS} more characters not shown)"
    else:
        truncated = source

    return TestFileContext(
        test_file       = test_file,
        source_code     = truncated,
        imports         = imports,
        base_classes    = base_classes,
        framework       = framework,
        fixture_style   = fixture_style,
        mock_style      = mock_style,
        example_functions = examples,
    )


def format_for_agent(context: TestFileContext) -> str:
    """
    Render a TestFileContext as a readable string for inclusion in an agent prompt.

    Args:
        context: Populated TestFileContext.

    Returns:
        Formatted multi-line string ready for agent consumption.
    """
    lines = [
        "=== EXISTING MODULE TESTS ===",
        f"File : {context.test_file}",
        f"Framework    : {context.framework}",
        f"Fixture style: {context.fixture_style}",
        f"Mock style   : {context.mock_style}",
    ]

    if context.base_classes:
        lines.append(f"Base classes : {', '.join(context.base_classes)}")

    if context.imports:
        lines += ["", "IMPORTS (reproduce these exactly):"]
        lines += [f"  {imp}" for imp in context.imports]

    if context.example_functions:
        lines += ["", "EXAMPLE TEST FUNCTIONS (mirror this style):"]
        for i, code in enumerate(context.example_functions, 1):
            lines += [f"\n--- Example {i} ---", code]

    lines += [
        "",
        "FULL SOURCE (for complete context — respect every pattern you see here):",
        context.source_code,
    ]

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _extract_imports(tree: ast.AST) -> List[str]:
    lines = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            try:
                lines.append(ast.unparse(node))
            except Exception:
                pass
    return lines


def _extract_base_classes(tree: ast.AST) -> List[str]:
    classes: List[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            for base in node.bases:
                try:
                    name = ast.unparse(base)
                    if name not in classes:
                        classes.append(name)
                except Exception:
                    pass
    return classes


def _detect_framework(
    imports: List[str],
    base_classes: List[str],
    source: str,
) -> str:
    imports_str = " ".join(imports)
    if "pytest" in imports_str:
        return "pytest"
    if "unittest" in imports_str or "TestCase" in " ".join(base_classes):
        return "unittest"
    # If test classes inherit from something other than the stdlib, assume custom
    non_stdlib = [c for c in base_classes if c not in ("object", "TestCase", "unittest.TestCase")]
    if non_stdlib:
        return "custom"
    return "pytest"


def _detect_fixture_style(tree: ast.AST, source: str) -> str:
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef):
            for dec in node.decorator_list:
                try:
                    name = ast.unparse(dec)
                    if "fixture" in name:
                        return "pytest_fixture"
                except Exception:
                    pass
    if "def setUp" in source or "def setUpClass" in source:
        return "setUp"
    # Detect custom decorator-based setup (e.g. @pre_invocation in sp-payments)
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef):
            for dec in node.decorator_list:
                try:
                    name = ast.unparse(dec)
                    if name not in ("staticmethod", "classmethod", "property"):
                        return "custom"
                except Exception:
                    pass
    return "none"


def _detect_mock_style(imports: List[str], source: str) -> str:
    imports_str = " ".join(imports)
    if "pytest_mock" in imports_str or "mocker" in source:
        return "pytest_mock"
    if "unittest.mock" in imports_str or "from mock import" in imports_str:
        return "unittest.mock"
    # Detect custom @mock decorator (e.g. sp-payments pattern)
    if "@mock(" in source or "from " in imports_str and "mock" in imports_str.lower():
        return "custom"
    if "@patch" in source or "MagicMock" in source or "patch(" in source:
        return "unittest.mock"
    return "none"


def _extract_examples(tree: ast.AST, source: str) -> List[str]:
    """
    Pull representative test functions from the file.

    Selects functions whose names start with "test" (or end with "_test"),
    excluding trivially short and excessively long ones, up to _MAX_EXAMPLES.
    """
    source_lines = source.splitlines()
    examples: List[str] = []

    candidates: List[ast.FunctionDef] = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            candidates.append(node)  # type: ignore[arg-type]

    for func in candidates:
        name = func.name
        if not (name.startswith("test") or name.endswith("_test")):
            continue

        start = func.lineno - 1
        end   = func.end_lineno or func.lineno
        lines = source_lines[start:end]

        if not (_MIN_FUNC_LINES <= len(lines) <= _MAX_FUNC_LINES):
            continue

        examples.append("\n".join(lines))
        if len(examples) >= _MAX_EXAMPLES:
            break

    # If we couldn't find any medium-sized ones, fall back to any test function
    if not examples:
        for func in candidates:
            name = func.name
            if not (name.startswith("test") or name.endswith("_test")):
                continue
            start = func.lineno - 1
            end   = func.end_lineno or func.lineno
            examples.append("\n".join(source_lines[start:end]))
            if len(examples) >= _MAX_EXAMPLES:
                break

    return examples
