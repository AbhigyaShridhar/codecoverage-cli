"""
HTTP server for the codecoverage documentation SPA.

GET /  → self-contained single-page app (HTML with embedded data)
"""

from __future__ import annotations

import webbrowser
from collections import defaultdict
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any, Dict, List, Optional

from codecoverage.web.flow_tracer import EntryPoint



class _Handler(BaseHTTPRequestHandler):
    html_bytes: bytes = b""

    def do_GET(self) -> None:  # noqa: N802
        path = self.path.split("?")[0]
        if path == "/":
            self._respond(200, "text/html; charset=utf-8", self.html_bytes)
        else:
            self._respond(404, "text/plain", b"Not found")

    def _respond(self, status: int, content_type: str, body: bytes) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt: str, *args: Any) -> None:  # noqa: ANN002
        pass  # suppress access log noise


def serve(
    project_name: str,
    doc_cache: Any,
    entry_points: List[EntryPoint],
    project_root: Any = None,
    port: int = 8080,
    open_browser: bool = True,
) -> None:
    """
    Build the documentation SPA from cached docs + entry points and serve it.

    Blocks until Ctrl+C.
    """
    from codecoverage.web.app import build_app_html

    data = _build_data(project_name, doc_cache, entry_points, project_root)
    _Handler.html_bytes = build_app_html(data).encode("utf-8")

    import socket
    httpd = HTTPServer(("localhost", port), _Handler)
    httpd.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    url = f"http://localhost:{port}"

    if open_browser:
        webbrowser.open(url)

    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()


# ---------------------------------------------------------------------------
# Data builder
# ---------------------------------------------------------------------------

def _build_data(
    project_name: str,
    doc_cache: Any,
    entry_points: List[EntryPoint],
    project_root: Any = None,
) -> Dict[str, Any]:
    """Assemble the JSON data object consumed by the SPA."""
    from codecoverage.core.markdown_renderer import _resolve_summary
    from codecoverage.analysis.test_refs import find_test_refs, find_test_refs_for_label
    from codecoverage.analysis.decision_extractor import extract_decision_points
    from codecoverage.tracing.reader import load_traces, match_trace

    # Load any runtime traces saved by the Django middleware
    traces = load_traces(project_root) if project_root else []

    # Function summaries grouped by file
    by_file: Dict[str, Dict[str, dict]] = defaultdict(dict)
    for key, entry in doc_cache._data.items():
        if "::" not in key:
            continue
        rel_file, func_name = key.split("::", 1)
        src = (project_root / rel_file) if project_root else None
        by_file[rel_file][func_name] = {
            "summary":         entry.get("summary", ""),
            "side_effects":    entry.get("side_effects"),
            "note":            entry.get("note"),
            "updated_at":      entry.get("updated_at", ""),
            "test_refs":       find_test_refs(rel_file, func_name, project_root) if project_root else [],
            "decision_points": extract_decision_points(src, func_name) if src and src.exists() else [],
        }

    # Entry points grouped by kind
    flows: Dict[str, list] = defaultdict(list)
    for ep in entry_points:
        url = None
        if ep.url_path:
            methods = " / ".join(ep.http_methods) if ep.http_methods else "GET"
            url = f"{methods} {ep.url_path}"

        # Prefer runtime trace; fall back to static call chain
        from codecoverage.web.flow_tracer import FlowFork as _FlowFork
        traced_chain = match_trace(ep.url_path, ep.http_methods, traces)
        if traced_chain is not None:
            raw_chain = traced_chain        # list of {"name", "file"} dicts
            chain_source = "traced"
        else:
            # Serialize FlowStep / FlowFork objects → plain dicts
            raw_chain = []
            for s in ep.call_chain:
                if isinstance(s, _FlowFork):
                    raw_chain.append({
                        "fork": True,
                        "alternatives": [{"name": a.name, "file": a.file} for a in s.alternatives],
                    })
                else:
                    raw_chain.append({"name": s.name, "file": s.file})
            chain_source = "static"

        # Enrich each step with its own decision points.
        # Fork steps get decision points per alternative.
        # Cache by (file, name) — cap unique extractions at 25 for perf.
        dp_cache: Dict[tuple, list] = {}
        enriched_chain: list = []

        def _get_dp(file: str, name: str) -> list:
            k = (file, name)
            if k not in dp_cache:
                if project_root and len(dp_cache) < 25:
                    src = project_root / file
                    dp_cache[k] = extract_decision_points(src, name) if src.exists() else []
                else:
                    dp_cache[k] = []
            return dp_cache[k]

        for step in raw_chain:
            if step.get("fork"):
                alts = [
                    {"name": a["name"], "file": a["file"],
                     "decision_points": _get_dp(a["file"], a["name"])}
                    for a in step["alternatives"]
                ]
                enriched_chain.append({"fork": True, "alternatives": alts})
            else:
                enriched_chain.append({
                    "name": step["name"],
                    "file": step["file"],
                    "decision_points": _get_dp(step["file"], step["name"]),
                })

        flows[ep.kind].append({
            "label":        ep.label,
            "url":          url,
            "file":         ep.file,
            "description":  ep.description,
            "summary":      _resolve_summary(ep, doc_cache),
            "call_chain":   enriched_chain,
            "chain_source": chain_source,
            "test_refs":    find_test_refs_for_label(ep.file, ep.label, project_root) if project_root else [],
            "decoupled_flows":     [
                {
                    "decorator_repr": df.decorator_repr,
                    "function_name":  df.function_name,
                    "file":           df.file,
                }
                for df in ep.decoupled_flows
            ],
        })

    return {
        "project":         project_name,
        "total_functions": len(doc_cache),
        "summary":         dict(by_file),
        "flows":           dict(flows),
    }
