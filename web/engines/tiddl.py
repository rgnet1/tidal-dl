from __future__ import annotations

import logging
import random
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Callable

from pathvalidate import sanitize_filename
from tiddl.core.api import TidalAPI, TidalClient
from tiddl.core.api.exceptions import ApiError
from tiddl.core.api.models.resources import (
    Album,
    Artist,
    Playlist,
    StreamVideoQuality,
    Track,
    TrackQuality,
    Video,
)
from tiddl.core.auth import AuthAPI
from tiddl.core.auth.exceptions import AuthClientError
from tiddl.core.metadata import add_track_metadata
from tiddl.core.utils import get_track_stream_data, get_video_stream_data
from tiddl.core.utils.ffmpeg import extract_flac

from .. import unified_state
from ..ui_quality import quality_badge_for_catalog_track
from .base import Engine

logger = logging.getLogger("tidal-dl-pro.web.tiddl")


def _track_quality(s: str) -> TrackQuality:
    q = str(s).upper()
    if q in ("LOW", "HIGH", "LOSSLESS", "HI_RES_LOSSLESS"):
        return q  # type: ignore[return-value]
    return "LOSSLESS"


def _playlist_row_kind(row: Any) -> str:
    """Normalize playlist / album page row discriminator (tiddl uses lowercase strings)."""
    return str(getattr(row, "type", "") or "").strip().lower()


_TRANSIENT_STATUSES = frozenset({429, 500, 502, 503, 504})


def _is_transient_api_error(e: ApiError) -> bool:
    status = getattr(e, "status", None)
    try:
        return int(status) in _TRANSIENT_STATUSES
    except (TypeError, ValueError):
        return False


def _retry_api(fn: Callable[..., Any], *args: Any, attempts: int = 4, base_delay: float = 0.6, **kwargs: Any) -> Any:
    """Call a tiddl API method, retrying only on transient 5xx / 429 responses.

    TIDAL occasionally returns 500/999 "unexpected error" for a few seconds at a
    time on endpoints like ``/playlists/{uuid}/items`` even when the resource is
    valid; without retry we surface a 502 to the UI and the user sees an empty
    list.
    """
    last_exc: Exception | None = None
    for i in range(attempts):
        try:
            return fn(*args, **kwargs)
        except ApiError as e:
            if not _is_transient_api_error(e) or i == attempts - 1:
                raise
            last_exc = e
            delay = base_delay * (2**i) + random.uniform(0, 0.3)
            logger.warning(
                "tiddl %s transient %s/%s, retrying in %.1fs (attempt %d/%d)",
                getattr(fn, "__name__", str(fn)),
                getattr(e, "status", "?"),
                getattr(e, "subStatus", "?"),
                delay,
                i + 1,
                attempts,
            )
            time.sleep(delay)
    if last_exc is not None:
        raise last_exc
    raise RuntimeError("unreachable")


def _video_quality(s: str) -> StreamVideoQuality:
    m: dict[str, StreamVideoQuality] = {
        "360": "LOW",
        "480": "LOW",
        "720": "MEDIUM",
        "1080": "HIGH",
    }
    return m.get(str(s), "MEDIUM")


def _file_begins_with_flac_magic(path: Path) -> bool:
    try:
        with path.open("rb") as f:
            return f.read(4) == b"fLaC"
    except OSError:
        return False


def _render_relpath(template: str, values: dict[str, Any], default_stem: str) -> Path:
    raw = str(template or "").strip()
    if not raw:
        raw = "{artist_name} - {track_title}"
    out = raw
    for key, val in values.items():
        out = out.replace("{" + key + "}", str(val if val is not None else ""))
    out = out.replace("\\", "/")
    parts: list[str] = []
    for p in out.split("/"):
        seg = sanitize_filename(p.strip())
        if seg and seg not in (".", ".."):
            parts.append(seg)
    if not parts:
        parts = [sanitize_filename(default_stem)]
    return Path(*parts)


