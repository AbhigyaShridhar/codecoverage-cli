"""
LangChain tools for CodeCoverage agent

These tools give the agent access to:
- Project pattern analysis (venv, dependencies, test patterns)
- Function dependency analysis
- Complexity metrics
"""

from typing import Optional, List, Dict
from langchain_core.tools import tool
from pathlib import Path
from dataclasses import is_dataclass

from codecoverage.core.codebase import Codebase
from codecoverage.analysis.venv_scanner import VirtualEnvScanner
from codecoverage.analysis.dependencies import parse_dependencies
from codecoverage.analysis.test_patterns import detect_test_patterns
from codecoverage.analysis.test_finder import find_test_files, extract_test_context, format_for_agent


# =============================================================================
# TOOL STATE (shared across tools)
# =============================================================================

class ToolState:
    """
    Shared state for all tools

    This allows tools to access the parsed codebase, etc.
    without passing them as parameters (which LangChain doesn't support well).
    """
    codebase: Optional[Codebase] = None
    project_root: Optional[Path] = None
    venv_packages: Optional[Dict] = None
    dependencies: Optional[Dict] = None
    test_patterns: Optional[Dict] = None


# Global state instance
_state = ToolState()


def initialize_tools(
        codebase: Codebase,
        project_root: Path
):
    """
    Initialize tool state

    Call this before using the tools.

    Args:
        codebase: Parsed codebase
        project_root: Project root directory
    """
    _state.codebase = codebase
    _state.project_root = project_root

    # Analyze project patterns (cached)
    print("Analyzing project patterns...")

    # Scan virtual environment
    scanner = VirtualEnvScanner()
    _state.venv_packages = scanner.scan(limit=50)  # Top 50 packages

    # Parse dependencies
    _state.dependencies = parse_dependencies(project_root)

    # Detect test patterns
    _state.test_patterns = detect_test_patterns(codebase)

    print("✓ Tools initialized")


# =============================================================================
# MODULE TEST DISCOVERY TOOL
# =============================================================================

@tool
def get_module_test_examples(source_file: str) -> str:
    """
    Find existing tests for a specific source file and return their style.

    ALWAYS call this tool first before generating any test code.  It
    searches for a test file that corresponds to the given source file using
    all common Python project conventions:
      - Same package: test_<module>.py, <module>_test.py
      - Package tests/ subdir: tests/test_<module>.py
      - Django-style sibling: tests.py or test.py in the same package
      - Top-level mirrors: tests/, unit_tests/, or test/ directories

    When tests are found the tool returns:
      - The detected testing framework (pytest / unittest / custom)
      - Fixture and mocking patterns
      - All import statements (reproduce these exactly)
      - Complete source of the test file (truncated if very large)
      - Representative example test functions

    When no tests are found it returns an explicit "NO EXISTING TESTS" message
    so the caller knows to fall back to project-wide patterns from
    analyze_project_patterns().

    Args:
        source_file: Relative path to the source file being tested,
                     e.g. "payments/gateway.py" or "src/auth/login.py"

    Returns:
        Formatted string with all style information, or a clear
        "NO EXISTING TESTS" notice.

    Examples:
        get_module_test_examples("payments/gateway.py")
        get_module_test_examples("src/auth/login.py")
    """
    if not _state.project_root:
        return "Error: project root not initialised"

    # Resolve the source file — accept relative or absolute paths
    candidate = Path(source_file)
    if not candidate.is_absolute():
        candidate = _state.project_root / candidate

    if not candidate.exists():
        return (
            f"NO EXISTING TESTS\n"
            f"Source file '{source_file}' could not be found at '{candidate}'.\n"
            f"Proceed with analyze_project_patterns() to get project-wide conventions."
        )

    found = find_test_files(candidate, _state.project_root)

    if not found:
        return (
            f"NO EXISTING TESTS\n"
            f"No test file found for '{source_file}' in any standard location.\n"
            f"Checked: same package, tests/ subdir, Django-style tests.py, "
            f"top-level tests/ / unit_tests/ / test/ directories.\n\n"
            f"Proceed with analyze_project_patterns() to determine the project's "
            f"default testing conventions and generate a test using that style."
        )

    # Use the most specific match (first in list) as the style authority.
    # Surface up to 2 files so the agent sees the full picture when a module
    # has both a same-package test and a top-level one.
    output_parts = [
        f"Found {len(found)} test file(s) for '{source_file}':",
        f"Primary reference: {found[0].relative_to(_state.project_root)}",
    ]
    if len(found) > 1:
        others = [str(f.relative_to(_state.project_root)) for f in found[1:3]]
        output_parts.append(f"Also found: {', '.join(others)}")

    output_parts.append("")

    # Extract and format context from the primary (most specific) test file
    ctx = extract_test_context(found[0])
    output_parts.append(format_for_agent(ctx))

    return "\n".join(output_parts)


