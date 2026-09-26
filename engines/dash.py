"""MPEG-DASH helpers for TIDAL OpenAPI track manifests.

The legacy playback endpoint returns an AAC manifest. Lossless audio is now a
DASH document delivered by ``openapi.tidal.com``. This module turns that XML
into ordered segment URLs and refuses DRM-protected representations.
"""

from __future__ import annotations

import math
import re
import xml.etree.ElementTree as ElementTree
from typing import Any
from urllib.parse import urljoin

_DURATION = re.compile(r"PT(?:(\d+(?:\.\d+)?)H)?(?:(\d+(?:\.\d+)?)M)?(?:(\d+(?:\.\d+)?)S)?")
_TEMPLATE = re.compile(r"\$(RepresentationID|Bandwidth|Number|Time)(?:%0(\d+)d)?\$")
_FLAC_ID = re.compile(r"FLAC(?:_[A-Z0-9]+)*,\d+,(\d{1,2})", re.IGNORECASE)
_MAX_SEGMENTS = 100_000


class DashManifestError(ValueError):
    """A DASH document could not be turned into playable audio URLs."""


class ProtectedDashError(DashManifestError):
    """The manifest is DRM-protected and must not be saved as audio."""


def _local_name(tag: str) -> str:
    """Return an XML tag without its namespace.

    Args:
        tag (str): Element tag, possibly Clark notation.

    Returns:
        str: Local tag name.
    """
    return tag.rsplit("}", 1)[-1]


def _strip_namespaces(root: ElementTree.Element) -> None:
    """Rewrite every tag in ``root`` to its local name.

    Args:
        root (ElementTree.Element): Parsed MPD element.
    """
    for element in root.iter():
        element.tag = _local_name(element.tag)


def _seconds(value: str | None) -> float | None:
    """Parse an ISO-8601 duration into seconds.

    Args:
        value (str | None): Duration such as ``PT3M1S``.

    Returns:
        float | None: Seconds, or None when ``value`` is empty or invalid.
    """
    if not value:
        return None
    match = _DURATION.fullmatch(value)
    if match is None:
        return None
    hours, minutes, seconds = match.groups()
    return (float(hours or 0) * 3600) + (float(minutes or 0) * 60) + float(seconds or 0)


def _integer(value: str | None) -> int | None:
    """Parse a decimal integer.

    Args:
        value (str | None): Numeric text.

    Returns:
        int | None: Parsed value, or None when it is not an integer.
    """
    if value is None or value == "":
        return None
    try:
        return int(value)
    except ValueError:
        return None


def _base_url(parent: str, node: ElementTree.Element) -> str:
    """Resolve a node's BaseURL against ``parent``.

    Args:
        parent (str): URL accumulated from ancestor elements.
        node (ElementTree.Element): MPD element that may contain BaseURL.

    Returns:
        str: Joined base URL.
    """
    child = node.find("BaseURL")
    if child is None or not child.text:
        return parent
    return urljoin(parent, child.text.strip())


def _expand_template(pattern: str, representation: ElementTree.Element, number: int, timestamp: int) -> str:
    """Substitute DASH segment-template identifiers.

    Args:
        pattern (str): ``initialization`` or ``media`` template.
        representation (ElementTree.Element): Representation element.
        number (int): Segment number (``$Number$``).
        timestamp (int): Segment time (``$Time$``).

    Returns:
        str: Concrete URL path or absolute URL.

    Raises:
        DashManifestError: The template expanded to an empty string.
    """
    values: dict[str, str] = {
        "RepresentationID": representation.get("id", ""),
        "Bandwidth": representation.get("bandwidth", ""),
        "Number": str(number),
        "Time": str(timestamp),
    }

    def replace(match: re.Match[str]) -> str:
        raw = values[match.group(1)]
        width = match.group(2)
        if width:
            return raw.zfill(int(width))
        return raw

    escaped = pattern.replace("$$", "\x00")
    result = _TEMPLATE.sub(replace, escaped).replace("\x00", "$")
    if not result:
        raise DashManifestError("Empty DASH segment URL.")
    return result


def _timeline(template: ElementTree.Element, duration: float | None, scale: int) -> list[int]:
    """Build segment timestamps from a SegmentTimeline or a fixed duration.

    Args:
        template (ElementTree.Element): SegmentTemplate element.
        duration (float | None): Period duration in seconds.
        scale (int): Timescale in ticks per second.

    Returns:
        list[int]: Presentation timestamps, one per media segment.

    Raises:
        DashManifestError: The timeline is missing, unbounded, or too large.
    """
    timeline = template.find("SegmentTimeline")
    timestamps: list[int] = []
    if timeline is not None:
        current = 0
        entries = list(timeline.findall("S"))
        for index, entry in enumerate(entries):
            current = int(entry.get("t", current))
            step = int(entry.get("d", "0"))
            if step <= 0:
                raise DashManifestError("Invalid DASH segment duration.")
            repeat = int(entry.get("r", "0"))
            if repeat < 0:
                following = entries[index + 1] if index + 1 < len(entries) else None
                end: int | None = None
                if following is not None and following.get("t"):
                    end = int(following.get("t", "0"))
                elif duration is not None:
                    end = int(duration * scale) + int(template.get("presentationTimeOffset", "0"))
                if end is None:
                    raise DashManifestError("Unbounded DASH timeline is not supported.")
                repeat = math.ceil((end - current) / step) - 1
            count = repeat + 1
            if count < 0 or len(timestamps) + count > _MAX_SEGMENTS:
                raise DashManifestError("Invalid or excessively large DASH timeline.")
            timestamps.extend(current + offset * step for offset in range(count))
            current += step * count
        return timestamps

    step_fixed = int(template.get("duration", "0"))
    if duration is not None and step_fixed > 0:
        count = math.ceil(duration * scale / step_fixed)
        if count > _MAX_SEGMENTS:
            raise DashManifestError("DASH timeline is too large.")
        return [offset * step_fixed for offset in range(count)]
    raise DashManifestError("DASH manifest has no finite segment timeline.")


