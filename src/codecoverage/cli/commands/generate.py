"""
Generate command - generate tests for functions
"""

import click
from pathlib import Path
from rich.console import Console
from rich.panel import Panel
from rich.syntax import Syntax
from rich.table import Table
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TaskProgressColumn

from codecoverage.core.parser import CodebaseParser
from codecoverage.core.config import load_config
from codecoverage.agents.base import TestGenerationAgent
from codecoverage.llm.providers import api_key_for_provider
from codecoverage.analysis.test_finder import find_test_files, extract_test_context
from codecoverage.analysis.test_resolver import resolve_test_output_path

console = Console()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_TEST_DIR_NAMES = {"tests", "test", "unit_tests", "integration_tests", "specs", "spec"}


def _is_test_file(path: Path) -> bool:
    """Return True if path is a test file or lives inside a test directory."""
    if path.name.startswith("test_") or path.name.endswith("_test.py"):
        return True
    return any(part in _TEST_DIR_NAMES for part in path.parts)


def _get_additional_context(source_file: Path, file_path: str, project_root: Path) -> str:
    """Return pre-flight context string based on existing test coverage."""
    found_test_files = find_test_files(source_file, project_root) if source_file.exists() else []

    if found_test_files:
        primary_ctx = extract_test_context(found_test_files[0])
        return (
            f"\nPre-flight note: {len(found_test_files)} existing test file(s) found for "
            f"this module.  The primary reference is "
            f"'{found_test_files[0].relative_to(project_root)}' "
            f"(framework: {primary_ctx.framework}, fixtures: {primary_ctx.fixture_style}, "
            f"mocks: {primary_ctx.mock_style}).  "
            f"You MUST call get_module_test_examples(\"{file_path}\") as your first action "
            f"to read the full style information before writing any code."
        )
    return (
        "\nPre-flight note: No existing test file was found for this module. "
        "Call analyze_project_patterns() to discover the project-wide testing "
        "conventions and use those as the baseline style."
    )


def _write_test(
    agent,
    function: str,
    file_path: str,
    project_root: Path,
    output: str | None,
    additional_context: str,
    *,
    show_preview: bool = True,
) -> str:
    """
    Run the agent for one function, write the output.

    Returns one of: "ok", "skip", "fail".
    """
    try:
        result = agent.generate_test(
            target_function=function,
            target_file=file_path,
            additional_context=additional_context,
        )
    except Exception as e:
        console.print(f"  [bold red]✗[/bold red] {function}: {e}")
        return "fail"

    if result is None:
        console.print(f"  [bold red]✗[/bold red] {function}: agent returned no result")
        return "fail"

    test_code, doc = result

    # Agent explicitly declined to test this function
    if test_code and test_code.startswith("__SKIP__:"):
        reason = test_code[len("__SKIP__:"):]
        console.print(f"  [yellow]⊘[/yellow]  {function}: {reason}")
        return "skip"

    if not test_code or not test_code.strip():
        console.print(f"  [bold red]✗[/bold red] {function}: agent returned empty code")
        return "fail"

    # Resolve output path
    if output:
        output_path = Path(output)
    else:
        output_path = resolve_test_output_path(
            source_file=project_root / file_path,
            project_root=project_root,
            function_name=function,
        )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(test_code)

    try:
        display_path = output_path.relative_to(project_root)
    except ValueError:
        display_path = output_path

    if show_preview:
        syntax = Syntax(test_code, "python", theme="monokai", line_numbers=True)
        console.print(Panel(syntax, title=f"Generated Test — {function}", border_style="green"))

    console.print(f"  [green]✓[/green] {function} → {display_path}")

    # Cache doc
    if doc:
        from codecoverage.core.doc_cache import DocCache
        src = project_root / file_path
        source_bytes = src.read_bytes() if src.exists() else None
        cache = DocCache(project_root).load()
        cache.put(file_path, function, doc, source_bytes=source_bytes)
        cache.save()

    return "ok"


# ---------------------------------------------------------------------------
# CLI command
# ---------------------------------------------------------------------------

