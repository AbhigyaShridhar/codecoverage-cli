"""
Static decision-point extractor.

Given a source file and function name, walks the function's AST and
produces a flat list of branching decisions (if/elif/else/try/except)
as structured dicts — no LLM, no import resolution.

Each item:
    {"type": "if"|"elif"|"else"|"try"|"except"|"finally",
     "condition": str,   # the test expression (without leading keyword)
     "outcome": str}     # terse summary of what the branch does
"""
from __future__ import annotations

import ast
from pathlib import Path
from typing import Dict, List, Optional

_MAX_COND = 80
_MAX_OUT = 65
_MAX_POINTS = 12


def extract_decision_points(
    source_file: Path,
    func_name: str,
) -> List[Dict[str, str]]:
    """
    Return decision points for *func_name* in *source_file*.
    Returns [] on any parse error or if no branches are found.
    """
    try:
        source = source_file.read_text(encoding="utf-8", errors="replace")
        tree = ast.parse(source)
    except (SyntaxError, OSError):
        return []

    func_node = _find_func(tree, func_name)
    if func_node is None:
        return []

    out: List[Dict[str, str]] = []
    _walk_body(func_node.body, out, depth=0)
    return out[:_MAX_POINTS]


# ---------------------------------------------------------------------------
# Internal
# ---------------------------------------------------------------------------

def _find_func(tree: ast.AST, name: str) -> Optional[ast.FunctionDef]:
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.name == name:
                return node  # type: ignore[return-value]
    return None


def _walk_body(stmts: list, out: list, depth: int) -> None:
    if depth > 2:
        return
    for stmt in stmts:
        if len(out) >= _MAX_POINTS:
            break
        if isinstance(stmt, ast.If):
            _handle_if(stmt, out, depth)
        elif isinstance(stmt, ast.Try):
            _handle_try(stmt, out, depth)


def _handle_if(node: ast.If, out: list, depth: int) -> None:
    cond = _unparse(node.test, _MAX_COND)
    out.append({"type": "if", "condition": cond, "outcome": _summarize(node.body)})

    # Recurse into the branch body if it contains further branches
    if depth < 2 and _has_branch(node.body):
        _walk_body(node.body, out, depth + 1)

    _handle_orelse(node.orelse, out, depth)


def _handle_orelse(orelse: list, out: list, depth: int) -> None:
    if not orelse:
        return
    if len(orelse) == 1 and isinstance(orelse[0], ast.If):
        node = orelse[0]
        cond = _unparse(node.test, _MAX_COND)
        out.append({"type": "elif", "condition": cond, "outcome": _summarize(node.body)})
        if depth < 2 and _has_branch(node.body):
            _walk_body(node.body, out, depth + 1)
        _handle_orelse(node.orelse, out, depth)
    else:
        out.append({"type": "else", "condition": "", "outcome": _summarize(orelse)})


def _handle_try(node: ast.Try, out: list, depth: int) -> None:
    out.append({"type": "try", "condition": "", "outcome": _summarize(node.body)})
    for handler in node.handlers:
        exc = _unparse(handler.type, 50) if handler.type else "Exception"
        out.append({"type": "except", "condition": exc, "outcome": _summarize(handler.body)})
    if node.orelse:
        out.append({"type": "else", "condition": "no exception", "outcome": _summarize(node.orelse)})
    if node.finalbody:
        out.append({"type": "finally", "condition": "", "outcome": _summarize(node.finalbody)})


def _has_branch(stmts: list) -> bool:
    return any(isinstance(s, (ast.If, ast.Try)) for s in stmts)


def _unparse(node: ast.AST, max_len: int) -> str:
    try:
        s = ast.unparse(node)
    except Exception:
        return "..."
    return s if len(s) <= max_len else s[:max_len - 3] + "..."


def _summarize(stmts: list) -> str:
    parts = []
    for stmt in stmts[:3]:
        if isinstance(stmt, ast.Return):
            if stmt.value is None:
                parts.append("returns None")
            else:
                parts.append("returns " + _unparse(stmt.value, _MAX_OUT))
        elif isinstance(stmt, ast.Raise):
            if stmt.exc:
                parts.append("raises " + _unparse(stmt.exc, _MAX_OUT))
            else:
                parts.append("re-raises")
        elif isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Call):
            parts.append("calls " + _unparse(stmt.value, _MAX_OUT))
        elif isinstance(stmt, (ast.Assign, ast.AugAssign, ast.AnnAssign)):
            val = getattr(stmt, "value", None)
            if val:
                parts.append("assigns " + _unparse(val, _MAX_OUT))
        elif isinstance(stmt, ast.If):
            parts.append("nested branch")
        elif isinstance(stmt, (ast.For, ast.While)):
            parts.append("iterates")
    return "; ".join(parts) if parts else "executes block"
