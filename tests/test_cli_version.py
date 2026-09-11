import importlib

from click.testing import CliRunner

# Import the CLI entry point defined with Click
from viento.cli.main import cli


def test_cli_version_flag_shows_correct_version():
    """Ensure the ``--version`` flag exits cleanly and reports the package version.

    The CLI is expected to expose a ``--version`` option that prints the
    package name and version (e.g., ``viento, version 0.4.0``). This test
    confirms that behaviour and that the reported version matches the value
    defined in the package's ``__init__``.
    """
    runner = CliRunner()
    result = runner.invoke(cli, ["--version"])

    # The command should succeed without errors.
    assert result.exit_code == 0, f"CLI exited with {result.exit_code}: {result.output}"

    # Load the package version dynamically to avoid hard‑coding.
    viento_pkg = importlib.import_module("viento")
    expected_version = getattr(viento_pkg, "__version__", None)
    assert expected_version is not None, "Package does not expose __version__"

    # The output should contain the package name and version string.
    output_lower = result.output.lower()
    assert "viento" in output_lower, "Output does not contain package name"
    assert expected_version in output_lower, f"Output does not contain expected version {expected_version}"
