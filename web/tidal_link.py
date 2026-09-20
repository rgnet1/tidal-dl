"""Parse TIDAL share links pasted into the web search bar."""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import parse_qs, urlparse

_MEDIA_TYPES = ("track", "video", "album", "playlist", "mix", "artist")
_SKIP_SEGMENTS = {"browse", "u", "view", "pages", "w"}
_URL_RE = re.compile(
    r"(https?://[^\s<>\"']+|(?:www\.)?(?:listen\.)?tidal\.com/[^\s<>\"']+)",
    re.IGNORECASE,
)


def parse_tidal_link(query: str) -> tuple[str, str] | None:
    """Extract a media type and id from a TIDAL URL.

    Accepts listen.tidal.com and tidal.com share links, including ``/browse/``
    paths, a trailing ``/u``, and query strings. Plain search text returns None.

    Args:
        query: Raw search-bar text.

    Returns:
        ``(media_type, media_id)`` or None when the text is not a TIDAL link.
    """
    raw = _tidal_url(query)
    if raw is None:
        return None
    parsed = urlparse(raw)
    if "tidal.com" not in parsed.netloc.lower():
        return None
    return _media_from_url(parsed)


def _tidal_url(query: str) -> str | None:
    """Return a normalized TIDAL URL, or None when the text is not a link."""
    text = str(query or "").strip()
    if not text:
        return None
    if text.endswith("/u") or text.endswith("?u"):
        text = text[:-2]
    match = _URL_RE.search(text)
    if match is None:
        return None
    raw = match.group(1).rstrip(").,;")
    if not raw.lower().startswith("http"):
        raw = "https://" + raw
    return raw


def _media_from_url(parsed: Any) -> tuple[str, str] | None:
    """Read a media type and id from a parsed TIDAL URL."""
    media_type, media_id = _media_from_path(parsed.path)
    if media_id is None:
        media_type, media_id = _media_from_query(parsed)
    if not media_type or not media_id:
        return None
    media_id = media_id.split("?")[0].strip()
    if not media_id or media_id.lower() in _SKIP_SEGMENTS:
        return None
    return media_type, media_id


def _media_from_path(path: str) -> tuple[str | None, str | None]:
    """Return the first media type and id found in a URL path."""
    segments = [part for part in path.split("/") if part and part.lower() not in _SKIP_SEGMENTS]
    for index, segment in enumerate(segments):
        kind = segment.lower()
        if kind in _MEDIA_TYPES and index + 1 < len(segments):
            return kind, segments[index + 1]
    return None, None


def _media_from_query(parsed: Any) -> tuple[str | None, str | None]:
    """Return a mix or track id carried in the query string."""
    params = {key.lower(): values for key, values in parse_qs(parsed.query).items()}
    segments = {segment.lower() for segment in parsed.path.split("/") if segment}
    if "mix" in segments or "mixid" in params:
        return "mix", _first(params, "id", "mixid")
    if "trackid" in params:
        return "track", _first(params, "trackid")
    return None, None


def _first(params: dict[str, list[str]], *keys: str) -> str | None:
    for key in keys:
        values = params.get(key) or []
        if values and values[0].strip():
            return values[0].strip()
    return None
