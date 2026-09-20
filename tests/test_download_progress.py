"""Album progress advances once per finished song, not per downloaded byte."""

from __future__ import annotations

from web.download_progress import AlbumProgress


def test_album_progress_steps_once_per_song() -> None:
    seen: list[float] = []
    progress = AlbumProgress(seen.append, min_interval_sec=0)
    progress.set_total(4)
    progress.chunk(1, 100)
    assert seen == []
    percent, done, total = progress.song_finished()
    assert (percent, done, total) == (25.0, 1, 4)
    assert seen[-1] == 25.0
    progress.song_finished()
    assert seen[-1] == 50.0


def test_single_item_uses_byte_percent() -> None:
    seen: list[float] = []
    progress = AlbumProgress(seen.append, min_interval_sec=0)
    progress.chunk(7, 40)
    assert seen[-1] == 40.0


def test_finished_album_stays_under_100() -> None:
    seen: list[float] = []
    progress = AlbumProgress(seen.append, min_interval_sec=0)
    progress.set_total(2)
    progress.song_finished()
    percent, done, total = progress.song_finished()
    progress.song_finished()
    assert (percent, done, total) == (99.0, 2, 2)
    assert seen[-1] == 99.0
    assert progress.done == 2


def test_album_item_finished_counts_a_song() -> None:
    seen: list[float] = []
    progress = AlbumProgress(seen.append, min_interval_sec=0)
    progress.set_total(4)
    progress.item_finished(3)
    assert progress.done == 1
    assert seen[-1] == 25.0


def test_byte_updates_are_throttled_for_a_single_track() -> None:
    seen: list[float] = []
    progress = AlbumProgress(seen.append, min_interval_sec=60)
    progress.chunk(1, 10)
    progress.chunk(1, 80)
    assert seen == [10.0]
