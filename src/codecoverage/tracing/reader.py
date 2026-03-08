"""
Reads runtime call-chain traces saved by the CodeCoverage Django middleware.

Trace files live at:  <project_root>/.codecoverage/traces/<METHOD>_<safe_path>.json

Each file contains:
    {"method": "POST", "path": "/payments/...", "call_chain": [{"name": ..., "file": ...}, ...]}
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Dict, List, Optional


def load_traces(project_root: Path) -> List[Dict]:
    """Return all trace dicts found under .codecoverage/traces/."""
    trace_dir = project_root / ".codecoverage" / "traces"
    if not trace_dir.exists():
        return []
    traces = []
    for f in sorted(trace_dir.glob("*.json")):
        try:
            traces.append(json.loads(f.read_text(encoding="utf-8")))
        except Exception:
            continue
    return traces


def match_trace(
    ep_url: str,
    ep_methods: List[str],
    traces: List[Dict],
) -> Optional[List[Dict]]:
    """
    Find a trace whose HTTP method and URL match *ep_url* / *ep_methods*.

    Matching strategy:
      - Strip path-parameter placeholders from ep_url: /webhooks/{gw}/ → /webhooks/
      - Check that the trace path contains the cleaned pattern as a suffix
      - Method must appear in ep_methods (case-insensitive)

    Returns the call_chain list, or None if no match found.
    """
    if not ep_url or not traces:
        return None

    # Strip {param} placeholders and collapse double slashes
    ep_clean = re.sub(r"\{[^}]+\}", "", ep_url)
    ep_clean = re.sub(r"/+", "/", ep_clean).rstrip("/")
    if not ep_clean:
        return None

    methods_upper = {m.upper() for m in ep_methods}

    for trace in traces:
        if trace.get("method", "").upper() not in methods_upper:
            continue
        trace_path = re.sub(r"/+", "/", trace.get("path", "")).rstrip("/")
        if ep_clean in trace_path or trace_path.endswith(ep_clean):
            chain = trace.get("call_chain", [])
            return chain if chain else None

    return None