# =============================================================================
# PROJECT ANALYSIS TOOLS
# =============================================================================

@tool
def analyze_project_patterns() -> str:
    """
    Analyze project patterns including dependencies, frameworks, and test setup.

    Returns comprehensive information about:
    - Installed packages (from virtual environment)
    - Project dependencies (from pyproject.toml, requirements.txt)
    - Detected frameworks (web, test, database, async)
    - Test patterns and conventions

    Use this to understand the project structure before generating code.

    Returns:
        JSON string with project analysis
    """
    output = ["=== PROJECT PATTERNS ===\n"]

    # Virtual Environment Packages
    if _state.venv_packages:
        output.append("INSTALLED PACKAGES (from virtual environment):")
        package_items = list(_state.venv_packages.items())[:10]
        for name, info in package_items:
            output.append(f"  • {name} v{info.version}")
            if info.test_utilities:
                test_utils = ', '.join(info.test_utilities)
                output.append(f"    Test utilities: {test_utils}")
            if info.decorators:
                decorators = ', '.join(info.decorators[:3])
                output.append(f"    Decorators: {decorators}")
        output.append("")

    # Dependencies (DependencyInfo dataclass - use attributes)
    if _state.dependencies:
        deps = _state.dependencies
        output.append("PROJECT DEPENDENCIES:")

        # Access dataclass attributes directly
        output.append(f"  Total: {len(deps.all_dependencies)}")

        if deps.web_framework:
            output.append(f"  Web framework: {deps.web_framework}")

        if deps.test_framework:
            output.append(f"  Test framework: {deps.test_framework}")

        if deps.database:
            output.append(f"  Database: {deps.database}")

        if deps.async_framework:
            output.append(f"  Async: {deps.async_framework}")

        output.append("")

    # Test Patterns (also likely a dataclass or dict - handle both)
    if _state.test_patterns:
        patterns = _state.test_patterns
        output.append("TEST PATTERNS:")

        # Check if it's a dataclass or dict
        if is_dataclass(patterns) and not isinstance(patterns, type):
            # It's a dataclass - use attributes
            output.append(f"  Framework: {patterns.framework}")    # type: ignore
            output.append(f"  Fixture style: {patterns.fixture_style}")    # type: ignore
            output.append(f"  Assertion style: {patterns.assertion_style}")    # type: ignore
            output.append(f"  Naming convention: {patterns.naming_convention}")    # type: ignore

            if patterns.uses_mocking:    # type: ignore
                output.append(f"  Mocking: {patterns.mocking_library}")    # type: ignore

            output.append(f"  Total test files: {patterns.total_test_files}")    # type: ignore
            output.append(f"  Total test functions: {patterns.total_test_functions}")    # type: ignore
        elif isinstance(patterns, dict):
            # It's a dict - use .get()
            output.append(f"  Framework: {patterns.get('framework', 'unknown')}")
            output.append(f"  Fixture style: {patterns.get('fixture_style', 'unknown')}")
            output.append(f"  Assertion style: {patterns.get('assertion_style', 'unknown')}")
            output.append(f"  Naming convention: {patterns.get('naming_convention', 'unknown')}")

            if patterns.get('uses_mocking'):
                output.append(f"  Mocking: {patterns.get('mocking_library', 'unknown')}")

            output.append(f"  Total test files: {patterns.get('total_test_files', 0)}")
            output.append(f"  Total test functions: {patterns.get('total_test_functions', 0)}")
        else:
            raise ValueError("Unknown data format!")

        output.append("")

    return "\n".join(output)


