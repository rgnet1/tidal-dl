from __future__ import annotations

import logging
from typing import Any, Callable

from rich.progress import BarColumn, Progress, SpinnerColumn, TaskProgressColumn, TextColumn
from tidalapi import Album, Artist, Playlist, Quality, Track, Video

from tidal_dl_ng.config import HandlingApp, Settings, Tidal
from tidal_dl_ng.constants import MediaType, QualityVideo
from tidal_dl_ng.download import Download
from tidal_dl_ng.helper.path import get_format_template
from tidal_dl_ng.helper.tidal import (
    favorite_function_factory,
    get_tidal_media_id,
    get_tidal_media_type,
    instantiate_media,
    search_results_all,
    user_media_lists,
)

from .. import unified_state
from ..ui_quality import quality_badge_for_catalog_track
from .base import Engine

logger = logging.getLogger("tidal-dl-pro.web.tdlng")

_TYPE_TO_MEDIA_TYPE: dict[str, MediaType] = {
    "track": MediaType.TRACK,
    "video": MediaType.VIDEO,
    "album": MediaType.ALBUM,
    "playlist": MediaType.PLAYLIST,
    "userplaylist": MediaType.PLAYLIST,
    "mix": MediaType.MIX,
    "artist": MediaType.ARTIST,
}


def reload_tidal_clients() -> tuple[Settings, Tidal]:
    """Reload Settings + Tidal singletons from disk after unified mirror."""
    settings = Settings()
    settings.read(settings.file_path)
    tidal = Tidal(settings)
    tidal.settings_apply()
    tidal.read(tidal.file_path)
    try:
        if tidal.token_from_storage:
            tidal.login_token()
    except Exception:
        logger.exception("reload_tidal_clients: login_token failed")
    return settings, tidal


def _attr(obj: Any, name: str, default: Any = None) -> Any:
    value = getattr(obj, name, default)
    if callable(value) and not isinstance(value, (str, bytes, int, float, bool, list, dict, tuple)):
        return default
    return value


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
        v = _attr(item, key)
        if isinstance(v, str) and v.strip():
            return v
    url = _cover_uuid_to_url(_attr(item, "cover"), size)
    if url:
        return url
    album = _attr(item, "album")
    if album is not None:
        for key in ("image_url", "squareImage"):
            v = _attr(album, key)
            if isinstance(v, str) and v.strip():
                return v
        return _cover_uuid_to_url(_attr(album, "cover"), size)
    return None


def media_to_item(item: Any) -> dict[str, Any]:
    name = _attr(item, "name") or _attr(item, "title") or ""
    result: dict[str, Any] = {
        "id": str(_attr(item, "id", "") or ""),
        "title": str(name),
        "type": type(item).__name__,
    }
    available = _attr(item, "available", None)
    if available is not None:
        result["available"] = bool(available)
    artist = _attr(item, "artist") or _attr(item, "artists")
    if artist:
        if isinstance(artist, list):
            result["artist"] = ", ".join(_attr(a, "name", "") or "" for a in artist if a)
        else:
            result["artist"] = str(_attr(artist, "name", "") or "")
    album = _attr(item, "album")
    if album:
        result["album"] = str(_attr(album, "name", "") or "")
    duration = _attr(item, "duration")
    if isinstance(duration, (int, float)):
        result["duration"] = int(duration)
    explicit = _attr(item, "explicit")
    if explicit is not None:
        result["explicit"] = bool(explicit)
    num_tracks = _attr(item, "num_tracks")
    if isinstance(num_tracks, (int, float)):
        result["num_tracks"] = int(num_tracks)
    description = _attr(item, "description")
    if description:
        result["description"] = str(description)
    image_url = _image_url_from_media(item)
    if image_url:
        result["image_url"] = image_url
    if type(item).__name__ == "Track":
        tags = _attr(item, "media_metadata_tags", None)
        aq = _attr(item, "audio_quality", None)
        if tags is not None or aq is not None:
            badge = quality_badge_for_catalog_track(
                list(tags) if tags is not None else None,
                str(aq) if aq is not None else None,
            )
            if badge:
                result["quality_badge"] = badge
    return result