def _media_kind_for_ui(obj: Any) -> str:
    """Match tidalapi class names (Track, Video, …) for the web UI.

    Playlist rows use tiddl subclasses (e.g. PlaylistTrack) whose ``__name__``
    is not ``Track``, which broke ``addToQueue`` (wrong ``media_type``) and
    filters that expect ``Track`` / ``Video``.
    """
    if isinstance(obj, Track):
        return "Track"
    if isinstance(obj, Video):
        return "Video"
    if isinstance(obj, Album):
        return "Album"
    if isinstance(obj, Artist):
        return "Artist"
    if isinstance(obj, Playlist):
        return "Playlist"
    return type(obj).__name__


def _cover_uuid_to_url(cover: Any, size: int = 320) -> str | None:
    c = str(cover or "").strip()
    if not c:
        return None
    if c.startswith("http://") or c.startswith("https://"):
        return c
    if "-" in c:
        return f"https://resources.tidal.com/images/{c.replace('-', '/')}/{size}x{size}.jpg"
    return None


def _image_url_from_media(item: Any, size: int = 320) -> str | None:
    if item is None:
        return None
    for key in ("image_url", "squareImage"):
        v = getattr(item, key, None)
        if isinstance(v, str) and v.strip():
            return v
    url = _cover_uuid_to_url(getattr(item, "cover", None), size)
    if url:
        return url
    album = getattr(item, "album", None)
    if album is not None:
        for key in ("image_url", "squareImage"):
            v = getattr(album, key, None)
            if isinstance(v, str) and v.strip():
                return v
        return _cover_uuid_to_url(getattr(album, "cover", None), size)
    return None


def _item_to_ui(obj: Any) -> dict[str, Any]:
    tid = getattr(obj, "id", None) or getattr(obj, "uuid", None)
    title = getattr(obj, "title", "") or getattr(obj, "name", "")
    typ = _media_kind_for_ui(obj)
    out: dict[str, Any] = {"id": str(tid or ""), "title": str(title), "type": typ}
    if hasattr(obj, "explicit"):
        out["explicit"] = bool(obj.explicit)
    if hasattr(obj, "duration") and isinstance(obj.duration, int):
        out["duration"] = int(obj.duration)
    if hasattr(obj, "numberOfTracks"):
        out["num_tracks"] = int(obj.numberOfTracks)
    if hasattr(obj, "description") and obj.description:
        out["description"] = str(obj.description)
    artists = getattr(obj, "artists", None) or []
    if artists:
        names = [getattr(a, "name", "") for a in artists if getattr(a, "name", None)]
        if names:
            out["artist"] = ", ".join(names)
    elif getattr(obj, "artist", None):
        out["artist"] = str(getattr(obj.artist, "name", "") or "")
    alb = getattr(obj, "album", None)
    if alb and getattr(alb, "title", None):
        out["album"] = str(alb.title)
    image_url = _image_url_from_media(obj)
    if image_url:
        out["image_url"] = image_url
    if typ == "Track":
        tags = None
        md = getattr(obj, "mediaMetadata", None)
        if md is not None:
            tags = getattr(md, "tags", None)
        aq = getattr(obj, "audioQuality", None)
        if tags is not None or aq is not None:
            badge = quality_badge_for_catalog_track(
                list(tags) if tags is not None else None,
                str(aq) if aq is not None else None,
            )
            if badge:
                out["quality_badge"] = badge
    return out


