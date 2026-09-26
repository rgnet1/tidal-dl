"""TIDAL OpenAPI v2 track manifests.

``GET /v1/tracks/{id}/playbackinfopostpaywall`` still answers, but it only
returns AAC (``mp4a.40.2``) even when the client asks for LOSSLESS. Hi-res and
CD-quality FLAC moved to ``https://openapi.tidal.com/v2/trackManifests/{id}``.
"""

from __future__ import annotations

import base64
import binascii
import logging
import time
from dataclasses import dataclass
from typing import Any

import requests

from engines.dash import DashManifestError, ProtectedDashError, best_dash_representation

logger = logging.getLogger("engines.track_manifest")

OPENAPI_TRACK_MANIFEST = "https://openapi.tidal.com/v2/trackManifests/{track_id}"
REQUEST_TIMEOUT_SEC = 45
_USAGES: tuple[str, ...] = ("DOWNLOAD", "PLAYBACK")
_RETRYABLE_STATUS = frozenset({403, 404, 405})
_LOSSLESS_QUALITIES = frozenset({"LOSSLESS", "HI_RES_LOSSLESS", "HI_RES", "HIRES_LOSSLESS"})


class TrackManifestError(Exception):
    """The OpenAPI track manifest could not be turned into audio URLs."""

    def __init__(self, message: str, status_code: int | None = None, error_codes: tuple[str, ...] = ()) -> None:
        """Store the HTTP status and TIDAL error codes alongside the message.

        Args:
            message (str): Human-readable failure.
            status_code (int | None): HTTP status, when the failure came from HTTP.
            error_codes (tuple[str, ...]): Codes from the JSON:API ``errors`` array.
        """
        super().__init__(message)
        self.status_code = status_code
        self.error_codes = error_codes


@dataclass
class AudioStreamManifest:
    """Segment list produced from an OpenAPI DASH manifest.

    Duck-types the fields ``tidal_dl_ng.download`` reads from tidalapi's
    ``StreamManifest``: ``get_urls``, ``is_encrypted``, ``codecs``,
    ``file_extension``, and ``encryption_key``.
    """

    urls: list[str]
    codecs: str
    file_extension: str
    audio_quality: str
    encryption_key: str | None = None
    sample_rate: int | None = None
    bit_depth: int | None = None

    def get_urls(self) -> list[str]:
        """Return media segment URLs, initialization segment first.

        Returns:
            list[str]: Absolute segment URLs in decode order.
        """
        return self.urls

    @property
    def is_encrypted(self) -> bool:
        """Whether the bytes need the legacy TIDAL decryption step.

        Returns:
            bool: Always False for OpenAPI clear DASH audio.
        """
        return self.encryption_key is not None


def quality_name(quality: object) -> str:
    """Normalize a tidalapi quality enum or plain string.

    Args:
        quality (object): ``Quality`` member or a quality name.

    Returns:
        str: Uppercase quality token such as ``HI_RES_LOSSLESS``.
    """
    value = getattr(quality, "value", quality)
    return str(value).strip().upper()


def uses_openapi_manifest(quality: object, atmos: bool = False) -> bool:
    """Whether this request must use the v2 track-manifest endpoint.

    Args:
        quality (object): Requested audio quality.
        atmos (bool): Dolby Atmos was requested for this track.

    Returns:
        bool: True for Atmos and for any lossless tier.
    """
    if atmos:
        return True
    return quality_name(quality) in _LOSSLESS_QUALITIES


def formats_for_quality(quality: object, atmos: bool = False) -> list[str]:
    """Map a quality choice onto OpenAPI ``formats`` query values.

    Args:
        quality (object): Requested audio quality.
        atmos (bool): Request Dolby Atmos (``EAC3_JOC``) instead of FLAC.

    Returns:
        list[str]: Formats in preference order. Hi-res lists FLAC last so a
        403 on the hi-res format can be retried as CD-quality FLAC.
    """
    if atmos:
        return ["EAC3_JOC"]
    name = quality_name(quality)
    if name in {"HI_RES_LOSSLESS", "HI_RES", "HIRES_LOSSLESS"}:
        return ["FLAC_HIRES", "FLAC"]
    return ["FLAC"]


def _error_codes(payload: object) -> tuple[str, ...]:
    """Collect error codes from a JSON:API or legacy TIDAL error body.

    Args:
        payload (object): Decoded JSON body.

    Returns:
        tuple[str, ...]: Codes, possibly empty.
    """
    if not isinstance(payload, dict):
        return ()
    codes: list[str] = []
    errors = payload.get("errors")
    if isinstance(errors, list):
        for item in errors:
            if not isinstance(item, dict):
                continue
            code = item.get("code") or item.get("error")
            if code:
                codes.append(str(code))
    sub_status = payload.get("subStatus")
    if sub_status:
        codes.append(str(sub_status))
    return tuple(codes)


