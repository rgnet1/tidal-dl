"""Catalog quality labels for UI (search / library rows)."""

from __future__ import annotations

from typing import Any, Sequence


def _norm_tag(t: Any) -> str:
    return str(t).upper().replace(" ", "_").replace("-", "_")


def quality_badge_for_catalog_track(
    tags: Sequence[str] | None,
    audio_quality: str | None,
) -> str | None:
    """Short badge for the best format TIDAL advertises on this track.

    Uses catalog ``mediaMetadata.tags`` (and ``audioQuality`` as a fallback),
    not what a specific playback client will stream.
    """
    norm = {_norm_tag(x) for x in (tags or [])}
    aq = (str(audio_quality).strip().upper() if audio_quality else "") or ""

    if "HIRES_LOSSLESS" in norm or "HI_RES_LOSSLESS" in norm:
        return "Hi-Res"
    if "LOSSLESS" in norm:
        return "Lossless"
    if "DOLBY_ATMOS" in norm:
        return "Atmos"
    if any(t.startswith("SONY_360") for t in norm):
        return "360"
    if aq in ("HI_RES_LOSSLESS", "HI_RES", "HIRES"):
        return "Hi-Res"
    if aq == "LOSSLESS":
        return "Lossless"
    if aq == "HIGH":
        return "High"
    if aq == "LOW":
        return "Low"
    if aq:
        return aq.replace("_", " ").title()
    return None
