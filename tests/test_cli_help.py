from click.testing import CliRunner

from viento.cli.main import cli


def test_cli_help_shows_usage():
    """Ensure the CLI loads and displays the help message without errors."""
    runner = CliRunner()
    result = runner.invoke(cli, ["--help"])
    # The command should exit cleanly
    assert result.exit_code == 0, f"CLI exited with non-zero code: {result.exit_code}\n{result.output}"
    # Click's help output always contains a 'Usage:' section
    assert "Usage:" in result.output
    # Optionally, check that the command name appears in the help output
    assert "viento" in result.output.lower()
