"""
CodeCoverage CLI

AI-powered test generation for Python projects.
"""

import click
from rich.console import Console

from codecoverage.__version__ import __version__
from codecoverage.cli.commands.init import init
from codecoverage.cli.commands.generate import generate
from codecoverage.cli.commands.diff_test import diff_test
from codecoverage.cli.commands.document import document
from codecoverage.cli.commands.serve import serve

console = Console()


@click.group()
@click.version_option(version=__version__, prog_name="codecoverage")
def cli():
    """
    CodeCoverage - AI-powered test generation

    Learn your codebase patterns and generate contextually appropriate tests.
    """
    pass


# Register commands
# noinspection PyTypeChecker
cli.add_command(init)
# noinspection PyTypeChecker
cli.add_command(generate)
# noinspection PyTypeChecker
cli.add_command(diff_test)
# noinspection PyTypeChecker
cli.add_command(document)
# noinspection PyTypeChecker
cli.add_command(serve)

if __name__ == '__main__':
    cli()
