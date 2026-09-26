"""OpenAPI v2 track manifests replace the AAC-only playback endpoint."""

from __future__ import annotations

import base64
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import pytest

from engines.dash import DashManifestError, ProtectedDashError, best_dash_representation
from engines.track_manifest import (
    TrackManifestError,
    fetch_audio_manifest,
    uses_openapi_manifest,
)
from tidal_dl_ng.download import Download

_CLEAR_MPD = """<MPD xmlns="urn:mpeg:dash:schema:mpd:2011"><Period>
  <AdaptationSet contentType="audio" mimeType="audio/mp4">
    <Representation id="aac" codecs="mp4a.40.2" bandwidth="96000" audioSamplingRate="44100">
      <SegmentTemplate initialization="https://audio.example/aac-init.mp4"
        media="https://audio.example/aac-$Number$.mp4" startNumber="1" timescale="44100">
        <SegmentTimeline><S d="44100" r="0" /></SegmentTimeline>
      </SegmentTemplate>
    </Representation>
    <Representation id="FLAC,44100,16" codecs="flac" bandwidth="900000" audioSamplingRate="44100">
      <SegmentTemplate initialization="https://audio.example/init.mp4"
        media="https://audio.example/$Number$.mp4" startNumber="1" timescale="44100">
        <SegmentTimeline><S d="48000" r="1" /></SegmentTimeline>
      </SegmentTemplate>
    </Representation>
  </AdaptationSet>
</Period></MPD>"""


def _data_uri(xml: str) -> str:
    encoded = base64.b64encode(xml.encode()).decode()
    return f"data:application/dash+xml;base64,{encoded}"


def _http(status: int, payload: dict[str, Any]) -> MagicMock:
    response = MagicMock()
    response.status_code = status
    response.json.return_value = payload
    response.headers = {}
    response.content = b"ok"
    return response


def _manifest_body(xml: str, formats: list[str], presentation: str = "FULL") -> dict[str, Any]:
    return {
        "data": {
            "attributes": {
                "formats": formats,
                "uri": _data_uri(xml),
                "trackPresentation": presentation,
            }
        }
    }


def test_dash_prefers_flac_segments_over_aac() -> None:
    chosen = best_dash_representation(_CLEAR_MPD)
    assert chosen["codec"] == "flac"
    assert chosen["urls"] == [
        "https://audio.example/init.mp4",
        "https://audio.example/1.mp4",
        "https://audio.example/2.mp4",
    ]


def test_dash_rejects_content_protection() -> None:
    protected = _CLEAR_MPD.replace(
        '<AdaptationSet contentType="audio" mimeType="audio/mp4">',
        '<AdaptationSet contentType="audio" mimeType="audio/mp4">'
        '<ContentProtection schemeIdUri="urn:mpeg:dash:mp4protection:2011"/>',
        1,
    )
    with pytest.raises(ProtectedDashError):
        best_dash_representation(protected)


def test_broken_xml_is_rejected() -> None:
    with pytest.raises(DashManifestError):
        best_dash_representation("<MPD>")


def test_lossless_uses_openapi_and_high_does_not() -> None:
    assert uses_openapi_manifest("LOSSLESS") is True
    assert uses_openapi_manifest("HI_RES_LOSSLESS") is True
    assert uses_openapi_manifest("HIGH") is False
    assert uses_openapi_manifest("LOW", atmos=True) is True


