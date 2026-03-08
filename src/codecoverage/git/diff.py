"""
Git diff analysis for function-level change detection.

Compares two git states and classifies changes at the function level,
so the diff-test command knows exactly which functions to re-test.
"""

import ast
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Literal, Optional, Set

import git


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class FunctionDiff:
    name: str
    change_type: Literal["added", "modified", "deleted"]


@dataclass
class FileDiff:
    """
    Function-level diff summary for a single Python file.

    Attributes:
        file_path   : Absolute path to the file (new version; old version if deleted)
        rel_path    : Path relative to repo root
        file_change : Whether the file itself was added / modified / deleted
        functions   : Per-function change list
        raw_diff    : Full unified diff text for this file (for LLM context)
    """
    file_path: Path
    rel_path: str
    file_change: Literal["added", "modified", "deleted"]
    functions: List[FunctionDiff] = field(default_factory=list)
    raw_diff: str = ""

    # Convenience views
    @property
    def added(self) -> List[str]:
        return [f.name for f in self.functions if f.change_type == "added"]

    @property
    def modified(self) -> List[str]:
        return [f.name for f in self.functions if f.change_type == "modified"]

    @property
    def deleted(self) -> List[str]:
        return [f.name for f in self.functions if f.change_type == "deleted"]

    @property
    def actionable(self) -> List[FunctionDiff]:
        """Functions that need test generation/update (not deleted)."""
        return [f for f in self.functions if f.change_type != "deleted"]


# ---------------------------------------------------------------------------
# Analyzer
# ---------------------------------------------------------------------------

