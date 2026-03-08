"""
Python code parser using AST

Parses Python files into structured representations:
- Functions
- Classes
- Imports
- Dependencies
- Complexity metrics

Parser uses Python's built-in 'ast' module for parsing.
"""

import ast
from pathlib import Path
from typing import Any, Dict, List, Optional, cast, Union
import re

from codecoverage.core.codebase import (
    FunctionInfo,
    ClassInfo,
    FileInfo,
    Codebase,
)
from codecoverage.core.metrics import (
    calculate_cyclomatic_complexity,
    calculate_cognitive_complexity,
    calculate_maintainability_index,
)


# =============================================================================
# AST UTILITIES
# =============================================================================

def get_function_signature(node: ast.FunctionDef) -> str:
    """
    Generate function signature as a string

    Example:
        def login(username: str, password: str) -> bool:

        Returns: "def login(username: str, password: str) -> bool"

    Args:
        node: FunctionDef AST node

    Returns:
        Function signature string
    """
    # Build argument list
    args = []

    # Regular arguments
    for arg in node.args.args:
        arg_str = arg.arg

        # Add type annotation if present
        if arg.annotation:
            try:
                arg_str += f": {ast.unparse(cast(ast.AST, arg.annotation))}"
            except (ValueError, TypeError, AttributeError, Exception):
                pass  # Skip if unparsing fails

        args.append(arg_str)

    # *args
    if node.args.vararg:
        vararg = f"*{node.args.vararg.arg}"
        if node.args.vararg.annotation:
            try:
                vararg += f": {ast.unparse(cast(ast.AST, node.args.vararg.annotation))}"
            except (ValueError, TypeError, AttributeError, Exception):
                pass
        args.append(vararg)

    # **kwargs
    if node.args.kwarg:
        kwarg = f"**{node.args.kwarg.arg}"
        if node.args.kwarg.annotation:
            try:
                kwarg += f": {ast.unparse(cast(ast.AST, node.args.kwarg.annotation))}"
            except (ValueError, TypeError, AttributeError, Exception):
                pass
        args.append(kwarg)

    # Build signature
    sig = f"def {node.name}({', '.join(args)})"

    # Add return type annotation
    if node.returns:
        try:
            sig += f" -> {ast.unparse(cast(ast.AST, node.returns))}"
        except (ValueError, TypeError, AttributeError, Exception):
            pass

    return sig


def _eval_ast_node(node: ast.AST):
    """
    Resolve a simple AST value node to a Python primitive or string.

    Handles:
      - ast.Constant  → the raw value (int, str, bool, None, …)
      - ast.Name      → the identifier string (e.g. "GatewayPaymentOrder")
      - ast.Attribute → dotted string via ast.unparse (e.g. "post_save")
      - everything else → ast.unparse() as a fallback string

    Args:
        node: Any AST expression node

    Returns:
        A Python primitive or string representation
    """
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, ast.Name):
        return node.id
    try:
        return ast.unparse(node)
    except Exception:
        return "<unparseable>"


