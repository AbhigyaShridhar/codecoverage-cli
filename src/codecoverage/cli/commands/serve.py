"""
serve command — browse codebase documentation in the browser.
"""

import click
from pathlib import Path
from rich.console import Console
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn

from codecoverage.core.config import load_config
from codecoverage.core.doc_cache import DocCache
from codecoverage.core.parser import CodebaseParser
from codecoverage.web.flow_tracer import FlowTracer
from codecoverage.web import server as web_server

console = Console()


@click.command()
@click.option(
    "--path",
    type=click.Path(exists=True),
    default=".",
    help="Path to project root (default: current directory)",
)
@click.option(
    "--port",
    type=int,
    default=8080,
    help="Port to serve on (default: 8080)",
)
@click.option(
    "--no-browser",
    is_flag=True,
    default=False,
    help="Do not open the browser automatically",
)
@click.option(
    "--config",
    type=click.Path(exists=True),
    default=None,
    help="Path to config file",
)
def serve(path: str, port: int, no_browser: bool, config: str) -> None:
    """
    Browse codebase documentation in the browser.

    Parses the project, loads cached function docs, and serves an
    interactive documentation UI at localhost:{port}.

    \\b
    Examples:
        codecoverage serve
        codecoverage serve --path ~/projects/myapp --port 9000
        codecoverage serve --no-browser
    """
    project_root = Path(path).resolve()
    cfg = load_config(project_root, config_path=config)

    console.print()
    console.print(
        Panel(
            f"[bold]Project:[/bold] {project_root}\n"
            f"[bold]Port:[/bold]    {port}",
            title="[cyan]codecoverage serve[/cyan]",
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

    console.print(
        f"[green]\u2713[/green] Parsed "
        f"[bold]{codebase.total_files}[/bold] files \u00b7 "
        f"[bold]{codebase.total_functions}[/bold] functions \u00b7 "
        f"[bold]{codebase.total_classes}[/bold] classes"
    )
    console.print(
        f"[green]\u2713[/green] Detected "
        f"[bold]{len(entry_points)}[/bold] entry points \u00b7 "
        f"[bold]{len(doc_cache)}[/bold] functions with cached docs"
    )
    console.print()

    url = f"http://localhost:{port}"
    console.print(f"  [bold]Docs[/bold] \u2192 [cyan]{url}[/cyan]")
    console.print(f"  [dim](Ctrl+C to stop)[/dim]")
    console.print()

    web_server.serve(
        project_name=project_root.name,
        doc_cache=doc_cache,
        entry_points=entry_points,
        project_root=project_root,
        port=port,
        open_browser=not no_browser,
    )

    console.print()
    console.print("[dim]Server stopped.[/dim]")
