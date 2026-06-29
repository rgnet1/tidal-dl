import asyncio
import json
import logging
import os
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from threading import Event, Lock
from typing import Any, Literal

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from pydantic import BaseModel
from tidalapi import Quality

from tidal_dl_ng.constants import QualityVideo

from web import unified_state
from web.engines.base import Engine
from web.engines.tdlng import TdlngEngine, reload_tidal_clients
from web.engines.tiddl import TiddlEngine

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("tidal-dl-pro.web")

app = FastAPI(title="Tidal DL Pro Web UI")

# Global state
download_queue: list[dict[str, Any]] = []
ws_connections: list[WebSocket] = []
_executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="dl")
_abort_event = Event()
_queue_lock = Lock()
_loop: asyncio.AbstractEventLoop | None = None

ENGINES: dict[str, Engine] = {}
tdlng_engine: TdlngEngine | None = None
tiddl_engine: TiddlEngine | None = None
settings = None  # tidal Settings singleton (rebound after reload)
tidal = None  # tidal Tidal singleton
pending_auth_engine: str | None = None

_CANON_TO_UI_TOKENS: dict[str, str] = {
    "{artist_name}": "{Artist}",
    "{album_title}": "{Album}",
    "{track_title}": "{Track}",
    "{album_track_num}": "{TrackNumber}",
    "{playlist_name}": "{Playlist}",
    "{mix_name}": "{Mix}",
    "{track_explicit}": "{Explicit}",
    "{album_explicit}": "{Explicit}",
    "{track_volume_num_optional}": "{Disc}",
}
_UI_TO_CANON_TOKENS: dict[str, str] = {
    "artist": "{artist_name}",
    "album": "{album_title}",
    "track": "{track_title}",
    "tracknumber": "{album_track_num}",
    "playlist": "{playlist_name}",
    "mix": "{mix_name}",
    "explicit": "{track_explicit}",
    "disc": "{track_volume_num_optional}",
}


def _to_ui_template(template: str) -> str:
    out = str(template or "")
    for old, new in _CANON_TO_UI_TOKENS.items():
        out = out.replace(old, new)
    return out


def _from_ui_template(template: str, fallback: str) -> str:
    raw = str(template or "").strip()
    if not raw:
        return fallback

    def repl(m: re.Match[str]) -> str:
        token = m.group(1).strip()
        if not token:
            return m.group(0)
        mapped = _UI_TO_CANON_TOKENS.get(token.lower())
        return mapped if mapped else m.group(0)

    out = re.sub(r"\{([^{}]+)\}", repl, raw)
    out = re.sub(r"\s*/\s*", "/", out)
    out = re.sub(r"/{2,}", "/", out)
    return out


def broadcast(payload: dict[str, Any]):
    if _loop and payload:
        fut = asyncio.run_coroutine_threadsafe(_broadcast_async(payload), _loop)

        def _log_broadcast_exc(f) -> None:
            if f.cancelled():
                return
            exc = f.exception()
            if exc is not None:
                logger.error("WebSocket broadcast failed: %s", exc, exc_info=exc)

        fut.add_done_callback(_log_broadcast_exc)
    return {"ok": True}


async def _broadcast_async(payload: dict[str, Any]):
    message = json.dumps(payload)
    dead: list[WebSocket] = []
    for ws in list(ws_connections):
        try:
            await ws.send_text(message)
        except Exception:
            dead.append(ws)
    for ws in dead:
        try:
            ws_connections.remove(ws)
        except ValueError:
            pass


def get_active_engine_name() -> Literal["tidal-dl-ng", "tiddl"]:
    env = os.environ.get("ACTIVE_ENGINE", "").strip().lower()
    if env in ("tiddl", "tidal-dl-ng"):
        return env  # type: ignore[return-value]
    return unified_state.load_settings().active_engine


def get_engine() -> Engine:
    name = get_active_engine_name()
    eng = ENGINES.get(name)
    if not eng:
        raise HTTPException(500, f"Engine not initialized: {name}")
    return eng


def _rebind_after_mirror() -> None:
    global settings, tidal
    settings, tidal = reload_tidal_clients()
    try:
        unified_state.merge_identity_from_logged_in_tidal_session(tidal.session)
    except Exception:
        logger.exception("merge tidal identity into unified auth failed")
    if tdlng_engine:
        tdlng_engine.bind(settings, tidal)
    if tiddl_engine:
        tiddl_engine.reload_from_disk()


