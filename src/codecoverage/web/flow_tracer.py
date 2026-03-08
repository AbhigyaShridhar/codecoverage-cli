"""
Entry-point detection and call-chain tracing.

Detects all meaningful entry points in a codebase (HTTP routes, Celery tasks,
Django signal receivers, management commands) and traces each one's call chain
into the codebase, collecting which decoupled flows live in the same execution
paths.

No LLM required — pure static analysis over the already-parsed Codebase.
"""

from __future__ import annotations

import ast
import re
import textwrap
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Literal, Optional, Set, Union

from codecoverage.core.codebase import Codebase, FileInfo, FunctionInfo


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class FlowStep:
    """A single function in a call chain."""
    name: str
    file: str           # relative to project root
    signature: str
    docstring: str


@dataclass
class DecoupledFlowEntry:
    """A framework-invoked function found in an entry point's execution path."""
    decorator_name: str     # e.g. "hook", "pre_transition", "receiver"
    decorator_repr: str     # e.g. "@hook(Idle, order=1)"
    function_name: str
    signature: str
    file: str               # relative to project root
    docstring: str


@dataclass
class FlowFork:
    """
    A dispatch point where the called function could be one of several
    implementations (e.g. strategy pattern, gateway dispatch).
    Shown as a fork in the call flow rather than a single step.
    """
    alternatives: List[FlowStep]


@dataclass
class EntryPoint:
    """
    A single callable entry point into the codebase with its full flow context.

    Attributes:
        kind         : Broad category — "http" | "task" | "signal" | "command"
        label        : Human-readable name (view class, task name, etc.)
        description  : Docstring or empty string
        file         : Relative path to the defining file
        http_methods : e.g. ["GET", "POST"] — empty for non-HTTP
        url_path     : URL pattern string — empty for non-HTTP
        call_chain   : Functions called from this entry point (depth-limited BFS)
        decoupled_flows : Framework-invoked functions found in the call chain's files
    """
    kind: Literal["http", "task", "signal", "command"]
    label: str
    description: str
    file: str
    http_methods: List[str] = field(default_factory=list)
    url_path: str = ""
    call_chain: List[Union[FlowStep, FlowFork]] = field(default_factory=list)
    decoupled_flows: List[DecoupledFlowEntry] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_HTTP_METHODS = {"get", "post", "put", "patch", "delete", "head", "options"}

# Decorators that indicate a Celery task regardless of args
_CELERY_TASK_DECORATORS = {"shared_task", "task", "periodic_task"}

# Decorators that indicate a Django signal receiver
_SIGNAL_DECORATORS = {"receiver"}

# DRF / Django method names that serve as framework entry points.
# When a class-based view has no direct HTTP methods we walk its MRO through
# project-level base classes and treat any of these methods as seeds.
_FRAMEWORK_ENTRY_METHODS = {
    # HTTP verbs (DRF CBV)
    "post", "get", "put", "patch", "delete", "head", "options",
    # DRF generic view hooks — project often overrides these
    "create", "perform_create",
    "update", "partial_update", "perform_update",
    "destroy", "perform_destroy",
    "list", "retrieve",
    "dispatch", "handle_exception",
    # Django management command
    "handle",
    # Queryset / serializer hooks commonly overridden in project files
    "get_queryset", "get_object", "get_serializer", "get_serializer_class",
    "perform_authentication", "validate",
}

# Decorators that are "noise" for the decoupled-flow collector
_NOISE_DECORATORS = {
    "staticmethod", "classmethod", "property", "override",
    "abstractmethod", "cached_property", "login_required",
    "permission_required", "csrf_exempt",
}

# Method names so common in Python (dict, list, str, ORM) that tracing them
# almost always produces false positives.  Skip them entirely.
_SKIP_GENERIC_NAMES = {
    # dict / Mapping methods
    "get", "set", "items", "keys", "values", "pop", "clear", "setdefault",
    "update",   # dict.update — too noisy; real .update() calls differ
    # list / sequence methods
    "append", "extend", "insert", "remove", "index", "count", "sort", "reverse",
    # str methods
    "encode", "decode", "strip", "lstrip", "rstrip", "split", "join",
    "replace", "format", "startswith", "endswith", "upper", "lower", "title",
    # file / IO
    "read", "write", "close", "seek", "flush", "readline", "readlines",
    # generic Python built-ins used as attribute calls
    "copy", "deepcopy",
}

