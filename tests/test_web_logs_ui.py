"""The queue log panel exposes copy only while lines are shown."""

from __future__ import annotations

from pathlib import Path


def test_copy_control_lives_inside_the_log_panel() -> None:
    html = Path("web/index.html").read_text(encoding="utf-8")
    panel_start = html.index('x-show="showLogPanel"')
    panel_end = html.index("Your queue is empty", panel_start)
    panel = html[panel_start:panel_end]
    assert "copyLogs()" in panel
    assert 'x-show="activityLogs.length"' in panel
    assert "No log lines yet" in panel
