"""
diff-test command — generate or update tests based on git diff.

Detects which functions changed since a git ref, then:
  • Added functions   → generate a fresh test (same as `generate`)
  • Modified functions → update the existing test with minimal changes
  • Deleted functions  → report orphaned tests (no LLM call, no auto-delete)
"""

import time
import click
from pathlib import Path
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.syntax import Syntax
from rich import box

from codecoverage.core.parser import CodebaseParser
from codecoverage.core.config import load_config
from codecoverage.agents.base import TestGenerationAgent
from codecoverage.llm.providers import api_key_for_provider
from codecoverage.analysis.test_finder import find_test_files
from codecoverage.git.diff import DiffAnalyzer, FileDiff

console = Console()


@click.command("diff-test")
@click.option(
    "--path",
    type=click.Path(exists=True),
    default=".",
    help="Path to project root / git repo (default: current directory)",
)
@click.option(
    "--config",
    type=click.Path(exists=True),
    default=None,
    help="Path to config file (default: .codecoverage.toml)",
)
@click.option(
    "--working",
    "mode",
    flag_value="working",
    default=True,
    help="[default] Diff uncommitted changes (staged + unstaged) vs HEAD",
)
@click.option(
    "--last-commit",
    "mode",
    flag_value="last-commit",
    help="Diff the most recent commit against its parent",
)
@click.option(
    "--last-merge",
    "mode",
    flag_value="last-merge",
    help="Diff the most recent merge commit against its first parent",
)
@click.option(
    "--since",
    "since_ref",
    default=None,
    metavar="REF",
    help="Diff HEAD against an arbitrary git ref (branch, tag, commit SHA)",
)
@click.option(
    "--output-dir",
    type=click.Path(),
    default=None,
    help="Write generated/updated test files to this directory",
)
@click.option(
    "--dry-run",
    is_flag=True,
    default=False,
    help="Show the plan (what would be generated/updated) without calling the LLM",
)
@click.option(
    "--provider",
    type=click.Choice(["anthropic", "openai", "cursor"], case_sensitive=False),
    default=None,
    help="LLM provider (default: anthropic). Overrides config file.",
)
@click.option(
    "--model",
    default=None,
    help="Model name. Defaults to provider default (e.g. claude-sonnet-4-6, gpt-4o).",
)
def diff_test(
    path: str,
    config: str,
    mode: str,
    since_ref: str,
    output_dir: str,
    dry_run: bool,
    provider: str,
    model: str,
) -> None:
    """
    Generate or update tests based on what changed in git.

    Detects changed functions at the git-diff level and takes targeted action:

    \b
      Added function   → generate a fresh test
      Modified function → update the existing test (minimal changes only)
      Deleted function  → report orphaned tests for manual review

    Examples:

    \b
        # Test uncommitted changes
        codecoverage diff-test

    \b
        # Test what the last commit changed
        codecoverage diff-test --last-commit

    \b
        # Test what changed since branching off main
        codecoverage diff-test --since main

    \b
        # Preview without calling the LLM
        codecoverage diff-test --dry-run
    """
    project_root = Path(path).resolve()

    console.print()
    console.print("[bold cyan]CodeCoverage — Diff-Based Test Generation[/bold cyan]")
    console.print()

    # ------------------------------------------------------------------
    # Resolve the diff
    # ------------------------------------------------------------------
    console.print("[cyan]Analysing git diff...[/cyan]")
    try:
        analyzer = DiffAnalyzer(project_root)

        if since_ref:
            file_diffs = analyzer.get_ref_diff(since_ref, "HEAD")
            scope_label = f"HEAD vs {since_ref}"
        elif mode == "last-commit":
            file_diffs = analyzer.get_last_commit_diff()
            scope_label = "last commit (HEAD~1 → HEAD)"
        elif mode == "last-merge":
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

    if not file_diffs:
        console.print("[green]No Python changes detected. Nothing to do.[/green]")
        console.print()
        return

    # ------------------------------------------------------------------
    # Build the work plan and display summary table
    # ------------------------------------------------------------------
    plan = _build_plan(file_diffs, project_root)

    _print_summary_table(plan)

    actionable = [item for item in plan if item["action"] != "flag-orphan"]
    orphans = [item for item in plan if item["action"] == "flag-orphan"]

    if orphans:
        console.print("[yellow]Orphaned tests (functions deleted — review manually):[/yellow]")
        for item in orphans:
            test_files = find_test_files(item["file_path"], project_root)
            if test_files:
                for tf in test_files:
                    console.print(
                        f"  [dim]{tf.relative_to(project_root)}[/dim] "
                        f"— may contain tests for [bold]{item['function']}[/bold]"
                    )
            else:
                console.print(
                    f"  [dim]No test file found for {item['rel_path']}[/dim] "
                    f"— [bold]{item['function']}[/bold] was deleted"
                )
        console.print()

    if not actionable:
        console.print("[green]Nothing to generate or update.[/green]")
        console.print()
        return

    if dry_run:
        console.print("[yellow]Dry run — no LLM calls made.[/yellow]")
        console.print()
        return

    # ------------------------------------------------------------------
    # Load config and parse codebase (once, shared across all calls)
    # ------------------------------------------------------------------
    cfg = load_config(project_root, config_path=config)

    console.print("[cyan]Parsing codebase...[/cyan]")
    parser = CodebaseParser(
        root=project_root,
        ignore_patterns=cfg.parsing.ignore_patterns,
    )
    codebase = parser.parse()
    console.print(
        f"  ✓ {codebase.total_files} files, "
        f"{codebase.total_functions} functions, "
        f"{codebase.total_classes} classes"
    )
    console.print()

    console.print("[cyan]Initializing agent...[/cyan]")
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
    console.print("  ✓ Agent ready")
    console.print()

    # ------------------------------------------------------------------
    # Process each actionable function
    # ------------------------------------------------------------------
    total = len(actionable)
    max_retries = cfg.generation.max_retries
    retry_delays = [60, 120, 180]

    for i, item in enumerate(actionable, 1):
        func_name = item["function"]
        rel_path = item["rel_path"]
        action = item["action"]
        raw_diff = item["raw_diff"]

        label = "Updating" if action == "update" else "Generating"
        console.rule(f"[{i}/{total}] {label} test for [bold]{func_name}[/bold]")
        console.print(f"  File: [dim]{rel_path}[/dim]")
        console.print()

        result = None
        last_error = None

        for attempt in range(max_retries):
            try:
                if action == "update":
                    result = agent.generate_test_update(
                        target_function=func_name,
                        target_file=rel_path,
                        diff_text=raw_diff,
                    )
                else:  # "create"
                    result = agent.generate_test(
                        target_function=func_name,
                        target_file=rel_path,
                    )
                break

            except Exception as e:
                error_str = str(e)
                is_rate_limit = "rate_limit" in error_str or "429" in error_str

                if is_rate_limit and attempt < max_retries - 1:
                    wait = retry_delays[min(attempt, len(retry_delays) - 1)]
                    console.print(
                        f"[yellow]⚠ Rate limit (attempt {attempt + 1}/{max_retries}). "
                        f"Waiting {wait}s...[/yellow]"
                    )
                    time.sleep(wait)
                    last_error = e
                    continue

                last_error = e
                break

        if result is None:
            console.print(f"[red]✗ Failed: {last_error}[/red]")
            console.print()
            continue

        test_code, doc = result

        # Output
        console.print("[bold green]✓ Done[/bold green]")
        console.print()

        syntax = Syntax(test_code, "python", theme="monokai", line_numbers=True)
        console.print(Panel(syntax, title=f"{func_name} — test", border_style="green"))

        if output_dir:
            _write_output(test_code, rel_path, func_name, action, Path(output_dir))
            console.print()

        # Persist doc to cache
        if doc:
            from codecoverage.core.doc_cache import DocCache
            source_file = project_root / rel_path
            source_bytes = source_file.read_bytes() if source_file.exists() else None
            cache = DocCache(project_root).load()
            cache.put(rel_path, func_name, doc, source_bytes=source_bytes)
            cache.save()
            console.print(f"  [dim]✓ Doc cached for {func_name}[/dim]")

    console.print()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _build_plan(file_diffs: list, project_root: Path) -> list:
    """
    Convert a list of FileDiff objects into a flat action plan.

    Each item:
        function  : str
        rel_path  : str
        file_path : Path
        action    : "create" | "update" | "flag-orphan"
        raw_diff  : str
    """
    plan = []
    for fd in file_diffs:
        for func_diff in fd.functions:
            if func_diff.change_type == "deleted":
                action = "flag-orphan"
            elif func_diff.change_type == "added":
                # If a test file already exists for this module, treat as update
                # (the function is new but the test file may already exist)
                existing = find_test_files(fd.file_path, project_root)
                action = "update" if existing else "create"
            else:  # modified
                action = "update"

            plan.append({
                "function":  func_diff.name,
                "rel_path":  fd.rel_path,
                "file_path": fd.file_path,
                "action":    action,
                "raw_diff":  fd.raw_diff,
            })
    return plan


