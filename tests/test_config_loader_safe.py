'''Tests for the safe configuration loader introduced in
viento/config/loader.py.
'''  # noqa: D401

import tempfile
from pathlib import Path

from viento.config.loader import load_config_safe


def test_missing_file_returns_empty():
    """When the file does not exist, the loader should return an empty dict."""
    missing_path = "non_existent_config.toml"
    # Ensure the file truly does not exist.
    if Path(missing_path).exists():
        Path(missing_path).unlink()
    result = load_config_safe(missing_path)
    assert isinstance(result, dict)
    assert result == {}


def test_none_path_returns_empty():
    """Passing ``None`` should also yield an empty configuration dictionary."""
    result = load_config_safe(None)
    assert isinstance(result, dict)
    assert result == {}


def test_valid_file_is_parsed():
    """A valid TOML file should be parsed and returned unchanged."""
    toml_content = """
    [database]
    host = \"localhost\"
    port = 5432
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        cfg_path = Path(tmpdir) / "config.toml"
        cfg_path.write_text(toml_content, encoding="utf-8")
        result = load_config_safe(str(cfg_path))
        # Expected dictionary structure based on the TOML above.
        expected = {"database": {"host": "localhost", "port": 5432}}
        assert result == expected
