import pytest
from click.testing import CliRunner

from viento.cli.main import cli


@pytest.fixture
def runner():
    return CliRunner()


def test_cli_help_shows_usage(runner: CliRunner):
    """The CLI should display usage information with --help and exit cleanly."""
    result = runner.invoke(cli, ["--help"])
    assert result.exit_code == 0, f"CLI exited with {result.exit_code}, output: {result.output}"
    # Click's help output always contains the word "Usage"
    assert "Usage" in result.output


def test_cli_invalid_command_returns_error(runner: CliRunner):
    """Invoking an unknown subcommand should result in a non‑zero exit code and an error message."""
    result = runner.invoke(cli, ["nonexistent-command"])
    # Click returns exit code 2 for usage errors
    assert result.exit_code != 0
    assert "No such command" in result.output or "Error" in result.output