def extract_decorator_details(
        node: Union[ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef]
) -> List[Dict]:
    """
    Extract full decorator information (name + arguments) from a function or class.

    Each decorator is returned as a dict with keys:
      - "name"      : decorator name (str, e.g. "post_transition", "receiver")
      - "full_name" : dotted name when the decorator is an attribute access
                      (str, e.g. "app.task"), same as "name" for simple names
      - "args"      : positional argument values (list)
      - "kwargs"    : keyword argument values (dict)

    Examples:
        @staticmethod
        → {"name": "staticmethod", "full_name": "staticmethod", "args": [], "kwargs": {}}

        @post_transition(order=0)
        → {"name": "post_transition", "full_name": "post_transition",
           "args": [], "kwargs": {"order": 0}}

        @receiver(post_save, sender=GatewayPaymentOrder)
        → {"name": "receiver", "full_name": "receiver",
           "args": ["post_save"], "kwargs": {"sender": "GatewayPaymentOrder"}}

        @app.task(bind=True)
        → {"name": "task", "full_name": "app.task",
           "args": [], "kwargs": {"bind": True}}

    Args:
        node: FunctionDef, AsyncFunctionDef, or ClassDef AST node

    Returns:
        List of decorator detail dicts
    """
    details = []

    for decorator in node.decorator_list:
        detail: Dict = {"name": None, "full_name": None, "args": [], "kwargs": {}}

        try:
            if isinstance(decorator, ast.Name):
                # @decorator
                detail["name"] = decorator.id
                detail["full_name"] = decorator.id

            elif isinstance(decorator, ast.Attribute):
                # @module.decorator  (no call)
                detail["name"] = decorator.attr
                try:
                    detail["full_name"] = ast.unparse(decorator)
                except Exception:
                    detail["full_name"] = decorator.attr

            elif isinstance(decorator, ast.Call):
                # @decorator(...)  or  @module.decorator(...)
                func = decorator.func
                if isinstance(func, ast.Name):
                    detail["name"] = func.id
                    detail["full_name"] = func.id
                elif isinstance(func, ast.Attribute):
                    detail["name"] = func.attr
                    try:
                        detail["full_name"] = ast.unparse(func)
                    except Exception:
                        detail["full_name"] = func.attr

                # Positional args
                for arg in decorator.args:
                    try:
                        detail["args"].append(_eval_ast_node(arg))
                    except Exception:
                        detail["args"].append("<unparseable>")

                # Keyword args
                for kw in decorator.keywords:
                    key = kw.arg or "**kwargs"
                    try:
                        detail["kwargs"][key] = _eval_ast_node(kw.value)
                    except Exception:
                        detail["kwargs"][key] = "<unparseable>"

            if detail["name"] is not None:
                details.append(detail)

        except AttributeError:
            continue

    return details


def extract_decorators(node: Union[ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef]) -> List[str]:
    """
    Extract decorator names from a function or class (names only).

    This is a backward-compatible wrapper around extract_decorator_details().
    Use extract_decorator_details() when you need the full argument information.

    Example:
        @staticmethod
        @lru_cache(maxsize=100)
        def cached_func():
            ...

        Returns: ["staticmethod", "lru_cache"]

    Args:
        node: FunctionDef, AsyncFunctionDef, or ClassDef node

    Returns:
        List of decorator names
    """
    return [d["name"] for d in extract_decorator_details(node) if d["name"]]


def extract_parameters(node: ast.FunctionDef) -> Dict[str, Optional[str]]:
    """
    Extract parameter names and type hints

    Returns:
        Dict mapping parameter names to type hints (or None)

    Example:
        def func(a: int, b: str, c) -> bool:

        Returns: {"a": "int", "b": "str", "c": None}
    """
    params = {}

    for arg in node.args.args:
        type_hint = None
        if arg.annotation:
            try:
                type_hint = ast.unparse(cast(ast.AST, arg.annotation))
            except (ValueError, TypeError, AttributeError):
                # Can't unparse annotation, leave as None
                pass
        params[arg.arg] = type_hint

    return params


def extract_return_type(node: ast.FunctionDef) -> Optional[str]:
    """
    Extract return type annotation

    Example:
        def func() -> bool:

        Returns: "bool"
    """
    if node.returns:
        try:
            return ast.unparse(cast(ast.AST, node.returns))
        except (ValueError, TypeError, AttributeError):
            # Can't unparse return type
            return None
    return None


# =============================================================================
# DEPENDENCY EXTRACTION
# =============================================================================

