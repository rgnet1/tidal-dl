"""Unified settings + auth persisted under /config/unified.

Each engine (tidal-dl-ng, tiddl) reads its native files under /config; this
module keeps a single canonical JSON representation and mirrors it into
both engines on every write so users can switch engines without re-login.
"""

from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path
from typing import Any, Literal

import tomllib
from pydantic import BaseModel, Field

from tidal_dl_ng.helper.path import path_file_settings, path_file_token

EngineName = Literal["tidal-dl-ng", "tiddl"]

_mirror_lock = threading.Lock()


def oauth_expiry_to_unix_seconds(value: Any) -> int:
    """Normalize OAuth expiry from tidalapi / JSON into Unix epoch seconds.

    Newer tidalapi versions expose ``Session.expiry_time`` as a ``datetime``;
    older code and token.json use numeric Unix timestamps.
    """
    if value is None:
        return 0
    if isinstance(value, (int, float)):
        sec = float(value)
        if sec > 1e12:
            sec /= 1000.0
        return int(sec) if sec > 0 else 0
    ts = getattr(value, "timestamp", None)
    if callable(ts):
        try:
            return int(ts())
        except (OSError, ValueError, OverflowError):
            return 0
    return 0


def _config_root() -> Path:
    return Path(os.environ.get("XDG_CONFIG_HOME", str(Path.home())))


def unified_dir() -> Path:
    return _config_root() / "unified"


def tiddl_data_dir() -> Path:
    return Path(os.environ.get("TIDDL_PATH", str(_config_root() / "tiddl")))


def unified_settings_path() -> Path:
    return unified_dir() / "settings.json"


def unified_auth_path() -> Path:
    return unified_dir() / "auth.json"


def tidal_settings_path() -> Path:
    return Path(path_file_settings())


def tidal_token_path() -> Path:
    return Path(path_file_token())


def tiddl_config_path() -> Path:
    return tiddl_data_dir() / "config.toml"


def tiddl_auth_path() -> Path:
    return tiddl_data_dir() / "auth.json"


class UnifiedAuth(BaseModel):
    access_token: str | None = None
    refresh_token: str | None = None
    expires_at: int = 0  # unix epoch seconds
    token_type: str = "Bearer"
    user_id: str | None = None
    country_code: str | None = None


class UnifiedSettings(BaseModel):
    download_base_path: str = "~/download"
    quality_audio: str = "HIGH"  # LOW | HIGH | LOSSLESS | HI_RES_LOSSLESS
    quality_video: str = "480"
    skip_existing: bool = True
    download_delay: bool = True
    lyrics_embed: bool = False
    lyrics_file: bool = False
    video_download: bool = True
    extract_flac: bool = True
    downloads_concurrent_max: int = Field(default=3, ge=1, le=5)
    active_engine: EngineName = "tidal-dl-ng"
    path_binary_ffmpeg: str = ""
    format_track: str = "Tracks/{artist_name} - {track_title}{track_explicit}"
    format_album: str = (
        "Albums/{album_artist} - {album_title}{album_explicit}/{track_volume_num_optional}"
        "{album_track_num}. {artist_name} - {track_title}{album_explicit}"
    )
    format_playlist: str = "Playlists/{playlist_name}/{list_pos}. {artist_name} - {track_title}"
    format_mix: str = "Mix/{mix_name}/{artist_name} - {track_title}"
    format_video: str = "Videos/{artist_name} - {track_title}{track_explicit}"
    use_single_path_template: bool = False


def load_settings() -> UnifiedSettings:
    p = unified_settings_path()
    if not p.exists():
        return UnifiedSettings()
    with p.open(encoding="utf-8") as f:
        return UnifiedSettings.model_validate_json(f.read())


def load_auth() -> UnifiedAuth:
    p = unified_auth_path()
    if not p.exists():
        return UnifiedAuth()
    with p.open(encoding="utf-8") as f:
        return UnifiedAuth.model_validate_json(f.read())


def save_settings(s: UnifiedSettings) -> None:
    unified_dir().mkdir(parents=True, exist_ok=True)
    unified_settings_path().write_text(s.model_dump_json(indent=2), encoding="utf-8")


