import importlib
import pkgutil


def iter_submodules(package):
    """Yield fully‑qualified names of all submodules in *package* recursively."""
    for _, name, is_pkg in pkgutil.iter_modules(package.__path__, package.__name__ + "."):
        yield name
        if is_pkg:
            sub_pkg = importlib.import_module(name)
            yield from iter_submodules(sub_pkg)


def test_all_viento_submodules_importable():
    """Sanity test that every submodule of the `viento` package can be imported.

    This catches import‑time errors such as missing optional dependencies or
    accidental runtime code execution during module import.
    """
    import viento

    for module_name in iter_submodules(viento):
        mod = importlib.import_module(module_name)
        # The import itself should not raise; the module object must be truthy.
        assert mod is not None, f"Failed to import {module_name}"
