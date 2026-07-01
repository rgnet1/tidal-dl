"""Shared fixtures for web API integration tests."""

from __future__ import annotations

from collections.abc import Generator
from typing import Any
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from web.engines.base import Engine


def _stub_tiddl_modules() -> None:
    """Allow importing web.main without the optional tiddl package (Docker-only runtime dep)."""
    import sys
    import types

    if "tiddl.core.api" in sys.modules:
        return

    def _mod(name: str, attrs: dict[str, Any] | None = None) -> types.ModuleType:
        module = types.ModuleType(name)
        for key, value in (attrs or {}).items():
            setattr(module, key, value)
        sys.modules[name] = module
        return module

    api_exceptions = _mod("tiddl.core.api.exceptions", {"ApiError": Exception})
    resources = _mod(
        "tiddl.core.api.models.resources",
        {
            "Album": object,
            "Artist": object,
            "Playlist": object,
            "StreamVideoQuality": object,
            "Track": object,
            "TrackQuality": str,
            "Video": object,
        },
    )
    models = _mod("tiddl.core.api.models")
    models.resources = resources
    api = _mod("tiddl.core.api", {"TidalAPI": MagicMock, "TidalClient": MagicMock})
    api.exceptions = api_exceptions
    api.models = models

    auth_exceptions = _mod("tiddl.core.auth.exceptions", {"AuthClientError": Exception})
    auth = _mod("tiddl.core.auth", {"AuthAPI": MagicMock})
    auth.exceptions = auth_exceptions

    ffmpeg = _mod("tiddl.core.utils.ffmpeg", {"extract_flac": MagicMock})
    utils = _mod(
        "tiddl.core.utils",
        {"get_track_stream_data": MagicMock, "get_video_stream_data": MagicMock},
    )
    utils.ffmpeg = ffmpeg

    metadata = _mod("tiddl.core.metadata", {"add_track_metadata": MagicMock})
    core = _mod("tiddl.core")
    core.api = api
    core.auth = auth
    core.metadata = metadata
    core.utils = utils
    tiddl = _mod("tiddl")
    tiddl.core = core


class FakeEngine(Engine):
    """In-memory engine stub for HTTP route tests (no TIDAL network calls)."""

    name: str

    def __init__(self, name: str, *, authenticated: bool = False) -> None:
        self.name = name
        self.authenticated = authenticated
        self.broadcast_fn: Any = None
        self.tidal = MagicMock()
        self.tidal.session.check_login.return_value = authenticated
        self.login_response: dict[str, Any] = {
            "login_url": "https://tidal.com/login/example",
            "expires_in": 300,
        }
        self.finalize_result = False
        self.search_response: dict[str, Any] = {"results": []}
        self.library_lists_response: dict[str, Any] = {
            "playlists": [],
            "mixes": [],
            "favorites": [],
        }
        self.library_items_response: dict[str, Any] = {"items": []}
        self.resolve_map: dict[str, dict[str, Any]] = {}
        self.download_calls: list[dict[str, Any]] = []
        self.logout_called = False

    def is_authenticated(self) -> bool:
        return self.authenticated

    def start_login(self) -> dict[str, Any]:
        if self.authenticated:
            return {"authenticated": True}
        return dict(self.login_response)

    def finalize_login(self) -> bool:
        if self.finalize_result:
            self.authenticated = True
        return self.finalize_result

    def logout(self) -> None:
        self.logout_called = True
        self.authenticated = False

    def library_lists(self) -> dict[str, Any]:
        return dict(self.library_lists_response)

    def library_items(self, list_id: str) -> dict[str, Any]:
        if list_id == "missing":
            raise LookupError(f"List not found: {list_id}")
        if list_id == "bad":
            raise ValueError("Invalid list id")
        return dict(self.library_items_response)

    def search(self, query: str, media_type: str) -> dict[str, Any]:
        return dict(self.search_response)

    def resolve_media(self, media_id: str, media_type: str) -> dict[str, Any] | None:
        return self.resolve_map.get(media_id)

    def download_entry(self, entry: dict[str, Any], abort: Any) -> None:
        self.download_calls.append(entry)
        if abort():
            entry["status"] = "failed"
            entry["error"] = "Aborted"
            entry["progress"] = -1
            return
        entry["status"] = "done"
        entry["progress"] = 100
        entry["error"] = None
        if self.broadcast_fn:
            self.broadcast_fn(
                {
                    "type": "download_finished",
                    "title": str(entry["title"]),
                    "progress": 100,
                }
            )


@pytest.fixture
def config_dir(tmp_path: Any, monkeypatch: pytest.MonkeyPatch) -> Any:
    """Isolated config directory for unified_state reads/writes."""
    root = tmp_path / "config"
    root.mkdir()
    (root / "unified").mkdir()
    (root / "tiddl").mkdir(parents=True)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(root))
    monkeypatch.setenv("TIDDL_PATH", str(root / "tiddl"))
    return root


@pytest.fixture
def web_client(
    config_dir: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> Generator[tuple[TestClient, FakeEngine, FakeEngine, Any], None, None]:
    """FastAPI TestClient with fake engines and no real TIDAL session."""
    _stub_tiddl_modules()
    import web.main as main

    fake_tdlng = FakeEngine("tidal-dl-ng")
    fake_tiddl = FakeEngine("tiddl")
    fake_tdlng.broadcast_fn = main.broadcast
    fake_tiddl.broadcast_fn = main.broadcast

    def _fake_tdlng(*_args: Any, **_kwargs: Any) -> FakeEngine:
        return fake_tdlng

    def _fake_tiddl(*_args: Any, **_kwargs: Any) -> FakeEngine:
        return fake_tiddl

    monkeypatch.setattr(main, "TdlngEngine", _fake_tdlng)
    monkeypatch.setattr(main, "TiddlEngine", _fake_tiddl)
    monkeypatch.setattr(main, "reload_tidal_clients", lambda: (MagicMock(), MagicMock()))
    monkeypatch.setattr(main.unified_state, "migrate_from_native_if_needed", lambda: None)
    monkeypatch.setattr(main.unified_state, "merge_identity_from_logged_in_tidal_session", lambda _s: None)
    monkeypatch.setattr(main, "_rebind_after_mirror", lambda: None)

    main.download_queue.clear()
    main.ws_connections.clear()
    main.pending_auth_engine = None
    main.ENGINES.clear()

    with TestClient(main.app) as client:
        yield client, fake_tdlng, fake_tiddl, main

    main.download_queue.clear()
    main.ws_connections.clear()
    main.pending_auth_engine = None


@pytest.fixture
def settings_payload() -> dict[str, Any]:
    """Valid settings body for PUT /api/settings."""
    return {
        "download_base_path": "/downloads",
        "quality_audio": "LOSSLESS",
        "quality_video": "720",
        "skip_existing": True,
        "download_delay": False,
        "lyrics_embed": True,
        "lyrics_file": False,
        "video_download": True,
        "extract_flac": True,
        "downloads_concurrent_max": 2,
        "active_engine": "tidal-dl-ng",
        "path_template_track": "Tracks/{Artist} - {Track}",
        "path_template_album": "Albums/{Artist} - {Album}",
        "path_template_playlist": "Playlists/{Playlist}/{Track}",
        "path_template_mix": "Mix/{Mix}/{Track}",
        "path_template_video": "Videos/{Artist} - {Track}",
        "use_single_path_template": False,
    }