def save_auth(a: UnifiedAuth) -> None:
    unified_dir().mkdir(parents=True, exist_ok=True)
    unified_auth_path().write_text(a.model_dump_json(indent=2), encoding="utf-8")


def _quality_audio_to_tiddl_literal(q: str) -> str:
    """Map tidalapi-style quality string to tiddl config.toml literal."""
    m = {
        "LOW": "low",
        "HIGH": "normal",
        "LOSSLESS": "high",
        "HI_RES_LOSSLESS": "max",
    }
    return m.get(q.upper(), "high")


def _quality_audio_from_tiddl_literal(lit: str) -> str:
    m = {
        "low": "LOW",
        "normal": "HIGH",
        "high": "LOSSLESS",
        "max": "HI_RES_LOSSLESS",
    }
    return m.get(str(lit).lower(), "HIGH")


def _quality_video_to_tiddl_literal(v: str) -> str:
    m = {"360": "sd", "480": "sd", "720": "hd", "1080": "fhd"}
    return m.get(str(v), "hd")


def _quality_video_from_tiddl_literal(lit: str) -> str:
    m = {"sd": "480", "hd": "720", "fhd": "1080"}
    return m.get(str(lit).lower(), "480")


_TIDAL_TO_TIDDL_TOKENS: dict[str, str] = {
    "{artist_name}": "{item.artist.name}",
    "{track_title}": "{item.title}",
    "{album_title}": "{item.album.title}",
    "{album_artist}": "{item.album.artist.name}",
    "{album_track_num}": "{item.track_number}",
    "{list_pos}": "{item.position}",
    "{track_explicit}": "",
    "{album_explicit}": "",
    "{track_volume_num_optional}": "",
    "{playlist_name}": "{playlist.title}",
    "{mix_name}": "{mix.title}",
}
_TIDDL_TO_TIDAL_TOKENS: dict[str, str] = {v: k for k, v in _TIDAL_TO_TIDDL_TOKENS.items() if v}


def _tidal_template_to_tiddl_template(s: str) -> str:
    out = str(s or "")
    for old, new in _TIDAL_TO_TIDDL_TOKENS.items():
        out = out.replace(old, new)
    return out


def _tiddl_template_to_tidal_template(s: str) -> str:
    out = str(s or "")
    for old, new in _TIDDL_TO_TIDAL_TOKENS.items():
        out = out.replace(old, new)
    return out


def from_tidal_json(settings_obj: dict[str, Any], token_obj: dict[str, Any] | None) -> tuple[UnifiedSettings, UnifiedAuth]:
    """Build unified models from tidal-dl-ng JSON dicts (already decoded)."""
    s = UnifiedSettings()
    if settings_obj:
        s.download_base_path = str(settings_obj.get("download_base_path", s.download_base_path))
        s.quality_audio = str(settings_obj.get("quality_audio", s.quality_audio))
        s.quality_video = str(settings_obj.get("quality_video", s.quality_video))
        for key in (
            "skip_existing",
            "download_delay",
            "lyrics_embed",
            "lyrics_file",
            "video_download",
            "extract_flac",
        ):
            if key in settings_obj:
                setattr(s, key, bool(settings_obj[key]))
        if "downloads_concurrent_max" in settings_obj:
            s.downloads_concurrent_max = max(1, min(5, int(settings_obj["downloads_concurrent_max"])))
        s.path_binary_ffmpeg = str(settings_obj.get("path_binary_ffmpeg", "") or "")
        s.format_track = str(settings_obj.get("format_track", s.format_track))
        s.format_album = str(settings_obj.get("format_album", s.format_album))
        s.format_playlist = str(settings_obj.get("format_playlist", s.format_playlist))
        s.format_mix = str(settings_obj.get("format_mix", s.format_mix))
        s.format_video = str(settings_obj.get("format_video", s.format_video))
        if "use_single_path_template" in settings_obj:
            s.use_single_path_template = bool(settings_obj.get("use_single_path_template"))

    a = UnifiedAuth()
    if token_obj:
        a.access_token = token_obj.get("access_token")
        a.refresh_token = token_obj.get("refresh_token")
        a.token_type = str(token_obj.get("token_type") or "Bearer")
        a.expires_at = oauth_expiry_to_unix_seconds(token_obj.get("expiry_time", 0))
    return s, a


