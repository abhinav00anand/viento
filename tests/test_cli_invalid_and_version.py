from click.testing import CliRunner

import viento
from viento.cli.main import cli


def test_cli_unknown_command_shows_error():
    """CLI should return an error for unknown commands."""
    runner = CliRunner()
    result = runner.invoke(cli, ["foobar"])
    # Click returns exit code 2 for usage errors
    assert result.exit_code != 0
    assert "No such command" in result.output


def test_cli_version_flag_displays_version():
    """CLI should display the package version when --version is used."""
    runner = CliRunner()
    result = runner.invoke(cli, ["--version"])
    assert result.exit_code == 0
    # The version string should be present in output
    assert viento.__version__ in result.output