@tool
def get_codebase_statistics() -> str:
    """
    Get overall codebase statistics.

    Returns:
        Statistics about files, functions, classes, complexity, etc.
    """
    if not _state.codebase:
        return "Error: Codebase not loaded"

    cb = _state.codebase

    output = ["=== CODEBASE STATISTICS ===\n", f"Total files: {cb.total_files}",
              f"Total functions: {cb.total_functions}", f"Total classes: {cb.total_classes}",
              f"Total lines of code: {cb.total_lines}", ""]

    # Complexity distribution
    if cb.total_functions > 0:
        all_funcs = []
        for file_info in cb.files.values():
            all_funcs.extend(file_info.get_all_functions())

        complexities = [f.cyclomatic_complexity for f in all_funcs]
        avg_complexity = sum(complexities) / len(complexities)
        max_complexity = max(complexities)

        output.append(f"Average complexity: {avg_complexity:.2f}")
        output.append(f"Maximum complexity: {max_complexity}")

        # Complex functions (complexity > 10)
        complex_funcs = [f for f in all_funcs if f.cyclomatic_complexity > 10]
        if complex_funcs:
            output.append(f"\nComplex functions (>10): {len(complex_funcs)}")
            for func in complex_funcs[:5]:
                output.append(f"  • {func.name} (complexity: {func.cyclomatic_complexity})")

    return "\n".join(output)


# =============================================================================
# FUNCTION ANALYSIS TOOLS
# =============================================================================

@tool
def get_function_dependencies(file_path: str, function_name: str) -> str:
    """
    Get dependencies of a specific function (what it calls).

    Args:
        file_path: Relative path to file (e.g., "src/auth/login.py")
        function_name: Name of the function

    Returns:
        List of functions this function calls

    Examples:
        get_function_dependencies("src/auth.py", "login")
    """
    if not _state.codebase:
        return "Error: Codebase not loaded"

    # Find the function
    target_funcs = _state.codebase.find_function(function_name)

    if not target_funcs:
        return f"Function '{function_name}' not found"

    # Filter by file path if specified
    if file_path:
        target_funcs = [f for f in target_funcs if file_path in str(f.file_path)]

    if not target_funcs:
        return f"Function '{function_name}' not found in '{file_path}'"

    func = target_funcs[0]

    output = [f"Dependencies of {func.name}:", f"Location: {func.file_path}:{func.line_start}", ""]

    if func.calls:
        output.append(f"Calls {len(func.calls)} functions:")
        for call in func.calls:
            output.append(f"  • {call}")
    else:
        output.append("No function calls detected")

    return "\n".join(output)


@tool
def analyze_function_complexity(file_path: str, function_name: str) -> str:
    """
    Analyze complexity metrics for a specific function.

    Args:
        file_path: Relative path to file
        function_name: Name of the function

    Returns:
        Complexity metrics and recommendations

    Examples:
        analyze_function_complexity("src/utils.py", "process_data")
    """
    if not _state.codebase:
        return "Error: Codebase not loaded"

    # Find the function
    target_funcs = _state.codebase.find_function(function_name)

    if not target_funcs:
        return f"Function '{function_name}' not found"

    if file_path:
        target_funcs = [f for f in target_funcs if file_path in str(f.file_path)]

    if not target_funcs:
        return f"Function '{function_name}' not found in '{file_path}'"

    func = target_funcs[0]

    output = [f"Complexity Analysis: {func.name}", f"Location: {func.file_path}:{func.line_start}", "",
              f"Cyclomatic Complexity: {func.cyclomatic_complexity}",
              f"Cognitive Complexity: {func.cognitive_complexity}", f"Lines of Code: {func.lines_of_code}", ""]

    # Recommendations
    if func.cyclomatic_complexity > 10:
        output.append("⚠ HIGH COMPLEXITY - Consider refactoring")
    elif func.cyclomatic_complexity > 5:
        output.append("⚠ MODERATE COMPLEXITY - May benefit from simplification")
    else:
        output.append("✓ LOW COMPLEXITY - Easy to test")

    return "\n".join(output)