def from_tiddl_files(config_bytes: bytes, auth_obj: dict[str, Any] | None) -> tuple[UnifiedSettings, UnifiedAuth]:
    data = tomllib.loads(config_bytes.decode("utf-8"))
    dl = data.get("download") or {}
    md = data.get("metadata") or {}
    tpls = data.get("templates") or {}
    s = UnifiedSettings()
    s.download_base_path = str(dl.get("download_path", s.download_base_path))
    s.quality_audio = _quality_audio_from_tiddl_literal(str(dl.get("track_quality", "high")))
    s.quality_video = _quality_video_from_tiddl_literal(str(dl.get("video_quality", "hd")))
    s.skip_existing = bool(dl.get("skip_existing", True))
    s.downloads_concurrent_max = max(1, min(5, int(dl.get("threads_count", 3))))
    s.lyrics_embed = bool(md.get("lyrics", False))
    s.lyrics_file = bool(dl.get("write_lrc_file", False))
    s.video_download = str(dl.get("videos_filter", "none")) != "none"
    s.extract_flac = True
    s.download_delay = True
    tt = str(tpls.get("track", "") or "").strip()
    tv = str(tpls.get("video", "") or "").strip()
    ta = str(tpls.get("album", "") or "").strip()
    tp = str(tpls.get("playlist", "") or "").strip()
    tm = str(tpls.get("mix", "") or "").strip()
    if tt:
        s.format_track = _tiddl_template_to_tidal_template(tt)
    if tv:
        s.format_video = _tiddl_template_to_tidal_template(tv)
    if ta:
        s.format_album = _tiddl_template_to_tidal_template(ta)
    if tp:
        s.format_playlist = _tiddl_template_to_tidal_template(tp)
    if tm:
        s.format_mix = _tiddl_template_to_tidal_template(tm)
    if "use_single_path_template" in dl:
        s.use_single_path_template = bool(dl.get("use_single_path_template"))

    a = UnifiedAuth()
    if auth_obj:
        a.access_token = auth_obj.get("token")
        a.refresh_token = auth_obj.get("refresh_token")
        a.expires_at = int(auth_obj.get("expires_at") or 0)
        a.user_id = str(auth_obj["user_id"]) if auth_obj.get("user_id") is not None else None
        a.country_code = auth_obj.get("country_code")
    return s, a


def _build_tidal_settings_dict(us: UnifiedSettings) -> dict[str, Any]:
    """Produce a JSON-compatible dict for tidal_dl_ng ModelSettings."""
    from tidal_dl_ng.model.cfg import Settings as ModelSettings

    base = json.loads(ModelSettings().to_json())
    fmt_track = us.format_track
    fmt_album = us.format_track if us.use_single_path_template else us.format_album
    fmt_playlist = us.format_track if us.use_single_path_template else us.format_playlist
    fmt_mix = us.format_track if us.use_single_path_template else us.format_mix
    fmt_video = us.format_track if us.use_single_path_template else us.format_video
    base.update(
        {
            "download_base_path": us.download_base_path,
            "quality_audio": us.quality_audio,
            "quality_video": us.quality_video,
            "skip_existing": us.skip_existing,
            "download_delay": us.download_delay,
            "lyrics_embed": us.lyrics_embed,
            "lyrics_file": us.lyrics_file,
            "video_download": us.video_download,
            "extract_flac": us.extract_flac,
            "downloads_concurrent_max": us.downloads_concurrent_max,
            "path_binary_ffmpeg": us.path_binary_ffmpeg or base.get("path_binary_ffmpeg", ""),
            "format_track": fmt_track,
            "format_album": fmt_album,
            "format_playlist": fmt_playlist,
            "format_mix": fmt_mix,
            "format_video": fmt_video,
            "use_single_path_template": us.use_single_path_template,
        }
    )
    return base


def _build_tidal_token_dict(ua: UnifiedAuth) -> dict[str, Any]:
    return {
        "token_type": ua.token_type or "Bearer",
        "access_token": ua.access_token,
        "refresh_token": ua.refresh_token,
        "expiry_time": float(ua.expires_at) if ua.expires_at else 0.0,
    }