def _bit_depth(representation: ElementTree.Element, adaptation: ElementTree.Element) -> int | None:
    """Read bit depth from attributes or a TIDAL representation id.

    Args:
        representation (ElementTree.Element): Representation element.
        adaptation (ElementTree.Element): Parent AdaptationSet.

    Returns:
        int | None: Bit depth when present.
    """
    raw = representation.get("audioBitDepth", adaptation.get("audioBitDepth", ""))
    parsed = _integer(raw)
    if parsed is not None:
        return parsed
    match = _FLAC_ID.fullmatch(representation.get("id", ""))
    if match is None:
        return None
    return int(match.group(1))


def dash_representations(content: str) -> list[dict[str, Any]]:
    """Return clear audio representations and their segment URLs.

    Args:
        content (str): MPEG-DASH MPD XML.

    Returns:
        list[dict[str, Any]]: One dict per audio representation. Each dict has
        ``urls``, ``id``, ``codec``, ``mime_type``, ``bandwidth``, ``sample_rate``,
        ``bit_depth``, and ``channels``.

    Raises:
        ProtectedDashError: Any ContentProtection element is present.
        DashManifestError: The document has no supported audio timeline.
    """
    try:
        root = ElementTree.fromstring(content)
    except ElementTree.ParseError as exc:
        raise DashManifestError("DASH manifest is not valid XML.") from exc
    _strip_namespaces(root)
    for element in root.iter():
        if element.tag == "ContentProtection":
            raise ProtectedDashError("DRM-protected DASH streams are not supported.")

    tracks: list[dict[str, Any]] = []
    presentation_duration = _seconds(root.get("mediaPresentationDuration"))
    for period in root.findall("Period"):
        duration = _seconds(period.get("duration"))
        if duration is None and presentation_duration is not None:
            duration = presentation_duration - (_seconds(period.get("start")) or 0)
        period_base = _base_url(_base_url("", root), period)
        for adaptation in period.findall("AdaptationSet"):
            adaptation_base = _base_url(period_base, adaptation)
            for representation in adaptation.findall("Representation"):
                media_type = representation.get("mimeType", adaptation.get("mimeType", ""))
                content_type = adaptation.get("contentType", "")
                if content_type != "audio" and not media_type.startswith("audio/"):
                    continue
                attrs: dict[str, str] = {}
                timeline_owner: ElementTree.Element | None = None
                for owner in (period, adaptation, representation):
                    template = owner.find("SegmentTemplate")
                    if template is None:
                        continue
                    attrs.update(template.attrib)
                    if template.find("SegmentTimeline") is not None:
                        timeline_owner = template
                template_node = timeline_owner
                if template_node is None:
                    for owner in (representation, adaptation, period):
                        found = owner.find("SegmentTemplate")
                        if found is not None:
                            template_node = found
                            break
                if template_node is None or not attrs.get("initialization") or not attrs.get("media"):
                    raise DashManifestError("DASH requires initialization and media segment templates.")
                prefix = _base_url(adaptation_base, representation)
                number = int(attrs.get("startNumber", "1"))
                scale = int(attrs.get("timescale", "1"))
                if scale <= 0:
                    raise DashManifestError("Invalid DASH timescale.")
                timestamps = _timeline(template_node, duration, scale)
                urls = [urljoin(prefix, _expand_template(attrs["initialization"], representation, number, 0))]
                urls.extend(
                    urljoin(prefix, _expand_template(attrs["media"], representation, number + index, timestamp))
                    for index, timestamp in enumerate(timestamps)
                )
                channel_node = representation.find("AudioChannelConfiguration")
                if channel_node is None:
                    channel_node = adaptation.find("AudioChannelConfiguration")
                channels = channel_node.get("value") if channel_node is not None else None
                tracks.append(
                    {
                        "urls": urls,
                        "id": representation.get("id", ""),
                        "codec": representation.get("codecs", adaptation.get("codecs", "")),
                        "mime_type": media_type,
                        "bandwidth": _integer(representation.get("bandwidth")),
                        "sample_rate": _integer(
                            representation.get("audioSamplingRate", adaptation.get("audioSamplingRate"))
                        ),
                        "bit_depth": _bit_depth(representation, adaptation),
                        "channels": _integer(channels),
                    }
                )
    if not tracks:
        raise DashManifestError("DASH manifest contains no supported audio representations.")
    return tracks


def _quality_key(representation: dict[str, Any]) -> tuple[int, int, int, int, int]:
    """Rank a representation by lossless codec, depth, rate, bandwidth, channels.

    Args:
        representation (dict[str, Any]): One entry from :func:`dash_representations`.

    Returns:
        tuple[int, int, int, int, int]: Sort key, highest fidelity last.
    """
    codec = str(representation.get("codec") or "").lower()
    lossless = int("flac" in codec or "alac" in codec)
    return (
        lossless,
        int(representation.get("bit_depth") or 0),
        int(representation.get("sample_rate") or 0),
        int(representation.get("bandwidth") or 0),
        int(representation.get("channels") or 0),
    )


def best_dash_representation(content: str) -> dict[str, Any]:
    """Select the highest-fidelity clear audio representation.

    Args:
        content (str): MPEG-DASH MPD XML.

    Returns:
        dict[str, Any]: Winning representation from :func:`dash_representations`.
    """
    return max(dash_representations(content), key=_quality_key)
