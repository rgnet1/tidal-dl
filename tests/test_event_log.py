"""Activity log buffer used by the queue panel."""

from __future__ import annotations

import logging
from collections.abc import Iterator

import pytest

from web import event_log


@pytest.fixture(autouse=True)
def _reset_log_buffer() -> Iterator[None]:
    event_log.clear()
    event_log.set_broadcast(None)
    yield
    event_log.clear()
    event_log.set_broadcast(None)


class _Boom(Exception):
    """Stand-in failure for broadcast tests."""


def test_append_list_and_clear() -> None:
    event_log.append("info", "Downloaded item 'Love All'", source="download")
    event_log.append("error", "rate limit")
    rows = event_log.list_entries(limit=10)
    assert [row["level"] for row in rows] == ["info", "error"]
    assert "Love All" in rows[0]["message"]
    event_log.clear()
    assert event_log.list_entries() == []


def test_blank_message_is_kept() -> None:
    entry = event_log.append("warning", "   ")
    assert entry["message"] == "(empty message)"


def test_broadcast_failure_does_not_drop_the_line() -> None:
    def fail(_payload: dict[str, object]) -> None:
        raise _Boom

    event_log.set_broadcast(fail)
    event_log.append("info", "still stored")
    assert event_log.list_entries()[-1]["message"] == "still stored"


def test_handler_copies_download_logger_records() -> None:
    handler = event_log.WebUiLogHandler()
    handler.setFormatter(logging.Formatter("%(message)s"))
    logger = logging.getLogger("tidal_dl_ng.download")
    previous_level = logger.level
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    try:
        logger.info("Downloaded item 'In The Bible'")
    finally:
        logger.removeHandler(handler)
        logger.setLevel(previous_level)
    assert any("In The Bible" in row["message"] for row in event_log.list_entries())