# =============================================================================
# UTILITY FUNCTIONS
# =============================================================================

@tool
def get_decoupled_flows(file_path: str) -> str:
    """
    Identify decoupled execution flows in a source file by analysing decorator arguments.

    Use this on any file before writing tests. It surfaces functions that are NOT
    called directly by user code — they are invoked by frameworks, signal dispatchers,
    task queues, or other runtime machinery. Knowing this is critical for writing
    correct tests: you need to know the calling convention, not just the function body.

    The tool scans every function and method in the file. For each one that carries
    decorator arguments it reports:
      - The decorator name and its full resolved arguments
      - Which class the function belongs to (if any)
      - The function signature

    The output is grouped by class so you can see the full execution chain at a glance.

    The tool does NOT hardcode any framework-specific logic. It extracts raw decorator
    data and presents it neutrally; the LLM is expected to interpret what each
    decorator means in context (e.g. @post_transition(order=0) from a state-machine
    framework, @receiver(post_save, sender=X) from Django signals, @shared_task from
    Celery, @pytest.fixture from pytest, etc.).

    Args:
        file_path: Relative path to the source file (e.g. "payments/states.py")

    Returns:
        Formatted string describing all decoupled flows found, or a clear
        "NO DECOUPLED FLOWS" message if every function uses only zero-argument
        decorators (@staticmethod, @classmethod, @property, or none at all).

    Examples:
        get_decoupled_flows("payments/interface_layer/payment_gateway/states.py")
        get_decoupled_flows("payments/tasks.py")
    """
    if not _state.codebase or not _state.project_root:
        return "Error: codebase not initialised"

    # Resolve path
    candidate = Path(file_path)
    if not candidate.is_absolute():
        candidate = _state.project_root / candidate

    # Find the matching FileInfo
    file_info = None
    for path, info in _state.codebase.files.items():
        if path == candidate or str(path).endswith(file_path):
            file_info = info
            break

    if file_info is None:
        return (
            f"File '{file_path}' not found in parsed codebase.\n"
            f"Ensure the file exists and was not excluded by ignore_patterns."
        )

    # ------------------------------------------------------------------ #
    # Collect methods with non-trivial decorator args, grouped by class   #
    # ------------------------------------------------------------------ #

    # Zero-arg decorators that carry no semantic information about calling
    # convention — we skip these to keep the output focused.
    NOISE_DECORATORS = {"staticmethod", "classmethod", "property", "override",
                        "abstractmethod", "cached_property"}

    def _fmt_decorator(detail: dict) -> str:
        """Render one decorator detail dict as a concise string."""
        parts = [f"@{detail['full_name'] or detail['name']}"]
        call_parts = []
        for a in detail.get("args", []):
            call_parts.append(str(a))
        for k, v in detail.get("kwargs", {}).items():
            call_parts.append(f"{k}={v!r}")
        if call_parts:
            parts.append(f"({', '.join(call_parts)})")
        return "".join(parts)

    def _has_meaningful_decorators(func) -> bool:
        for d in func.decorator_details:
            if d["name"] not in NOISE_DECORATORS and (d["args"] or d["kwargs"]):
                return True
        return False

    # top-level functions
    standalone: list = []
    for func in file_info.functions:
        if _has_meaningful_decorators(func):
            standalone.append(func)

    # class methods, grouped by class name
    by_class: dict = {}
    for cls in file_info.classes:
        decorated_methods = [m for m in cls.methods if _has_meaningful_decorators(m)]
        if decorated_methods:
            by_class[cls.name] = decorated_methods

    if not standalone and not by_class:
        return (
            f"NO DECOUPLED FLOWS\n"
            f"No functions with non-trivial decorator arguments found in '{file_path}'.\n"
            f"All decorators are zero-argument (e.g. @staticmethod, @classmethod) or "
            f"the file has no decorated functions."
        )

    lines = [f"Decoupled flows detected in '{file_path}':\n"]

    # Standalone (module-level) functions
    if standalone:
        lines.append("── Module-level decorated functions ──")
        for func in standalone:
            for d in func.decorator_details:
                if d["name"] not in NOISE_DECORATORS and (d["args"] or d["kwargs"]):
                    lines.append(f"  {_fmt_decorator(d)}")
            lines.append(f"  {func.signature}")
            lines.append("")

    # Per-class grouping
    for class_name, methods in by_class.items():
        lines.append(f"── {class_name} ──")

        # Group methods by their first meaningful decorator name for readability
        by_decorator: dict = {}
        for method in methods:
            for d in method.decorator_details:
                if d["name"] not in NOISE_DECORATORS and (d["args"] or d["kwargs"]):
                    key = d["name"]
                    by_decorator.setdefault(key, []).append((method, d))

        for dec_name, entries in by_decorator.items():
            # Sort by order kwarg if present (common in state-machine decorators)
            entries.sort(key=lambda x: x[1].get("kwargs", {}).get("order", 0))
            lines.append(f"  [{dec_name}]")
            for method, d in entries:
                lines.append(f"    {_fmt_decorator(d)}  →  {method.signature}")
            lines.append("")

    lines.append(
        "NOTE: Functions listed above are likely invoked by a framework, not called\n"
        "directly. Read the decorator definition to understand the calling convention\n"
        "before deciding how to test them."
    )

    return "\n".join(lines)