def _print_summary_table(plan: list) -> None:
    table = Table(box=box.SIMPLE_HEAD, show_header=True)
    table.add_column("Function", style="bold")
    table.add_column("File", style="dim")
    table.add_column("Change", justify="center")
    table.add_column("Action", justify="center")

    action_style = {
        "create":      "[green]create test[/green]",
        "update":      "[cyan]update test[/cyan]",
        "flag-orphan": "[yellow]flag orphan[/yellow]",
    }
    change_style = {
        "create":      "[green]added[/green]",
        "update":      "[cyan]modified[/cyan]",
        "flag-orphan": "[yellow]deleted[/yellow]",
    }

    for item in plan:
        table.add_row(
            item["function"],
            item["rel_path"],
            change_style.get(item["action"], item["action"]),
            action_style.get(item["action"], item["action"]),
        )

    console.print(table)
    console.print()


def _write_output(
    test_code: str,
    rel_path: str,
    func_name: str,
    action: str,
    output_dir: Path,
) -> None:
    """Write generated test code to output_dir, mirroring the source structure."""
    # Mirror the source path: payments/gateway.py → test_gateway.py
    source_path = Path(rel_path)
    stem = source_path.stem
    test_filename = f"test_{stem}.py" if not stem.startswith("test_") else f"{stem}.py"

    # Preserve directory structure under output_dir
    relative_dir = source_path.parent
    dest_dir = output_dir / relative_dir
    dest_dir.mkdir(parents=True, exist_ok=True)

    dest = dest_dir / test_filename

    if dest.exists() and action == "update":
        # Back up original before overwriting
        backup = dest.with_suffix(".py.bak")
        backup.write_text(dest.read_text())
        console.print(f"  [dim]Backup: {backup}[/dim]")

    dest.write_text(test_code)
    console.print(f"  [green]✓ Written:[/green] {dest}")
