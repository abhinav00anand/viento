from click.testing import CliRunner

from viento import __version__
from viento.cli.main import cli


def test_cli_version_flag():
    """The CLI should exit with code 0 and print the package version when --version is used."""
    runner = CliRunner()
    result = runner.invoke(cli, ["--version"])
    assert result.exit_code == 0, f"CLI exited with {result.exit_code}, output: {result.output}"
    # The version string should appear in the output (exact format may vary, so we check containment)
    assert __version__ in result.output, f"Version {__version__} not found in output: {result.output}"


def test_cli_unknown_command():
    """Invoking an undefined subcommand should result in a non-zero exit code and an error message."""
    runner = CliRunner()
    result = runner.invoke(cli, ["nonexistentcommand"])
    # Click returns exit code 2 for usage errors
    assert result.exit_code != 0, "CLI should fail for unknown commands"
    # Ensure the error message mentions the unknown command
    assert "No such command" in result.output or "Error" in result.output
