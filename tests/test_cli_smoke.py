import pytest
from click.testing import CliRunner

from viento.cli.main import cli


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


def test_cli_help(runner: CliRunner) -> None:
    result = runner.invoke(cli, ["--help"])
    assert result.exit_code == 0
    assert "Usage:" in result.output


def test_cli_version(runner: CliRunner) -> None:
    result = runner.invoke(cli, ["--version"])
    assert result.exit_code == 0
    # The version output should contain the package name or version number
    assert "viento" in result.output.lower()
