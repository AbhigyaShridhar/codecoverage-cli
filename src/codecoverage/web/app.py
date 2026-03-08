"""
Single-page application HTML for ``codecoverage serve``.

All CSS and JS are self-contained — no external dependencies.
Project data is embedded as a JS constant at build time.
"""

from __future__ import annotations

import json
from typing import Any, Dict

_PROJ = "__CC_PROJECT__"
_DATA = "__CC_DATA__"


def build_app_html(data: Dict[str, Any]) -> str:
    """Return a complete, self-contained HTML string for the docs SPA."""
    project = data.get("project", "docs")
    data_json = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    # Prevent </script> in any string value from closing the script tag early
    data_json = data_json.replace("</", "<\\/")
    return _TEMPLATE.replace(_PROJ, project).replace(_DATA, data_json)


_TEMPLATE = """\
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>__CC_PROJECT__ \u2014 docs</title>
  <style>
*,*::before,*::after{box-sizing:border-box;margin:0;padding:0}
html,body{height:100%;font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;font-size:16px;color:#111827;background:#f5f6f8;-webkit-font-smoothing:antialiased}

/* ---- Header ---- */
#hdr{display:flex;align-items:center;gap:16px;height:56px;padding:0 20px;background:#0f172a;color:#fff;position:sticky;top:0;z-index:100;border-bottom:1px solid rgba(255,255,255,.07)}
.brand{display:flex;align-items:center;gap:10px;text-decoration:none;color:#fff;flex-shrink:0}
.brand-mark{width:28px;height:28px;border-radius:7px;background:linear-gradient(135deg,#6366f1,#8b5cf6);display:flex;align-items:center;justify-content:center;font-size:14px;font-weight:800;color:#fff}
.brand-name{font-size:14.5px;font-weight:700;letter-spacing:-.01em}
.brand-sep{opacity:.25;margin:0 2px}
.brand-sub{font-weight:400;opacity:.4;font-size:13px}
.search-wrap{flex:1;max-width:400px;position:relative}
.search-icon{position:absolute;left:11px;top:50%;transform:translateY(-50%);width:14px;height:14px;opacity:.3;pointer-events:none}
#search{width:100%;height:36px;padding:0 14px 0 33px;border:1px solid rgba(255,255,255,.12);border-radius:7px;background:rgba(255,255,255,.07);color:#fff;font-size:13px;outline:none;transition:all .15s}
#search::placeholder{color:rgba(255,255,255,.28)}
#search:focus{background:rgba(255,255,255,.12);border-color:rgba(255,255,255,.35)}
.hdr-right{margin-left:auto;display:flex;align-items:center;gap:12px}
#hdr-stats{font-size:11.5px;color:rgba(255,255,255,.3)}

/* ---- Layout ---- */
#layout{display:flex;height:calc(100vh - 56px);overflow:hidden}

/* ---- Sidebar ---- */
#sidebar{width:272px;min-width:272px;background:#fff;border-right:1px solid #e9ecef;overflow-y:auto;overflow-x:hidden;padding-bottom:60px}
.sec{margin-bottom:2px}
.sec-hdr{display:flex;align-items:center;gap:8px;padding:14px 16px 6px;font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:.1em;color:#9ca3af;cursor:pointer;user-select:none;background:#fff;position:sticky;top:0;z-index:1}
.sec-hdr:hover{color:#6b7280}
.sec-body{display:block}
.grp{margin:0 10px 1px}
.grp-hdr{display:flex;align-items:center;gap:7px;padding:6px 10px;font-size:12.5px;font-weight:600;color:#374151;cursor:pointer;border-radius:6px;user-select:none;transition:background .1s}
.grp-hdr:hover{background:#f3f4f6}
.grp-body{display:none;padding:0 0 6px}
.grp-body.open{display:block}
.nav-item{display:flex;align-items:center;gap:7px;padding:5px 10px 5px 22px;font-size:12.5px;color:#6b7280;text-decoration:none;border-radius:6px;margin:1px 0;overflow:hidden;white-space:nowrap;transition:background .1s,color .1s}
.nav-item:hover{background:#f3f4f6;color:#374151}
.nav-item.active{background:#eef2ff;color:#4f46e5;font-weight:600}
.nav-method{font-size:9.5px;font-weight:700;padding:1px 5px;border-radius:3px;flex-shrink:0;letter-spacing:.04em}
.nav-get{background:#dcfce7;color:#15803d}
.nav-post{background:#dbeafe;color:#1d4ed8}
.nav-put,.nav-patch{background:#fef9c3;color:#92400e}
.nav-delete{background:#fee2e2;color:#b91c1c}
.nav-any{background:#f3f4f6;color:#6b7280}
.nav-label{flex:1;overflow:hidden;text-overflow:ellipsis}
.chev{font-size:8px;color:#d1d5db;transition:transform .15s;flex-shrink:0}
.chev.open{transform:rotate(90deg)}
.nav-badge{font-size:10.5px;color:#d1d5db;margin-left:auto;flex-shrink:0}
.kind-dot{width:7px;height:7px;border-radius:50%;flex-shrink:0}
.dot-http{background:#6366f1}.dot-task{background:#f59e0b}.dot-signal{background:#10b981}.dot-command{background:#8b5cf6}

/* ---- Content ---- */
#content{flex:1;overflow-y:auto;background:#f5f6f8}
#content-inner{max-width:1060px;padding:52px 64px}

/* ---- Breadcrumb ---- */
.breadcrumb{display:flex;align-items:center;flex-wrap:wrap;gap:5px;font-size:12px;color:#9ca3af;margin-bottom:14px}
.breadcrumb .sep{opacity:.5}
.bc-cur{color:#6b7280;font-weight:500}

/* ---- Page header ---- */
h1.doc-title{font-size:1.9rem;font-weight:800;font-family:"SFMono-Regular",Consolas,"Liberation Mono",Menlo,monospace;color:#0f172a;margin-bottom:12px;word-break:break-all;line-height:1.25;letter-spacing:-.02em}
.ep-meta{display:flex;align-items:center;gap:10px;flex-wrap:wrap;margin-bottom:8px}
.ep-method{font-size:12px;font-weight:700;padding:4px 10px;border-radius:5px;letter-spacing:.06em}
.method-get{background:#dcfce7;color:#15803d}
.method-post{background:#dbeafe;color:#1d4ed8}
.method-put,.method-patch{background:#fef9c3;color:#92400e}
.method-delete{background:#fee2e2;color:#b91c1c}
.method-any{background:#f3f4f6;color:#374151}
.ep-url{font-family:monospace;font-size:14px;color:#374151;background:#fff;border:1.5px solid #e5e7eb;padding:4px 12px;border-radius:6px;letter-spacing:.01em}
.ep-file{font-family:monospace;font-size:12px;color:#9ca3af;display:block;margin-bottom:26px;margin-top:4px}
.divider{border:none;border-top:1px solid #e9ecef;margin:28px 0}

/* ---- Summary / description ---- */
p.summary{font-size:15.5px;line-height:1.85;color:#374151;margin-bottom:22px;max-width:760px}
p.description{font-size:14.5px;line-height:1.8;color:#6b7280;font-style:italic;margin-bottom:20px;max-width:720px;border-left:3px solid #e5e7eb;padding-left:14px}

/* ---- Section title ---- */
h2.sec-title{font-size:10.5px;font-weight:700;text-transform:uppercase;letter-spacing:.1em;color:#9ca3af;margin:40px 0 18px;display:flex;align-items:center;gap:10px}
h2.sec-title::after{content:'';flex:1;height:1px;background:#f3f4f6}

/* ---- Callouts ---- */
.callout{border-left:3px solid;padding:12px 16px;border-radius:0 8px 8px 0;margin:14px 0;font-size:14px;line-height:1.7}
.callout-label{font-size:9px;font-weight:700;text-transform:uppercase;letter-spacing:.1em;margin-bottom:5px;opacity:.75}
.callout-effects{border-color:#f59e0b;background:#fffbeb}.callout-effects .callout-label{color:#92400e}
.callout-note{border-color:#6366f1;background:#eef2ff}.callout-note .callout-label{color:#4338ca}

/* ---- Source badge ---- */
.source-badge{font-size:10.5px;font-weight:700;letter-spacing:.06em;padding:4px 10px;border-radius:20px;text-transform:uppercase}
.badge-traced{background:#dcfce7;color:#15803d}
.badge-static{background:#f3f4f6;color:#6b7280}
.flow-actions{display:flex;gap:8px;margin-left:auto}
.flow-btn{font-size:11.5px;color:#9ca3af;background:#fff;border:1px solid #e9ecef;padding:4px 12px;border-radius:5px;cursor:pointer;transition:all .15s;user-select:none}
.flow-btn:hover{border-color:#d1d5db;color:#6b7280}
.flow-top{display:flex;align-items:center;margin-bottom:24px}

/* ==================================================
   FLOW TIMELINE
   ================================================== */
.flow-timeline{position:relative;padding-left:52px}
/* vertical connecting line */
.flow-timeline::before{content:'';position:absolute;left:15px;top:28px;bottom:28px;width:2px;background:#e5e7eb;border-radius:2px}

/* ---- Step ---- */
.fn-step{position:relative;margin-bottom:10px}

/* numbered circle */
.fn-num{position:absolute;left:-52px;top:18px;width:32px;height:32px;border-radius:50%;display:flex;align-items:center;justify-content:center;font-size:11px;font-weight:800;background:#fff;border:2px solid #e5e7eb;color:#9ca3af;z-index:2;transition:all .2s}
.fn-num.c-entry{background:#f0fdf4;border-color:#86efac;color:#15803d}
.fn-num.c-svc{background:#eef2ff;border-color:#a5b4fc;color:#4338ca}

/* step card */
.fn-card{background:#fff;border:2px solid #e5e7eb;border-radius:14px;overflow:hidden;transition:border-color .2s,box-shadow .2s}
.fn-card.has-toggle{cursor:pointer}
.fn-card.has-toggle:hover{border-color:#c7d2fe;box-shadow:0 4px 20px rgba(0,0,0,.07)}
.fn-card.open{border-color:#818cf8;box-shadow:0 4px 24px rgba(99,102,241,.12)}

/* card top row */
.fn-hdr{display:flex;align-items:flex-start;padding:22px 26px 0;gap:16px}
.fn-info{flex:1;min-width:0}
.fn-name{font-family:"SFMono-Regular",Consolas,"Liberation Mono",Menlo,monospace;font-size:18px;font-weight:700;color:#0f172a;line-height:1.3}
.fn-name-paren{font-weight:400;color:#9ca3af}
.fn-file{font-size:12px;color:#94a3b8;font-family:monospace;margin-top:5px}
.fn-badges{display:flex;flex-wrap:wrap;gap:6px;margin-top:10px}
.fn-badge{font-size:10px;font-weight:600;padding:2px 8px;border-radius:12px;border:1px solid;letter-spacing:.03em}
.fn-badge-doc{background:#f0fdf4;border-color:#bbf7d0;color:#15803d}
.fn-badge-dp{background:#f5f3ff;border-color:#ddd6fe;color:#7c3aed}
.fn-badge-tests{background:#fff7ed;border-color:#fed7aa;color:#c2410c}
.fn-toggle-btn{flex-shrink:0;padding:6px 8px;border-radius:6px;color:#9ca3af;font-size:13px;transition:all .15s;margin-top:2px;background:transparent;border:none;cursor:pointer}
.fn-card:hover .fn-toggle-btn{color:#6b7280}
.fn-card.open .fn-toggle-btn{color:#6d28d9;transform:rotate(180deg)}

/* summary (always visible) */
.fn-summary{padding:14px 26px 18px;font-size:14.5px;line-height:1.8;color:#374151;max-width:760px}
.fn-se{margin:0 26px 14px;border-left:3px solid #f59e0b;background:#fffbeb;padding:10px 14px;border-radius:0 6px 6px 0;font-size:13.5px;line-height:1.65;color:#374151}
.fn-se-label{font-size:9px;font-weight:700;text-transform:uppercase;letter-spacing:.1em;color:#92400e;margin-bottom:4px}
.fn-note{margin:0 26px 14px;border-left:3px solid #6366f1;background:#eef2ff;padding:10px 14px;border-radius:0 6px 6px 0;font-size:13.5px;line-height:1.65;color:#374151}
.fn-note-label{font-size:9px;font-weight:700;text-transform:uppercase;letter-spacing:.1em;color:#4338ca;margin-bottom:4px}

/* expandable section (decision logic) */
.fn-expand{display:none;border-top:1px solid #f3f4f6}
.fn-card.open .fn-expand{display:block}
.fn-expand-inner{padding:18px 26px 22px}
.fn-expand-label{font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:.09em;color:#d1d5db;margin-bottom:12px}

/* bottom padding strip */
.fn-bottom{height:22px}

/* ---- Decision rows ---- */
.dp-table{width:100%;border-collapse:collapse;font-size:13.5px}
.dp-table tr{border-bottom:1px solid #f3f4f6}
.dp-table tr:last-child{border-bottom:none}
.dp-table td{padding:8px 6px;vertical-align:top}
.dp-table td:first-child{padding-left:0;width:60px}
.dp-table td:last-child{padding-right:0}
.dp-type{font-size:9.5px;font-weight:700;letter-spacing:.05em;padding:3px 7px;border-radius:4px;white-space:nowrap;text-transform:uppercase;display:inline-block}
.t-if{background:#ede9fe;color:#6d28d9}
.t-elif{background:#e0e7ff;color:#4338ca}
.t-else{background:#f3f4f6;color:#6b7280}
.t-try{background:#dbeafe;color:#1d4ed8}
.t-except{background:#fee2e2;color:#b91c1c}
.t-finally{background:#f0fdf4;color:#15803d}
.dp-cond{font-family:monospace;font-size:12px;color:#1e293b;word-break:break-all;padding-right:8px}
.dp-sep{color:#e5e7eb;font-size:11px;white-space:nowrap;padding:0 4px}
.dp-out{font-size:12.5px;color:#64748b;font-style:italic;word-break:break-word}

/* connector arrow between steps */
.fn-connector{position:relative;height:44px;display:flex;flex-direction:column;align-items:center;padding-left:0;z-index:1}
.fn-connector::before{content:'\u2193';font-size:18px;color:#d1d5db;position:absolute;left:-36px;top:50%;transform:translateY(-50%)}

/* ==================================================
   FORK NODE
   ================================================== */
.fn-fork{position:relative;margin-bottom:10px}
.fn-fork-rail{position:absolute;left:-52px;top:18px;width:32px;height:32px;border-radius:50%;display:flex;align-items:center;justify-content:center;font-size:16px;background:#fff7ed;border:2px solid #fed7aa;color:#c2410c;z-index:2}

.fn-fork-card{background:#fff;border:2px solid #e5e7eb;border-radius:14px;overflow:hidden}
.fn-fork-header{display:flex;align-items:center;gap:12px;padding:18px 24px 16px;background:linear-gradient(to right,#fff7ed,#fffbf5);border-bottom:1px solid #fde68a}
.fn-fork-title{font-size:15px;font-weight:700;color:#92400e}
.fn-fork-sub{font-size:13px;color:#a16207;margin-top:2px}
.fn-fork-icon{width:36px;height:36px;border-radius:8px;background:#fef3c7;display:flex;align-items:center;justify-content:center;font-size:18px;flex-shrink:0}

/* branches container */
.fn-fork-branches{display:grid;grid-template-columns:repeat(auto-fill,minmax(280px,1fr));gap:0;border-top:none}
/* each branch */
.fn-fork-branch{border-right:1px solid #f3f4f6;padding:0;position:relative;transition:background .15s}
.fn-fork-branch:last-child{border-right:none}
.fn-fork-branch:hover{background:#fafafa}
.fn-fork-branch.open{background:#fafafa}
.fn-fork-branch.open::before{content:'';position:absolute;top:0;left:0;right:0;height:3px;background:linear-gradient(to right,#818cf8,#a78bfa)}
/* branch inner */
.fbb-inner{padding:20px 22px}
.fbb-name{font-family:monospace;font-size:15px;font-weight:700;color:#0f172a;line-height:1.3}
.fbb-name-paren{font-weight:400;color:#9ca3af}
.fbb-file{font-size:11px;color:#94a3b8;font-family:monospace;margin-top:4px}
.fbb-summary{font-size:13.5px;line-height:1.75;color:#374151;margin-top:12px;padding-top:12px;border-top:1px solid #f3f4f6}
.fbb-toggle{display:inline-flex;align-items:center;gap:5px;margin-top:14px;font-size:11.5px;color:#9ca3af;cursor:pointer;padding:4px 0;user-select:none;transition:color .15s;border:none;background:none}
.fbb-toggle:hover{color:#6b7280}
.fn-fork-branch.open .fbb-toggle{color:#6d28d9}
.fbb-expand{display:none;padding:0 22px 20px;border-top:1px solid #f3f4f6;margin-top:14px}
.fn-fork-branch.open .fbb-expand{display:block}
.fbb-expand-label{font-size:9.5px;font-weight:700;text-transform:uppercase;letter-spacing:.09em;color:#d1d5db;margin-bottom:10px}

/* ==================================================
   DECISION TREE (standalone for function pages)
   ================================================== */
.dt{border:1.5px solid #e5e7eb;border-radius:10px;overflow:hidden}
.dt-row{display:grid;grid-template-columns:72px 1fr 18px 1fr;gap:10px;align-items:baseline;padding:11px 16px;border-bottom:1px solid #f9fafb;font-size:13.5px}
.dt-row:last-child{border-bottom:none}
.dt-row:nth-child(odd){background:#fff}
.dt-row:nth-child(even){background:#fafafa}
.dt-tag{font-size:9.5px;font-weight:700;letter-spacing:.05em;padding:3px 7px;border-radius:4px;white-space:nowrap;text-transform:uppercase;display:inline-block}
.dt-cond{font-family:monospace;font-size:12.5px;color:#1f2937;word-break:break-all}
.dt-sep{color:#d1d5db;text-align:center}
.dt-out{font-size:12.5px;color:#64748b;font-style:italic;word-break:break-word}

/* ==================================================
   DECOUPLED FLOWS
   ================================================== */
.decoupled-list{border:2px solid #e5e7eb;border-radius:10px;overflow:hidden}
.decoupled-item{display:flex;align-items:baseline;flex-wrap:wrap;gap:10px;padding:14px 18px;border-bottom:1px solid #f9fafb;font-size:14px}
.decoupled-item:last-child{border-bottom:none}
.decoupled-item:nth-child(odd){background:#fff}
.decoupled-item:nth-child(even){background:#fafafa}
.dl-dec{font-family:monospace;font-size:12px;background:#f5f3ff;padding:3px 8px;border-radius:4px;color:#7c3aed;border:1px solid #ede9fe;white-space:nowrap}
.dl-arrow{color:#d1d5db;flex-shrink:0}
.dl-fn{font-family:monospace;font-size:13px;font-weight:600;color:#111827}
.dl-file{font-size:11px;color:#9ca3af;font-family:monospace;margin-left:auto;white-space:nowrap;padding-left:14px}

/* ==================================================
   TEST REFS
   ================================================== */
.test-list{border:2px solid #e5e7eb;border-radius:10px;overflow:hidden}
.test-item{padding:14px 18px;border-bottom:1px solid #f9fafb}
.test-item:last-child{border-bottom:none}
.test-item:nth-child(odd){background:#fff}
.test-item:nth-child(even){background:#fafafa}
.test-file{font-size:13px;font-family:monospace;color:#374151;font-weight:500;margin-bottom:8px}
.test-names{display:flex;flex-wrap:wrap;gap:6px}
.test-names code{font-family:monospace;font-size:12px;background:#f0fdf4;border:1.5px solid #bbf7d0;padding:3px 10px;border-radius:5px;color:#15803d}

/* ==================================================
   WELCOME / EMPTY STATES
   ================================================== */
.welcome-hero{text-align:center;padding:80px 24px 60px}
.welcome-hero h2{font-size:1.6rem;font-weight:800;color:#1e293b;margin-bottom:12px;letter-spacing:-.02em}
.welcome-hero p{font-size:15px;color:#94a3b8;line-height:1.8;max-width:500px;margin:0 auto}
.welcome-hero code{background:#f3f4f6;padding:2px 8px;border-radius:4px;font-size:13.5px}
.stat-row{display:flex;gap:20px;justify-content:center;margin-top:36px;flex-wrap:wrap}
.stat-box{background:#fff;border:2px solid #e5e7eb;border-radius:12px;padding:20px 32px;text-align:center}
.stat-num{font-size:2rem;font-weight:800;color:#4f46e5;letter-spacing:-.03em}
.stat-label{font-size:11px;color:#9ca3af;text-transform:uppercase;letter-spacing:.08em;margin-top:4px}
.empty-chain{background:#fff;border:2px dashed #e5e7eb;border-radius:14px;padding:32px 28px;color:#9ca3af;font-size:14px;line-height:1.75}
.empty-chain strong{color:#6b7280;display:block;margin-bottom:6px;font-size:15px}

.doc-meta{font-size:11.5px;color:#e2e8f0;margin-top:36px}
  </style>
</head>
<body>
  <header id="hdr">
    <a class="brand" href="#">
      <div class="brand-mark">C</div>
      <span class="brand-name">__CC_PROJECT__<span class="brand-sep">/</span><span class="brand-sub">docs</span></span>
    </a>
    <div class="search-wrap">
      <svg class="search-icon" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.8"><circle cx="7" cy="7" r="5"/><path d="M11 11l3 3"/></svg>
      <input type="search" id="search" placeholder="Search entry points and functions\u2026" autocomplete="off" spellcheck="false">
    </div>
    <div class="hdr-right"><span id="hdr-stats"></span></div>
  </header>
  <div id="layout">
    <nav id="sidebar"></nav>
    <main id="content"><div id="content-inner"></div></main>
  </div>
  <script>
const DATA=__CC_DATA__;
const ci=document.getElementById('content-inner');
const sb=document.getElementById('sidebar');

// ---- Utilities --------------------------------------------------------------
function esc(s){
  return String(s==null?'':s)
    .replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}
function seText(se){
  if(!se)return null;
  if(Array.isArray(se)){var t=se.filter(Boolean).join(' \u00b7 ');return t||null;}
  var t=String(se).trim();
  return(t&&t.toLowerCase()!=='null')?t:null;
}

// ---- Documentation lookup ---------------------------------------------------
// This is the core framework: given a step's file+name, retrieve any cached docs.
function getDoc(file,name){
  var fd=DATA.summary[file];
  if(!fd)return null;
  return fd[name]||null;
}

// ---- Header stats -----------------------------------------------------------
(function(){
  var totalEps=Object.values(DATA.flows).reduce(function(s,a){return s+a.length;},0);
  var el=document.getElementById('hdr-stats');
  if(el)el.textContent=totalEps+' endpoints \u00b7 '+DATA.total_functions+' functions';
})();

// ---- Sidebar ----------------------------------------------------------------
function navMethod(url){
  if(!url)return '';
  var m=url.split(' ')[0].toLowerCase();
  var cls={get:'nav-get',post:'nav-post',put:'nav-put',patch:'nav-patch',delete:'nav-delete'}[m]||'nav-any';
  return '<span class="nav-method '+cls+'">'+esc(m.toUpperCase())+'</span>';
}

function buildSidebar(){
  var files=Object.keys(DATA.summary).sort();
  var kinds=['http','task','signal','command'];
  var kindLabels={http:'HTTP Routes',task:'Celery Tasks',signal:'Signal Receivers',command:'Management Commands'};
  var kindDots={http:'dot-http',task:'dot-task',signal:'dot-signal',command:'dot-command'};
  var totalEps=kinds.reduce(function(s,k){return s+(DATA.flows[k]?DATA.flows[k].length:0);},0);
  var html='';

  // === Entry points FIRST ===
  html+='<div class="sec">';
  html+='<div class="sec-hdr"><span class="chev open">&#9658;</span>Entry Points<span class="nav-badge">'+totalEps+'</span></div>';
  html+='<div class="sec-body open">';
  for(var ki=0;ki<kinds.length;ki++){
    var kind=kinds[ki];
    var eps=DATA.flows[kind]||[];
    if(!eps.length)continue;
    html+='<div class="grp">';
    html+='<div class="grp-hdr"><span class="kind-dot '+kindDots[kind]+'"></span>'+kindLabels[kind]+'<span class="nav-badge">'+eps.length+'</span></div>';
    html+='<div class="grp-body open">';
    for(var ei=0;ei<eps.length;ei++){
      var ep=eps[ei];
      var h='flow::'+kind+'::'+ep.label;
      html+='<a class="nav-item" href="#'+esc(h)+'" data-h="'+esc(h)+'">';
      if(ep.url)html+=navMethod(ep.url);
      html+='<span class="nav-label">'+esc(ep.label)+'</span>';
      html+='</a>';
    }
    html+='</div></div>';
  }
  html+='</div></div>';

  // === Functions second ===
  html+='<div class="sec">';
  html+='<div class="sec-hdr"><span class="chev">&#9658;</span>Functions<span class="nav-badge">'+DATA.total_functions+'</span></div>';
  html+='<div class="sec-body">';
  for(var fi=0;fi<files.length;fi++){
    var file=files[fi];
    var funcs=DATA.summary[file];
    var names=Object.keys(funcs).sort();
    var short=file.split('/').pop();
    html+='<div class="grp"><div class="grp-hdr"><span class="chev">&#9658;</span>'+esc(short)+'<span class="nav-badge">'+names.length+'</span></div>';
    html+='<div class="grp-body">';
    for(var ni=0;ni<names.length;ni++){
      var fn=names[ni];
      var fh='func::'+file+'::'+fn;
      html+='<a class="nav-item" href="#'+esc(fh)+'" data-h="'+esc(fh)+'"><span class="nav-label">'+esc(fn)+'</span></a>';
    }
    html+='</div></div>';
  }
  html+='</div></div>';

  sb.innerHTML=html;
  sb.querySelectorAll('.sec-hdr,.grp-hdr').forEach(function(hdr){
    hdr.addEventListener('click',function(){
      var body=hdr.nextElementSibling;
      var open=body.classList.toggle('open');
      var chev=hdr.querySelector('.chev');
      if(chev)chev.classList.toggle('open',open);
    });
  });
}

// ---- Routing ----------------------------------------------------------------
function route(){
  var hash=window.location.hash.slice(1);
  if(!hash){renderWelcome();return;}
  var i1=hash.indexOf('::');
  if(i1===-1){renderWelcome();return;}
  var section=hash.slice(0,i1),rest=hash.slice(i1+2);
  if(section==='func'){
    var i2=rest.lastIndexOf('::');
    if(i2===-1)return;
    renderFunction(rest.slice(0,i2),rest.slice(i2+2));
  }else if(section==='flow'){
    var i2=rest.indexOf('::');
    if(i2===-1)return;
    renderEndpoint(rest.slice(0,i2),rest.slice(i2+2));
  }
  setActive(hash);
  openParents(hash);
}
function setActive(hash){
  sb.querySelectorAll('.nav-item').forEach(function(el){el.classList.toggle('active',el.dataset.h===hash);});
}
function openParents(hash){
  var el=null;
  sb.querySelectorAll('.nav-item').forEach(function(item){if(item.dataset.h===hash)el=item;});
  if(!el)return;
  var node=el.parentElement;
  while(node&&node!==sb){
    if(node.classList.contains('grp-body')||node.classList.contains('sec-body')){
      node.classList.add('open');
      var hdr=node.previousElementSibling;
      if(hdr){var c=hdr.querySelector('.chev');if(c)c.classList.add('open');}
    }
    node=node.parentElement;
  }
  el.scrollIntoView({block:'nearest'});
}

// ---- Decision rows (shared) ------------------------------------------------
function dpTable(points){
  if(!points||!points.length)return '';
  var h='<table class="dp-table">';
  for(var i=0;i<points.length;i++){
    var p=points[i];
    h+='<tr><td><span class="dp-type t-'+esc(p.type)+'">'+esc(p.type)+'</span></td>';
    h+='<td class="dp-cond"><code>'+esc(p.condition||'')+'</code></td>';
    h+='<td class="dp-sep">\u2192</td>';
    h+='<td class="dp-out">'+esc(p.out||p.outcome||'')+'</td></tr>';
  }
  h+='</table>';
  return h;
}

// ---- Flow: step node -------------------------------------------------------
var _nc=0;
function stepCol(file,entryFile,idx){
  if(idx===0||file===entryFile)return 'c-entry';
  return 'c-svc';
}

function renderStepNode(step,idx,entryFile){
  var id='fn-'+(_nc++);
  var doc=getDoc(step.file,step.name);
  var summary=(doc&&doc.summary)?doc.summary:'';
  var se=(doc&&doc.side_effects)?seText(doc.side_effects):null;
  var note=(doc&&doc.note&&String(doc.note).toLowerCase()!=='null')?doc.note:null;
  var dps=step.decision_points||[];
  var tests=(doc&&doc.test_refs&&doc.test_refs.length)?doc.test_refs:[];
  var hasDocs=!!(summary||se||note);
  var hasExpand=dps.length>0;
  var col=stepCol(step.file,entryFile,idx);

  // badges
  var badges='';
  if(hasDocs)badges+='<span class="fn-badge fn-badge-doc">documented</span>';
  if(dps.length)badges+='<span class="fn-badge fn-badge-dp">'+dps.length+' branch'+(dps.length!==1?'es':'')+'</span>';
  if(tests.length)badges+='<span class="fn-badge fn-badge-tests">'+tests.length+' test'+(tests.length!==1?'s':'')+'</span>';

  var h='<div class="fn-step">';
  h+='<div class="fn-num '+col+'">'+(idx+1)+'</div>';
  h+='<div class="fn-card'+(hasExpand?' has-toggle':'')+(hasExpand?' open':'')+'" id="'+id+'"';
  if(hasExpand)h+=' onclick="toggleCard(event,this)"';
  h+='>';

  // header
  h+='<div class="fn-hdr">';
  h+='<div class="fn-info">';
  h+='<div class="fn-name">'+esc(step.name)+'<span class="fn-name-paren">()</span></div>';
  h+='<div class="fn-file">'+esc(step.file)+'</div>';
  if(badges)h+='<div class="fn-badges">'+badges+'</div>';
  h+='</div>';
  if(hasExpand)h+='<button class="fn-toggle-btn" title="Toggle decision logic">&#9660;</button>';
  h+='</div>';

  // summary (always shown if available)
  if(summary)h+='<div class="fn-summary">'+esc(summary)+'</div>';
  if(se)h+='<div class="fn-se"><div class="fn-se-label">Side effects</div>'+esc(se)+'</div>';
  if(note)h+='<div class="fn-note"><div class="fn-note-label">Note</div>'+esc(note)+'</div>';

  // expandable: decision logic
  if(hasExpand){
    h+='<div class="fn-expand"><div class="fn-expand-inner">';
    h+='<div class="fn-expand-label">Decision logic</div>';
    h+=dpTable(dps);
    h+='</div></div>';
  }

  h+='<div class="fn-bottom"></div>';
  h+='</div></div>';
  return h;
}

// ---- Flow: fork node -------------------------------------------------------
function renderForkNode(step){
  var alts=step.alternatives||[];
  var h='<div class="fn-fork">';
  h+='<div class="fn-fork-rail">\u21C6</div>';
  h+='<div class="fn-fork-card">';
  h+='<div class="fn-fork-header">';
  h+='<div class="fn-fork-icon">\u2387</div>';
  h+='<div>';
  h+='<div class="fn-fork-title">Dispatches to one of '+alts.length+' implementations</div>';
  h+='<div class="fn-fork-sub">Gateway / strategy pattern \u2014 runtime selection based on input</div>';
  h+='</div></div>';
  h+='<div class="fn-fork-branches">';
  for(var i=0;i<alts.length;i++){
    var alt=alts[i];
    var bid='fb-'+(_nc++);
    var doc=getDoc(alt.file,alt.name);
    var summary=(doc&&doc.summary)?doc.summary:'';
    var se=(doc&&doc.side_effects)?seText(doc.side_effects):null;
    var dps=alt.decision_points||[];
    var hasExpand=dps.length>0||(doc&&doc.side_effects);

    h+='<div class="fn-fork-branch open" id="'+bid+'">';
    h+='<div class="fbb-inner">';
    h+='<div class="fbb-name">'+esc(alt.name)+'<span class="fbb-name-paren">()</span></div>';
    h+='<div class="fbb-file">'+esc(alt.file)+'</div>';
    if(summary)h+='<div class="fbb-summary">'+esc(summary)+'</div>';
    if(hasExpand){
      h+='<button class="fbb-toggle" onclick="toggleBranch(event,this.parentElement.parentElement)">';
      h+='\u25be '+(dps.length?dps.length+' branch'+(dps.length!==1?'es':''):'details');
      h+='</button>';
    }
    h+='</div>';
    if(hasExpand){
      h+='<div class="fbb-expand">';
      if(se)h+='<div class="fn-se" style="margin:0 0 12px"><div class="fn-se-label">Side effects</div>'+esc(se)+'</div>';
      if(dps.length){
        h+='<div class="fbb-expand-label">Decision logic</div>';
        h+=dpTable(dps);
      }
      h+='</div>';
    }
    h+='</div>';
  }
  h+='</div></div></div>';
  return h;
}

// ---- Render full flow chain ------------------------------------------------
function renderFlowChain(steps,entryFile){
  if(!steps||!steps.length)return '';
  _nc=0;
  var h='<div class="flow-timeline">';
  var stepIdx=0;
  for(var i=0;i<steps.length;i++){
    if(i>0)h+='<div class="fn-connector"></div>';
    var step=steps[i];
    if(step.fork){
      h+=renderForkNode(step);
    }else{
      h+=renderStepNode(step,stepIdx,entryFile);
      stepIdx++;
    }
  }
  h+='</div>';
  return h;
}

// ---- Toggle interactions ---------------------------------------------------
function toggleCard(e,card){
  e.stopPropagation();
  card.classList.toggle('open');
}
function toggleBranch(e,branch){
  e.stopPropagation();
  branch.classList.toggle('open');
}
function expandAll(){
  document.querySelectorAll('.fn-card.has-toggle').forEach(function(c){c.classList.add('open');});
  document.querySelectorAll('.fn-fork-branch').forEach(function(b){b.classList.add('open');});
}
function collapseAll(){
  document.querySelectorAll('.fn-card.has-toggle').forEach(function(c){c.classList.remove('open');});
  document.querySelectorAll('.fn-fork-branch').forEach(function(b){b.classList.remove('open');});
}

// ---- Standalone decision tree (for function pages) -------------------------
function renderDecisionTree(points){
  if(!points||!points.length)return '';
  var h='<div class="dt">';
  for(var i=0;i<points.length;i++){
    var p=points[i];
    h+='<div class="dt-row">';
    h+='<span class="dt-tag t-'+esc(p.type)+'">'+esc(p.type)+'</span>';
    h+='<code class="dt-cond">'+esc(p.condition||'')+'</code>';
    h+='<span class="dt-sep">\u2192</span>';
    h+='<span class="dt-out">'+esc(p.out||p.outcome||'')+'</span>';
    h+='</div>';
  }
  h+='</div>';
  return h;
}

// ---- Test refs -------------------------------------------------------------
function renderTestRefs(refs){
  if(!refs||!refs.length)return '';
  var h='<div class="test-list">';
  for(var i=0;i<refs.length;i++){
    var ref=refs[i];
    h+='<div class="test-item"><div class="test-file">'+esc(ref.file)+'</div><div class="test-names">';
    for(var j=0;j<ref.tests.length;j++)h+='<code>'+esc(ref.tests[j])+'</code>';
    h+='</div></div>';
  }
  h+='</div>';
  return h;
}

// ---- Method badge ----------------------------------------------------------
function methodBadge(url){
  if(!url)return '';
  var parts=url.split(' ');
  var path=parts[parts.length-1];
  var methods=parts.slice(0,parts.length-1).join(' ').split(' / ');
  var badges='';
  for(var i=0;i<methods.length;i++){
    var m=methods[i].trim();
    badges+='<span class="ep-method method-'+esc(m.toLowerCase())+'">'+esc(m)+'</span>';
  }
  return '<div class="ep-meta">'+badges+'<span class="ep-url">'+esc(path)+'</span></div>';
}

// ---- Renderers -------------------------------------------------------------
function renderWelcome(){
  var totalEps=Object.values(DATA.flows).reduce(function(s,a){return s+a.length;},0);
  if(DATA.total_functions===0&&totalEps===0){
    ci.innerHTML='<div class="welcome-hero"><h2>No documentation found</h2>'
      +'<p>Run <code>codecoverage document --enrich &lt;path&gt;</code> to generate docs, '
      +'or ensure you are running <code>codecoverage serve</code> from the project root.</p></div>';
    return;
  }
  var fileCount=Object.keys(DATA.summary).length;
  var h='<div class="welcome-hero"><h2>Select an entry point from the sidebar</h2>'
    +'<p>Navigate using the sidebar or search above. Entry points show the full call flow with inline documentation.</p>';
  h+='<div class="stat-row">';
  if(totalEps)h+='<div class="stat-box"><div class="stat-num">'+totalEps+'</div><div class="stat-label">Entry points</div></div>';
  if(DATA.total_functions)h+='<div class="stat-box"><div class="stat-num">'+DATA.total_functions+'</div><div class="stat-label">Functions documented</div></div>';
  if(fileCount)h+='<div class="stat-box"><div class="stat-num">'+fileCount+'</div><div class="stat-label">Files</div></div>';
  h+='</div></div>';
  ci.innerHTML=h;
}

function renderFunction(file,fn){
  var entry=DATA.summary[file]&&DATA.summary[file][fn];
  if(!entry){ci.innerHTML='<p style="color:#9ca3af;padding:40px">Not found.</p>';return;}
  var parts=file.split('/');
  var bc=parts.map(function(p,i){
    return '<span'+(i===parts.length-1?' class="bc-cur"':'')+'>'+esc(p)+'</span>';
  }).join(' <span class="sep">\u203a</span> ');

  var h='<div class="breadcrumb">'+bc+'</div>';
  h+='<h1 class="doc-title">'+esc(fn)+'</h1>';
  h+='<code class="ep-file">'+esc(file)+'</code>';
  h+='<hr class="divider">';
  if(entry.summary)h+='<p class="summary">'+esc(entry.summary)+'</p>';
  var se=seText(entry.side_effects);
  if(se)h+='<div class="callout callout-effects"><div class="callout-label">Side effects</div>'+esc(se)+'</div>';
  var note=entry.note&&String(entry.note).toLowerCase()!=='null'?entry.note:null;
  if(note)h+='<div class="callout callout-note"><div class="callout-label">Note</div>'+esc(note)+'</div>';
  if(entry.decision_points&&entry.decision_points.length){
    h+='<h2 class="sec-title">Decision logic</h2>';
    h+=renderDecisionTree(entry.decision_points);
  }
  if(entry.test_refs&&entry.test_refs.length){
    h+='<h2 class="sec-title">Tests</h2>';
    h+=renderTestRefs(entry.test_refs);
  }
  if(entry.updated_at)h+='<p class="doc-meta">Updated '+esc(entry.updated_at.slice(0,10))+'</p>';
  ci.innerHTML=h;
  document.getElementById('content').scrollTop=0;
}

function renderEndpoint(kind,label){
  var eps=DATA.flows[kind]||[];
  var ep=eps.find(function(e){return e.label===label;});
  if(!ep){ci.innerHTML='<p style="color:#9ca3af;padding:40px">Not found.</p>';return;}

  var h='<h1 class="doc-title">'+esc(ep.label)+'</h1>';
  if(ep.url)h+=methodBadge(ep.url);
  h+='<code class="ep-file">'+esc(ep.file)+'</code>';
  h+='<hr class="divider">';

  // Summary: prefer doc cache summary, fall back to class description
  var mainSummary=ep.summary||'';
  var fallbackDesc=ep.description||'';
  if(mainSummary)h+='<p class="summary">'+esc(mainSummary)+'</p>';
  else if(fallbackDesc)h+='<p class="description">'+esc(fallbackDesc)+'</p>';

  // Call flow
  if(ep.call_chain&&ep.call_chain.length){
    var isTraced=ep.chain_source==='traced';
    var chainSteps=ep.call_chain.length;
    var h2='<h2 class="sec-title">Call flow</h2>';
    h2+='<div class="flow-top">';
    h2+='<span class="source-badge '+(isTraced?'badge-traced':'badge-static')+'">'+(isTraced?'Live traced':'Statically inferred')+'</span>';
    h2+='<div class="flow-actions">';
    h2+='<span class="flow-btn" onclick="expandAll()">Expand all</span>';
    h2+='<span class="flow-btn" onclick="collapseAll()">Collapse all</span>';
    h2+='</div></div>';
    h+=h2;
    h+=renderFlowChain(ep.call_chain,ep.file);
  }else{
    // No call chain detected — show helpful context
    h+='<h2 class="sec-title">Call flow</h2>';
    h+='<div class="empty-chain">';
    h+='<strong>No call chain detected</strong>';
    h+='This view class does not define HTTP handler methods directly. ';
    h+='It likely inherits them from its mixin base classes (e.g. <code>CreateAPIMixin</code>, <code>generics.CreateAPIView</code>). ';
    h+='The actual request handling is provided by Django REST Framework internals.';
    if(fallbackDesc&&!mainSummary)h+='<br><br><em>Class note: '+esc(fallbackDesc)+'</em>';
    h+='</div>';
  }

  // Decoupled flows
  if(ep.decoupled_flows&&ep.decoupled_flows.length){
    h+='<h2 class="sec-title">Decoupled flows</h2>';
    h+='<div class="decoupled-list">';
    for(var i=0;i<ep.decoupled_flows.length;i++){
      var df=ep.decoupled_flows[i];
      h+='<div class="decoupled-item">';
      h+='<code class="dl-dec">'+esc(df.decorator_repr)+'</code>';
      h+='<span class="dl-arrow">\u2192</span>';
      h+='<span class="dl-fn">'+esc(df.function_name)+'</span>';
      h+='<span class="dl-file">'+esc(df.file)+'</span>';
      h+='</div>';
    }
    h+='</div>';
  }

  // Tests
  if(ep.test_refs&&ep.test_refs.length){
    h+='<h2 class="sec-title">Tests</h2>';
    h+=renderTestRefs(ep.test_refs);
  }

  ci.innerHTML=h;
  document.getElementById('content').scrollTop=0;
}

// ---- Search ----------------------------------------------------------------
document.getElementById('search').addEventListener('input',function(){
  var q=this.value.trim().toLowerCase();
  if(!q){
    sb.querySelectorAll('.nav-item,.grp').forEach(function(el){el.style.display='';});
    return;
  }
  sb.querySelectorAll('.nav-item').forEach(function(el){
    el.style.display=el.textContent.toLowerCase().indexOf(q)!==-1?'':'none';
  });
  sb.querySelectorAll('.grp').forEach(function(grp){
    var has=Array.from(grp.querySelectorAll('.nav-item')).some(function(el){return el.style.display!=='none';});
    grp.style.display=has?'':'none';
    if(has){
      var body=grp.querySelector('.grp-body');
      var chev=grp.querySelector('.chev');
      if(body)body.classList.add('open');
      if(chev)chev.classList.add('open');
    }
  });
});

// ---- Init ------------------------------------------------------------------
buildSidebar();
route();
window.addEventListener('hashchange',route);
  </script>
</body>
</html>
"""
