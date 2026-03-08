"""
document command — write codebase documentation to markdown files.
"""

import time
import click
from pathlib import Path
from typing import List, Optional, Tuple
from rich.console import Console
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, MofNCompleteColumn

from codecoverage.core.config import load_config
from codecoverage.core.doc_cache import DocCache
from codecoverage.core.markdown_renderer import render_flows_markdown, render_summary_markdown
from codecoverage.core.parser import CodebaseParser
from codecoverage.web.flow_tracer import FlowTracer

# Method names too generic to document meaningfully without full class context
# resolved by the agent (post/get are handled with class_context, but pure
# dunder noise like __repr__ etc is skipped)
_SKIP_NAMES = {"__repr__", "__eq__", "__hash__", "__len__", "__iter__", "__next__"}

console = Console()


@click.command()
@click.option(
    "--path",
    type=click.Path(exists=True),
    default=".",
    help="Path to project root (default: current directory)",
)
@click.option(
    "--output",
    type=click.Path(),
    default=None,
    help="Output directory (default: .codecoverage/docs/)",
)
@click.option(
    "--config",
    type=click.Path(exists=True),
    default=None,
    help="Path to config file (default: .codecoverage.toml)",
)
@click.option(
    "--enrich",
    "enrich_path",
    type=click.Path(),
    default=None,
    metavar="DIR",
    help=(
        "Run LLM doc generation for all functions under DIR before rendering. "
        "Skips functions already in the cache. DIR is relative to --path."
    ),
)
# ---------------------------------------------------------------------------
# Git-diff modes (mutually exclusive with --enrich)
# ---------------------------------------------------------------------------
@click.option(
    "--working",
    "diff_mode",
    flag_value="working",
    default=False,
    help="Update docs for uncommitted changes (staged + unstaged) vs HEAD.",
)
@click.option(
    "--last-commit",
    "diff_mode",
    flag_value="last-commit",
    help="Update docs for functions changed in the most recent commit.",
)
@click.option(
    "--last-merge",
    "diff_mode",
    flag_value="last-merge",
    help="Update docs for functions changed in the most recent merge commit.",
)
@click.option(
    "--since",
    "since_ref",
    default=None,
    metavar="REF",
    help="Update docs for functions changed between HEAD and a git ref (branch/tag/SHA).",
)
@click.option(
    "--dry-run",
    is_flag=True,
    default=False,
    help="Show which functions would be re-documented without calling the LLM.",
)
@click.option(
    "--provider",
    type=click.Choice(["anthropic", "openai", "cursor"], case_sensitive=False),
    default=None,
    help="LLM provider for --enrich / diff modes (default: anthropic). Overrides config file.",
)
@click.option(
    "--model",
    default=None,
    help="Model name for enrichment. Defaults to provider default.",
)
def document(path: str, output: str, config: str, enrich_path: Optional[str],
             diff_mode: Optional[str], since_ref: Optional[str], dry_run: bool,
             provider: str, model: str) -> None:
    """
    Write codebase documentation to markdown files.

    Generates two files in the output directory:

    \b
      FLOWS.md   — all entry points (HTTP endpoints, background tasks,
                   signal handlers, management commands) with their full
                   call chains and decoupled flows. LLM summaries are
                   shown as blockquotes where available.

      SUMMARY.md — all cached function docs grouped by source file.
                   Grows incrementally as you run generate / diff-test.

    Use --enrich DIR to document all functions under a directory.
    Use diff flags to document only what changed in git (mirrors diff-test):

    \b
      --working      Update docs for uncommitted changes vs HEAD  [default]
      --last-commit  Update docs for functions changed in the last commit
      --last-merge   Update docs for the last merge commit
      --since REF    Update docs for everything changed since a branch/tag/SHA

    \b
    Examples:
        codecoverage document
        codecoverage document --output docs/
        codecoverage document --enrich payments/interface_layer/payment_gateway
        codecoverage document --last-commit
        codecoverage document --since main --provider cursor
        codecoverage document --working --dry-run
    """
    project_root = Path(path).resolve()
    cfg = load_config(project_root, config_path=config)
    out_dir = Path(output).resolve() if output else project_root / ".codecoverage" / "docs"

    console.print()
    console.print(
        Panel(
            f"[bold]Project:[/bold] {project_root}\n"
            f"[bold]Output:[/bold]  {out_dir}",
            title="[cyan]codecoverage document[/cyan]",
            border_style="cyan",
        )
    )
    console.print()

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
        transient=True,
    ) as progress:
        task = progress.add_task("Parsing codebase...", total=None)
        parser = CodebaseParser(
            root=project_root,
            ignore_patterns=cfg.parsing.ignore_patterns,
        )
        codebase = parser.parse()

        progress.update(task, description="Tracing entry points & call chains...")
        tracer = FlowTracer(codebase, project_root)
        entry_points = tracer.detect_all_entry_points()

        progress.update(task, description="Loading doc cache...")
        doc_cache = DocCache(project_root).load()

        progress.update(task, description="Finding test coverage...")
        from codecoverage.analysis.test_refs import find_test_refs
        test_refs_map = _build_test_refs_map(doc_cache, project_root)

        progress.update(task, description="Rendering markdown...")
        flows_md = render_flows_markdown(entry_points, project_root.name, doc_cache)
        summary_md = render_summary_markdown(doc_cache, project_root.name, test_refs_map=test_refs_map)

    console.print(
        f"[green]✓[/green] Parsed "
        f"[bold]{codebase.total_files}[/bold] files · "
        f"[bold]{codebase.total_functions}[/bold] functions · "
        f"[bold]{codebase.total_classes}[/bold] classes"
    )
    console.print(
        f"[green]✓[/green] Detected [bold]{len(entry_points)}[/bold] entry points · "
        f"[bold]{len(doc_cache)}[/bold] functions with cached docs"
    )

    # ------------------------------------------------------------------
    # Git-diff enrichment pass (--working / --last-commit / --last-merge / --since)
    # ------------------------------------------------------------------
    if diff_mode or since_ref:
        from codecoverage.git.diff import DiffAnalyzer
        try:
            analyzer = DiffAnalyzer(project_root)
            if since_ref:
                file_diffs = analyzer.get_ref_diff(since_ref, "HEAD")
                scope_label = f"HEAD vs {since_ref}"
            elif diff_mode == "last-commit":
                file_diffs = analyzer.get_last_commit_diff()
                scope_label = "last commit (HEAD~1 → HEAD)"
            elif diff_mode == "last-merge":
                file_diffs = analyzer.get_last_merge_diff()
                scope_label = "last merge commit"
            else:
                file_diffs = analyzer.get_working_diff()
                scope_label = "uncommitted changes vs HEAD"
        except ValueError as e:
            console.print(f"[bold red]✗ Git error:[/bold red] {e}")
            return

        console.print(f"  Scope: [dim]{scope_label}[/dim]")
        console.print()

        # Collect (rel_file, func_name, change_type) for actionable functions
        diff_targets = []
        deleted_funcs = []
        for fd in file_diffs:
            for fn_diff in fd.functions:
                if fn_diff.change_type == "deleted":
                    deleted_funcs.append((fd.rel_path, fn_diff.name))
                else:
                    diff_targets.append((fd.rel_path, fn_diff.name, fn_diff.change_type))

        if not diff_targets and not deleted_funcs:
            console.print("[green]No Python function changes detected. Nothing to document.[/green]")
            console.print()
        else:
            from rich.table import Table
            from rich import box
            table = Table(box=box.SIMPLE_HEAD, show_header=True)
            table.add_column("Function", style="bold")
            table.add_column("File", style="dim")
            table.add_column("Change", justify="center")
            for rel_file, func_name, change_type in diff_targets:
                style = "[green]added[/green]" if change_type == "added" else "[cyan]modified[/cyan]"
                table.add_row(func_name, rel_file, style)
            for rel_file, func_name in deleted_funcs:
                table.add_row(func_name, rel_file, "[yellow]deleted[/yellow]")
            console.print(table)

            # Remove deleted functions from cache
            for rel_file, func_name in deleted_funcs:
                cache_key = f"{rel_file}::{func_name}"
                if cache_key in doc_cache._data:
                    del doc_cache._data[cache_key]
                    console.print(f"  [yellow]— removed cached doc:[/yellow] {func_name} ({rel_file})")

            if dry_run:
                console.print()
                console.print("[yellow]Dry run — no LLM calls made.[/yellow]")
                console.print()
            elif diff_targets:
                cfg = load_config(project_root, config_path=config)
                from codecoverage.agents.base import TestGenerationAgent
                from codecoverage.llm.providers import api_key_for_provider
                effective_provider = provider or getattr(cfg.llm, "provider", "anthropic")
                agent = TestGenerationAgent(
                    codebase=codebase,
                    project_root=project_root,
                    llm_config={
                        "provider":    effective_provider,
                        "model":       model or cfg.llm.model,
                        "api_key":     api_key_for_provider(effective_provider, cfg.llm),
                        "temperature": cfg.llm.temperature,
                    },
                )

                max_retries = getattr(cfg.generation, "max_retries", 3)
                done = 0
                console.print()
                console.print(
                    f"[cyan]Documenting [bold]{len(diff_targets)}[/bold] changed "
                    f"function(s)...[/cyan]"
                )
                console.print("[dim](~30-60s per function — Ctrl+C to stop early)[/dim]")
                console.print()

                for rel_file, func_name, change_type in diff_targets:
                    done += 1
                    console.print(
                        f"  [{done}/{len(diff_targets)}] [dim]{rel_file}[/dim] · "
                        f"[bold]{func_name}[/bold]"
                    )
                    doc = None
                    for attempt in range(max_retries):
                        try:
                            doc = agent.generate_doc(
                                target_function=func_name,
                                target_file=rel_file,
                            )
                            break
                        except Exception as e:
                            err = str(e)
                            if ("rate_limit" in err or "429" in err) and attempt < max_retries - 1:
                                console.print(f"  [yellow]⚠ Rate limit — retrying...[/yellow]")
                                continue
                            console.print(f"  [red]✗ {e}[/red]")
                            break

                    if doc and doc.get("summary"):
                        source_file = project_root / rel_file
                        source_bytes = source_file.read_bytes() if source_file.exists() else None
                        doc_cache.put(rel_file, func_name, doc, source_bytes=source_bytes)
                        doc_cache.save()
                        console.print(f"    [green]✓[/green] {doc['summary'][:80]}")
                    else:
                        console.print(f"    [dim]— no doc produced[/dim]")

                console.print()
                console.print(
                    f"[green]✓[/green] Diff enrichment complete · "
                    f"[bold]{len(doc_cache)}[/bold] total cached docs"
                )

                # Re-render with updated cache
                test_refs_map = _build_test_refs_map(doc_cache, project_root)
                flows_md = render_flows_markdown(entry_points, project_root.name, doc_cache)
                summary_md = render_summary_markdown(doc_cache, project_root.name, test_refs_map=test_refs_map)

    # ------------------------------------------------------------------
    # LLM enrichment pass (--enrich DIR)
    # ------------------------------------------------------------------
    if enrich_path:
        enrich_abs = (project_root / enrich_path).resolve()
        targets = _collect_enrich_targets(codebase, project_root, enrich_abs, doc_cache)
        console.print()
        console.print(
            f"[cyan]Enriching {len(targets)} functions under "
            f"[bold]{enrich_path}[/bold] (skipping cached)...[/cyan]"
        )
        console.print("[dim](~30-60s per function — Ctrl+C to stop early)[/dim]")
        console.print()

        cfg = load_config(project_root, config_path=config)
        from codecoverage.agents.base import TestGenerationAgent
        from codecoverage.llm.providers import api_key_for_provider
        effective_provider = provider or getattr(cfg.llm, "provider", "anthropic")
        agent = TestGenerationAgent(
            codebase=codebase,
            project_root=project_root,
            llm_config={
                "provider":    effective_provider,
                "model":       model or cfg.llm.model,
                "api_key":     api_key_for_provider(effective_provider, cfg.llm),
                "temperature": cfg.llm.temperature,
            },
        )

        retry_delays = [60, 120, 180]
        max_retries = getattr(cfg.generation, "max_retries", 3)
        done = 0

        for rel_file, func_name, class_name in targets:
            done += 1
            label = f"{class_name}.{func_name}" if class_name else func_name
            console.print(
                f"  [{done}/{len(targets)}] [dim]{rel_file}[/dim] · [bold]{label}[/bold]"
            )

            doc = None
            for attempt in range(max_retries):
                try:
                    doc = agent.generate_doc(
                        target_function=func_name,
                        target_file=rel_file,
                        class_context=class_name,
                    )
                    break
                except Exception as e:
                    err = str(e)
                    if ("rate_limit" in err or "429" in err) and attempt < max_retries - 1:
                        wait = retry_delays[min(attempt, len(retry_delays) - 1)]
                        console.print(f"  [yellow]⚠ Rate limit — waiting {wait}s...[/yellow]")
                        time.sleep(wait)
                        continue
                    console.print(f"  [red]✗ {e}[/red]")
                    break

            if doc and doc.get("summary"):
                source_file = project_root / rel_file
                source_bytes = source_file.read_bytes() if source_file.exists() else None
                doc_cache.put(rel_file, func_name, doc, source_bytes=source_bytes)
                doc_cache.save()
                console.print(f"    [green]✓[/green] {doc['summary'][:80]}")
            else:
                console.print(f"    [dim]— no doc produced[/dim]")

        console.print()
        console.print(
            f"[green]✓[/green] Enrichment complete · "
            f"[bold]{len(doc_cache)}[/bold] total cached docs"
        )

        # Re-render markdown with freshly populated cache
        test_refs_map = _build_test_refs_map(doc_cache, project_root)
        flows_md = render_flows_markdown(entry_points, project_root.name, doc_cache)
        summary_md = render_summary_markdown(doc_cache, project_root.name, test_refs_map=test_refs_map)
    console.print()

    out_dir.mkdir(parents=True, exist_ok=True)

    flows_path = out_dir / "FLOWS.md"
    flows_path.write_text(flows_md, encoding="utf-8")
    try:
        display = flows_path.relative_to(project_root)
    except ValueError:
        display = flows_path
    console.print(f"[green]✓[/green] {display}")

    summary_path = out_dir / "SUMMARY.md"
    summary_path.write_text(summary_md, encoding="utf-8")
    try:
        display = summary_path.relative_to(project_root)
    except ValueError:
        display = summary_path
    console.print(f"[green]✓[/green] {display}")

    console.print()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _build_test_refs_map(doc_cache, project_root: Path) -> dict:
    """
    Build a mapping of ``rel_file::func_name`` → test refs for all cached functions.
    Pure static analysis — no LLM calls.
    """
    from codecoverage.analysis.test_refs import find_test_refs
    refs_map = {}
    for key in doc_cache._data:
        if "::" not in key:
            continue
        rel_file, func_name = key.split("::", 1)
        refs = find_test_refs(rel_file, func_name, project_root)
        if refs:
            refs_map[key] = refs
    return refs_map