def _retryable(error: TrackManifestError) -> bool:
    """Whether another usage or format might still succeed.

    Args:
        error (TrackManifestError): Failure from one manifest attempt.

    Returns:
        bool: True for usage-specific 403/404/405 that are not entitlement blocks.
    """
    if "CLIENT_NOT_ENTITLED" in error.error_codes:
        return False
    if "PREREQUISITE_MISSING" in error.error_codes:
        return True
    return error.status_code in _RETRYABLE_STATUS


def _decode_data_uri(uri: str) -> str:
    """Decode a ``data:...;base64,`` manifest URI.

    Args:
        uri (str): Value of ``attributes.uri``.

    Returns:
        str: UTF-8 MPD document.

    Raises:
        TrackManifestError: The URI is missing, not base64, or not UTF-8.
    """
    if "," not in uri:
        raise TrackManifestError("Stream manifest is empty.")
    header, payload = uri.split(",", 1)
    if ";base64" not in header.lower():
        raise TrackManifestError("Stream manifest encoding is unsupported.")
    try:
        return base64.b64decode(payload, validate=True).decode("utf-8")
    except (binascii.Error, ValueError, UnicodeDecodeError) as exc:
        raise TrackManifestError("Stream manifest is invalid.") from exc


def _extension_for(codec: str, mime_type: str) -> str:
    """Choose a filename suffix for a DASH representation.

    Args:
        codec (str): Representation codecs attribute.
        mime_type (str): Representation MIME type.

    Returns:
        str: ``.flac`` for a raw FLAC file, otherwise ``.m4a``.
    """
    codec_text = codec.lower()
    mime_text = mime_type.lower()
    if "flac" in codec_text and "mp4" not in mime_text and "m4a" not in mime_text:
        return ".flac"
    return ".m4a"


def _quality_from_formats(formats: list[str], codec: str) -> str:
    """Label the stream that TIDAL actually returned.

    Args:
        formats (list[str]): ``attributes.formats`` from the manifest.
        codec (str): Selected representation codec.

    Returns:
        str: ``HI_RES_LOSSLESS``, ``LOSSLESS``, ``DOLBY_ATMOS``, or empty.
    """
    available = {item.upper() for item in formats}
    if "FLAC_HIRES" in available:
        return "HI_RES_LOSSLESS"
    if "FLAC" in available or "flac" in codec.lower():
        return "LOSSLESS"
    if "EAC3_JOC" in available or "eac3" in codec.lower() or "ec-3" in codec.lower():
        return "DOLBY_ATMOS"
    return ""


def _codec_label(codec: str) -> str:
    """Map a DASH codec string onto the labels the downloader already checks.

    Args:
        codec (str): Representation codecs attribute.

    Returns:
        str: ``FLAC``, ``EAC3``, or the original codec uppercased.
    """
    text = codec.lower()
    if "flac" in text:
        return "FLAC"
    if "eac3" in text or "ec-3" in text:
        return "EAC3"
    if text.startswith("mp4a"):
        return "MP4A"
    return codec.upper()


def _manifest_from_attributes(attributes: dict[str, Any]) -> AudioStreamManifest:
    """Parse JSON:API manifest attributes into segment URLs.

    Args:
        attributes (dict[str, Any]): ``data.attributes`` object.

    Returns:
        AudioStreamManifest: Clear audio segments.

    Raises:
        TrackManifestError: The manifest is empty, protected, or not lossless/Atmos.
        ProtectedDashError: Re-raised as part of format fallback by the caller.
    """
    uri = str(attributes.get("uri") or "")
    xml = _decode_data_uri(uri)
    representation = best_dash_representation(xml)
    formats_raw = attributes.get("formats") or []
    formats = [str(item) for item in formats_raw] if isinstance(formats_raw, list) else []
    codec = str(representation.get("codec") or "")
    audio_quality = _quality_from_formats(formats, codec)
    if not audio_quality:
        raise TrackManifestError("Lossless FLAC stream is not available for this track.")
    urls = [str(url) for url in representation["urls"]]
    if not urls:
        raise TrackManifestError("Lossless FLAC manifest did not contain segment URLs.")
    mime_type = str(representation.get("mime_type") or "")
    return AudioStreamManifest(
        urls=urls,
        codecs=_codec_label(codec),
        file_extension=_extension_for(codec, mime_type),
        audio_quality=audio_quality,
        sample_rate=representation.get("sample_rate"),
        bit_depth=representation.get("bit_depth"),
    )