def extract_function_calls(node: ast.FunctionDef) -> List[str]:
    """
    Extract all function calls made within a function

    Example:
        def login(user, password):
            validate(user)
            authenticate(password)
            log_activity(user)

        Returns: ["validate", "authenticate", "log_activity"]

    Args:
        node: FunctionDef node

    Returns:
        List of function names called
    """
    calls = set()

    for child in ast.walk(node):
        if isinstance(child, ast.Call):
            try:
                # Direct function call: func()
                if isinstance(child.func, ast.Name):
                    calls.add(child.func.id)

                # Method call: obj.method()
                elif isinstance(child.func, ast.Attribute):
                    calls.add(child.func.attr)

                # Nested call: module.submodule.func()
                # Just take the final name

            except AttributeError:
                # Malformed call node, skip it
                continue

    return list(calls)


def extract_imports(tree: ast.AST) -> List[str]:
    """
    Extract all imports from a file

    Example:
        import os
        from pathlib import Path
        from typing import List, Dict

        Returns: ["os", "pathlib.Path", "typing.List", "typing.Dict"]

    Args:
        tree: AST tree of entire file

    Returns:
        List of imported names
    """
    imports = []

    for node in ast.walk(tree):
        try:
            # import module
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imports.append(alias.name)

            # from module import name
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ''
                for alias in node.names:
                    if module:
                        imports.append(f"{module}.{alias.name}")
                    else:
                        # Relative import
                        imports.append(alias.name)

        except AttributeError:
            # Malformed import, skip it
            continue

    return imports


# =============================================================================
# FUNCTION PARSER
# =============================================================================

def parse_function(
        node: ast.FunctionDef,
        file_path: Path,
        source_lines: List[str]
) -> FunctionInfo:
    """
    Parse a function AST node into FunctionInfo

    Args:
        node: FunctionDef AST node
        file_path: Path to the file containing this function
        source_lines: List of source code lines (for LOC calculation)

    Returns:
        FunctionInfo object with all metadata
    """
    # Basic info
    name = node.name
    line_start = node.lineno
    line_end = node.end_lineno or node.lineno

    # Code
    signature = get_function_signature(node)

    try:
        code = ast.unparse(node)
    except (ValueError, TypeError, AttributeError):
        # Can't unparse, use placeholder
        code = f"# Could not parse {name}"

    docstring = ast.get_docstring(node)

    # Metadata
    is_async = isinstance(node, ast.AsyncFunctionDef)
    decorator_details = extract_decorator_details(node)
    decorators = [d["name"] for d in decorator_details if d["name"]]

    is_staticmethod = "staticmethod" in decorators
    is_classmethod = "classmethod" in decorators
    is_property = "property" in decorators

    # Dependencies
    calls = extract_function_calls(node)

    # Metrics
    cyclomatic = calculate_cyclomatic_complexity(node)
    cognitive = calculate_cognitive_complexity(node)

    # Calculate actual LOC (non-blank, non-comment)
    function_lines = source_lines[line_start - 1:line_end]
    loc = len([
        line for line in function_lines
        if line.strip() and not line.strip().startswith('#')
    ])

    # Type information
    parameters = extract_parameters(node)
    return_type = extract_return_type(node)

    return FunctionInfo(
        name=name,
        file_path=file_path,
        line_start=line_start,
        line_end=line_end,
        signature=signature,
        code=code,
        docstring=docstring,
        is_async=is_async,
        is_method=False,  # Will be set to True if inside a class
        is_staticmethod=is_staticmethod,
        is_classmethod=is_classmethod,
        is_property=is_property,
        calls=calls,
        imports=[],
        cyclomatic_complexity=cyclomatic,
        cognitive_complexity=cognitive,
        lines_of_code=loc,
        parameters=parameters,
        return_type=return_type,
        decorators=decorators,
        decorator_details=decorator_details,
    )


# =============================================================================
# CLASS PARSER
# =============================================================================

