'''viento.config.loader

Utility functions for loading configuration files.

The original `load_config` function expects a valid TOML file path and will raise
`FileNotFoundError` if the file does not exist. In many usage scenarios a config
file is optional – the SDK can operate with built‑in defaults. To make the SDK
more tolerant we provide a thin wrapper `load_config_safe` that returns an empty
configuration dictionary when the file is missing.
'''  # noqa: D401

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional

import tomli

__all__ = ["load_config", "load_config_safe"]


def load_config(path: str) -> Dict[str, Any]:
    """Load a TOML configuration file.

    Parameters
    ----------
    path:
        Path to a TOML file.

    Returns
    -------
    dict
        Parsed configuration dictionary.
    """
    with open(path, "rb") as f:
        return tomli.load(f)


def load_config_safe(path: Optional[str] = None) -> Dict[str, Any]:
    """Safely load a configuration file.

    This helper returns an empty dictionary when the supplied ``path`` is ``None``
    or points to a non‑existent file, instead of raising ``FileNotFoundError``.
    When a valid path is provided the function delegates to :func:`load_config`.

    Parameters
    ----------
    path:
        Optional path to a TOML configuration file. If ``None`` the function
        behaves as if the file does not exist.

    Returns
    -------
    dict
        The parsed configuration if the file exists, otherwise an empty dict.
    """
    if not path:
        # No path supplied – treat as missing configuration.
        return {}

    # Resolve the path to handle user‑home shortcuts and relative paths.
    resolved_path = Path(path).expanduser().resolve()
    if not resolved_path.is_file():
        # File does not exist – return an empty configuration instead of raising.
        return {}

    # File exists – load it using the original loader.
    return load_config(str(resolved_path))
