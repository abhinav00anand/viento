from click.testing import CliRunner

from viento.cli.main import cli


def test_cli_invalid_command_exits_with_error():
    """Ensure the CLI exits with an error for unknown commands."""
    runner = CliRunner()
    result = runner.invoke(cli, ["foobar"])
    # Click returns exit code 2 for usage errors
    assert result.exit_code != 0, "CLI should exit with a non-zero code for unknown commands"
    # The output should contain an indication that the command is not recognized
    assert (
        "No such command" in result.output
        or "Error:" in result.output
    ), "CLI output should indicate an unknown command error"
