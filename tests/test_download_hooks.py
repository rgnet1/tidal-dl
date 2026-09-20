"""Web progress hooks on the downloader do not break a download when unused."""

from __future__ import annotations

from types import SimpleNamespace

from tidal_dl_ng.download import Download


def test_missing_hooks_are_ignored() -> None:
    host = SimpleNamespace(progress=SimpleNamespace(tasks={1: SimpleNamespace(percentage=15)}))
    Download._notify_chunk_progress(host, 1)
    Download._notify_item_finished(host)


def test_chunk_hook_receives_percent() -> None:
    seen: list[float] = []
    host = SimpleNamespace(
        progress=SimpleNamespace(tasks={1: SimpleNamespace(percentage=42.5)}),
        on_chunk_progress=seen.append,
    )
    Download._notify_chunk_progress(host, 1)
    assert seen == [42.5]


class _Boom(Exception):
    """Stand-in failure for hook and broadcast tests."""


def test_hook_errors_are_swallowed() -> None:
    def fail(_percent: float) -> None:
        raise _Boom

    host = SimpleNamespace(
        progress=SimpleNamespace(tasks={1: SimpleNamespace(percentage=1)}),
        on_chunk_progress=fail,
        on_item_finished=fail,
    )
    Download._notify_chunk_progress(host, 1)
    Download._notify_item_finished(host)