# DRF mixin/view name patterns → HTTP methods they handle.
# Used to infer the correct method when a CBV has no direct HTTP verbs defined.
_MIXIN_NAME_TO_METHODS: Dict[str, List[str]] = {
    "create":   ["POST"],
    "list":     ["GET"],
    "retrieve": ["GET"],
    "update":   ["PUT", "PATCH"],
    "destroy":  ["DELETE"],
    "detail":   ["GET"],
}

# DRF framework-level serializer methods that contain real project logic.
# When a view declares `serializer_class`, we seed the chain from these.
_SERIALIZER_SEED_METHODS = {
    "create", "update", "validate", "to_internal_value",
}


# ---------------------------------------------------------------------------
# FlowTracer
# ---------------------------------------------------------------------------

class FlowTracer:
    """
    Detects all entry points and traces their execution flows.

    Usage:
        tracer = FlowTracer(codebase, project_root)
        entry_points = tracer.detect_all_entry_points()
    """

    def __init__(self, codebase: Codebase, project_root: Path) -> None:
        self.codebase = codebase
        self.project_root = project_root
        self._import_cache: Dict[Path, Set[Path]] = {}  # source file → imported project files

        # Map (file_path, func_name, line_start) → class_name (or None if module-level)
        # Used to avoid tracing calls to methods of unrelated classes in the same file.
        self._method_class: Dict[tuple, Optional[str]] = {}
        for file_info in codebase.files.values():
            for func in file_info.functions:
                self._method_class[(file_info.path, func.name, func.line_start)] = None
            for cls in file_info.classes:
                for method in cls.methods:
                    self._method_class[(file_info.path, method.name, method.line_start)] = cls.name

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def detect_all_entry_points(self) -> List[EntryPoint]:
        """Return all detected entry points, sorted by kind then label."""
        eps: List[EntryPoint] = []
        eps.extend(self._detect_django_endpoints())
        eps.extend(self._detect_generic_http_routes())   # FastAPI / Flask
        eps.extend(self._detect_celery_tasks())
        eps.extend(self._detect_signal_receivers())
        eps.extend(self._detect_management_commands())

        # Deduplicate by (kind, label, url_path)
        seen: Set[tuple] = set()
        unique: List[EntryPoint] = []
        for ep in eps:
            key = (ep.kind, ep.label, ep.url_path)
            if key not in seen:
                seen.add(key)
                unique.append(ep)

        # Enrich with call chain + decoupled flows
        for ep in unique:
            self._enrich(ep)

        unique.sort(key=lambda e: (e.kind, e.label))
        return unique

    # ------------------------------------------------------------------
    # Entry-point detection
    # ------------------------------------------------------------------

    def _detect_django_endpoints(self) -> List[EntryPoint]:
        """Parse urlpatterns in all urls.py files."""
        eps: List[EntryPoint] = []

        for file_info in self.codebase.files.values():
            if file_info.path.name != "urls.py":
                continue
            try:
                source = file_info.path.read_text(encoding="utf-8")
                tree = ast.parse(source)
            except (OSError, SyntaxError):
                continue

            for node in ast.walk(tree):
                if not (
                    isinstance(node, ast.Assign)
                    and len(node.targets) == 1
                    and isinstance(node.targets[0], ast.Name)
                    and node.targets[0].id == "urlpatterns"
                    and isinstance(node.value, (ast.List, ast.Tuple))
                ):
                    continue

                for elt in node.value.elts:
                    ep = self._parse_django_url_element(elt, file_info)
                    if ep:
                        eps.append(ep)

        return eps

    def _parse_django_url_element(
        self, node: ast.expr, urls_file: FileInfo
    ) -> Optional[EntryPoint]:
        if not isinstance(node, ast.Call):
            return None

        func_name = _call_func_name(node)
        if func_name not in ("url", "re_path", "path") or len(node.args) < 2:
            return None

        raw_pattern = _eval_str(node.args[0])
        if raw_pattern is None:
            return None

        view_node = node.args[1]
        view_class_name = _extract_view_class_name(view_node)
        if view_class_name is None:
            return None

        url_path = _regex_to_openapi_path(raw_pattern)

        # Find view class
        class_list = self.codebase.classes_by_name.get(view_class_name, [])
        class_info = class_list[0] if class_list else None

        http_methods = []
        description = ""
        file_rel = self._rel(urls_file.path)

        if class_info:
            file_rel = self._rel(class_info.file_path)
            description = class_info.docstring or ""
            http_methods = [
                m.name.upper()
                for m in class_info.methods
                if m.name.lower() in _HTTP_METHODS
            ]
            # No direct methods — infer from class/mixin names in the MRO.
            if not http_methods:
                http_methods = self._infer_http_methods_from_mro(class_info)

        if not http_methods:
            http_methods = ["GET"]

        return EntryPoint(
            kind="http",
            label=view_class_name,
            description=description,
            file=file_rel,
            http_methods=http_methods,
            url_path=url_path,
        )

    def _detect_generic_http_routes(self) -> List[EntryPoint]:
        """
        Detect FastAPI / Flask route handlers via decorator_details.

        FastAPI: @router.get("/path") → decorator full_name like "router.get"
        Flask:   @app.route("/path", methods=["GET"])
        """
        eps: List[EntryPoint] = []

        for file_info in self.codebase.files.values():
            for func in file_info.get_all_functions():
                for dec in func.decorator_details:
                    name = dec.get("name", "")
                    full = dec.get("full_name", "")
                    args = dec.get("args", [])
                    kwargs = dec.get("kwargs", {})

                    # FastAPI-style: @router.get("/path") or @app.get("/path")
                    if name in _HTTP_METHODS and "." in (full or ""):
                        url = next((a for a in args if isinstance(a, str) and a.startswith("/")), "")
                        eps.append(EntryPoint(
                            kind="http",
                            label=func.name,
                            description=func.docstring or "",
                            file=self._rel(func.file_path),
                            http_methods=[name.upper()],
                            url_path=url,
                        ))
                        break

                    # Flask-style: @app.route("/path", methods=[...])
                    if name == "route" and args:
                        url = args[0] if isinstance(args[0], str) else ""
                        methods = kwargs.get("methods", ["GET"])
                        if isinstance(methods, list):
                            methods = [m.upper() for m in methods]
                        else:
                            methods = ["GET"]
                        eps.append(EntryPoint(
                            kind="http",
                            label=func.name,
                            description=func.docstring or "",
                            file=self._rel(func.file_path),
                            http_methods=methods,
                            url_path=url,
                        ))
                        break

        return eps

    def _detect_celery_tasks(self) -> List[EntryPoint]:
        """Detect @shared_task / @app.task / @celery.task functions."""
        eps: List[EntryPoint] = []

        for file_info in self.codebase.files.values():
            for func in file_info.get_all_functions():
                for dec in func.decorator_details:
                    name = dec.get("name", "")
                    if name in _CELERY_TASK_DECORATORS:
                        eps.append(EntryPoint(
                            kind="task",
                            label=func.name,
                            description=func.docstring or "",
                            file=self._rel(func.file_path),
                        ))
                        break

        return eps

    def _detect_signal_receivers(self) -> List[EntryPoint]:
        """Detect @receiver(signal, sender=X) functions."""
        eps: List[EntryPoint] = []

        for file_info in self.codebase.files.values():
            for func in file_info.get_all_functions():
                for dec in func.decorator_details:
                    if dec.get("name") not in _SIGNAL_DECORATORS:
                        continue
                    args = dec.get("args", [])
                    kwargs = dec.get("kwargs", {})
                    signal = args[0] if args else "unknown_signal"
                    sender = kwargs.get("sender", "")
                    label = f"{func.name} ← {signal}"
                    if sender:
                        label += f"[{sender}]"
                    eps.append(EntryPoint(
                        kind="signal",
                        label=label,
                        description=func.docstring or "",
                        file=self._rel(func.file_path),
                    ))
                    break

        return eps

    def _detect_management_commands(self) -> List[EntryPoint]:
        """Detect Django management commands (classes inheriting BaseCommand)."""
        eps: List[EntryPoint] = []

        for file_info in self.codebase.files.values():
            for cls in file_info.classes:
                if "BaseCommand" not in cls.bases and "Command" not in cls.bases:
                    continue
                # Find the handle() method
                handle = next((m for m in cls.methods if m.name == "handle"), None)
                eps.append(EntryPoint(
                    kind="command",
                    label=cls.name,
                    description=(handle.docstring if handle else cls.docstring) or "",
                    file=self._rel(cls.file_path),
                ))

        return eps

    # ------------------------------------------------------------------
    # Flow enrichment
    # ------------------------------------------------------------------

    def _collect_inherited_seeds(self, cls) -> List[FunctionInfo]:
        """
        Walk the class MRO through project-level base classes (breadth-first) and
        collect framework hook methods that Django/DRF would call during a request.

        Non-project classes (DRF, stdlib) are silently skipped — their call chain
        is opaque to static analysis, but their project-level overrides are not.
        """
        seeds: List[FunctionInfo] = []
        visited: Set[str] = {cls.name}
        queue: List[str] = list(cls.bases)

        while queue and len(seeds) < 6:
            base_name = queue.pop(0)
            if base_name in visited:
                continue
            visited.add(base_name)

            base_classes = self.codebase.classes_by_name.get(base_name, [])
            if not base_classes:
                # Not in the project (DRF / stdlib) — nothing to trace, skip.
                continue

            base_cls = base_classes[0]
            for method in base_cls.methods:
                if method.name in _FRAMEWORK_ENTRY_METHODS:
                    seeds.append(method)

            # Continue up the chain in case the base also inherits from something useful.
            queue.extend(base_cls.bases)

        return seeds

    def _infer_http_methods_from_mro(self, cls) -> List[str]:
        """
        Walk the full MRO (project classes + name heuristics) to infer which
        HTTP method(s) this CBV handles, when it defines none directly.

        Checks each base class name against _MIXIN_NAME_TO_METHODS keywords.
        E.g. "CreateAPIMixin" contains "create" → ["POST"].
        """
        visited: Set[str] = {cls.name}
        queue: List[str] = list(cls.bases)

        while queue:
            base_name = queue.pop(0)
            if base_name in visited:
                continue
            visited.add(base_name)

            lower = base_name.lower()
            for keyword, methods in _MIXIN_NAME_TO_METHODS.items():
                if keyword in lower:
                    return methods

            # Keep walking through project-level bases
            base_classes = self.codebase.classes_by_name.get(base_name, [])
            if base_classes:
                queue.extend(base_classes[0].bases)

        return []

    def _get_serializer_seeds(self, cls) -> List[FunctionInfo]:
        """
        If *cls* declares `serializer_class = SomeSerializer`, find that
        serializer class in the project and return its domain-logic methods
        (create, update, validate, validate_*, to_internal_value) as seeds.

        This bridges the DRF gap: CBVs with no body delegate all logic to
        the serializer's create/validate path.
        """
        serializer_name = _extract_class_attr_value(cls.code, "serializer_class")
        if not serializer_name:
            return []

        ser_classes = self.codebase.classes_by_name.get(serializer_name, [])
        if not ser_classes:
            return []

        seeds: List[FunctionInfo] = []
        for method in ser_classes[0].methods:
            if (
                method.name in _SERIALIZER_SEED_METHODS
                or method.name.startswith("validate_")
            ):
                seeds.append(method)
        return seeds

    def _enrich(self, ep: EntryPoint) -> None:
        """
        Populate ep.call_chain and ep.decoupled_flows via static analysis.

        Call chain: depth-limited BFS from the entry point's function(s).
        Decoupled flows: all framework-invoked functions in files touched by the chain.
        """
        # Find the seed function(s) to trace from
        seeds: List[FunctionInfo] = []

        if ep.kind == "http":
            # For class-based views, trace each HTTP method
            class_list = self.codebase.classes_by_name.get(ep.label, [])
            if class_list:
                cls = class_list[0]
                for method in cls.methods:
                    if method.name.lower() in _HTTP_METHODS or method.name in ("dispatch", "handle"):
                        seeds.append(method)
                # No direct HTTP methods — view delegates to framework base classes.
                # Walk the MRO through project-level classes to find overridden
                # framework hooks (handle_exception, get_queryset, perform_create, …).
                if not seeds:
                    seeds = self._collect_inherited_seeds(cls)

                # Always add serializer seeds: `serializer_class = XSerializer`
                # is the primary delegation mechanism in DRF generic views.
                # These often hold all the real business logic.
                serializer_seeds = self._get_serializer_seeds(cls)
                # Append serializer seeds that aren't already in the chain.
                existing_names = {s.name for s in seeds}
                for ss in serializer_seeds:
                    if ss.name not in existing_names:
                        seeds.append(ss)
                        existing_names.add(ss.name)

            # For function-based views (FastAPI/Flask), find the function directly
            if not seeds:
                func_list = self.codebase.functions_by_name.get(ep.label, [])
                seeds.extend(func_list)
        else:
            func_list = self.codebase.functions_by_name.get(ep.label.split(" ←")[0].strip(), [])
            seeds.extend(func_list)

        visited_keys: Set[str] = set()
        chain_steps: List[FlowStep] = []
        chain_files: Set[Path] = {
            next(
                (fi.path for fi in self.codebase.files.values() if self._rel(fi.path) == ep.file),
                Path(),
            )
        }

        for seed in seeds[:3]:  # limit seeds to avoid explosion
            self._trace_calls(seed, visited_keys, chain_steps, chain_files, depth=0, max_depth=4)

        ep.call_chain = chain_steps

        # Collect decoupled flows from files in the call chain
        ep.decoupled_flows = self._collect_decoupled_flows(chain_files)

    def _get_imported_files(self, source_file: Path) -> Set[Path]:
        """
        Return the set of project file paths that *source_file* imports.
        Result is cached after the first parse.
        """
        if source_file in self._import_cache:
            return self._import_cache[source_file]

        imported: Set[Path] = set()
        try:
            source = source_file.read_text(encoding="utf-8", errors="replace")
            tree = ast.parse(source)
        except (OSError, SyntaxError):
            self._import_cache[source_file] = imported
            return imported

        # Collect all module names referenced in import statements
        modules: List[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                modules.append(node.module)
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    modules.append(alias.name)

        # Map module dotted names → project file paths
        for file_path in self.codebase.files:
            try:
                rel = file_path.relative_to(self.project_root).with_suffix("")
            except ValueError:
                continue
            rel_dotted = ".".join(rel.parts)
            for mod in modules:
                # Exact match or the file is a submodule of the import
                if rel_dotted == mod or rel_dotted.endswith("." + mod) or mod.endswith("." + rel_dotted):
                    imported.add(file_path)
                    break

        self._import_cache[source_file] = imported
        return imported

    def _resolve_candidates(
        self, func: FunctionInfo, called_name: str
    ) -> List[FunctionInfo]:
        """
        Return project functions named *called_name* that are reachable from
        *func* based on what its file actually imports.

        - Skips names so generic they would almost always be false positives.
        - For same-file candidates, prefers those in the same class (or module-level).
          Methods of *other* classes in the same file are excluded to avoid
          tracing e.g. dict.get() matching an unrelated view's get() method.
        - Falls through to import-based filter when no same-file match survives.
        - Returns [] if nothing passes the filter (skip rather than guess wrong).
        """
        if called_name in _SKIP_GENERIC_NAMES:
            return []

        all_candidates = self.codebase.functions_by_name.get(called_name, [])
        if not all_candidates:
            return []

        same_file = [c for c in all_candidates if c.file_path == func.file_path]
        if same_file:
            caller_class = self._method_class.get((func.file_path, func.name, func.line_start))
            if caller_class is not None:
                # Narrow to same class or module-level; exclude unrelated class methods
                narrowed = [
                    c for c in same_file
                    if self._method_class.get((c.file_path, c.name, c.line_start)) in (caller_class, None)
                ]
                same_file = narrowed  # may be empty — fall through to import filter below
            if same_file:
                return same_file

        imported = self._get_imported_files(func.file_path)
        filtered = [c for c in all_candidates if c.file_path in imported]
        return filtered  # may be empty — caller will skip rather than guess

    def _trace_calls(
        self,
        func: FunctionInfo,
        visited: Set[str],
        chain: List[Union[FlowStep, FlowFork]],
        files: Set[Path],
        depth: int,
        max_depth: int,
    ) -> None:
        key = f"{func.file_path}::{func.name}"
        if key in visited or depth > max_depth:
            return
        visited.add(key)

        chain.append(FlowStep(
            name=func.name,
            file=self._rel(func.file_path),
            signature=func.signature,
            docstring=func.docstring or "",
        ))
        files.add(func.file_path)

        for called_name in func.calls:
            candidates = self._resolve_candidates(func, called_name)
            if not candidates:
                continue  # skip — no import-valid match; don't guess wrong
            if len(candidates) == 1:
                self._trace_calls(candidates[0], visited, chain, files, depth + 1, max_depth)
            else:
                # Multiple valid implementations (e.g. strategy/gateway dispatch).
                # Show a fork rather than arbitrarily picking one.
                alts = [
                    FlowStep(name=c.name, file=self._rel(c.file_path),
                             signature=c.signature, docstring=c.docstring or "")
                    for c in candidates[:5]
                ]
                chain.append(FlowFork(alternatives=alts))
                # Track files touched by all alternatives for decoupled-flow collection
                for c in candidates[:5]:
                    files.add(c.file_path)

    def _collect_decoupled_flows(
        self, files: Set[Path]
    ) -> List[DecoupledFlowEntry]:
        """
        Collect all framework-invoked functions from the given set of files.

        A function is "framework-invoked" if it has a non-noise decorator
        that carries args or kwargs (i.e. not just @staticmethod).
        """
        flows: List[DecoupledFlowEntry] = []
        seen: Set[str] = set()

        for file_path in files:
            file_info = self.codebase.files.get(file_path)
            if not file_info:
                continue

            all_funcs: List[FunctionInfo] = list(file_info.functions)
            for cls in file_info.classes:
                all_funcs.extend(cls.methods)

            for func in all_funcs:
                for dec in func.decorator_details:
                    dec_name = dec.get("name", "")
                    if not dec_name or dec_name in _NOISE_DECORATORS:
                        continue
                    # Must have args or kwargs to be meaningful
                    if not (dec.get("args") or dec.get("kwargs")):
                        continue

                    key = f"{func.file_path}::{func.name}::{dec_name}"
                    if key in seen:
                        continue
                    seen.add(key)

                    flows.append(DecoupledFlowEntry(
                        decorator_name=dec_name,
                        decorator_repr=_fmt_decorator(dec),
                        function_name=func.name,
                        signature=func.signature,
                        file=self._rel(func.file_path),
                        docstring=func.docstring or "",
                    ))

        # Sort by decorator name, then by function name for stable output
        flows.sort(key=lambda f: (f.decorator_name, f.function_name))
        return flows

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _rel(self, path: Path) -> str:
        try:
            return str(path.relative_to(self.project_root))
        except ValueError:
            return str(path)


# ---------------------------------------------------------------------------
# Module-level helpers (shared with schema_generator)
# ---------------------------------------------------------------------------

def _fmt_decorator(detail: dict) -> str:
    name = detail.get("full_name") or detail.get("name", "")
    parts = [f"@{name}"]
    call_parts = [str(a) for a in detail.get("args", [])]
    call_parts += [f"{k}={v!r}" for k, v in detail.get("kwargs", {}).items()]
    if call_parts:
        parts.append(f"({', '.join(call_parts)})")
    return "".join(parts)


def _call_func_name(node: ast.Call) -> str:
    func = node.func
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return ""


def _eval_str(node: ast.expr) -> Optional[str]:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if hasattr(ast, "Str") and isinstance(node, ast.Str):  # type: ignore[attr-defined]
        return node.s  # type: ignore[attr-defined]
    return None


def _extract_view_class_name(node: ast.expr) -> Optional[str]:
    if isinstance(node, ast.Call):
        func = node.func
        if isinstance(func, ast.Attribute) and func.attr == "as_view":
            if isinstance(func.value, ast.Name):
                return func.value.id
            if isinstance(func.value, ast.Attribute):
                return func.value.attr
    if isinstance(node, ast.Name):
        return node.id
    return None


def _extract_class_attr_value(class_code: str, attr_name: str) -> Optional[str]:
    """
    Parse a class's source code (from ClassInfo.code, which is ast.unparse output)
    and return the RHS name for a simple `attr_name = SomeName` assignment,
    or None if not found or the RHS is not a plain name.
    """
    try:
        tree = ast.parse(textwrap.dedent(class_code))
    except SyntaxError:
        return None

    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef):
            continue
        for stmt in node.body:
            if not isinstance(stmt, ast.Assign):
                continue
            for target in stmt.targets:
                if isinstance(target, ast.Name) and target.id == attr_name:
                    if isinstance(stmt.value, ast.Name):
                        return stmt.value.id
                    if isinstance(stmt.value, ast.Attribute):
                        return stmt.value.attr
    return None


def _regex_to_openapi_path(pattern: str) -> str:
    p = pattern.lstrip("^").rstrip("$")
    p = re.sub(r"\\/\?$", "/", p)
    p = re.sub(r"\(\?P<(\w+)>[^)]+\)", r"{\1}", p)
    p = re.sub(r"<(?:\w+:)?(\w+)>", r"{\1}", p)
    p = re.sub(r"[\\^$*+?|()\[\]]", "", p)
    if not p.startswith("/"):
        p = "/" + p
    return re.sub(r"//+", "/", p)