def test_fetch_requests_v2_track_manifest_not_playbackinfo(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    def fake_get(url: str, headers: dict[str, str] | None = None, params: Any = None, timeout: float = 0) -> MagicMock:
        captured["url"] = url
        captured["headers"] = headers
        captured["params"] = list(params or [])
        return _http(200, _manifest_body(_CLEAR_MPD, ["FLAC_HIRES", "FLAC"]))

    monkeypatch.setattr("engines.track_manifest.requests.get", fake_get)
    manifest = fetch_audio_manifest("token-value", 465909959, "HI_RES_LOSSLESS")
    assert captured["url"] == "https://openapi.tidal.com/v2/trackManifests/465909959"
    assert "playbackinfopostpaywall" not in captured["url"]
    assert ("formats", "FLAC_HIRES") in captured["params"]
    assert ("formats", "FLAC") in captured["params"]
    assert ("usage", "DOWNLOAD") in captured["params"]
    assert captured["headers"]["Authorization"] == "Bearer token-value"
    assert manifest.codecs == "FLAC"
    assert manifest.audio_quality == "HI_RES_LOSSLESS"
    assert manifest.file_extension == ".m4a"
    assert manifest.is_encrypted is False
    assert manifest.get_urls()[0] == "https://audio.example/init.mp4"


def test_preview_manifest_retries_playback_usage(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[list[tuple[str, str]]] = []

    def fake_get(url: str, headers: dict[str, str] | None = None, params: Any = None, timeout: float = 0) -> MagicMock:
        del url, headers, timeout
        query = list(params or [])
        calls.append(query)
        usage = dict(query)["usage"]
        presentation = "PREVIEW" if usage == "DOWNLOAD" else "FULL"
        return _http(200, _manifest_body(_CLEAR_MPD, ["FLAC"], presentation))

    monkeypatch.setattr("engines.track_manifest.requests.get", fake_get)
    manifest = fetch_audio_manifest("token", 1, "LOSSLESS")
    assert [dict(call)["usage"] for call in calls] == ["DOWNLOAD", "PLAYBACK"]
    assert manifest.audio_quality == "LOSSLESS"
    assert manifest.file_extension == ".m4a"


def test_protected_hires_retries_flac_only(monkeypatch: pytest.MonkeyPatch) -> None:
    protected = _CLEAR_MPD.replace(
        '<AdaptationSet contentType="audio" mimeType="audio/mp4">',
        '<AdaptationSet contentType="audio" mimeType="audio/mp4">'
        '<ContentProtection schemeIdUri="urn:mpeg:dash:mp4protection:2011"/>',
        1,
    )
    calls: list[list[str]] = []

    def fake_get(url: str, headers: dict[str, str] | None = None, params: Any = None, timeout: float = 0) -> MagicMock:
        del url, headers, timeout
        formats = [value for key, value in list(params or []) if key == "formats"]
        calls.append(formats)
        xml = protected if "FLAC_HIRES" in formats else _CLEAR_MPD
        return _http(200, _manifest_body(xml, formats))

    monkeypatch.setattr("engines.track_manifest.requests.get", fake_get)
    manifest = fetch_audio_manifest("token", 7, "HI_RES_LOSSLESS")
    assert calls[0] == ["FLAC_HIRES", "FLAC"]
    assert calls[1] == ["FLAC"]
    assert manifest.audio_quality == "LOSSLESS"
    assert manifest.codecs == "FLAC"


def test_aac_manifest_is_not_a_successful_lossless_download(monkeypatch: pytest.MonkeyPatch) -> None:
    aac_only = """<MPD><Period><AdaptationSet contentType="audio" mimeType="audio/mp4">
      <Representation codecs="mp4a.40.2" bandwidth="320000" audioSamplingRate="44100">
        <SegmentTemplate initialization="https://audio.example/aac-init.mp4"
          media="https://audio.example/aac-$Number$.mp4" startNumber="1" timescale="44100">
          <SegmentTimeline><S d="44100" r="0" /></SegmentTimeline>
        </SegmentTemplate>
      </Representation>
    </AdaptationSet></Period></MPD>"""

    def fake_get(url: str, headers: dict[str, str] | None = None, params: Any = None, timeout: float = 0) -> MagicMock:
        del url, headers, params, timeout
        return _http(200, _manifest_body(aac_only, ["AAC"]))

    monkeypatch.setattr("engines.track_manifest.requests.get", fake_get)
    with pytest.raises(TrackManifestError, match="not available"):
        fetch_audio_manifest("token", 3, "LOSSLESS")


def test_native_engine_does_not_call_legacy_playback_for_lossless(monkeypatch: pytest.MonkeyPatch) -> None:
    from engines.track_manifest import AudioStreamManifest

    manifest = AudioStreamManifest(
        urls=["https://audio.example/init.mp4"],
        codecs="FLAC",
        file_extension=".m4a",
        audio_quality="HI_RES_LOSSLESS",
    )

    def fail_get_stream() -> None:
        raise AssertionError("legacy playbackinfopostpaywall must not be used for lossless")

    def fake_fetch(token: str, track_id: int, quality: object, atmos: bool = False) -> AudioStreamManifest:
        assert token == "secret-token"
        assert track_id == 99
        assert atmos is False
        assert quality == "HI_RES_LOSSLESS"
        return manifest

    monkeypatch.setattr("tidal_dl_ng.download.fetch_audio_manifest", fake_fetch)
    media = SimpleNamespace(id=99, audio_modes=[], get_stream=fail_get_stream)

    class _Host:
        """Stand-in download worker; instance calls still resolve Download methods."""

        _openapi_track_stream_info = Download._openapi_track_stream_info

    host = _Host()
    host.settings = SimpleNamespace(data=SimpleNamespace(download_dolby_atmos=False, extract_flac=True))  # type: ignore[attr-defined]
    host.tidal = SimpleNamespace(restore_normal_session=lambda: True)  # type: ignore[attr-defined]
    host.session = SimpleNamespace(audio_quality="HI_RES_LOSSLESS", access_token="secret-token")  # type: ignore[attr-defined]
    host.fn_logger = SimpleNamespace(error=lambda *_a, **_k: None, exception=lambda *_a, **_k: None)  # type: ignore[attr-defined]
    info = Download._get_track_stream_info(host, media)  # type: ignore[arg-type]
    assert info.stream_manifest is manifest
    assert info.requires_flac_extraction is True
    assert info.file_extension == ".flac"


def test_native_engine_keeps_legacy_playback_for_aac_tiers(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "tidal_dl_ng.download.fetch_audio_manifest",
        lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("openapi used for HIGH")),
    )
    stream = SimpleNamespace(
        get_stream_manifest=lambda: SimpleNamespace(file_extension=".m4a", codecs="MP4A"),
    )
    media = SimpleNamespace(id=1, audio_modes=[], get_stream=lambda: stream)

    class _Host:
        """Stand-in download worker for the legacy AAC playback path."""

    host = _Host()
    host.settings = SimpleNamespace(data=SimpleNamespace(download_dolby_atmos=False, extract_flac=False))  # type: ignore[attr-defined]
    host.tidal = SimpleNamespace(restore_normal_session=lambda: True)  # type: ignore[attr-defined]
    host.session = SimpleNamespace(audio_quality="HIGH", access_token="token")  # type: ignore[attr-defined]
    host.fn_logger = SimpleNamespace(error=lambda *_a, **_k: None, exception=lambda *_a, **_k: None)  # type: ignore[attr-defined]
    info = Download._get_track_stream_info(host, media)  # type: ignore[arg-type]
    assert info.file_extension == ".m4a"
    assert info.stream_manifest is not None
    assert info.stream_manifest.codecs == "MP4A"