class TiddlEngine(Engine):
    name = "tiddl"

    def __init__(self, broadcast: Callable[[dict[str, Any]], Any]) -> None:
        self._broadcast = broadcast
        self._auth_api = AuthAPI()
        self._device_code: str | None = None
        self._client: TidalClient | None = None
        self._api: TidalAPI | None = None

    def _ensure_api(self) -> TidalAPI:
        if self._api is not None:
            return self._api
        ua = unified_state.load_auth()
        if not ua.access_token or not ua.user_id or not ua.country_code:
            raise RuntimeError("Not authenticated (missing tiddl session)")
        self._rebuild_client(ua)
        assert self._api is not None
        return self._api

    def _rebuild_client(self, ua: unified_state.UnifiedAuth) -> None:
        if not ua.access_token:
            self._client = None
            self._api = None
            return

        def on_refresh() -> str | None:
            try:
                cur = unified_state.load_auth()
                if not cur.refresh_token:
                    return None
                r = self._auth_api.refresh_token(cur.refresh_token)
                unified_state.merge_tiddl_access_token_refresh(
                    r.access_token,
                    int(r.expires_in),
                )
                if self.on_token_refresh:
                    self.on_token_refresh({"access_token": r.access_token, "expires_in": r.expires_in})
                try:
                    from .tdlng import reload_tidal_clients

                    reload_tidal_clients()
                except Exception:
                    logger.exception("reload tidal after tiddl refresh")
                return r.access_token
            except Exception:
                logger.exception("tiddl on_token_expiry refresh failed")
                return None

        self._client = TidalClient(
            token=ua.access_token,
            cache_name=":memory:",
            omit_cache=True,
            on_token_expiry=on_refresh,
        )
        self._api = TidalAPI(self._client, ua.user_id, ua.country_code)

    def reload_from_disk(self) -> None:
        ua = unified_state.load_auth()
        self._rebuild_client(ua)

    def is_authenticated(self) -> bool:
        ua = unified_state.load_auth()
        return bool(ua.access_token and ua.user_id and ua.country_code)

    def start_login(self) -> dict[str, Any]:
        if self.is_authenticated():
            self._device_code = None
            self.reload_from_disk()
            return {"authenticated": True}
        dev = self._auth_api.get_device_auth()
        self._device_code = dev.deviceCode
        url = dev.verificationUriComplete
        if not str(url).startswith("http"):
            url = f"https://{url}"
        return {"authenticated": False, "login_url": url, "expires_in": dev.expiresIn}

    def finalize_login(self) -> bool:
        if not self._device_code:
            return False
        try:
            auth = self._auth_api.get_auth(self._device_code)
        except AuthClientError as e:
            if getattr(e, "error", None) == "authorization_pending":
                return False
            logger.error("tiddl auth error: %s", e)
            return False
        except Exception:
            logger.exception("tiddl finalize failed")
            return False

        self._device_code = None
        unified_state.merge_auth_from_tiddl_response(
            auth.access_token,
            auth.refresh_token,
            int(auth.expires_in),
            int(auth.user.userId),
            str(auth.user.countryCode),
        )
        try:
            from .tdlng import reload_tidal_clients

            reload_tidal_clients()
        except Exception:
            logger.exception("reload tidal after tiddl login")
        self.reload_from_disk()
        return True

    def logout(self) -> None:
        ua = unified_state.load_auth()
        if ua.access_token:
            try:
                self._auth_api.logout_token(ua.access_token)
            except Exception:
                logger.exception("tiddl logout_token failed")
        unified_state.clear_auth()
        self._client = None
        self._api = None
        try:
            from .tdlng import reload_tidal_clients

            reload_tidal_clients()
        except Exception:
            logger.exception("reload tidal after tiddl logout")

    def library_lists(self) -> dict[str, Any]:
        api = self._ensure_api()
        fav = api.get_favorites()
        playlists: list[dict[str, Any]] = []
        with ThreadPoolExecutor(max_workers=8) as pool:
            futs = [pool.submit(api.get_playlist, pid) for pid in (fav.PLAYLIST or [])[:80]]
            for fut in as_completed(futs):
                try:
                    pl = fut.result()
                    playlists.append(_item_to_ui(pl))
                except Exception:
                    logger.debug("skip playlist", exc_info=True)

        favorites = [
            {"id": "fav_tracks", "title": "Favorite Tracks", "type": "favorites"},
            {"id": "fav_albums", "title": "Favorite Albums", "type": "favorites"},
            {"id": "fav_artists", "title": "Favorite Artists", "type": "favorites"},
            {"id": "fav_videos", "title": "Favorite Videos", "type": "favorites"},
        ]
        return {"playlists": playlists, "mixes": [], "favorites": favorites}

    def library_items(self, list_id: str) -> dict[str, Any]:
        api = self._ensure_api()
        if list_id.startswith("fav_"):
            key = list_id.removeprefix("fav_")
            fav = api.get_favorites()
            if key == "tracks":

                def one(tid: str) -> dict[str, Any] | None:
                    try:
                        return _item_to_ui(api.get_track(int(tid)))
                    except Exception:
                        return None

                items: list[dict[str, Any]] = []
                with ThreadPoolExecutor(max_workers=8) as pool:
                    futs = [pool.submit(one, tid) for tid in (fav.TRACK or [])[:500]]
                    for fut in as_completed(futs):
                        it = fut.result()
                        if it:
                            items.append(it)
                return {"items": items}
            if key == "albums":

                def one_a(aid: str) -> dict[str, Any] | None:
                    try:
                        return _item_to_ui(api.get_album(int(aid)))
                    except Exception:
                        return None

                items = []
                with ThreadPoolExecutor(max_workers=8) as pool:
                    for fut in as_completed([pool.submit(one_a, x) for x in (fav.ALBUM or [])[:200]]):
                        it = fut.result()
                        if it:
                            items.append(it)
                return {"items": items}
            if key == "artists":

                def one_ar(i: str) -> dict[str, Any] | None:
                    try:
                        return _item_to_ui(api.get_artist(int(i)))
                    except Exception:
                        return None

                items = []
                with ThreadPoolExecutor(max_workers=8) as pool:
                    for fut in as_completed([pool.submit(one_ar, x) for x in (fav.ARTIST or [])[:200]]):
                        it = fut.result()
                        if it:
                            items.append(it)
                return {"items": items}
            if key == "videos":

                def one_v(vid: str) -> dict[str, Any] | None:
                    try:
                        return _item_to_ui(api.get_video(int(vid)))
                    except Exception:
                        return None

                items = []
                with ThreadPoolExecutor(max_workers=8) as pool:
                    for fut in as_completed([pool.submit(one_v, x) for x in (fav.VIDEO or [])[:200]]):
                        it = fut.result()
                        if it:
                            items.append(it)
                return {"items": items}
            if key == "mixes":
                return {"items": []}
            raise ValueError(f"Unknown favorite type: {key}")

        def _paginate_playlist(pid: str) -> dict[str, Any]:
            items: list[dict[str, Any]] = []
            offset = 0
            warned_unknown = False
            while True:
                chunk = _retry_api(api.get_playlist_items, pid, limit=100, offset=offset)
                kinds: set[str] = set()
                for row in chunk.items:
                    k = _playlist_row_kind(row)
                    kinds.add(k or "?")
                    if k == "track":
                        items.append(_item_to_ui(row.item))
                    elif k == "video":
                        items.append(_item_to_ui(row.item))
                got = len(chunk.items)
                if got and not warned_unknown and kinds.isdisjoint({"track", "video"}):
                    logger.warning(
                        "tiddl playlist %s page offset=%s has no track/video rows (kinds=%s)",
                        pid,
                        offset,
                        sorted(kinds),
                    )
                    warned_unknown = True
                if got == 0:
                    break
                offset += got
                total = getattr(chunk, "totalNumberOfItems", None)
                if total is not None and offset >= int(total):
                    break
            return {"items": items}

        def _paginate_mix(mid: str) -> dict[str, Any]:
            items: list[dict[str, Any]] = []
            offset = 0
            while True:
                chunk = _retry_api(api.get_mix_items, mid, limit=100, offset=offset)
                for row in chunk.items:
                    items.append(_item_to_ui(row.item))
                got = len(chunk.items)
                if got == 0:
                    break
                offset += got
                total = getattr(chunk, "totalNumberOfItems", None)
                if total is not None and offset >= int(total):
                    break
            return {"items": items}

        def _paginate_album(aid: int) -> dict[str, Any]:
            items: list[dict[str, Any]] = []
            offset = 0
            while True:
                chunk = _retry_api(api.get_album_items, aid, limit=100, offset=offset)
                for row in chunk.items:
                    k = _playlist_row_kind(row)
                    if k == "track":
                        items.append(_item_to_ui(row.item))
                    elif k == "video":
                        items.append(_item_to_ui(row.item))
                got = len(chunk.items)
                if got == 0:
                    break
                offset += got
                total = getattr(chunk, "totalNumberOfItems", None)
                if total is not None and offset >= int(total):
                    break
            return {"items": items}

        # Playlist UUIDs and mix IDs can both contain hyphens. Only the
        # discriminator call (get_playlist) decides which endpoint to hit —
        # otherwise a transient 500 on /playlists/{uuid}/items wrongly falls
        # through to /mixes/{uuid}/items (which will also 500 since the id is
        # not a mix) and the UI ends up empty.
        if "-" in list_id:
            is_playlist = False
            try:
                _retry_api(api.get_playlist, list_id)
                is_playlist = True
            except ApiError as e:
                logger.info(
                    "tiddl get_playlist(%s) failed (%s/%s); treating as mix",
                    list_id,
                    getattr(e, "status", "?"),
                    getattr(e, "subStatus", "?"),
                )
            if is_playlist:
                return _paginate_playlist(list_id)
            return _paginate_mix(list_id)

        if list_id.isdigit():
            return _paginate_album(int(list_id))

        return _paginate_mix(list_id)

    def search(self, query: str, media_type: str) -> dict[str, Any]:
        api = self._ensure_api()
        res = api.get_search(query)
        key = media_type.lower()
        groups = {
            "track": res.tracks.items,
            "album": res.albums.items,
            "playlist": res.playlists.items,
            "artist": res.artists.items,
            "video": res.videos.items,
        }
        items = [_item_to_ui(m) for m in groups.get(key, res.tracks.items)]
        return {"results": items}

    def resolve_media(self, media_id: str, media_type: str) -> dict[str, Any] | None:
        api = self._ensure_api()
        mt = media_type.lower()
        try:
            if mt in ("track", "playlisttrack"):
                m = api.get_track(int(media_id))
            elif mt in ("video", "playlistvideo"):
                m = api.get_video(int(media_id))
            elif mt == "album":
                m = api.get_album(int(media_id))
            elif mt in ("playlist", "userplaylist"):
                m = api.get_playlist(media_id)
            elif mt == "artist":
                m = api.get_artist(int(media_id))
            elif mt == "mix":
                return {"id": media_id, "title": f"Mix {media_id}", "type": "Mix"}
            else:
                return None
            ui = _item_to_ui(m)
            return {"id": str(media_id), "title": ui["title"], "type": ui["type"]}
        except Exception:
            logger.exception("tiddl resolve_media failed")
            return None

    def _download_base(self) -> Path:
        p = Path(unified_state.load_settings().download_base_path).expanduser()
        p.mkdir(parents=True, exist_ok=True)
        return p

    def _maybe_delay(self) -> None:
        us = unified_state.load_settings()
        if not us.download_delay:
            return
        lo, hi = 3.0, 5.0
        time.sleep(round(random.uniform(lo, hi), 1))

    def _download_album_tracks(self, album_id: int, abort: Callable[[], bool]) -> None:
        api = self._ensure_api()
        us = unified_state.load_settings()
        conc = max(1, min(5, int(us.downloads_concurrent_max)))
        offset = 0
        while True:
            chunk = _retry_api(api.get_album_items, album_id, limit=100, offset=offset)

            def work(row: Any) -> None:
                if abort():
                    return
                k = _playlist_row_kind(row)
                if k == "track":
                    self._maybe_delay()
                    self._download_track_file(int(row.item.id))
                elif k == "video" and us.video_download:
                    self._maybe_delay()
                    self._download_video_file(int(row.item.id))

            with ThreadPoolExecutor(max_workers=conc) as pool:
                futs = [pool.submit(work, row) for row in chunk.items]
                for f in as_completed(futs):
                    f.result()
            got = len(chunk.items)
            if got == 0:
                break
            offset += got
            total = getattr(chunk, "totalNumberOfItems", None)
            if total is not None and offset >= int(total):
                break

    def _download_track_file(self, track_id: int) -> None:
        api = self._ensure_api()
        us = unified_state.load_settings()
        track = api.get_track(track_id)
        requested_quality = _track_quality(us.quality_audio)
        stream = api.get_track_stream(track_id, requested_quality)
        delivered_quality = str(getattr(stream, "audioQuality", "") or "")
        data, ext = get_track_stream_data(stream)
        if not data:
            raise RuntimeError(f"tiddl: empty stream payload for track {track_id}")
        base = self._download_base()
        artist_name = track.artist.name if getattr(track, "artist", None) else "Unknown"
        album = getattr(track, "album", None)
        album_title = str(getattr(album, "title", "") or "")
        album_artist = ""
        if album is not None and getattr(album, "artist", None) is not None:
            album_artist = str(getattr(album.artist, "name", "") or "")
        track_num = getattr(track, "trackNumber", None)
        vol_num = getattr(track, "volumeNumber", None)
        values = {
            "artist_name": artist_name,
            "album_title": album_title,
            "track_title": str(track.title),
            "album_artist": album_artist,
            "album_track_num": int(track_num) if isinstance(track_num, int) else "",
            "track_explicit": " [E]" if bool(getattr(track, "explicit", False)) else "",
            "album_explicit": "",
            "track_volume_num_optional": f"{vol_num}-" if isinstance(vol_num, int) and vol_num > 1 else "",
        }
        rel = _render_relpath(us.format_track, values, f"{artist_name} - {track.title}")
        if not rel.suffix:
            rel = rel.with_name(rel.name + ext)
        out = base / rel
        out.parent.mkdir(parents=True, exist_ok=True)
        if us.skip_existing and out.exists() and out.stat().st_size > 0:
            logger.info("tiddl skip existing %s", out)
            return
        out.write_bytes(data)

        # Only try MP4->FLAC extraction when TIDAL actually delivered a
        # Hi-Res FLAC stream wrapped in mp4. Checking the *requested* quality
        # produces 0-byte .flac files when the account is downgraded to HIGH
        # (AAC in .m4a) because ffmpeg -c copy can't lift a FLAC stream out.
        if (
            us.extract_flac
            and ext.lower() in (".mp4", ".m4a")
            and delivered_quality == "HI_RES_LOSSLESS"
        ):
            try:
                flac_path = extract_flac(out)
                if flac_path.exists() and flac_path.stat().st_size > 0:
                    if flac_path != out:
                        out.unlink(missing_ok=True)
                    out = flac_path
                else:
                    logger.warning("tiddl extract_flac produced empty file; keeping %s", out)
                    flac_path.unlink(missing_ok=True)
            except Exception:
                logger.exception("tiddl extract_flac failed; keeping container at %s", out)
        try:
            if out.suffix.lower() == ".flac" and not _file_begins_with_flac_magic(out):
                logger.warning("tiddl skipping metadata (file is not native FLAC): %s", out)
            else:
                add_track_metadata(out, track)
        except Exception:
            logger.exception("tiddl add_track_metadata failed")
        logger.info(
            "tiddl downloaded %s (requested=%s, delivered=%s, size=%d)",
            out,
            requested_quality,
            delivered_quality or "?",
            out.stat().st_size if out.exists() else 0,
        )

    def _download_video_file(self, video_id: int) -> None:
        api = self._ensure_api()
        us = unified_state.load_settings()
        vid = api.get_video(video_id)
        vq = _video_quality(us.quality_video)
        stream = api.get_video_stream(video_id, vq)
        data = get_video_stream_data(stream)
        base = self._download_base()
        artist_name = vid.artist.name if vid.artist else "Unknown"
        values = {
            "artist_name": artist_name,
            "track_title": str(vid.title),
            "album_title": "",
            "playlist_name": "",
            "mix_name": "",
            "track_explicit": " [E]" if bool(getattr(vid, "explicit", False)) else "",
        }
        rel = _render_relpath(us.format_video, values, f"{artist_name} - {vid.title}")
        if not rel.suffix:
            rel = rel.with_name(rel.name + ".mp4")
        out = base / rel
        out.parent.mkdir(parents=True, exist_ok=True)
        if us.skip_existing and out.exists():
            return
        out.write_bytes(data)
        logger.info("tiddl downloaded video %s", out)

    def download_entry(self, entry: dict[str, Any], abort: Callable[[], bool]) -> None:
        self._broadcast({"type": "download_started", "title": str(entry["title"])})
        try:
            if abort():
                entry["status"] = "failed"
                entry["progress"] = -1
                entry["error"] = "Aborted"
                return
            api = self._ensure_api()
            us = unified_state.load_settings()
            et = str(entry["type"])
            eid = str(entry["id"])
            if et.lower() == "track":
                self._maybe_delay()
                self._download_track_file(int(eid))
            elif et.lower() == "video":
                if not us.video_download:
                    raise RuntimeError("Video download disabled in settings")
                self._maybe_delay()
                self._download_video_file(int(eid))
            elif et.lower() == "album":
                self._download_album_tracks(int(eid), abort)
            elif et.lower() in ("playlist", "userplaylist"):
                offset = 0
                conc = max(1, min(5, int(us.downloads_concurrent_max)))
                while True:
                    chunk = _retry_api(api.get_playlist_items, eid, limit=100, offset=offset)

                    def work_pl(row: Any) -> None:
                        if abort():
                            return
                        k = _playlist_row_kind(row)
                        if k == "track":
                            self._maybe_delay()
                            self._download_track_file(int(row.item.id))
                        elif k == "video" and us.video_download:
                            self._maybe_delay()
                            self._download_video_file(int(row.item.id))

                    with ThreadPoolExecutor(max_workers=conc) as pool:
                        futs = [pool.submit(work_pl, row) for row in chunk.items]
                        for f in as_completed(futs):
                            f.result()
                    got = len(chunk.items)
                    if got == 0:
                        break
                    offset += got
                    total = getattr(chunk, "totalNumberOfItems", None)
                    if total is not None and offset >= int(total):
                        break
            elif et.lower() == "mix":
                offset = 0
                conc = max(1, min(5, int(us.downloads_concurrent_max)))
                while True:
                    chunk = _retry_api(api.get_mix_items, eid, limit=100, offset=offset)

                    def work_mx(row: Any) -> None:
                        if abort():
                            return
                        self._maybe_delay()
                        self._download_track_file(int(row.item.id))

                    with ThreadPoolExecutor(max_workers=conc) as pool:
                        futs = [pool.submit(work_mx, row) for row in chunk.items]
                        for f in as_completed(futs):
                            f.result()
                    got = len(chunk.items)
                    if got == 0:
                        break
                    offset += got
                    total = getattr(chunk, "totalNumberOfItems", None)
                    if total is not None and offset >= int(total):
                        break
            elif et.lower() == "artist":
                offset = 0
                while True:
                    alb_chunk = api.get_artist_albums(int(eid), limit=50, offset=offset)
                    for al in alb_chunk.items:
                        if abort():
                            break
                        self._download_album_tracks(int(al.id), abort)
                    offset += len(alb_chunk.items)
                    if offset >= alb_chunk.totalNumberOfItems or not alb_chunk.items:
                        break
            else:
                raise RuntimeError(f"Unsupported media type for tiddl: {et}")

            entry["status"] = "finished"
            entry["progress"] = 100
        except Exception as e:
            logger.exception("tiddl download error for %s", entry.get("title"))
            entry["status"] = "failed"
            entry["progress"] = -1
            entry["error"] = str(e)
        finally:
            self._broadcast(
                {
                    "type": f"download_{entry['status']}",
                    "title": str(entry["title"]),
                    "progress": entry["progress"],
                }
            )
