"""Album downloads keep folder grouping and track numbers."""

from __future__ import annotations

from web.engines.tiddl import _render_relpath
from web.unified_state import UnifiedSettings


def test_album_template_includes_folder_and_track_number() -> None:
    settings = UnifiedSettings()
    relative = _render_relpath(
        settings.format_album,
        {
            "album_artist": "Drake",
            "album_title": "Certified Lover Boy",
            "album_explicit": "",
            "track_volume_num_optional": "",
            "album_track_num": 7,
            "artist_name": "Drake",
            "track_title": "Love All",
        },
        "fallback",
    )
    assert relative.as_posix() == "Albums/Drake - Certified Lover Boy/7. Drake - Love All"


def test_single_track_template_is_not_used_for_albums() -> None:
    settings = UnifiedSettings()
    relative = _render_relpath(
        settings.format_track,
        {
            "artist_name": "Drake",
            "track_title": "Love All",
            "track_explicit": "",
        },
        "fallback",
    )
    assert relative.as_posix() == "Tracks/Drake - Love All"
    assert "7." not in relative.as_posix()
