"""Ring buffer of recent log lines for the web UI (downloads, rate limits, errors)."""

from __future__ import annotations

import logging
import threading
from collections import deque
from collections.abc import Callable
from contextlib import suppress
from datetime import UTC, datetime
from typing import Any

MAX_LOG_ENTRIES = 500

_lock = threading.Lock()
_entries: deque[dict[str, Any]] = deque(maxlen=MAX_LOG_ENTRIES)
_broadcast: Callable[[dict[str, Any]], Any] | None = None

# Loggers whose records are mirrored into the UI log panel.
_UI_LOG_LOGGER_NAMES = (
    "tidal-dl-pro.web",
    "tidal-dl-pro.web.tdlng",
    "tidal-dl-pro.web.tiddl",
    "tidal_dl_ng.download",
    "tidal_dl_ng.helper.tidal",
)


def set_broadcast(callback: Callable[[dict[str, Any]], Any] | None) -> None:
    """Register WebSocket broadcast used for live log lines."""
    global _broadcast
    _broadcast = callback


def append(level: str, message: str, *, source: str | None = None) -> dict[str, Any]:
    """Append one log line and optionally push it to connected browsers."""
    text = str(message or "").strip()
    if not text:
        text = "(empty message)"
    entry: dict[str, Any] = {
        "ts": datetime.now(UTC).isoformat(),
        "level": str(level or "info").lower(),
        "message": text,
        "source": source,
    }
    with _lock:
        _entries.append(entry)
    if _broadcast is not None:
        with suppress(Exception):
            _broadcast({"type": "log", **entry})
    return entry


def list_entries(limit: int = 200) -> list[dict[str, Any]]:
    """Return the most recent log entries (oldest first within the window)."""
    cap = max(1, min(MAX_LOG_ENTRIES, int(limit)))
    with _lock:
        rows = list(_entries)
    return rows[-cap:]


def clear() -> None:
    """Remove all buffered log lines."""
    with _lock:
        _entries.clear()


class WebUiLogHandler(logging.Handler):
    """Copy selected application log records into the UI log buffer."""

    def emit(self, record: logging.LogRecord) -> None:
        try:
            message = self.format(record)
            append(record.levelname, message, source=record.name)
        except Exception:
            self.handleError(record)


def install_ui_log_handler() -> WebUiLogHandler:
    """Attach the UI handler to download/TIDAL loggers (idempotent)."""
    handler = WebUiLogHandler()
    handler.setLevel(logging.INFO)
    handler.setFormatter(logging.Formatter("%(message)s"))
    for name in _UI_LOG_LOGGER_NAMES:
        log = logging.getLogger(name)
        if handler not in log.handlers:
            log.addHandler(handler)
        if log.level == logging.NOTSET:
            log.setLevel(logging.INFO)
    return handler
