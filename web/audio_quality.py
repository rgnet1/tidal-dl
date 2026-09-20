"""Per-track audio quality selection and queue badge labels for the web UI.

Mirrors the desktop GUI rule: when the user asks for hi-res, request the best
tier the track actually offers (24-bit when tagged, otherwise CD lossless).
"""

from __future__ import annotations

import logging
from typing import Any

from tidalapi import Album, Quality, Track

from tidal_dl_ng.helper.tidal import quality_audio_highest

QUALITY_RANK: dict[str, int] = {
    "LOW": 0,
    "HIGH": 1,
    "LOSSLESS": 2,
    "HI_RES_LOSSLESS": 3,
}

TIER_RANK: dict[str, int] = {
    "low": 0,
    "lossless": 1,
    "hi_res": 2,
}

BADGE_LABELS: dict[str, str] = {
    "hi_res": "Hi-Res",
    "lossless": "CD",
    "low": "Low",
}


def normalize_quality_name(value: Any) -> str:
    """Map tidalapi / tiddl quality strings onto LOW|HIGH|LOSSLESS|HI_RES_LOSSLESS.

    Args:
        value: Enum, string, or None.

    Returns:
        Canonical quality name. Unknown values become HIGH.
    """
    raw = getattr(value, "value", value)
    text = str(raw or "").strip().upper().replace("-", "_").replace(" ", "_")
    aliases = {
        "HI_RES": "HI_RES_LOSSLESS",
        "HIRES": "HI_RES_LOSSLESS",
        "HIRES_LOSSLESS": "HI_RES_LOSSLESS",
        "HI_RES_LOSSLESS": "HI_RES_LOSSLESS",
        "MAX": "HI_RES_LOSSLESS",
        "HIGH_LOSSLESS": "LOSSLESS",
        "LOSSLESS": "LOSSLESS",
        "NORMAL": "HIGH",
        "LOW": "LOW",
        "HIGH": "HIGH",
    }
    if text in aliases:
        return aliases[text]
    if "HI_RES" in text or "HIRES" in text:
        return "HI_RES_LOSSLESS"
    if "LOSSLESS" in text:
        return "LOSSLESS"
    return "HIGH"


def _tag_set(media: Any) -> set[str]:
    """Collect catalog quality tags from tidalapi or tiddl track objects."""
    found: set[str] = set()
    raw_tags = getattr(media, "media_metadata_tags", None)
    if raw_tags:
        for tag in raw_tags:
            token = getattr(tag, "value", tag)
            found.add(str(token).upper().replace("-", "_").replace(" ", "_"))
    metadata = getattr(media, "mediaMetadata", None)
    nested = getattr(metadata, "tags", None) if metadata is not None else None
    if nested:
        for tag in nested:
            found.add(str(tag).upper().replace("-", "_").replace(" ", "_"))
    return found


def catalog_highest_name(media: Any) -> str:
    """Best quality name advertised for a track or album.

    Args:
        media: tidalapi or tiddl media object.

    Returns:
        Canonical quality name.
    """
    if isinstance(media, Track | Album):
        try:
            return normalize_quality_name(quality_audio_highest(media))
        except Exception:
            logging.getLogger("tidal-dl-pro.web").debug("Could not read catalog quality", exc_info=True)

    tags = _tag_set(media)
    if any("HIRES_LOSSLESS" in tag or tag == "HI_RES_LOSSLESS" for tag in tags):
        return "HI_RES_LOSSLESS"
    if "LOSSLESS" in tags:
        return "LOSSLESS"

    audio_quality = getattr(media, "audioQuality", None) or getattr(media, "audio_quality", None)
    if audio_quality:
        return normalize_quality_name(audio_quality)
    return "HIGH"


def effective_quality_for_track(user_setting: str, media: Any) -> str:
    """Quality string to request for one track, capped by the user setting.

    Args:
        user_setting: Settings quality (LOW, HIGH, LOSSLESS, HI_RES_LOSSLESS).
        media: Track-like object used to read catalog tags.

    Returns:
        Canonical quality name to request from TIDAL.
    """
    user = normalize_quality_name(user_setting)
    if user in ("LOW", "HIGH"):
        return user
    highest = catalog_highest_name(media)
    if QUALITY_RANK.get(highest, 1) > QUALITY_RANK.get(user, 3):
        return user
    return highest


def effective_quality_enum(user_setting: str, media: Any) -> Quality:
    """Same as ``effective_quality_for_track`` as a tidalapi ``Quality``."""
    return Quality(effective_quality_for_track(user_setting, media))


def delivered_tier_label(raw: str) -> str:
    """Map a delivered stream quality string to a queue badge tier.

    Args:
        raw: TIDAL audioQuality or similar.

    Returns:
        ``hi_res``, ``lossless``, or ``low``.
    """
    name = normalize_quality_name(raw) if raw else "HIGH"
    if name == "HI_RES_LOSSLESS":
        return "hi_res"
    if name == "LOSSLESS":
        return "lossless"
    return "low"


def badge_label(tier: str | None) -> str:
    """Short UI label for a delivered tier.

    Args:
        tier: ``hi_res``, ``lossless``, or ``low``.

    Returns:
        Display text, or an empty string when unknown.
    """
    return BADGE_LABELS.get(str(tier or ""), "")


def summarize_delivery(user_setting: str, tiers: list[str], transcoded: bool) -> tuple[str, str | None]:
    """Pick the worst badge and one toast for a finished queue item.

    Args:
        user_setting: Quality the user asked for.
        tiers: Delivered tiers for one or more files.
        transcoded: True if any file was transcoded from lossy audio.

    Returns:
        ``(tier, notice)``. Tier defaults to ``low`` when ``tiers`` is empty.
    """
    if not tiers:
        return "low", quality_notice(user_setting, "low", transcoded)
    worst = min(tiers, key=lambda tier: TIER_RANK.get(tier, 0))
    return worst, quality_notice(user_setting, worst, transcoded)


def quality_notice(user_setting: str, delivered_tier: str, transcoded: bool) -> str | None:
    """User-facing note when the saved file is below the requested max.

    Args:
        user_setting: Quality the user asked for.
        delivered_tier: Badge tier of the file that was written.
        transcoded: True when AAC (or other lossy) was re-encoded to FLAC.

    Returns:
        Toast text, or None when nothing should be shown.
    """
    if transcoded:
        return "Highest quality available was lossy. Saved as FLAC (transcoded)."
    requested = delivered_tier_label(user_setting)
    if TIER_RANK.get(delivered_tier, 0) < TIER_RANK.get(requested, 0):
        if delivered_tier == "lossless":
            return "Highest quality available was CD lossless (16-bit), not hi-res."
        return "Downloaded below the requested quality."
    return None
