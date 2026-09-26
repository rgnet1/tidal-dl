"""Import hyphenated engine folders as normal Python modules."""

from __future__ import annotations

import importlib.abc
import importlib.machinery
import importlib.util
import sys
from pathlib import Path

_ENGINE_MODULES: dict[str, str] = {
    "engines.tidal_dl_pro": "tidal-dl-pro",
    "engines.tidal_dl": "tidal-dl",
}


class _HyphenEngineFinder(importlib.abc.MetaPathFinder):
    """Import ``engines/<hyphen-name>/`` as ``engines.<underscore_name>``."""

    def find_spec(
        self,
        fullname: str,
        path: object = None,
        target: object = None,
    ) -> importlib.machinery.ModuleSpec | None:
        """Return a module spec for a known engine folder.

        Args:
            fullname: Dotted module name being imported.
            path: Parent package search path. Unused; engines are loaded by folder name.
            target: Existing module object, when reloading. Unused.

        Returns:
            A spec for the engine package, or None when ``fullname`` is not an engine.
        """
        folder = _ENGINE_MODULES.get(fullname)
        if folder is None:
            return None
        del path, target
        init = Path(__file__).resolve().parent / folder / "__init__.py"
        loader = importlib.machinery.SourceFileLoader(fullname, str(init))
        return importlib.util.spec_from_loader(fullname, loader, origin=str(init))


def _prefer_vendored_engines() -> None:
    """Put each engine's own source tree ahead of site-packages.

    ``engines/tidal-dl-pro/tidal_dl_ng`` and ``engines/tidal-dl/tiddl`` stay
    importable as ``tidal_dl_ng`` and ``tiddl``.
    """
    root = Path(__file__).resolve().parent
    for folder in ("tidal-dl-pro", "tidal-dl"):
        entry = str(root / folder)
        if entry not in sys.path:
            sys.path.insert(0, entry)


def install_engine_finder() -> None:
    """Register the hyphen-folder finder once per process."""
    _prefer_vendored_engines()
    if any(isinstance(finder, _HyphenEngineFinder) for finder in sys.meta_path):
        return
    sys.meta_path.append(_HyphenEngineFinder())