class DiffAnalyzer:
    """
    Analyses a git repository to produce function-level diff information.

    Usage:
        analyzer = DiffAnalyzer(Path("/path/to/repo"))

        # Uncommitted changes (staged + unstaged) vs HEAD
        diffs = analyzer.get_working_diff()

        # Last commit
        diffs = analyzer.get_last_commit_diff()

        # Last merge commit
        diffs = analyzer.get_last_merge_diff()

        # Arbitrary refs
        diffs = analyzer.get_ref_diff("main", "HEAD")
    """

    def __init__(self, repo_path: Path):
        try:
            self.repo = git.Repo(repo_path, search_parent_directories=True)
            self.root = Path(self.repo.working_dir)
        except git.InvalidGitRepositoryError:
            raise ValueError(f"Not a git repository: {repo_path}")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_working_diff(self) -> List[FileDiff]:
        """Staged + unstaged changes vs HEAD."""
        # Collect changed files from both staged and unstaged
        staged_paths = self._changed_paths_from_diff_index(
            self.repo.index.diff(self.repo.head.commit)
        )
        unstaged_paths = self._changed_paths_from_diff_index(
            self.repo.head.commit.diff(None)
        )
        all_paths = staged_paths | unstaged_paths

        results = []
        for rel_path, file_change in all_paths.items():
            raw = self._raw_diff_working(rel_path)
            fd = self._build_file_diff(rel_path, file_change, raw, base_blob=None)
            if fd:
                results.append(fd)
        return results

    def get_last_commit_diff(self) -> List[FileDiff]:
        """Changes introduced by the most recent commit."""
        return self.get_ref_diff("HEAD~1", "HEAD")

    def get_last_merge_diff(self) -> List[FileDiff]:
        """Changes introduced by the most recent merge commit."""
        for commit in self.repo.iter_commits():
            if len(commit.parents) >= 2:
                parent = commit.parents[0]
                return self.get_ref_diff(parent.hexsha, commit.hexsha)
        raise ValueError("No merge commits found in repository history.")

    def get_ref_diff(self, base: str, head: str = "HEAD") -> List[FileDiff]:
        """Diff between two arbitrary git refs."""
        try:
            base_commit = self.repo.commit(base)
            head_commit = self.repo.commit(head)
        except git.BadName as e:
            raise ValueError(f"Unknown git ref: {e}")

        diff_index = base_commit.diff(head_commit)
        results = []

        for item in diff_index:
            rel_path, file_change = self._classify_diff_item(item)
            if not rel_path.endswith(".py"):
                continue

            raw = self._raw_diff_refs(base, head, rel_path)
            base_blob = item.a_blob if file_change != "added" else None
            fd = self._build_file_diff(rel_path, file_change, raw, base_blob)
            if fd:
                results.append(fd)

        return results

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _changed_paths_from_diff_index(
        self, diff_index
    ) -> Dict[str, Literal["added", "modified", "deleted"]]:
        result: Dict[str, Literal["added", "modified", "deleted"]] = {}
        for item in diff_index:
            rel, change = self._classify_diff_item(item)
            if rel.endswith(".py"):
                result[rel] = change
        return result

    @staticmethod
    def _classify_diff_item(
        item,
    ) -> tuple[str, Literal["added", "modified", "deleted"]]:
        if item.new_file:
            return item.b_path, "added"
        if item.deleted_file:
            return item.a_path, "deleted"
        return (item.b_path or item.a_path), "modified"

    def _raw_diff_working(self, rel_path: str) -> str:
        """Get unified diff for a file vs HEAD (staged + unstaged)."""
        try:
            unstaged = self.repo.git.diff("HEAD", "--", rel_path)
            staged = self.repo.git.diff("--cached", "HEAD", "--", rel_path)
            # Prefer unstaged (more up-to-date); fall back to staged
            return (unstaged or staged).strip()
        except Exception:
            return ""

    def _raw_diff_refs(self, base: str, head: str, rel_path: str) -> str:
        try:
            return self.repo.git.diff(base, head, "--", rel_path).strip()
        except Exception:
            return ""

    def _build_file_diff(
        self,
        rel_path: str,
        file_change: Literal["added", "modified", "deleted"],
        raw_diff: str,
        base_blob,
    ) -> Optional[FileDiff]:
        """Build a FileDiff with function-level classification."""
        from codecoverage.core.parser import parse_file

        abs_path = self.root / rel_path

        fd = FileDiff(
            file_path=abs_path,
            rel_path=rel_path,
            file_change=file_change,
            raw_diff=raw_diff,
        )

        # Functions in the old version
        old_names: Set[str] = set(_funcs_from_blob(base_blob))

        # Functions in the new version
        new_funcs: Dict[str, object] = {}
        if file_change != "deleted" and abs_path.exists():
            file_info = parse_file(abs_path, self.root)
            if file_info:
                for f in file_info.get_all_functions():
                    new_funcs[f.name] = f

        new_names = set(new_funcs.keys())
        changed_lines = _changed_line_numbers(raw_diff)

        for name in new_names - old_names:
            fd.functions.append(FunctionDiff(name, "added"))

        for name in old_names - new_names:
            fd.functions.append(FunctionDiff(name, "deleted"))

        for name in old_names & new_names:
            func = new_funcs[name]
            func_lines = set(range(func.line_start, func.line_end + 1))  # type: ignore[attr-defined]
            if func_lines & changed_lines:
                fd.functions.append(FunctionDiff(name, "modified"))

        # Only include this file if something actually changed at function level,
        # or if the whole file was added/deleted.
        if fd.functions or file_change in ("added", "deleted"):
            return fd
        return None


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------

def _funcs_from_blob(blob) -> List[str]:
    """Extract all function names from a git blob (old file version)."""
    if blob is None:
        return []
    try:
        source = blob.data_stream.read().decode("utf-8", errors="replace")
        tree = ast.parse(source)
        return [
            node.name
            for node in ast.walk(tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        ]
    except Exception:
        return []


def _changed_line_numbers(diff_text: str) -> Set[int]:
    """
    Parse a unified diff and return the set of line numbers (new-file side)
    that were added or modified.
    """
    changed: Set[int] = set()
    current = 0
    for line in diff_text.splitlines():
        if line.startswith("@@"):
            m = re.search(r"\+(\d+)", line)
            if m:
                current = int(m.group(1)) - 1
        elif line.startswith("+") and not line.startswith("+++"):
            current += 1
            changed.add(current)
        elif line.startswith("-") and not line.startswith("---"):
            pass  # deletion — don't advance new-file line counter
        else:
            current += 1
    return changed
