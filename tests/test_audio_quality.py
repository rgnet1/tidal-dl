"""Tests for per-track quality selection and FLAC-only output."""

from __future__ import annotations

import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from web.audio_quality import delivered_tier_label, effective_quality_for_track, quality_notice
from web.flac_output import ensure_flac_file, resolve_ffmpeg


def _media(tags: list[str]) -> SimpleNamespace:
    return SimpleNamespace(mediaMetadata=SimpleNamespace(tags=tags))


class TestEffectiveQuality:
    """Request the best tier the track offers, capped by the user setting."""

    def test_hi_res_when_tagged(self) -> None:
        assert effective_quality_for_track("HI_RES_LOSSLESS", _media(["HIRES_LOSSLESS"])) == "HI_RES_LOSSLESS"

    def test_cd_when_track_is_not_hi_res(self) -> None:
        assert effective_quality_for_track("HI_RES_LOSSLESS", _media(["LOSSLESS"])) == "LOSSLESS"

    def test_user_lossless_never_requests_hi_res(self) -> None:
        assert effective_quality_for_track("LOSSLESS", _media(["HIRES_LOSSLESS"])) == "LOSSLESS"

    def test_explicit_high_is_not_upgraded(self) -> None:
        assert effective_quality_for_track("HIGH", _media(["HIRES_LOSSLESS"])) == "HIGH"


class TestQualityNotices:
    """Toasts when the saved file is below the requested maximum."""

    def test_cd_fallback_notice(self) -> None:
        notice = quality_notice("HI_RES_LOSSLESS", "lossless", False)
        assert notice is not None
        assert "CD" in notice

    def test_transcode_notice(self) -> None:
        notice = quality_notice("HI_RES_LOSSLESS", "low", True)
        assert notice is not None
        assert "lossy" in notice.lower()

    def test_no_notice_when_hi_res_delivered(self) -> None:
        assert quality_notice("HI_RES_LOSSLESS", "hi_res", False) is None

    def test_tier_labels(self) -> None:
        assert delivered_tier_label("HI_RES_LOSSLESS") == "hi_res"
        assert delivered_tier_label("LOSSLESS") == "lossless"
        assert delivered_tier_label("HIGH") == "low"


class TestFlacOutput:
    """Audio files are rewritten to .flac."""

    def test_native_flac_kept(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        src = tmp_path / "song.flac"
        src.write_bytes(b"fLaC" + b"\x00" * 16)
        monkeypatch.setattr("web.flac_output.probe_flac_tier", lambda *_args, **_kwargs: "lossless")
        outcome = ensure_flac_file(src, "ffmpeg", source_quality="LOSSLESS")
        assert outcome.path == src
        assert outcome.transcoded is False
        assert outcome.tier == "lossless"

    def test_flac_inside_m4a_is_remuxed(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        src = tmp_path / "song.m4a"
        src.write_bytes(b"mp4-wrapped")

        def fake_run(cmd: list[str], **_kwargs: object) -> SimpleNamespace:
            Path(cmd[-1]).write_bytes(b"fLaC" + b"\x00" * 8)
            return SimpleNamespace(returncode=0)

        monkeypatch.setattr("web.flac_output.subprocess.run", fake_run)
        monkeypatch.setattr("web.flac_output.probe_flac_tier", lambda *_args, **_kwargs: "hi_res")
        outcome = ensure_flac_file(src, "ffmpeg", source_quality="HI_RES_LOSSLESS")
        assert outcome.remuxed is True
        assert outcome.transcoded is False
        assert outcome.tier == "hi_res"
        assert outcome.path.suffix == ".flac"
        assert outcome.path.exists()
        assert not src.exists()

    def test_lossy_container_is_transcoded(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        src = tmp_path / "song.m4a"
        src.write_bytes(b"aac-bytes")

        def fake_run(cmd: list[str], **_kwargs: object) -> SimpleNamespace:
            dest = Path(cmd[-1])
            if "copy" in cmd:
                dest.write_bytes(b"not-flac")
                return SimpleNamespace(returncode=0)
            dest.write_bytes(b"fLaC" + b"\x00" * 8)
            return SimpleNamespace(returncode=0)

        monkeypatch.setattr("web.flac_output.subprocess.run", fake_run)
        outcome = ensure_flac_file(src, "ffmpeg", source_quality="HIGH")
        assert outcome.transcoded is True
        assert outcome.tier == "low"
        assert outcome.path.suffix == ".flac"
        assert outcome.path.exists()
        assert not src.exists()

    def test_missing_ffmpeg_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("web.flac_output.shutil.which", lambda _name: None)
        with pytest.raises(FileNotFoundError):
            resolve_ffmpeg("")

    def test_conversion_failure_raises(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        src = tmp_path / "song.m4a"
        src.write_bytes(b"aac-bytes")

        def fake_run(_cmd: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
            return subprocess.CompletedProcess(args=[], returncode=1)

        monkeypatch.setattr("web.flac_output.subprocess.run", fake_run)
        with pytest.raises(RuntimeError):
            ensure_flac_file(src, "ffmpeg")
