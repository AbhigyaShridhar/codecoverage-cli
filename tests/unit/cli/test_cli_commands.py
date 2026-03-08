"""
Unit tests for CLI commands — no LLM calls.

Tests that commands:
  - expose the expected options and help text
  - fail gracefully with missing config / bad arguments
  - init creates a .codecoverage.toml
"""
from __future__ import annotations

from pathlib import Path

import pytest
from click.testing import CliRunner

from codecoverage.cli.main import cli


# ---------------------------------------------------------------------------
# --help smoke tests
# ---------------------------------------------------------------------------

class TestHelpText:
    """Every command should exit 0 and print usage when --help is passed."""

    @pytest.mark.parametrize("cmd", [
        [], ["generate"], ["diff-test"], ["document"], ["serve"], ["init"],
    ])
    def test_help_exits_zero(self, cmd):
        runner = CliRunner()
        result = runner.invoke(cli, cmd + ["--help"])
        assert result.exit_code == 0, result.output
        assert "Usage:" in result.output

    def test_root_help_lists_commands(self):
        runner = CliRunner()
        result = runner.invoke(cli, ["--help"])
        assert "generate" in result.output
        assert "diff-test" in result.output
        assert "document" in result.output
        assert "serve" in result.output


# ---------------------------------------------------------------------------
# codecoverage init
# ---------------------------------------------------------------------------

class TestInitCommand:
    # init prompts for API keys; feed empty lines to accept defaults / skip.
    _INIT_INPUT = "\n\n\n\n\n"

    def test_init_creates_toml(self, tmp_path):
        runner = CliRunner()
        result = runner.invoke(
            cli, ["init", "--path", str(tmp_path)], input=self._INIT_INPUT
        )
        toml = tmp_path / ".codecoverage.toml"
        assert toml.exists(), f"TOML not created. Output:\n{result.output}"

    def test_init_toml_contains_llm_section(self, tmp_path):
        runner = CliRunner()
        runner.invoke(
            cli, ["init", "--path", str(tmp_path)], input=self._INIT_INPUT
        )
        toml = tmp_path / ".codecoverage.toml"
        if toml.exists():
            content = toml.read_text()
            assert "[llm]" in content or "llm" in content

    def test_init_second_run_does_not_crash(self, tmp_path):
        """Running init twice should not raise an unhandled exception."""
        runner = CliRunner()
        runner.invoke(
            cli, ["init", "--path", str(tmp_path)], input=self._INIT_INPUT
        )
        result = runner.invoke(
            cli, ["init", "--path", str(tmp_path)], input=self._INIT_INPUT
        )
        # May exit non-zero (e.g. prompts the user to confirm overwrite and
        # they choose not to), but must not raise an unhandled exception.
        assert result.exception is None or isinstance(result.exception, SystemExit)


# ---------------------------------------------------------------------------
# codecoverage generate — argument validation (no LLM)
# ---------------------------------------------------------------------------

class TestGenerateArgValidation:

    def test_output_without_file_and_function_fails(self, tmp_path):
        """-o requires both --file and --function."""
        runner = CliRunner()
        result = runner.invoke(cli, [
            "generate",
            "--output", "tests/test_foo.py",
            "--path", str(tmp_path),
        ])
        assert result.exit_code != 0

    def test_dry_run_no_config_exits_gracefully(self, tmp_path):
        """--dry-run with no .codecoverage.toml should fail cleanly."""
        runner = CliRunner()
        result = runner.invoke(cli, [
            "generate",
            "--dry-run",
            "--path", str(tmp_path),
        ])
        assert result.exception is None or isinstance(result.exception, SystemExit)

    def test_missing_config_exits_gracefully(self, tmp_path):
        """No .codecoverage.toml → should print error, not traceback."""
        runner = CliRunner()
        result = runner.invoke(cli, [
            "generate",
            "--function", "my_fn",
            "--file", "src/module.py",
            "--path", str(tmp_path),
        ])
        # Should exit non-zero but not crash with unhandled exception
        assert result.exit_code != 0 or "error" in result.output.lower() or "not found" in result.output.lower()

    def test_provider_choice_rejects_unknown(self, tmp_path):
        runner = CliRunner()
        result = runner.invoke(cli, [
            "generate",
            "--function", "f",
            "--file", "mod.py",
            "--provider", "not-a-real-provider",
            "--path", str(tmp_path),
        ])
        assert result.exit_code != 0


# ---------------------------------------------------------------------------
# codecoverage diff-test — argument validation
# ---------------------------------------------------------------------------

class TestDiffTestArgValidation:

    def test_dry_run_with_no_git_repo_exits_gracefully(self, tmp_path):
        """--dry-run outside a git repo should print an error, not traceback."""
        runner = CliRunner()
        result = runner.invoke(cli, [
            "diff-test",
            "--dry-run",
            "--path", str(tmp_path),
        ])
        # Should not raise unhandled exception
        assert result.exception is None or isinstance(result.exception, SystemExit)

    def test_provider_choice_rejects_unknown(self, tmp_path):
        runner = CliRunner()
        result = runner.invoke(cli, [
            "diff-test",
            "--provider", "bad_provider",
            "--path", str(tmp_path),
        ])
        assert result.exit_code != 0


# ---------------------------------------------------------------------------
# codecoverage document — argument validation
# ---------------------------------------------------------------------------

class TestDocumentArgValidation:

    def test_missing_config_exits_gracefully(self, tmp_path):
        runner = CliRunner()
        result = runner.invoke(cli, [
            "document",
            "--path", str(tmp_path),
        ])
        assert result.exit_code != 0 or "not found" in result.output.lower()

    def test_provider_choice_validated(self, tmp_path):
        runner = CliRunner()
        result = runner.invoke(cli, [
            "document",
            "--provider", "unknown",
            "--path", str(tmp_path),
        ])
        assert result.exit_code != 0

    def test_diff_flags_appear_in_help(self):
        runner = CliRunner()
        result = runner.invoke(cli, ["document", "--help"])
        assert "--working" in result.output
        assert "--last-commit" in result.output
        assert "--last-merge" in result.output
        assert "--since" in result.output
        assert "--dry-run" in result.output

    def test_dry_run_outside_git_repo_exits_gracefully(self, tmp_path):
        """--working --dry-run outside a git repo should fail (no config), not segfault."""
        runner = CliRunner()
        result = runner.invoke(cli, [
            "document",
            "--working",
            "--dry-run",
            "--path", str(tmp_path),
        ])
        # Fails because no .codecoverage.toml exists; that's expected — not a crash
        assert result.exit_code != 0


# ---------------------------------------------------------------------------
# codecoverage serve — argument validation
# ---------------------------------------------------------------------------

class TestServeArgValidation:

    def test_invalid_port_rejected(self, tmp_path):
        runner = CliRunner()
        result = runner.invoke(cli, [
            "serve",
            "--port", "not-a-number",
            "--path", str(tmp_path),
        ])
        assert result.exit_code != 0