def parse_class(
        node: ast.ClassDef,
        file_path: Path,
        source_lines: List[str]
) -> ClassInfo:
    """
    Parse a class AST node into ClassInfo

    Args:
        node: ClassDef AST node
        file_path: Path to the file
        source_lines: Source code lines

    Returns:
        ClassInfo object with all methods and metadata
    """
    # Basic info
    name = node.name
    line_start = node.lineno
    line_end = node.end_lineno or node.lineno

    # Code
    try:
        code = ast.unparse(node)
    except (ValueError, TypeError, AttributeError):
        code = f"# Could not parse class {name}"

    docstring = ast.get_docstring(node)

    # Inheritance
    bases = []
    for base in node.bases:
        try:
            bases.append(ast.unparse(cast(ast.AST, base)))
        except (ValueError, TypeError, AttributeError):
            # Can't unparse base class, skip it
            continue

    # Decorators
    decorators = extract_decorators(node)

    # Extract methods
    methods = []
    for item in node.body:
        if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
            try:
                method = parse_function(item, file_path, source_lines)
                # Mark as method
                # Need to reconstruct FunctionInfo with is_method=True
                method_dict = method.to_dict()
                method_dict['is_method'] = True
                method = FunctionInfo(
                    name=method_dict['name'],
                    file_path=Path(method_dict['file_path']),
                    line_start=method_dict['line_start'],
                    line_end=method_dict['line_end'],
                    signature=method_dict['signature'],
                    code=method_dict['code'],
                    docstring=method_dict['docstring'],
                    is_async=method_dict['is_async'],
                    is_method=True,  # This is the key change
                    is_staticmethod=method_dict['is_staticmethod'],
                    is_classmethod=method_dict['is_classmethod'],
                    is_property=method_dict['is_property'],
                    calls=method_dict['calls'],
                    imports=method_dict['imports'],
                    cyclomatic_complexity=method_dict['cyclomatic_complexity'],
                    cognitive_complexity=method_dict['cognitive_complexity'],
                    lines_of_code=method_dict['lines_of_code'],
                    parameters=method_dict['parameters'],
                    return_type=method_dict['return_type'],
                    decorators=method_dict['decorators'],
                    decorator_details=method_dict.get('decorator_details', []),
                )
                methods.append(method)
            except (ValueError, TypeError, AttributeError):
                # Skip methods that can't be parsed
                # Log error in production
                continue

    # Extract properties
    properties = []
    for item in node.body:
        if isinstance(item, ast.FunctionDef):
            if "property" in extract_decorators(item):
                properties.append(item.name)

    # Extract class variables
    class_variables = []
    for item in node.body:
        if isinstance(item, ast.Assign):
            for target in item.targets:
                if isinstance(target, ast.Name):
                    class_variables.append(target.id)

    return ClassInfo(
        name=name,
        file_path=file_path,
        line_start=line_start,
        line_end=line_end,
        code=code,
        docstring=docstring,
        bases=bases,
        methods=methods,
        properties=properties,
        class_variables=class_variables,
        decorators=decorators,
    )


# =============================================================================
# FILE PARSER
# =============================================================================

def parse_file(file_path: Path, project_root: Path) -> Optional[FileInfo]:
    """
    Parse a single Python file

    Args:
        file_path: Path to .py file
        project_root: Root of the project (for module name calculation)

    Returns:
        FileInfo object, or None if parsing fails
    """
    try:
        # Read the source
        source = file_path.read_text(encoding='utf-8')
        source_lines = source.splitlines()

        # Parse AST
        tree = ast.parse(source, filename=str(file_path))

    except SyntaxError:
        # File has syntax errors, skip it
        # In production, you might want to log this
        return None

    except UnicodeDecodeError:
        # Not a text file or wrong encoding
        return None

    except (OSError, IOError):
        # File system errors (permissions, file not found, etc.)
        return None

    # Calculate module name
    try:
        relative = file_path.relative_to(project_root)
        module_parts = list(relative.parts[:-1])  # Remove filename
        module_parts.append(relative.stem)  # Add filename without .py
        module_name = ".".join(module_parts)
    except ValueError:
        # File not under project_root
        module_name = file_path.stem

    # Extract top-level docstring
    docstring = ast.get_docstring(tree)

    # Extract functions (top-level only)
    functions = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            try:
                func = parse_function(node, file_path, source_lines)
                functions.append(func)
            except (ValueError, TypeError, AttributeError):
                # Skip functions that can't be parsed
                continue

    # Extract classes
    classes = []
    for node in tree.body:
        if isinstance(node, ast.ClassDef):
            try:
                cls = parse_class(node, file_path, source_lines)
                classes.append(cls)
            except (ValueError, TypeError, AttributeError):
                # Skip classes that can't be parsed
                continue

    # Extract imports
    imports = extract_imports(tree)

    # Calculate metrics
    loc = len([line for line in source_lines
               if line.strip() and not line.strip().startswith('#')])

    mi = calculate_maintainability_index(source)

    # Get file modification time
    try:
        last_modified = file_path.stat().st_mtime
    except (OSError, IOError):
        last_modified = 0.0

    return FileInfo(
        path=file_path,
        module_name=module_name,
        docstring=docstring,
        lines_of_code=loc,
        last_modified=last_modified,
        functions=functions,
        classes=classes,
        imports=imports,
        maintainability_index=mi,
    )