def _build_tiddl_config_dict(us: UnifiedSettings) -> dict[str, Any]:
    vfilter = "allow" if us.video_download else "none"
    fmt_track = us.format_track
    fmt_album = us.format_track if us.use_single_path_template else us.format_album
    fmt_playlist = us.format_track if us.use_single_path_template else us.format_playlist
    fmt_mix = us.format_track if us.use_single_path_template else us.format_mix
    fmt_video = us.format_track if us.use_single_path_template else us.format_video
    track_tpl = _tidal_template_to_tiddl_template(fmt_track)
    video_tpl = _tidal_template_to_tiddl_template(fmt_video)
    album_tpl = _tidal_template_to_tiddl_template(fmt_album)
    playlist_tpl = _tidal_template_to_tiddl_template(fmt_playlist)
    mix_tpl = _tidal_template_to_tiddl_template(fmt_mix)
    return {
        "enable_cache": True,
        "debug": False,
        "metadata": {
            "enable": True,
            "lyrics": us.lyrics_embed,
            "cover": False,
            "album_review": False,
        },
        "cover": {"save": False, "size": 1280, "allowed": [], "templates": {"track": "", "album": "", "playlist": ""}},
        "download": {
            "track_quality": _quality_audio_to_tiddl_literal(us.quality_audio),
            "video_quality": _quality_video_to_tiddl_literal(us.quality_video),
            "skip_existing": us.skip_existing,
            "threads_count": us.downloads_concurrent_max,
            "download_path": us.download_base_path,
            "scan_path": us.download_base_path,
            "singles_filter": "none",
            "videos_filter": vfilter,
            "update_mtime": False,
            "rewrite_metadata": False,
            "write_lrc_file": us.lyrics_file,
            "use_single_path_template": us.use_single_path_template,
        },
        "m3u": {"save": False, "allowed": [], "templates": {"album": "", "playlist": "", "mix": ""}},
        "templates": {
            "default": track_tpl or "{item.artist.name}/{item.title}",
            "track": track_tpl,
            "video": video_tpl,
            "album": album_tpl,
            "playlist": playlist_tpl,
            "mix": mix_tpl,
        },
    }


def _build_tiddl_auth_dict(ua: UnifiedAuth) -> dict[str, Any]:
    return {
        "token": ua.access_token,
        "refresh_token": ua.refresh_token,
        "expires_at": int(ua.expires_at or 0),
        "user_id": ua.user_id,
        "country_code": ua.country_code,
    }


def mirror_to_disk(us: UnifiedSettings, ua: UnifiedAuth) -> None:
    """Write unified JSON + mirror into both engines' native files."""
    import tomli_w

    with _mirror_lock:
        unified_dir().mkdir(parents=True, exist_ok=True)
        tiddl_data_dir().mkdir(parents=True, exist_ok=True)
        tidal_settings_path().parent.mkdir(parents=True, exist_ok=True)
        tidal_token_path().parent.mkdir(parents=True, exist_ok=True)

        save_settings(us)
        save_auth(ua)

        td_set = _build_tidal_settings_dict(us)
        with tidal_settings_path().open("w", encoding="utf-8") as f:
            json.dump(td_set, f, indent=4)

        td_tok = _build_tidal_token_dict(ua)
        with tidal_token_path().open("w", encoding="utf-8") as f:
            json.dump(td_tok, f, indent=4)
        try:
            os.chmod(tidal_token_path(), 0o600)
        except OSError:
            pass

        tiddl_cfg = _build_tiddl_config_dict(us)
        with tiddl_config_path().open("wb") as f:
            tomli_w.dump(tiddl_cfg, f)

        tiddl_auth = _build_tiddl_auth_dict(ua)
        with tiddl_auth_path().open("w", encoding="utf-8") as f:
            json.dump(tiddl_auth, f, indent=2)
        try:
            os.chmod(tiddl_auth_path(), 0o600)
        except OSError:
            pass