@click.command()
@click.option(
    '--function', '-f',
    default=None,
    help='Function name to generate test for. If omitted, generates tests for all functions.'
)
@click.option(
    '--file', 'file_path',
    default=None,
    help='Source file containing the function (relative to project root). '
         'If omitted, all files in --dir (or the whole project) are processed.'
)
@click.option(
    '--dir', 'dir_path',
    default=None,
    help='Limit bulk generation to this subdirectory (relative to project root). '
         'Ignored when --file is specified.'
)
@click.option(
    '--path',
    type=click.Path(exists=True),
    default='.',
    help='Path to project root (default: current directory)'
)
@click.option(
    '--config',
    type=click.Path(exists=True),
    default=None,
    help='Path to config file (default: .codecoverage.toml)'
)
@click.option(
    '--output', '-o',
    type=click.Path(),
    default=None,
    help='Output file path (default: auto-detected from project test layout). '
         'Only valid when generating for a single function.'
)
@click.option(
    '--provider',
    type=click.Choice(['anthropic', 'openai', 'cursor'], case_sensitive=False),
    default=None,
    help='LLM provider (default: anthropic). Overrides config file.'
)
@click.option(
    '--model',
    default=None,
    help='Model name. Defaults to provider default (e.g. claude-sonnet-4-6, gpt-4o).'
)
@click.option(
    '--dry-run',
    is_flag=True,
    default=False,
    help='Show which functions would be processed without making LLM calls.'
)
@click.option(
    '--extra-context', '-x',
    default=None,
    help='Extra instructions passed verbatim to the agent for every function. '
         'E.g. "skip boilerplate" or "decide whether this module is worth testing".'
)
@click.option(
    '--overwrite',
    is_flag=True,
    default=False,
    help='In bulk mode, regenerate tests even for files that already have a test file. '
         'Default: skip files with existing tests.'
)
def generate(
    function: str,
    file_path: str,
    dir_path: str,
    path: str,
    config: str,
    output: str,
    provider: str,
    model: str,
    dry_run: bool,
    extra_context: str,
    overwrite: bool,
) -> None:
    """
    Generate tests for functions.

    Single-function mode (requires --file and --function):

        codecoverage generate -f login --file src/auth.py

    Bulk mode — generate tests for every function in the project:

        codecoverage generate

    Bulk mode scoped to a subdirectory:

        codecoverage generate --dir payments/interface_layer/

    Bulk mode scoped to a single file:

        codecoverage generate --file payments/gateway.py

    The agent first studies any existing tests for the target module and
    replicates their exact style.  Multiple LLM calls are made — one per
    function — so context stays focused and manageable.

    Pass extra instructions with -x / --extra-context:

        codecoverage generate --file payments/gateway.py -x "skip boilerplate"
        codecoverage generate -x "decide whether this module is worth testing at all"
    """
    project_root = Path(path).resolve()

    # ------------------------------------------------------------------
    # Validate option combinations
    # ------------------------------------------------------------------
    if output and not (function and file_path):
        console.print("[bold red]Error:[/bold red] -o / --output requires both --file and --function to be specified.")
        raise SystemExit(1)

    # ------------------------------------------------------------------
    # Load config
    # ------------------------------------------------------------------
    try:
        cfg = load_config(project_root, config_path=config)
    except FileNotFoundError as e:
        console.print(f"[bold red]Error:[/bold red] {e}")
        raise SystemExit(1)

    # ------------------------------------------------------------------
    # Parse codebase
    # ------------------------------------------------------------------
    console.print()
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

    # ------------------------------------------------------------------
    # Build work list: (rel_file_path, function_name) pairs
    # ------------------------------------------------------------------
    work: list[tuple[str, str]] = []

    if file_path and function:
        # Single-function mode — trust the user, no filtering
        work.append((file_path, function))

    elif file_path:
        # One file, all functions
        target = project_root / file_path
        if _is_test_file(Path(file_path)):
            console.print(f"[yellow]⊘  {file_path} looks like a test file — nothing to generate.[/yellow]")
            return
        if not overwrite and find_test_files(target, project_root):
            console.print(
                f"[yellow]⊘  {file_path} already has a test file — skipping.[/yellow]\n"
                f"  Pass [bold]--overwrite[/bold] to regenerate."
            )
            return
        for file_key, file_info in codebase.files.items():
            if file_key == target or str(file_key) == str(target):
                for fn in file_info.get_all_functions():
                    work.append((file_path, fn.name))
                break
        if not work:
            console.print(f"[bold red]Error:[/bold red] No functions found in {file_path}")
            raise SystemExit(1)

    else:
        # Bulk mode — all files (optionally scoped to --dir), all functions
        scope = project_root / dir_path if dir_path else None
        if scope and not scope.is_dir():
            console.print(f"[bold red]Error:[/bold red] --dir '{dir_path}' is not a directory under {project_root}")
            raise SystemExit(1)

        already_covered = 0
        for file_key, file_info in codebase.files.items():
            # Apply --dir filter
            if scope:
                try:
                    file_key.relative_to(scope)
                except ValueError:
                    continue  # outside the requested subdirectory

            try:
                rel = str(file_key.relative_to(project_root))
            except ValueError:
                rel = str(file_key)

            # Skip test files and test directories
            if _is_test_file(Path(rel)):
                continue

            # Skip files that already have a test file unless --overwrite
            if not overwrite and find_test_files(file_key, project_root):
                already_covered += len(file_info.get_all_functions())
                continue

            for fn in file_info.get_all_functions():
                work.append((rel, fn.name))

        if already_covered:
            console.print(
                f"  [dim]⊘  {already_covered} function(s) in files with existing tests "
                f"skipped — pass --overwrite to regenerate.[/dim]"
            )
            console.print()

    if not work:
        console.print("[yellow]No functions found to generate tests for.[/yellow]")
        return

    # ------------------------------------------------------------------
    # Dry-run: just show the plan
    # ------------------------------------------------------------------
    if dry_run:
        table = Table(title=f"Test generation plan — {len(work)} function(s)", show_lines=False)
        table.add_column("File", style="cyan")
        table.add_column("Function", style="bold")
        for fp, fn in work:
            table.add_row(fp, fn)
        console.print(table)
        console.print()
        if extra_context:
            console.print(f"[dim]Extra context:[/dim] {extra_context}")
            console.print()
        console.print("[dim]--dry-run: no LLM calls made.[/dim]")
        return

    # ------------------------------------------------------------------
    # Initialize agent once (codebase is shared across all calls)
    # ------------------------------------------------------------------
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
    # Generate — one LLM call per function
    # ------------------------------------------------------------------
    single_mode = len(work) == 1
    succeeded = 0
    skipped = 0
    failed = 0

    if single_mode:
        fp, fn = work[0]
        panel_body = f"[bold]Function:[/bold] {fn}\n[bold]File:[/bold] {fp}"
        if extra_context:
            panel_body += f"\n[bold]Extra context:[/bold] {extra_context}"
        console.print(Panel(panel_body, title="Generating Test", border_style="cyan"))
        console.print()

        # Pre-flight scan
        console.print("[bold cyan]Scanning for existing module tests...[/bold cyan]")
        source_file = project_root / fp
        found_test_files = find_test_files(source_file, project_root) if source_file.exists() else []
        if found_test_files:
            primary_ctx = extract_test_context(found_test_files[0])
            t = Table(show_header=False, box=None, padding=(0, 2))
            t.add_column(style="green")
            t.add_column(style="dim")
            for i, tf in enumerate(found_test_files):
                rel = tf.relative_to(project_root)
                t.add_row(f"✓  {rel}", "[primary]" if i == 0 else "[also found]")
            console.print(t)
            console.print(
                f"  [green]Framework:[/green] {primary_ctx.framework}  "
                f"[green]Fixtures:[/green] {primary_ctx.fixture_style}  "
                f"[green]Mocks:[/green] {primary_ctx.mock_style}"
            )
        else:
            console.print("  [yellow]No existing module tests found[/yellow]")
            console.print("  [dim]Agent will use project-wide conventions or standard pytest[/dim]")
        console.print()

        additional_context = _get_additional_context(project_root / fp, fp, project_root)
        if extra_context:
            additional_context += f"\n\nUser instructions: {extra_context}"
        console.print("[cyan]Generating test...[/cyan]")
        console.print("[dim](This may take a while for large codebases)[/dim]")
        console.print()

        outcome = _write_test(agent, fn, fp, project_root, output, additional_context, show_preview=True)
        if outcome == "ok": succeeded += 1
        elif outcome == "skip": skipped += 1
        else: failed += 1

    else:
        console.print(f"[bold cyan]Bulk mode:[/bold cyan] generating tests for {len(work)} function(s)")
        console.print("[dim]One LLM call per function. Context stays focused per-module.[/dim]")
        console.print()

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TaskProgressColumn(),
            console=console,
            transient=False,
        ) as progress:
            task = progress.add_task("Generating...", total=len(work))

            for fp, fn in work:
                progress.update(task, description=f"[cyan]{fn}[/cyan] in {fp}")
                additional_context = _get_additional_context(project_root / fp, fp, project_root)
                if extra_context:
                    additional_context += f"\n\nUser instructions: {extra_context}"
                outcome = _write_test(agent, fn, fp, project_root, None, additional_context, show_preview=False)
                if outcome == "ok": succeeded += 1
                elif outcome == "skip": skipped += 1
                else: failed += 1
                progress.advance(task)

        console.print()
        console.print(
            f"[bold]Done.[/bold] "
            f"[green]{succeeded} succeeded[/green]  "
            f"[yellow]{skipped} skipped[/yellow]  "
            f"{'[red]' if failed else '[dim]'}{failed} failed{'[/red]' if failed else '[/dim]'}"
        )

    console.print()
