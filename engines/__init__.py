"""Download engine.

Hyphenated folders (``engines/tidal-dl-pro``, ``engines/tidal-dl``) are imported
as ``engines.tidal_dl_pro`` and ``engines.tidal_dl``.
"""

from __future__ import annotations

from engines._load import install_engine_finder
from engines.base import Engine

install_engine_finder()

__all__ = ["Engine"]
