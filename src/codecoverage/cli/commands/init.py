"""
Init command - initialize CodeCoverage in a project
"""

import click
from pathlib import Path
from rich.console import Console
from rich.prompt import Prompt, Confirm

console = Console()


@click.command()
@click.option(
    '--path',
    type=click.Path(),
    default='.',
    help='Path to project root'
)
def init(path: str) -> None:
    """
    Initialize CodeCoverage in your project

    Creates a .codecoverage.toml configuration file.

    Example:
        codecoverage init
        codecoverage init --path /path/to/project
    """
    project_root = Path(path).resolve()
    config_path = project_root / '.codecoverage.toml'

    console.print()
    console.print("[bold cyan]CodeCoverage Initialization[/bold cyan]")
    console.print()

    if config_path.exists():
        if not Confirm.ask(f"[yellow]Config already exists at {config_path}. Overwrite?[/yellow]"):
            console.print("[yellow]Aborted.[/yellow]")
            raise SystemExit(1)

    # ----------------------------------------------------------------
    # Provider selection
    # ----------------------------------------------------------------
    console.print("[bold]LLM Configuration[/bold]")
    console.print()

    provider = Prompt.ask(
        "Provider",
        choices=["anthropic", "openai", "cursor"],
        default="anthropic",
    )

    # ----------------------------------------------------------------
    # Provider-specific defaults and key prompt
    # ----------------------------------------------------------------
    _DEFAULTS = {
        "anthropic": ("claude-sonnet-4-6",   "ANTHROPIC_API_KEY",  "sk-ant-..."),
        "openai":    ("gpt-4o",               "OPENAI_API_KEY",     "sk-proj-..."),
        "cursor":    ("sonnet-4.6",           "CURSOR_API_KEY",     "crsr_..."),
    }
    _KEY_FIELD = {
        "anthropic": "anthropic_api_key",
        "openai":    "openai_api_key",
        "cursor":    "cursor_api_key",
    }

    default_model, env_var, key_hint = _DEFAULTS[provider]

    console.print(
        f"  [dim]API key can also be set via the [bold]{env_var}[/bold] environment variable.[/dim]"
    )
    api_key = Prompt.ask(
        f"  {env_var}",
        password=True,
        default="",
    )

    model = Prompt.ask(
        "  Model",
        default=default_model,
    )

    # ----------------------------------------------------------------
    # Build config content
    # ----------------------------------------------------------------
    key_line = (
        f'{_KEY_FIELD[provider]} = "{api_key}"'
        if api_key
        else f"# {_KEY_FIELD[provider]} = \"{key_hint}\"  # or set {env_var} env var"
    )

    config_content = f"""# CodeCoverage Configuration

[project]
name = "{project_root.name}"

[parsing]
# Files/directories to ignore during parsing
ignore_patterns = [
    "*.pyc",
    "__pycache__",
    ".git",
    ".venv",
    "venv",
    "env",
    "node_modules",
    ".pytest_cache",
    ".mypy_cache",
    "build",
    "dist",
    "migrations",
    "static",
]

[llm]
provider    = "{provider}"
model       = "{model}"
temperature = 0.0
{key_line}

[generation]
max_retries = 3
"""

    # Write config
    project_root.mkdir(parents=True, exist_ok=True)
    config_path.write_text(config_content)

    console.print()
    console.print(f"[bold green]✓ Configuration saved to:[/bold green] {config_path}")
    if api_key:
        console.print(
            f"  [yellow]Note:[/yellow] API key written to .codecoverage.toml — "
            f"consider adding it to [bold]{env_var}[/bold] env var and removing it from the file."
        )
    console.print()
    console.print("[bold]Next steps:[/bold]")
    console.print("  1. Run: [cyan]codecoverage generate -f <function> --file <path>[/cyan]")
    console.print("  2. Browse docs: [cyan]codecoverage serve[/cyan]")
    console.print()
