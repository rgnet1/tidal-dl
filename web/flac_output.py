"""Force successful audio downloads to a real ``.flac`` file.

Native FLAC is kept. FLAC wrapped in MP4/M4A is remuxed. Lossy AAC is
transcoded to FLAC so the library never keeps ``.m4a`` / ``.aac`` on success.
"""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from web.audio_quality import delivered_tier_label


@dataclass(frozen=True)
class FlacOutcome:
    """Result of normalizing one audio file to FLAC.

    Attributes:
        path: Final ``.flac`` path.
        tier: ``hi_res``, ``lossless``, or ``low``.
        transcoded: True when the source was lossy and re-encoded.
        remuxed: True when FLAC was copied out of a container.
        source_quality: Raw quality string when known (may be empty).
    """

    path: Path
    tier: str
    transcoded: bool
    remuxed: bool
    source_quality: str = ""


class FfmpegMissingError(FileNotFoundError):
    """Raised when ffmpeg cannot be located."""

    def __init__(self) -> None:
        super().__init__(
            "ffmpeg was not found. Install ffmpeg or set path_binary_ffmpeg so audio can be saved as FLAC."
        )


class AudioFileMissingError(FileNotFoundError):
    """Raised when the downloaded audio file is gone."""

    def __init__(self, path: Path) -> None:
        super().__init__(f"Audio file missing: {path}")


class FlacConversionError(RuntimeError):
    """Raised when ffmpeg cannot produce a FLAC file."""

    def __init__(self, name: str) -> None:
        super().__init__(f"Could not convert {name} to FLAC (ffmpeg failed).")


def resolve_ffmpeg(configured: str | None) -> str:
    """Locate the ffmpeg binary.

    Args:
        configured: Optional absolute path from settings.

    Returns:
        Executable path.

    Raises:
        FileNotFoundError: When ffmpeg cannot be found.
    """
    if configured:
        candidate = Path(configured)
        if candidate.is_file():
            return str(candidate)
    found = shutil.which("ffmpeg")
    if found:
        return found
    raise FfmpegMissingError


def file_is_flac(path: Path) -> bool:
    """Return True when ``path`` starts with the FLAC magic bytes."""
    try:
        with path.open("rb") as handle:
            return handle.read(4) == b"fLaC"
    except OSError:
        return False


def _ffprobe_bin(ffmpeg: str) -> str:
    sibling = Path(ffmpeg).with_name("ffprobe")
    if sibling.is_file():
        return str(sibling)
    found = shutil.which("ffprobe")
    return found or "ffprobe"


def probe_flac_tier(path: Path, ffmpeg: str) -> str:
    """Guess hi-res vs CD from bit depth. Falls back to lossless for native FLAC.

    Args:
        path: FLAC file.
        ffmpeg: ffmpeg path used to locate ffprobe.

    Returns:
        ``hi_res`` or ``lossless``.
    """
    try:
        completed = subprocess.run(
            [
                _ffprobe_bin(ffmpeg),
                "-v",
                "error",
                "-select_streams",
                "a:0",
                "-show_entries",
                "stream=bits_per_raw_sample,bits_per_sample",
                "-of",
                "default=noprint_wrappers=1:nokey=1",
                str(path),
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired):
        return "lossless"
    depths: list[int] = []
    for line in (completed.stdout or "").splitlines():
        token = line.strip()
        if token.isdigit():
            depths.append(int(token))
    if any(depth >= 20 for depth in depths):
        return "hi_res"
    return "lossless"


def _run_ffmpeg(ffmpeg: str, args: list[str]) -> bool:
    try:
        completed = subprocess.run(
            [ffmpeg, "-y", "-hide_banner", "-loglevel", "error", *args],
            check=False,
            capture_output=True,
            timeout=600,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return completed.returncode == 0


def _apply_hint(probed: str, hinted: str, *, remuxed: bool) -> str:
    """Prefer the catalog hint when probing cannot see the real tier."""
    if hinted == "hi_res":
        return "hi_res"
    if not remuxed and hinted == "low":
        return "low"
    if remuxed and hinted == "lossless" and probed == "low":
        return "lossless"
    return probed


def _replace_with_flac_suffix(path: Path) -> Path:
    """Rename a FLAC payload so the suffix is ``.flac``."""
    final = path if path.suffix.lower() == ".flac" else path.with_suffix(".flac")
    if final != path:
        if final.exists():
            final.unlink()
        path.replace(final)
    return final


def _outcome(path: Path, tier: str, *, transcoded: bool, remuxed: bool, source_quality: str) -> FlacOutcome:
    """Build one FLAC result."""
    return FlacOutcome(
        path=path,
        tier=tier,
        transcoded=transcoded,
        remuxed=remuxed,
        source_quality=source_quality,
    )


def ensure_flac_file(
    path: Path,
    ffmpeg: str,
    *,
    source_quality: str = "",
) -> FlacOutcome:
    """Rewrite ``path`` so the kept file is ``.flac``.

    Args:
        path: Downloaded audio file.
        ffmpeg: ffmpeg executable.
        source_quality: Optional TIDAL audioQuality used when probing is inconclusive.

    Returns:
        Outcome describing the final file.

    Raises:
        FileNotFoundError: When ``path`` does not exist.
        RuntimeError: When conversion fails.
    """
    if not path.is_file():
        raise AudioFileMissingError(path)

    hinted = delivered_tier_label(source_quality) if source_quality else ""
    if file_is_flac(path):
        final = _replace_with_flac_suffix(path)
        tier = _apply_hint(probe_flac_tier(final, ffmpeg), hinted, remuxed=False)
        return _outcome(final, tier, transcoded=False, remuxed=False, source_quality=source_quality)

    dest = path.with_suffix(".flac")
    if dest.exists():
        dest.unlink()
    if _copied_flac(path, dest, ffmpeg):
        path.unlink(missing_ok=True)
        tier = _apply_hint(probe_flac_tier(dest, ffmpeg), hinted, remuxed=True)
        return _outcome(dest, tier, transcoded=False, remuxed=True, source_quality=source_quality)

    dest.unlink(missing_ok=True)
    if not _encoded_flac(path, dest, ffmpeg):
        raise FlacConversionError(path.name)
    path.unlink(missing_ok=True)
    return _outcome(dest, "low", transcoded=True, remuxed=False, source_quality=source_quality)


def _copied_flac(source: Path, dest: Path, ffmpeg: str) -> bool:
    """Copy a FLAC stream out of a container without re-encoding."""
    copied = _run_ffmpeg(ffmpeg, ["-i", str(source), "-map", "0:a:0", "-c:a", "copy", str(dest)])
    return copied and file_is_flac(dest) and dest.stat().st_size > 0


def _encoded_flac(source: Path, dest: Path, ffmpeg: str) -> bool:
    """Transcode a lossy file to FLAC."""
    encoded = _run_ffmpeg(ffmpeg, ["-i", str(source), "-map", "0:a:0", "-c:a", "flac", str(dest)])
    return encoded and dest.is_file() and dest.stat().st_size > 0