class TdlngEngine(Engine):
    name = "tidal-dl-ng"

    def __init__(
        self,
        broadcast: Callable[[dict[str, Any]], Any],
        settings: Settings,
        tidal: Tidal,
    ) -> None:
        self._broadcast = broadcast
        self.settings = settings
        self.tidal = tidal
        self.link_login = None

    def bind(self, settings: Settings, tidal: Tidal) -> None:
        self.settings = settings
        self.tidal = tidal

    def is_authenticated(self) -> bool:
        try:
            return bool(self.tidal.session.check_login())
        except Exception:
            return False

    def start_login(self) -> dict[str, Any]:
        if self.tidal.login_token():
            return {"authenticated": True}
        self.link_login = self.tidal.session.get_link_login()
        url = self.link_login.verification_uri_complete
        if not str(url).startswith("http"):
            url = f"https://{url}"
        return {
            "authenticated": False,
            "login_url": url,
            "expires_in": getattr(self.link_login, "expires_in", 300),
        }

    def finalize_login(self) -> bool:
        if not self.link_login:
            return False
        try:
            self.tidal.session.process_link_login(self.link_login, until_expiry=False)
            ok = self.tidal.login_finalize()
            if ok:
                self.link_login = None
                sess = self.tidal.session
                user = getattr(sess, "user", None)
                uid = str(user.id) if user is not None and getattr(user, "id", None) is not None else None
                cc_raw = getattr(sess, "country_code", None)
                cc = str(cc_raw) if cc_raw else None
                unified_state.merge_auth_from_tidal_session(
                    sess.token_type or "Bearer",
                    sess.access_token or "",
                    sess.refresh_token or "",
                    sess.expiry_time,
                    user_id=uid,
                    country_code=cc,
                )
                reload_tidal_clients()
            return bool(ok)
        except Exception as e:
            logger.error("Login finalize error: %s", e)
            return False

    def logout(self) -> None:
        try:
            self.tidal.logout()
        except Exception as e:
            logger.error("Logout error: %s", e)
        unified_state.clear_auth()
        reload_tidal_clients()

    def library_lists(self) -> dict[str, Any]:
        lists = user_media_lists(self.tidal.session) or {}
        playlist_items = lists.get("playlists", []) if isinstance(lists, dict) else []
        mix_items = lists.get("mixes", []) if isinstance(lists, dict) else []

        playlists = [media_to_item(p) for p in playlist_items if p is not None]
        mixes = [media_to_item(m) for m in mix_items if m is not None]

        favorites = [
            {"id": "fav_tracks", "title": "Favorite Tracks", "type": "favorites"},
            {"id": "fav_albums", "title": "Favorite Albums", "type": "favorites"},
            {"id": "fav_artists", "title": "Favorite Artists", "type": "favorites"},
            {"id": "fav_videos", "title": "Favorite Videos", "type": "favorites"},
        ]
        return {"playlists": playlists, "mixes": mixes, "favorites": favorites}

    def library_items(self, list_id: str) -> dict[str, Any]:
        session = self.tidal.session
        fav_prefix = "fav_"
        if list_id.startswith(fav_prefix):
            fav_key = list_id[len(fav_prefix) :]
            fav_map = {
                "tracks": "tracks_paginated",
                "albums": "albums_paginated",
                "artists": "artists_paginated",
                "videos": "videos",
                "mixes": "mixes",
            }
            func_name = fav_map.get(fav_key)
            if not func_name:
                raise ValueError(f"Unknown favorite type: {fav_key}")
            getter = favorite_function_factory(session, func_name)
            items = getter() or []
            return {"items": [media_to_item(i) for i in items if i is not None]}

        lists = user_media_lists(session) or {}
        all_lists = []
        if isinstance(lists, dict):
            for bucket in lists.values():
                all_lists.extend(bucket or [])

        target = next((li for li in all_lists if str(getattr(li, "id", "")) == list_id), None)
        if not target:
            raise LookupError("List not found")

        children: list[dict[str, Any]] = []
        kind = type(target).__name__

        # Mixes only expose ``items()`` (tracks). ``tracks()`` / ``all_tracks()`` are absent,
        # so the old path returned an empty list for every mix.
        if kind == "Mix":
            getter = getattr(target, "items", None)
            if callable(getter):
                for it in getter():
                    if it is not None:
                        children.append(media_to_item(it))
            return {"items": children}

        # Folders sit in the same sidebar bucket as playlists; their ``items()`` are
        # child playlists / folders, not flat tracks.
        if kind == "Folder":
            getter = getattr(target, "items", None)
            if callable(getter):
                for it in getter():
                    if it is not None:
                        children.append(media_to_item(it))
            return {"items": children}

        tracks_iter = None
        if hasattr(target, "all_tracks") and callable(getattr(target, "all_tracks")):
            tracks_iter = target.all_tracks()
        elif hasattr(target, "tracks") and callable(getattr(target, "tracks")):
            tracks_iter = target.tracks()
        if tracks_iter:
            for t in tracks_iter:
                if t is not None:
                    children.append(media_to_item(t))
        return {"items": children}

    def search(self, query: str, media_type: str) -> dict[str, Any]:
        # tidalapi >= 0.8 takes a list of model classes as ``models=``; the old
        # ``SearchTypes.TRACK`` enum-style access raises ``AttributeError: 'list'
        # object has no attribute 'TRACK'`` because ``SearchTypes`` is now a plain
        # list of classes.
        type_map: dict[str, type] = {
            "track": Track,
            "album": Album,
            "playlist": Playlist,
            "artist": Artist,
            "video": Video,
        }
        st = type_map.get(media_type.lower(), Track)
        if query.startswith("http"):
            mtype = get_tidal_media_type(query)
            mid = get_tidal_media_id(query)
            media = instantiate_media(self.tidal.session, mtype, mid) if mid else None
            return {"results": [media_to_item(media)] if media else []}
        results = search_results_all(self.tidal.session, query, [st])
        items: list[dict[str, Any]] = []
        # ``top_hit`` repeats an entry that also appears in its list bucket, so
        # track seen ids to avoid surfacing the same media twice.
        seen_ids: set[str] = set()
        for _, group in results.items():
            # tidalapi may return either a list of media objects or a single
            # media object per group depending on version/response shape.
            members = group if isinstance(group, (list, tuple, set)) else [group]
            for m in members:
                if m is None:
                    continue
                if hasattr(m, "available") and not m.available:
                    continue
                item = media_to_item(m)
                item_id = item.get("id")
                if item_id and item_id in seen_ids:
                    continue
                if item_id:
                    seen_ids.add(item_id)
                items.append(item)
        return {"results": items}

    def resolve_media(self, media_id: str, media_type: str) -> dict[str, Any] | None:
        media = instantiate_media(self.tidal.session, media_type.lower(), media_id)
        if not media:
            return None
        return {
            "id": media_id,
            "title": str(getattr(media, "name", "") or getattr(media, "title", "")),
            "type": type(media).__name__,
        }

    def _build_download_worker(self) -> Download:
        handling = HandlingApp()
        progress = Progress(
            TextColumn("[progress.description]{task.description}"),
            SpinnerColumn(),
            BarColumn(),
            TaskProgressColumn(),
            auto_refresh=False,
            disable=True,
            transient=True,
        )
        progress_overall = Progress(
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TaskProgressColumn(),
            auto_refresh=False,
            disable=True,
            transient=True,
        )
        return Download(
            tidal_obj=self.tidal,
            skip_existing=self.settings.data.skip_existing,
            path_base=self.settings.data.download_base_path,
            fn_logger=logger,
            progress=progress,
            progress_overall=progress_overall,
            event_abort=handling.event_abort,
            event_run=handling.event_run,
        )

    def download_entry(self, entry: dict[str, Any], abort: Callable[[], bool]) -> None:
        self._broadcast({"type": "download_started", "title": str(entry["title"])})
        try:
            if abort():
                entry["status"] = "failed"
                entry["progress"] = -1
                entry["error"] = "Aborted"
                return

            media_type = _TYPE_TO_MEDIA_TYPE.get(str(entry["type"]).lower(), MediaType.TRACK)
            media = instantiate_media(self.tidal.session, media_type, str(entry["id"]))
            if not media:
                raise RuntimeError("Media not found on TIDAL")

            file_template = get_format_template(media, self.settings)
            if not isinstance(file_template, str):
                file_template = self.settings.data.format_track

            dl = self._build_download_worker()
            quality_audio = Quality(str(self.settings.data.quality_audio))
            try:
                quality_video = QualityVideo(str(self.settings.data.quality_video))
            except ValueError:
                quality_video = QualityVideo.P720

            if media_type in (MediaType.TRACK, MediaType.VIDEO):
                result = dl.item(
                    media=media,
                    file_template=file_template,
                    download_delay=self.settings.data.download_delay,
                    quality_audio=quality_audio,
                    quality_video=quality_video,
                )
                success = bool(result[0]) if isinstance(result, tuple) else bool(result)
            else:
                dl.items(
                    media=media,
                    media_id=str(entry["id"]),
                    media_type=media_type,
                    file_template=file_template,
                    video_download=self.settings.data.video_download,
                    download_delay=self.settings.data.download_delay,
                    quality_audio=quality_audio,
                    quality_video=quality_video,
                )
                success = True

            entry["status"] = "finished" if success else "failed"
            entry["progress"] = 100 if success else -1
        except Exception as e:
            logger.exception("Download error for %s", entry["title"])
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