# =============================================================================
# CODEBASE PARSER (THIS WAS MISSING!)
# =============================================================================

class CodebaseParser:
    """
    Main parser for entire codebases

    Handles:
    - Finding Python files
    - Respecting ignore patterns
    - Parsing files
    - Progress reporting

    Usage:
        >>> parser = CodebaseParser(
        ...     root=Path("/path/to/project"),
        ...     ignore_patterns=["venv/", ".git/"]
        ... )
        >>> codebase = parser.parse()
        >>> print(f"Parsed {codebase.total_files} files")
    """

    def __init__(self, root: Path, ignore_patterns: List[str]):
        """
        Initialize parser

        Args:
            root: Project root directory
            ignore_patterns: Glob patterns to ignore
        """
        self.root = root.resolve()
        self.ignore_patterns = ignore_patterns

    def parse(self) -> Codebase:
        """
        Parse the entire codebase

        Returns:
            Codebase object with all parsed files
        """
        # Find all Python files
        python_files = self._find_python_files()

        # Parse each file
        files: Dict[Path, FileInfo] = {}

        for file_path in python_files:
            file_info = parse_file(file_path, self.root)
            if file_info:
                files[file_path] = file_info

        # Build complete codebase
        codebase = Codebase.from_files(files)

        return codebase

    def _find_python_files(self) -> List[Path]:
        """
        Find all Python files in the project

        Returns:
            List of .py file paths
        """
        python_files = []

        for path in self.root.rglob("*.py"):
            # Check if should be ignored
            if self._should_ignore(path):
                continue

            python_files.append(path)

        return python_files

    def _should_ignore(self, path: Path) -> bool:
        """
        Check if path matches ignore patterns

        Args:
            path: Path to check

        Returns:
            True if should be ignored
        """
        try:
            # Get the path relative to root
            relative = path.relative_to(self.root)
            relative_str = str(relative)

            # Check each 'ignore' pattern
            for pattern in self.ignore_patterns:
                # Simple glob-style matching
                if self._matches_pattern(relative_str, pattern):
                    return True

            return False

        except ValueError:
            # Path not under root
            return True

    @staticmethod
    def _matches_pattern(path: str, pattern: str) -> bool:
        """
        Check if the path matches the glob-style pattern

        Supports:
        - Exact match: "venv/"
        - Wildcard: "*.pyc"
        - Directory prefix: matches if the path starts with the pattern

        Args:
            path: Path string (relative)
            pattern: Pattern string

        Returns:
            True if matches
        """
        # Convert to forward slashes for consistency
        path = path.replace('\\', '/')
        pattern = pattern.replace('\\', '/')

        # Directory pattern (ends with /)
        if pattern.endswith('/'):
            return path.startswith(pattern) or ('/' + pattern) in path

        # Wildcard pattern
        if '*' in pattern:
            regex = pattern.replace('.', r'\.').replace('*', '.*')
            return bool(re.match(regex, path))

        # Exact match
        return pattern in path