def migrate_from_native_if_needed() -> tuple[UnifiedSettings, UnifiedAuth]:
    """If unified/ is empty, bootstrap from tidal-dl-ng and/or tiddl native files."""
    if unified_settings_path().exists() and unified_auth_path().exists():
        return load_settings(), load_auth()

    us = UnifiedSettings()
    ua = UnifiedAuth()
    env_engine = os.environ.get("ACTIVE_ENGINE", "").strip().lower()
    if env_engine in ("tiddl", "tidal-dl-ng"):
        us.active_engine = env_engine  # type: ignore[assignment]

    loaded = False
    if tidal_settings_path().exists():
        with tidal_settings_path().open(encoding="utf-8") as f:
            td_s = json.load(f)
        td_t: dict[str, Any] | None = None
        if tidal_token_path().exists():
            with tidal_token_path().open(encoding="utf-8") as f:
                td_t = json.load(f)
        us, ua = from_tidal_json(td_s, td_t)
        loaded = True

    if not loaded and tiddl_config_path().exists():
        cfg_b = tiddl_config_path().read_bytes()
        auth_d = None
        if tiddl_auth_path().exists():
            with tiddl_auth_path().open(encoding="utf-8") as f:
                auth_d = json.load(f)
        us, ua = from_tiddl_files(cfg_b, auth_d)
        loaded = True

    if not loaded:
        env_dl = os.environ.get("DOWNLOAD_PATH")
        if env_dl:
            us.download_base_path = env_dl

    mirror_to_disk(us, ua)
    return us, ua


def merge_auth_from_tidal_session(
    token_type: str,
    access_token: str,
    refresh_token: str,
    expiry_time: Any,
    *,
    user_id: str | None = None,
    country_code: str | None = None,
) -> None:
    """After tidalapi OAuth finalize, push tokens into unified + mirror.

    ``user_id`` and ``country_code`` come from the tidalapi session; tiddl
    needs them on the same access token to build ``TidalAPI``.
    """
    us = load_settings()
    ua = load_auth()
    ua.token_type = token_type or "Bearer"
    ua.access_token = access_token
    ua.refresh_token = refresh_token
    ua.expires_at = oauth_expiry_to_unix_seconds(expiry_time)
    if user_id:
        ua.user_id = user_id
    if country_code:
        ua.country_code = country_code
    mirror_to_disk(us, ua)


def merge_identity_from_logged_in_tidal_session(session: Any) -> None:
    """If tokens exist but user/country are missing, copy them from a logged-in tidalapi session."""
    try:
        if session is None or not session.check_login():
            return
    except Exception:
        return
    ua = load_auth()
    if not ua.access_token or (ua.user_id and ua.country_code):
        return
    user = getattr(session, "user", None)
    uid = str(user.id) if user is not None and getattr(user, "id", None) is not None else None
    cc_raw = getattr(session, "country_code", None)
    cc = str(cc_raw) if cc_raw else None
    if not uid or not cc:
        return
    us = load_settings()
    ua.user_id = uid
    ua.country_code = cc
    mirror_to_disk(us, ua)


def merge_auth_from_tiddl_response(
    access_token: str,
    refresh_token: str | None,
    expires_in: int,
    user_id: int,
    country_code: str,
) -> None:
    us = load_settings()
    ua = load_auth()
    ua.access_token = access_token
    if refresh_token:
        ua.refresh_token = refresh_token
    ua.expires_at = int(time.time()) + int(expires_in)
    ua.user_id = str(user_id)
    ua.country_code = country_code
    mirror_to_disk(us, ua)


def merge_tiddl_access_token_refresh(access_token: str, expires_in: int) -> None:
    """After tiddl AuthAPI.refresh_token (no new refresh_token in body)."""
    us = load_settings()
    ua = load_auth()
    ua.access_token = access_token
    ua.expires_at = int(time.time()) + int(expires_in)
    mirror_to_disk(us, ua)


def clear_auth() -> None:
    us = load_settings()
    ua = UnifiedAuth()
    mirror_to_disk(us, ua)


def update_settings_partial(**kwargs: Any) -> UnifiedSettings:
    us = load_settings()
    for k, v in kwargs.items():
        if hasattr(us, k) and v is not None:
            setattr(us, k, v)
    ua = load_auth()
    mirror_to_disk(us, ua)
    return us
