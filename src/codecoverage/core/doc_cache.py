"""
Persistent cache for LLM-generated function documentation.

Stored at .codecoverage/docs-cache.json, relative to the project root.
Updated incrementally by `generate` and `diff-test` commands.
Read (no LLM calls) by the `serve` command.

Cache key: "rel/path/to/file.py::func_name"

Entry shape:
    summary       str   — one-sentence behavioural description
    behaviors     list  — key observable behaviors
    side_effects  list  — signals emitted, tasks enqueued, DB writes
    test_coverage str   — what the generated tests verify
    hash          str   — sha256[:16] of source file bytes at write time
    updated_at    str   — ISO-8601 UTC timestamp
"""

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional


class DocCache:
    """
    Thin JSON-backed store mapping function identifiers to LLM-generated docs.

    Usage (write side — generate / diff-test):
        cache = DocCache(project_root).load()
        cache.put(rel_file, func_name, doc_dict, source_bytes=bytes)
        cache.save()

    Usage (read side — serve):
        cache = DocCache(project_root).load()
        summary = cache.get_summary(rel_file, func_name)  # None if not cached
    """

    def __init__(self, project_root: Path) -> None:
        self._path = project_root / ".codecoverage" / "docs-cache.json"
        self._data: Dict[str, Any] = {}

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def load(self) -> "DocCache":
        """Load from disk. Returns self for chaining."""
        if self._path.exists():
            try:
                self._data = json.loads(self._path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                self._data = {}
        return self

    def save(self) -> None:
        """Persist to disk atomically."""
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(
            json.dumps(self._data, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    def get_summary(self, rel_file: str, func_name: str) -> Optional[str]:
        """Return the cached one-sentence summary, or None if not found."""
        entry = self._data.get(_key(rel_file, func_name))
        return entry.get("summary") if entry else None

    def get_entry(self, rel_file: str, func_name: str) -> Optional[Dict[str, Any]]:
        """Return the full cached doc entry dict, or None."""
        return self._data.get(_key(rel_file, func_name))

    # ------------------------------------------------------------------
    # Write
    # ------------------------------------------------------------------

    def put(
        self,
        rel_file: str,
        func_name: str,
        doc: Dict[str, Any],
        source_bytes: Optional[bytes] = None,
    ) -> None:
        """
        Store a doc entry for a function.

        Args:
            rel_file:     Relative path to the source file (e.g. "payments/views.py").
            func_name:    Function or class name.
            doc:          Dict from the LLM — must contain at least "summary".
            source_bytes: Raw source file bytes; used to record a hash for auditing.
        """
        entry: Dict[str, Any] = {k: v for k, v in doc.items() if v}
        if source_bytes is not None:
            entry["hash"] = hashlib.sha256(source_bytes).hexdigest()[:16]
        entry["updated_at"] = datetime.now(timezone.utc).isoformat()
        self._data[_key(rel_file, func_name)] = entry

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def __len__(self) -> int:
        return len(self._data)

    def __contains__(self, item: object) -> bool:
        return item in self._data


def _key(rel_file: str, func_name: str) -> str:
    return f"{rel_file}::{func_name}"