def _on_tiddl_token_refresh(_payload: dict[str, Any]) -> None:
    _rebind_after_mirror()


@app.on_event("startup")
async def _startup():
    global _loop, settings, tidal, tdlng_engine, tiddl_engine
    # Must use the *running* uvicorn loop; a sync startup runs in a threadpool
    # where ``asyncio.get_event_loop()`` returns a fresh idle loop, which makes
    # every ``run_coroutine_threadsafe`` silently no-op (queues coroutines to
    # a loop nothing is draining).
    _loop = asyncio.get_running_loop()

    unified_state.migrate_from_native_if_needed()
    us = unified_state.load_settings()
    ua = unified_state.load_auth()

    env_dl = os.environ.get("DOWNLOAD_PATH")
    if env_dl and us.download_base_path in ("", "~/download", "~/Downloads", "/home/app/downloads"):
        us.download_base_path = env_dl

    if not us.path_binary_ffmpeg:
        for candidate in ("/usr/bin/ffmpeg", "/usr/local/bin/ffmpeg"):
            if os.path.exists(candidate):
                us.path_binary_ffmpeg = candidate
                logger.info("path_binary_ffmpeg auto-detected at %s", candidate)
                break

    unified_state.mirror_to_disk(us, ua)
    settings, tidal = reload_tidal_clients()
    try:
        unified_state.merge_identity_from_logged_in_tidal_session(tidal.session)
    except Exception:
        logger.exception("startup: merge tidal identity into unified auth failed")

    tdlng_engine = TdlngEngine(broadcast, settings, tidal)
    tiddl_engine = TiddlEngine(broadcast)
    tiddl_engine.on_token_refresh = _on_tiddl_token_refresh

    ENGINES["tidal-dl-ng"] = tdlng_engine
    ENGINES["tiddl"] = tiddl_engine

    logger.info(
        "Tidal DL Pro web backend started (engine=%s, config=%s)",
        get_active_engine_name(),
        os.environ.get("XDG_CONFIG_HOME", "~"),
    )


class SearchPayload(BaseModel):
    query: str
    media_type: str = "Track"


class DownloadAddPayload(BaseModel):
    media_id: str
    media_type: str
    engine: str | None = None


class SettingsPayload(BaseModel):
    download_base_path: str
    quality_audio: str
    quality_video: str
    skip_existing: bool
    download_delay: bool
    lyrics_embed: bool
    lyrics_file: bool
    video_download: bool
    extract_flac: bool
    downloads_concurrent_max: int | None = None
    active_engine: str | None = None
    path_template_track: str | None = None
    path_template_album: str | None = None
    path_template_playlist: str | None = None
    path_template_mix: str | None = None
    path_template_video: str | None = None
    use_single_path_template: bool | None = None