def _collect_enrich_targets(
    codebase,
    project_root: Path,
    enrich_abs: Path,
    doc_cache: DocCache,
) -> List[Tuple[str, str, str]]:
    """
    Return (rel_file, func_name, class_name) tuples for all functions under
    enrich_abs that are not already in doc_cache.

    Skips:
      - Functions whose (rel_file, func_name) key is already cached
      - Names in _SKIP_NAMES (pure dunder noise)
    """
    targets = []
    seen_keys = set()  # deduplicate (rel_file, func_name) pairs

    for key, fi in codebase.files.items():
        try:
            file_abs = Path(key) if Path(key).is_absolute() else project_root / key
            file_abs.relative_to(enrich_abs)
        except ValueError:
            continue

        try:
            rel = str(Path(key).relative_to(project_root))
        except ValueError:
            rel = str(key).replace(str(project_root) + "/", "")

        # Module-level functions
        for fn in fi.functions:
            if fn.name in _SKIP_NAMES:
                continue
            dedup_key = (rel, fn.name)
            if dedup_key in seen_keys:
                continue
            seen_keys.add(dedup_key)
            if doc_cache.get_entry(rel, fn.name) is None:
                targets.append((rel, fn.name, ""))

        # Class methods
        for cls in fi.classes:
            for m in cls.methods:
                if m.name in _SKIP_NAMES:
                    continue
                dedup_key = (rel, m.name)
                if dedup_key in seen_keys:
                    continue
                seen_keys.add(dedup_key)
                if doc_cache.get_entry(rel, m.name) is None:
                    targets.append((rel, m.name, cls.name))

    return targets