def _fetch_once(access_token: str, track_id: int, formats: list[str], usage: str) -> dict[str, Any]:
    """Request one manifest document.

    Args:
        access_token (str): User bearer token.
        track_id (int): TIDAL track id.
        formats (list[str]): OpenAPI format tokens.
        usage (str): ``DOWNLOAD`` or ``PLAYBACK``.

    Returns:
        dict[str, Any]: ``data.attributes``.

    Raises:
        TrackManifestError: HTTP failure, invalid JSON, or a missing document.
    """
    params: list[tuple[str, str]] = [
        ("manifestType", "MPEG_DASH"),
        ("uriScheme", "DATA"),
        ("usage", usage),
        ("adaptive", "false"),
    ]
    for item in formats:
        params.append(("formats", item))
    url = OPENAPI_TRACK_MANIFEST.format(track_id=track_id)
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/vnd.api+json",
    }
    response: requests.Response | None = None
    try:
        response = requests.get(url, headers=headers, params=params, timeout=REQUEST_TIMEOUT_SEC)
        if response.status_code == 429:
            delay = 1.0
            retry_after = response.headers.get("Retry-After")
            if retry_after and retry_after.isdigit():
                delay = min(float(retry_after), 5.0)
            response.close()
            response = None
            time.sleep(delay)
            response = requests.get(url, headers=headers, params=params, timeout=REQUEST_TIMEOUT_SEC)
        if response.status_code != 200:
            payload: object = {}
            try:
                payload = response.json()
            except ValueError:
                payload = {}
            codes = _error_codes(payload)
            raise TrackManifestError(
                f"Track manifest request failed (HTTP {response.status_code}).",
                status_code=response.status_code,
                error_codes=codes,
            )
        try:
            data = response.json()
        except ValueError as exc:
            raise TrackManifestError("Track manifest request returned invalid JSON.", response.status_code) from exc
    finally:
        if response is not None:
            response.close()
    if not isinstance(data, dict):
        raise TrackManifestError("Track manifest request returned an invalid payload.")
    attributes = data.get("data", {})
    if isinstance(attributes, dict):
        attributes = attributes.get("attributes")
    if not isinstance(attributes, dict):
        raise TrackManifestError("Track manifest response attributes are missing.")
    return attributes


def fetch_audio_manifest(
    access_token: str,
    track_id: int,
    quality: object,
    atmos: bool = False,
) -> AudioStreamManifest:
    """Download a clear FLAC or Atmos manifest for one track.

    Tries ``DOWNLOAD`` before ``PLAYBACK``. A hi-res request that TIDAL rejects
    or protects is retried as CD-quality FLAC. Preview-only documents are not
    returned. The legacy playback endpoint is not used: it no longer yields FLAC.

    Args:
        access_token (str): User bearer token. Not logged.
        track_id (int): TIDAL track id.
        quality (object): Requested quality (``LOSSLESS`` or ``HI_RES_LOSSLESS``).
        atmos (bool): Request ``EAC3_JOC`` instead of FLAC.

    Returns:
        AudioStreamManifest: Segment URLs and the quality TIDAL delivered.

    Raises:
        TrackManifestError: Every usage and format was rejected or unusable.
    """
    if not access_token:
        raise TrackManifestError("Missing access token for track manifest request.")
    formats = formats_for_quality(quality, atmos=atmos)
    format_attempts = [formats]
    if len(formats) > 1:
        format_attempts.append(formats[-1:])

    last_error: TrackManifestError | None = None
    for usage in _USAGES:
        for attempt_formats in format_attempts:
            try:
                attributes = _fetch_once(access_token, track_id, attempt_formats, usage)
            except TrackManifestError as exc:
                last_error = exc
                if not _retryable(exc):
                    raise
                logger.debug(
                    "Track %s manifest usage=%s formats=%s unavailable (%s); trying next option.",
                    track_id,
                    usage,
                    attempt_formats,
                    exc,
                )
                continue
            presentation = str(attributes.get("trackPresentation") or "FULL").strip().upper()
            if presentation == "PREVIEW":
                last_error = TrackManifestError("TIDAL returned a preview-only stream instead of the full track.")
                logger.debug(
                    "Track %s manifest usage=%s formats=%s returned PREVIEW; trying next usage.",
                    track_id,
                    usage,
                    attempt_formats,
                )
                break
            try:
                return _manifest_from_attributes(attributes)
            except ProtectedDashError as exc:
                last_error = TrackManifestError(str(exc))
                logger.debug(
                    "Track %s manifest usage=%s formats=%s is DRM-protected; trying next option.",
                    track_id,
                    usage,
                    attempt_formats,
                )
                continue
            except DashManifestError as exc:
                raise TrackManifestError(str(exc)) from exc
    if last_error is not None:
        raise last_error
    raise TrackManifestError("Track manifest request failed.")


def download_segments(urls: list[str], timeout: float = REQUEST_TIMEOUT_SEC) -> bytes:
    """Download DASH segments and concatenate them in order.

    Args:
        urls (list[str]): Initialization segment, then media segments.
        timeout (float): Per-request timeout in seconds.

    Returns:
        bytes: Joined audio bytes.

    Raises:
        TrackManifestError: A segment request failed or the payload is empty.
    """
    if not urls:
        raise TrackManifestError("Track manifest did not include segment URLs.")
    chunks: list[bytes] = []
    with requests.Session() as session:
        for url in urls:
            response = session.get(url, timeout=timeout)
            try:
                response.raise_for_status()
                if not response.content:
                    raise TrackManifestError("A track manifest segment was empty.")
                chunks.append(response.content)
            except requests.HTTPError as exc:
                raise TrackManifestError(f"Segment download failed (HTTP {response.status_code}).") from exc
            finally:
                response.close()
    return b"".join(chunks)
