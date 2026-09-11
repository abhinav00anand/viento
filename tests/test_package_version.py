import importlib.metadata


def test_package_version_consistency() -> None:
    """Ensure the package version reported by metadata matches __version__ if defined.

    The SDK may expose a ``__version__`` attribute. This test confirms that, when present,
    it aligns with the version declared in ``pyproject.toml`` (exposed via
    ``importlib.metadata.version``). This guards against accidental version drift.
    """
    # Retrieve the version from the installed package metadata.
    metadata_version = importlib.metadata.version("viento")
    assert isinstance(metadata_version, str) and metadata_version, "Metadata version should be a non‑empty string"

    # Attempt to import __version__ from the package; it may not be defined.
    try:
        from viento import __version__  # type: ignore
    except Exception:
        # If the attribute does not exist, the test only verifies that metadata provides a version.
        return

    # If __version__ exists, it must match the metadata version.
    assert __version__ == metadata_version, f"Package __version__ ({__version__}) does not match metadata version ({metadata_version})"