@app.websocket("/ws")
async def ws_endpoint(websocket: WebSocket):
    await websocket.accept()
    ws_connections.append(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        ws_connections.remove(websocket)


@app.get("/api/status")
def status():
    try:
        auth = get_engine().is_authenticated()
    except Exception:
        auth = False
    return {
        "authenticated": bool(auth),
        "queued": len(download_queue),
        "engine": get_active_engine_name(),
    }


@app.post("/api/auth/login")
def auth_login():
    global pending_auth_engine
    pending_auth_engine = get_active_engine_name()
    return ENGINES[pending_auth_engine].start_login()


@app.post("/api/auth/finalize")
def auth_finalize():
    global pending_auth_engine
    name = pending_auth_engine or get_active_engine_name()
    eng = ENGINES.get(name)
    if not eng:
        raise HTTPException(400, "No login in progress")
    try:
        ok = eng.finalize_login()
        if ok:
            pending_auth_engine = None
        return {"authenticated": bool(ok)}
    except Exception as e:
        logger.error("Login finalize error: %s", e)
        return {"authenticated": False}


@app.post("/api/auth/logout")
def auth_logout():
    try:
        if tdlng_engine and tdlng_engine.tidal.session.check_login():
            tdlng_engine.tidal.logout()
    except Exception as e:
        logger.error("tidal logout: %s", e)
    ua = unified_state.load_auth()
    if ua.access_token:
        try:
            from tiddl.core.auth import AuthAPI

            AuthAPI().logout_token(ua.access_token)
        except Exception as e:
            logger.debug("tiddl logout_token: %s", e)
    unified_state.clear_auth()
    _rebind_after_mirror()
    return {"ok": True}


@app.post("/api/search")
def search(data: SearchPayload):
    eng = get_engine()
    if not eng.is_authenticated():
        raise HTTPException(401, "Not authenticated")
    try:
        return eng.search(data.query, data.media_type)
    except Exception:
        logger.exception("search failed")
        raise HTTPException(502, "Search failed")


@app.get("/api/library/lists")
def library_lists():
    eng = get_engine()
    if not eng.is_authenticated():
        raise HTTPException(401, "Not authenticated")
    try:
        return eng.library_lists()
    except Exception:
        logger.exception("library_lists failed")
        raise HTTPException(502, "Failed to load library from TIDAL")


@app.get("/api/library/items/{list_id}")
def library_items(list_id: str):
    eng = get_engine()
    if not eng.is_authenticated():
        raise HTTPException(401, "Not authenticated")
    try:
        return eng.library_items(list_id)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    except LookupError as e:
        raise HTTPException(404, str(e)) from e
    except Exception:
        logger.exception("library_items failed")
        raise HTTPException(502, "Failed to load library items")


@app.post("/api/download/add")
def download_add(data: DownloadAddPayload):
    global download_queue
    eng = get_engine()
    if not eng.is_authenticated():
        raise HTTPException(401, "Not authenticated")
    engine_name = (data.engine or get_active_engine_name()).strip().lower()
    if engine_name not in ENGINES:
        raise HTTPException(400, f"Unknown engine: {engine_name}")
    use_eng = ENGINES[engine_name]
    ids = [m.strip() for m in data.media_id.split(",") if m.strip()]
    added = 0
    for mid in ids:
        resolved = use_eng.resolve_media(mid, data.media_type)
        if resolved:
            download_queue.append(
                {
                    "id": resolved["id"],
                    "title": resolved["title"],
                    "type": resolved["type"],
                    "status": "waiting",
                    "progress": 0,
                    "error": None,
                    "engine": engine_name,
                }
            )
            added += 1
    return {"added": added, "queue_size": len(download_queue)}


@app.get("/api/download/queue")
def download_queue_get():
    return {"queue": download_queue}


def _log_future_exception(fut):
    exc = fut.exception()
    if exc:
        logger.error("Background download worker crashed: %s", exc, exc_info=exc)
        try:
            broadcast({"type": "all_done"})
        except Exception:
            pass


@app.post("/api/download/start")
def download_start():
    if not download_queue:
        return {"message": "Queue is empty"}
    _abort_event.clear()
    fut = _executor.submit(_process_queue)
    fut.add_done_callback(_log_future_exception)
    return {"message": "Processing started"}


@app.delete("/api/download/queue")
def download_queue_clear():
    download_queue.clear()
    return {"ok": True}


@app.get("/api/settings")
def settings_get():
    s = unified_state.load_settings()
    return {
        "download_base_path": str(s.download_base_path),
        "quality_audio": s.quality_audio,
        "quality_video": s.quality_video,
        "skip_existing": bool(s.skip_existing),
        "download_delay": bool(s.download_delay),
        "lyrics_embed": bool(s.lyrics_embed),
        "lyrics_file": bool(s.lyrics_file),
        "video_download": bool(s.video_download),
        "extract_flac": bool(s.extract_flac),
        "downloads_concurrent_max": int(s.downloads_concurrent_max),
        "active_engine": s.active_engine,
        "path_template_track": _to_ui_template(s.format_track),
        "path_template_album": _to_ui_template(s.format_album),
        "path_template_playlist": _to_ui_template(s.format_playlist),
        "path_template_mix": _to_ui_template(s.format_mix),
        "path_template_video": _to_ui_template(s.format_video),
        "use_single_path_template": bool(s.use_single_path_template),
    }


@app.put("/api/settings")
def settings_put(data: SettingsPayload):
    try:
        quality_audio = Quality(data.quality_audio)
    except ValueError:
        raise HTTPException(400, f"Invalid quality_audio: {data.quality_audio!r}") from None
    try:
        quality_video = QualityVideo(str(data.quality_video))
    except ValueError:
        raise HTTPException(400, f"Invalid quality_video: {data.quality_video!r}") from None

    us = unified_state.load_settings()
    ua = unified_state.load_auth()
    us.download_base_path = data.download_base_path
    us.quality_audio = quality_audio.value
    us.quality_video = quality_video.value
    us.skip_existing = data.skip_existing
    us.download_delay = data.download_delay
    us.lyrics_embed = data.lyrics_embed
    us.lyrics_file = data.lyrics_file
    us.video_download = data.video_download
    us.extract_flac = data.extract_flac
    if data.downloads_concurrent_max is not None:
        us.downloads_concurrent_max = max(1, min(5, int(data.downloads_concurrent_max)))
    if data.active_engine is not None and data.active_engine in ("tidal-dl-ng", "tiddl"):
        us.active_engine = data.active_engine  # type: ignore[assignment]
    if data.path_template_track is not None:
        us.format_track = _from_ui_template(data.path_template_track, us.format_track)
    if data.path_template_album is not None:
        us.format_album = _from_ui_template(data.path_template_album, us.format_album)
    if data.path_template_playlist is not None:
        us.format_playlist = _from_ui_template(data.path_template_playlist, us.format_playlist)
    if data.path_template_mix is not None:
        us.format_mix = _from_ui_template(data.path_template_mix, us.format_mix)
    if data.path_template_video is not None:
        us.format_video = _from_ui_template(data.path_template_video, us.format_video)
    if data.use_single_path_template is not None:
        us.use_single_path_template = bool(data.use_single_path_template)
    if us.use_single_path_template:
        us.format_album = us.format_track
        us.format_playlist = us.format_track
        us.format_mix = us.format_track
        us.format_video = us.format_track

    unified_state.mirror_to_disk(us, ua)
    _rebind_after_mirror()
    return {"saved": True}


def _fail_waiting(message: str) -> None:
    for entry in download_queue:
        if entry["status"] == "waiting":
            entry["status"] = "failed"
            entry["progress"] = -1
            entry["error"] = message


def _download_one_entry(entry: dict[str, Any]) -> None:
    # Match UI: processing uses the engine selected in settings now, not the
    # engine active when the item was queued (TIDAL media ids are shared).
    name = get_active_engine_name()
    eng = ENGINES.get(name)
    if not eng:
        entry["status"] = "failed"
        entry["progress"] = -1
        entry["error"] = f"Unknown engine: {name}"
        broadcast(
            {
                "type": "download_failed",
                "title": str(entry["title"]),
                "progress": -1,
            }
        )
        return
    if not eng.is_authenticated():
        entry["status"] = "failed"
        entry["progress"] = -1
        entry["error"] = "Not authenticated with TIDAL"
        broadcast(
            {
                "type": "download_failed",
                "title": str(entry["title"]),
                "progress": -1,
            }
        )
        return
    eng.download_entry(entry, _abort_event.is_set)


def _process_queue():
    if not download_queue:
        broadcast({"type": "all_done"})
        return

    with _queue_lock:
        claimed: list[dict] = []
        for entry in download_queue:
            if entry["status"] == "waiting":
                entry["status"] = "downloading"
                entry["progress"] = 0
                entry["error"] = None
                claimed.append(entry)

    if not claimed:
        broadcast({"type": "all_done"})
        return

    us = unified_state.load_settings()
    concurrent = max(1, min(int(us.downloads_concurrent_max or 3), len(claimed)))
    logger.info("Starting %d download(s) with concurrency=%d", len(claimed), concurrent)

    with ThreadPoolExecutor(max_workers=concurrent, thread_name_prefix="dl-queue") as pool:
        future_map = {pool.submit(_download_one_entry, entry): entry for entry in claimed}
        for fut in as_completed(future_map):
            try:
                fut.result()
            except Exception as e:
                entry = future_map[fut]
                logger.exception("Worker crashed for %s", entry.get("title"))
                entry["status"] = "failed"
                entry["progress"] = -1
                entry["error"] = f"Worker crashed: {e}"

    broadcast({"type": "all_done"})


def _index_path():
    base = Path(__file__).parent
    p = base / "index.html"
    return str(p) if p.exists() else str(base.parent / "index.html")


@app.get("/")
def index():
    return FileResponse(
        _index_path(),
        media_type="text/html",
        headers={
            # Prevent stale frontend JS/HTML after backend hotfixes.
            "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
            "Pragma": "no-cache",
            "Expires": "0",
        },
    )


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
