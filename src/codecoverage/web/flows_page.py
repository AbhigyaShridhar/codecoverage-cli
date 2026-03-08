"""
HTML template for the /flows documentation page.

Renders a self-contained, zero-CDN-dependency page that shows all detected
entry points grouped by kind, with their call chains and decoupled flows.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from jinja2 import Template

from codecoverage.web.flow_tracer import EntryPoint


_FLOWS_HTML = Template(r"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>{{ project_name }} — Flow Docs</title>
  <style>
    *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }

    :root {
      --bg:         #0f1117;
      --surface:    #1a1d27;
      --surface2:   #22263a;
      --border:     #2e3250;
      --text:       #d4d8f0;
      --muted:      #7880a8;
      --http:       #3b82f6;
      --task:       #f59e0b;
      --signal:     #10b981;
      --command:    #a855f7;
      --accent:     #6366f1;
      --code-bg:    #13152a;
    }

    body {
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      background: var(--bg);
      color: var(--text);
      display: flex;
      height: 100vh;
      overflow: hidden;
    }

    /* ── Sidebar ── */
    #sidebar {
      width: 280px;
      min-width: 240px;
      background: var(--surface);
      border-right: 1px solid var(--border);
      display: flex;
      flex-direction: column;
      overflow: hidden;
    }

    #sidebar-header {
      padding: 18px 16px 12px;
      border-bottom: 1px solid var(--border);
    }

    #sidebar-header h1 {
      font-size: 15px;
      font-weight: 700;
      color: #fff;
      margin-bottom: 2px;
    }

    #sidebar-header p {
      font-size: 12px;
      color: var(--muted);
    }

    #sidebar-search {
      padding: 10px 12px;
      border-bottom: 1px solid var(--border);
    }

    #sidebar-search input {
      width: 100%;
      background: var(--code-bg);
      border: 1px solid var(--border);
      border-radius: 6px;
      color: var(--text);
      font-size: 12px;
      padding: 6px 10px;
      outline: none;
    }

    #sidebar-search input:focus { border-color: var(--accent); }

    #nav { overflow-y: auto; flex: 1; padding: 8px 0; }

    .nav-group { margin-bottom: 4px; }

    .nav-group-label {
      font-size: 10px;
      font-weight: 700;
      letter-spacing: .08em;
      text-transform: uppercase;
      color: var(--muted);
      padding: 8px 16px 4px;
    }

    .nav-item {
      display: flex;
      align-items: center;
      gap: 8px;
      padding: 6px 16px;
      font-size: 13px;
      color: var(--text);
      cursor: pointer;
      border-radius: 0;
      transition: background .12s;
      text-decoration: none;
    }

    .nav-item:hover { background: var(--surface2); }
    .nav-item.active { background: var(--surface2); color: #fff; }

    .badge {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      font-size: 10px;
      font-weight: 700;
      border-radius: 4px;
      padding: 1px 5px;
      flex-shrink: 0;
    }

    .badge-http    { background: #1d3a6e; color: var(--http); }
    .badge-task    { background: #3d2a05; color: var(--task); }
    .badge-signal  { background: #063a25; color: var(--signal); }
    .badge-command { background: #2d1550; color: var(--command); }

    /* ── Main content ── */
    #main {
      flex: 1;
      overflow-y: auto;
      padding: 32px 40px;
    }

    .section-title {
      font-size: 20px;
      font-weight: 700;
      color: #fff;
      margin-bottom: 6px;
      padding-bottom: 10px;
      border-bottom: 1px solid var(--border);
    }

    .section-subtitle {
      font-size: 13px;
      color: var(--muted);
      margin-bottom: 24px;
    }

    /* ── Entry-point card ── */
    .ep-card {
      background: var(--surface);
      border: 1px solid var(--border);
      border-radius: 10px;
      margin-bottom: 20px;
      overflow: hidden;
    }

    .ep-header {
      display: flex;
      align-items: flex-start;
      gap: 12px;
      padding: 16px 20px;
      cursor: pointer;
      user-select: none;
    }

    .ep-header:hover { background: var(--surface2); }

    .ep-kind-dot {
      width: 10px;
      height: 10px;
      border-radius: 50%;
      margin-top: 5px;
      flex-shrink: 0;
    }

    .dot-http    { background: var(--http); }
    .dot-task    { background: var(--task); }
    .dot-signal  { background: var(--signal); }
    .dot-command { background: var(--command); }

    .ep-meta { flex: 1; min-width: 0; }

    .ep-label {
      font-size: 15px;
      font-weight: 700;
      color: #fff;
      margin-bottom: 4px;
    }

    .ep-url {
      font-family: "SFMono-Regular", Consolas, monospace;
      font-size: 12px;
      color: var(--accent);
      margin-bottom: 4px;
    }

    .ep-file {
      font-size: 11px;
      color: var(--muted);
    }

    .ep-methods { display: flex; gap: 6px; flex-wrap: wrap; }

    .method-pill {
      font-size: 11px;
      font-weight: 700;
      border-radius: 4px;
      padding: 2px 7px;
    }

    .pill-GET    { background: #0e3a1f; color: #4ade80; }
    .pill-POST   { background: #1d3a6e; color: #93c5fd; }
    .pill-PUT    { background: #3d2a05; color: #fcd34d; }
    .pill-PATCH  { background: #2d2005; color: #fde68a; }
    .pill-DELETE { background: #3a0e0e; color: #f87171; }

    .ep-toggle {
      font-size: 18px;
      color: var(--muted);
      line-height: 1;
      padding-top: 2px;
      transition: transform .2s;
    }

    .ep-body {
      border-top: 1px solid var(--border);
      padding: 16px 20px;
      display: none;
    }

    .ep-body.open { display: block; }

    .ep-description {
      font-size: 13px;
      line-height: 1.6;
      color: var(--text);
      margin-bottom: 16px;
    }

    .ep-llm-summary {
      font-size: 13px;
      line-height: 1.6;
      color: #e2e8f0;
      background: #1e2a45;
      border-left: 3px solid var(--accent);
      border-radius: 0 6px 6px 0;
      padding: 8px 12px;
      margin-bottom: 12px;
    }

    .ep-llm-label {
      font-size: 10px;
      font-weight: 700;
      text-transform: uppercase;
      letter-spacing: .07em;
      color: var(--accent);
      margin-bottom: 4px;
    }

    /* ── Subsections ── */
    .subsection { margin-bottom: 16px; }

    .subsection-title {
      font-size: 11px;
      font-weight: 700;
      text-transform: uppercase;
      letter-spacing: .07em;
      color: var(--muted);
      margin-bottom: 8px;
    }

    /* ── Call chain ── */
    .chain-list { list-style: none; }

    .chain-item {
      display: flex;
      gap: 10px;
      padding: 6px 0;
      border-bottom: 1px solid var(--border);
      align-items: flex-start;
    }

    .chain-item:last-child { border-bottom: none; }

    .chain-depth {
      font-size: 10px;
      color: var(--muted);
      min-width: 20px;
      margin-top: 3px;
    }

    .chain-sig {
      font-family: "SFMono-Regular", Consolas, monospace;
      font-size: 12px;
      color: #c4b5fd;
    }

    .chain-file { font-size: 11px; color: var(--muted); margin-top: 2px; }
    .chain-doc  { font-size: 12px; color: var(--text); margin-top: 2px; }

    /* ── Decoupled flows ── */
    .flows-group { margin-bottom: 12px; }

    .flows-group-label {
      font-size: 11px;
      font-weight: 700;
      color: var(--accent);
      margin-bottom: 6px;
    }

    .flow-item {
      background: var(--code-bg);
      border: 1px solid var(--border);
      border-radius: 6px;
      padding: 8px 12px;
      margin-bottom: 6px;
    }

    .flow-decorator {
      font-family: "SFMono-Regular", Consolas, monospace;
      font-size: 12px;
      color: #86efac;
      margin-bottom: 4px;
    }

    .flow-sig {
      font-family: "SFMono-Regular", Consolas, monospace;
      font-size: 12px;
      color: #c4b5fd;
      margin-bottom: 2px;
    }

    .flow-meta { font-size: 11px; color: var(--muted); }
    .flow-doc  { font-size: 12px; color: var(--text); margin-top: 4px; }

    /* ── Empty state ── */
    .empty { text-align: center; color: var(--muted); padding: 60px 0; font-size: 14px; }

    /* ── Scrollbars ── */
    ::-webkit-scrollbar { width: 6px; }
    ::-webkit-scrollbar-track { background: transparent; }
    ::-webkit-scrollbar-thumb { background: var(--border); border-radius: 3px; }

    .swagger-link {
      display: inline-flex;
      align-items: center;
      gap: 6px;
      font-size: 12px;
      color: var(--accent);
      text-decoration: none;
      padding: 5px 10px;
      border: 1px solid var(--border);
      border-radius: 6px;
      margin-top: 4px;
    }
    .swagger-link:hover { background: var(--surface2); }
  </style>
</head>
<body>

<!-- ─── Sidebar ─── -->
<div id="sidebar">
  <div id="sidebar-header">
    <h1>{{ project_name }}</h1>
    <p>{{ total }} entry point{{ 's' if total != 1 else '' }} detected</p>
    <a class="swagger-link" href="/" target="_blank">↗ Swagger UI (HTTP)</a>
  </div>
  <div id="sidebar-search">
    <input type="text" id="search" placeholder="Filter entry points…" oninput="filterNav(this.value)" />
  </div>
  <div id="nav">
    {% for kind, label, count in groups %}
    <div class="nav-group" data-kind="{{ kind }}">
      <div class="nav-group-label">{{ label }} ({{ count }})</div>
      {% for ep in entry_points if ep.kind == kind %}
      <a class="nav-item" href="#ep-{{ loop.index0 }}-{{ ep.kind }}-{{ ep.label | replace(' ', '_') }}"
         onclick="activateNav(this)">
        <span class="badge badge-{{ ep.kind }}">{{ ep.kind[0].upper() }}</span>
        <span class="nav-label">{{ ep.label }}</span>
      </a>
      {% endfor %}
    </div>
    {% endfor %}
  </div>
</div>

<!-- ─── Main ─── -->
<div id="main">

  {% if not entry_points %}
  <div class="empty">No entry points detected in this codebase.</div>
  {% endif %}

  {% for kind, label, count in groups %}
  {% set eps_in_group = entry_points | selectattr('kind', 'equalto', kind) | list %}
  {% if eps_in_group %}

  <div class="section-title">{{ label }}</div>
  <div class="section-subtitle">
    {{ count }} entry point{{ 's' if count != 1 else '' }}
    — static analysis, no LLM
  </div>

  {% for ep in eps_in_group %}
  {% set card_id = "ep-" ~ loop.index0 ~ "-" ~ ep.kind ~ "-" ~ ep.label | replace(' ', '_') %}
  <div class="ep-card" id="{{ card_id }}">

    <!-- Header (clickable) -->
    <div class="ep-header" onclick="toggleCard(this)">
      <div class="ep-kind-dot dot-{{ ep.kind }}"></div>
      <div class="ep-meta">
        <div class="ep-label">{{ ep.label }}</div>
        {% if ep.url_path %}
        <div class="ep-url">{{ ep.url_path }}</div>
        {% endif %}
        <div class="ep-file">{{ ep.file }}</div>
        {% if ep.http_methods %}
        <div class="ep-methods" style="margin-top:6px">
          {% for m in ep.http_methods %}
          <span class="method-pill pill-{{ m }}">{{ m }}</span>
          {% endfor %}
        </div>
        {% endif %}
      </div>
      <div class="ep-toggle">›</div>
    </div>

    <!-- Body (collapsed by default) -->
    <div class="ep-body">

      {% set llm_sum = summaries.get(ep.file ~ "::" ~ ep.label) %}
      {% if llm_sum %}
      <div class="ep-llm-summary">
        <div class="ep-llm-label">AI summary</div>
        {{ llm_sum }}
      </div>
      {% endif %}

      {% if ep.description %}
      <div class="ep-description">{{ ep.description }}</div>
      {% endif %}

      <!-- Call chain -->
      {% if ep.call_chain %}
      <div class="subsection">
        <div class="subsection-title">Call chain (depth ≤ 4)</div>
        <ul class="chain-list">
          {% for step in ep.call_chain %}
          <li class="chain-item">
            <span class="chain-depth">{{ loop.index }}.</span>
            <div>
              <div class="chain-sig">{{ step.signature }}</div>
              <div class="chain-file">{{ step.file }}</div>
              {% if step.docstring %}
              <div class="chain-doc">{{ step.docstring[:120] }}{% if step.docstring|length > 120 %}…{% endif %}</div>
              {% endif %}
            </div>
          </li>
          {% endfor %}
        </ul>
      </div>
      {% endif %}

      <!-- Decoupled flows -->
      {% if ep.decoupled_flows %}
      <div class="subsection">
        <div class="subsection-title">
          Decoupled flows in this execution path
        </div>
        {% set ns = namespace(current_dec='') %}
        {% for flow in ep.decoupled_flows %}
        {% if flow.decorator_name != ns.current_dec %}
        {% if not loop.first %}</div>{% endif %}
        {% set ns.current_dec = flow.decorator_name %}
        <div class="flows-group">
          <div class="flows-group-label">@{{ flow.decorator_name }}</div>
        {% endif %}
          <div class="flow-item">
            <div class="flow-decorator">{{ flow.decorator_repr }}</div>
            <div class="flow-sig">{{ flow.signature }}</div>
            <div class="flow-meta">{{ flow.file }}</div>
            {% if flow.docstring %}
            <div class="flow-doc">{{ flow.docstring[:120] }}{% if flow.docstring|length > 120 %}…{% endif %}</div>
            {% endif %}
          </div>
        {% if loop.last %}</div>{% endif %}
        {% endfor %}
      </div>
      {% endif %}

      {% if not ep.call_chain and not ep.decoupled_flows and not ep.description %}
      <div style="color: var(--muted); font-size: 13px;">No additional flow information detected.</div>
      {% endif %}

    </div><!-- /.ep-body -->
  </div><!-- /.ep-card -->
  {% endfor %}

  <div style="margin-bottom: 40px;"></div>
  {% endif %}
  {% endfor %}

</div><!-- /#main -->

<script>
  function toggleCard(header) {
    const body = header.nextElementSibling;
    const toggle = header.querySelector('.ep-toggle');
    const open = body.classList.toggle('open');
    toggle.style.transform = open ? 'rotate(90deg)' : '';
  }

  function activateNav(el) {
    document.querySelectorAll('.nav-item').forEach(i => i.classList.remove('active'));
    el.classList.add('active');
    // Auto-open the card
    const target = document.querySelector(el.getAttribute('href'));
    if (target) {
      const body = target.querySelector('.ep-body');
      const toggle = target.querySelector('.ep-toggle');
      if (body && !body.classList.contains('open')) {
        body.classList.add('open');
        toggle.style.transform = 'rotate(90deg)';
      }
    }
  }

  function filterNav(query) {
    const q = query.toLowerCase();
    document.querySelectorAll('.nav-item').forEach(item => {
      const label = item.querySelector('.nav-label').textContent.toLowerCase();
      item.style.display = label.includes(q) ? '' : 'none';
    });
    document.querySelectorAll('.nav-group').forEach(group => {
      const visible = [...group.querySelectorAll('.nav-item')]
        .some(i => i.style.display !== 'none');
      group.style.display = visible ? '' : 'none';
    });
  }

  // Activate nav item matching current hash on load
  window.addEventListener('load', () => {
    if (location.hash) {
      const link = document.querySelector(`.nav-item[href="${location.hash}"]`);
      if (link) activateNav(link);
    }
  });
</script>

</body>
</html>
""")