@tool
def read_source_file(file_path: str) -> str:
    """
    Read the complete source code of a file.

    ALWAYS call this before writing any test code. It returns the raw source
    so you can extract the exact class names, method signatures, field names,
    imports, and every code branch.

    Never guess or infer names from memory — read the source first.

    Args:
        file_path: Relative path to the source file (e.g. "payments/gateway.py")

    Returns:
        Full source code of the file with line numbers, or an error message.

    Examples:
        read_source_file("payments/interface_layer/payment_gateway/views.py")
        read_source_file("src/auth/login.py")
    """
    if not _state.project_root:
        return "Error: project root not initialised"

    candidate = Path(file_path)
    if not candidate.is_absolute():
        candidate = _state.project_root / candidate

    if not candidate.exists():
        return f"Error: file '{file_path}' not found at '{candidate}'"

    try:
        source = candidate.read_text(encoding="utf-8", errors="replace")
        lines = source.splitlines()
        numbered = "\n".join(f"{i + 1:4d}  {line}" for i, line in enumerate(lines))
        return f"# Source: {file_path}\n# Lines: {len(lines)}\n\n{numbered}"
    except Exception as e:
        return f"Error reading '{file_path}': {e}"


def get_all_tools() -> List:
    """
    Get all available tools for the agent.

    Returns:
        List of LangChain tools
    """
    return [
        get_module_test_examples,       # Must be called first — style authority
        read_source_file,               # Read actual source before writing tests
        get_decoupled_flows,            # Identify framework-invoked functions via decorators
        analyze_project_patterns,
        get_codebase_statistics,
        get_function_dependencies,
        analyze_function_complexity,
    ]


def get_tool_descriptions() -> str:
    """
    Get human-readable descriptions of all tools.

    Returns:
        Formatted string describing all tools
    """
    tools = get_all_tools()

    output = ["=== AVAILABLE TOOLS ===\n"]

    for tool_func in tools:
        output.append(f"• {tool_func.name}")
        output.append(f"  {tool_func.description}")
        output.append("")

    return "\n".join(output)
