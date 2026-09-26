import pathlib
from dataclasses import dataclass
from typing import Protocol

from requests import HTTPError
from tidalapi.media import Stream


class MediaStreamManifest(Protocol):
    """Fields the downloader reads from a track manifest.

    Implemented by tidalapi ``StreamManifest`` and by the hosted OpenAPI
    manifest in ``engines.track_manifest``.
    """

    codecs: str
    file_extension: str
    encryption_key: str | None

    def get_urls(self) -> list[str]:
        """Return segment URLs in decode order.

        Returns:
            list[str]: Absolute media URLs.
        """

    @property
    def is_encrypted(self) -> bool:
        """Whether segment bytes still need TIDAL decryption.

        Returns:
            bool: True when ``encryption_key`` is set.
        """


@dataclass
class DownloadSegmentResult:
    result: bool
    url: str
    path_segment: pathlib.Path
    id_segment: int
    error: HTTPError | None = None


@dataclass
class TrackStreamInfo:
    """Container for track stream information."""

    stream_manifest: MediaStreamManifest | None
    file_extension: str
    requires_flac_extraction: bool
    media_stream: Stream | None