_KIND_LABELS = [
    ("http",    "HTTP Endpoints"),
    ("task",    "Background Tasks"),
    ("signal",  "Signal Handlers"),
    ("command", "Management Commands"),
]


def render_flows_page(
    entry_points: List[EntryPoint],
    project_name: str,
    doc_cache: Optional[Any] = None,
) -> str:
    """
    Render the /flows HTML page from a list of EntryPoint objects.

    Args:
        entry_points: Detected entry points (already enriched with call chains).
        project_name: Shown in the page title and sidebar header.
        doc_cache:    Optional DocCache; if provided, LLM summaries are shown as
                      highlighted callouts on each entry-point card.

    Returns:
        Complete HTML string, self-contained (no external resources).
    """
    counts: Dict[str, int] = {}
    for ep in entry_points:
        counts[ep.kind] = counts.get(ep.kind, 0) + 1

    groups = [
        (kind, label, counts[kind])
        for kind, label in _KIND_LABELS
        if counts.get(kind, 0) > 0
    ]

    # Build a flat {"{file}::{label}": summary} dict for template lookup.
    # Resolution order:
    #   1. Direct match on (ep.file, ep.label)  — works when generate was run on the class/func
    #   2. Walk the call chain for any step in the same file with a cached doc
    summaries: Dict[str, str] = {}
    if doc_cache is not None:
        for ep in entry_points:
            key = f"{ep.file}::{ep.label}"
            s = doc_cache.get_summary(ep.file, ep.label)
            if s:
                summaries[key] = s
                continue
            for step in ep.call_chain:
                if step.file == ep.file:
                    s = doc_cache.get_summary(step.file, step.name)
                    if s:
                        summaries[key] = s
                        break

    return _FLOWS_HTML.render(
        project_name=project_name,
        entry_points=entry_points,
        groups=groups,
        total=len(entry_points),
        summaries=summaries,
    )
