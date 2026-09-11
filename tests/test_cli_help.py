import pytest
from click.testing import CliRunner

from viento.cli.main import cli


@pytest.fixture
def runner():
    return CliRunner()

def test_cli_help_exits_successfully(runner: CliRunner):
    """The CLI should display help and exit with code 0 when invoked with --help."""
    result = runner.invoke(cli, ["--help"])
    # Ensure the command completed successfully
    assert result.exit_code == 0, f"CLI exited with non‑zero code: {result.exit_code}\n{result.output}"
    # Basic sanity check that help text is present
    assert "Usage" in result.output
    assert "Options" in result.output
