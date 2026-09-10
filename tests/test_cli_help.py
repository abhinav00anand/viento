import pytest
from click.testing import CliRunner

from viento.cli.main import cli


@pytest.fixture
def runner():
    return CliRunner()

def test_cli_help_exits_successfully(runner):
    """Ensure the CLI displays help without errors."""
    result = runner.invoke(cli, ["--help"])
    # Click returns exit code 0 for successful help display
    assert result.exit_code == 0, f"CLI exited with {result.exit_code}: {result.output}"
    # Basic sanity check that the help output contains the command name
    assert "viento" in result.output.lower()
