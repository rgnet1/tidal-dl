"""Tests for pasting TIDAL share links into search."""

from __future__ import annotations

from web.tidal_link import parse_tidal_link


def test_browse_track_link() -> None:
    assert parse_tidal_link("https://tidal.com/browse/track/12345678") == ("track", "12345678")


def test_listen_album_link_with_share_suffix() -> None:
    assert parse_tidal_link("https://listen.tidal.com/album/998877/u") == ("album", "998877")


def test_playlist_link_strips_query() -> None:
    url = "https://tidal.com/browse/playlist/aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee?u"
    assert parse_tidal_link(url) == ("playlist", "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee")


def test_link_without_scheme() -> None:
    assert parse_tidal_link("tidal.com/browse/artist/42") == ("artist", "42")


def test_plain_search_text_is_not_a_link() -> None:
    assert parse_tidal_link("daft punk") is None


def test_mix_query_param() -> None:
    assert parse_tidal_link("https://listen.tidal.com/view/pages/mix?mixId=001abc") == ("mix", "001abc")


def test_empty_and_unrelated_text() -> None:
    assert parse_tidal_link("") is None
    assert parse_tidal_link("https://example.com/album/1") is None


def test_video_link() -> None:
    assert parse_tidal_link("https://tidal.com/browse/video/555") == ("video", "555")


def test_link_embedded_in_a_sentence() -> None:
    text = "please grab https://www.tidal.com/browse/track/77 thanks"
    assert parse_tidal_link(text) == ("track", "77")
