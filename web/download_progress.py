"""Turn per-chunk and per-track events into a throttled album progress percent."""

from __future__ import annotations

import threading
import time
from collections.abc import Callable


class AlbumProgress:
    """Combine finished tracks and in-flight byte progress into one percentage.

    Attributes:
        total: Number of tracks in the album. ``0`` means a single item.
    """

    def __init__(self, emit: Callable[[float], None], *, min_interval_sec: float = 0.25) -> None:
        """Create a progress combiner.

        Args:
            emit: Called with a percentage from 0 to 99 while work is in progress.
            min_interval_sec: Minimum time between non-forced updates.
        """
        self._emit_cb = emit
        self._min_interval_sec = min_interval_sec
        self._lock = threading.Lock()
        self._last_emit = 0.0
        self.total = 0
        self.done = 0
        self._inflight: dict[int, float] = {}

    def set_total(self, total: int) -> None:
        """Set how many tracks the album (or playlist) contains.

        Args:
            total: Track count. Values below 1 disable album weighting.
        """
        with self._lock:
            self.total = max(0, int(total))
            self.done = 0
            self._inflight.clear()

    def chunk(self, thread_id: int, track_percent: float) -> None:
        """Record byte progress for a single track. Ignored during album downloads.

        Args:
            thread_id: Worker thread identity.
            track_percent: Current track progress, 0-100.
        """
        if self.total:
            return
        fraction = max(0.0, min(1.0, float(track_percent) / 100.0))
        with self._lock:
            self._inflight[thread_id] = fraction
        self._publish(force=False)

    def song_finished(self) -> tuple[float, int, int]:
        """Advance album progress by one completed song.

        Returns:
            ``(percent, songs_done, songs_total)``. Percent stays under 100.
        """
        with self._lock:
            if self.total:
                self.done = min(self.total, self.done + 1)
            done = self.done
            total = self.total
        percent = self.percent()
        self._publish(force=True)
        return percent, done, total

    def item_finished(self, thread_id: int) -> None:
        """Mark one in-flight single-track download complete.

        Args:
            thread_id: Worker thread identity used in ``chunk``.
        """
        if self.total:
            self.song_finished()
            return
        with self._lock:
            self._inflight.pop(thread_id, None)
        self._publish(force=True)

    def percent(self) -> float:
        """Current percentage. Albums count finished songs only."""
        with self._lock:
            if self.total > 0:
                raw = self.done / self.total * 100.0
            elif self._inflight:
                raw = max(self._inflight.values()) * 100.0
            else:
                raw = 0.0
        return max(0.0, min(99.0, raw))

    def _publish(self, *, force: bool) -> None:
        now = time.monotonic()
        with self._lock:
            if not force and (now - self._last_emit) < self._min_interval_sec:
                return
            self._last_emit = now
        self._emit_cb(self.percent())
