"""Integration tests for the Tidal DL Pro web API (auth, search, library, downloads, settings)."""

from __future__ import annotations

import time
from typing import Any

from fastapi.testclient import TestClient

from tests.conftest import FakeEngine


class TestStatusAndIndex:
    """Health, status, and static UI routes."""

    def test_index_returns_html(self, web_client: tuple[TestClient, FakeEngine, FakeEngine, Any]) -> None:
        client, *_ = web_client
        response = client.get("/")
        assert response.status_code == 200
        assert "text/html" in response.headers["content-type"]
        assert "Tidal DL Pro" in response.text or "app()" in response.text

    def test_status_unauthenticated(self, web_client: tuple[TestClient, FakeEngine, FakeEngine, Any]) -> None:
        client, fake_tdlng, _, main = web_client
        fake_tdlng.authenticated = False
        response = client.get("/api/status")
        assert response.status_code == 200
        body = response.json()
        assert body["authenticated"] is False
        assert body["queued"] == 0
        assert body["engine"] in ("tidal-dl-ng", "tiddl")

    def test_status_authenticated(self, web_client: tuple[TestClient, FakeEngine, FakeEngine, Any]) -> None:
        client, fake_tdlng, _, main = web_client
        fake_tdlng.authenticated = True
        main.download_queue.append({"id": "1", "status": "waiting"})
        response = client.get("/api/status")
        body = response.json()
        assert body["authenticated"] is True
        assert body["queued"] == 1


class TestAuthentication:
    """TIDAL OAuth login, finalize, and logout."""

    def test_login_returns_device_url(self, web_client: tuple[TestClient, FakeEngine, FakeEngine, Any]) -> None:
        client, fake_tdlng, _, _ = web_client
        fake_tdlng.authenticated = False
        response = client.post("/api/auth/login")
        assert response.status_code == 200
        body = response.json()
        assert body["login_url"] == "https://tidal.com/login/example"
        assert body["expires_in"] == 300

    def test_login_when_already_authenticated(
        self, web_client: tuple[TestClient, FakeEngine, FakeEngine, Any]
    ) -> None:
        client, fake_tdlng, _, _ = web_client
        fake_tdlng.authenticated = True
        response = client.post("/api/auth/login")
        assert response.json() == {"authenticated": True}

    def test_finalize_pending(self, web_client: tuple[TestClient, FakeEngine, FakeEngine, Any]) -> None:
        client, fake_tdlng, _, main = web_client
        fake_tdlng.finalize_result = False
        main.pending_auth_engine = "tidal-dl-ng"
        response = client.post("/api/auth/finalize")
        assert response.status_code == 200
        assert response.json() == {"authenticated": False}

    def test_finalize_success(self, web_client: tuple[TestClient, FakeEngine, FakeEngine, Any]) -> None:
        client, fake_tdlng, _, main = web_client
        fake_tdlng.finalize_result = True
        main.pending_auth_engine = "tidal-dl-ng"
        response = client.post("/api/auth/finalize")
        assert response.json() == {"authenticated": True}
        assert fake_tdlng.authenticated is True
        assert main.pending_auth_engine is None

    def test_logout_clears_session(self, web_client: tuple[TestClient, FakeEngine, FakeEngine, Any]) -> None:
        client, fake_tdlng, _, _ = web_client
        fake_tdlng.authenticated = True
        fake_tdlng.tidal.session.check_login.return_value = True
        response = client.post("/api/auth/logout")
        assert response.status_code == 200
        assert response.json() == {"ok": True}


class TestSearch:
    """Search requires authentication and returns engine results."""

    def test_search_requires_auth(self, web_client: tuple[TestClient, FakeEngine, FakeEngine, Any]) -> None:
        client, fake_tdlng, _, _ = web_client
        fake_tdlng.authenticated = False
        response = client.post("/api/search", json={"query": "test track", "media_type": "Track"})
        assert response.status_code == 401

    def test_search_returns_results(self, web_client: tuple[TestClient, FakeEngine, FakeEngine, Any]) -> None:
        client, fake_tdlng, _, _ = web_client
        fake_tdlng.authenticated = True
        fake_tdlng.search_response = {
            "results": [
                {
                    "id": "123",
                    "title": "Example Track",
                    "type": "Track",
                    "artist": "Example Artist",
                }
            ]
        }
        response = client.post("/api/search", json={"query": "example", "media_type": "Track"})
        assert response.status_code == 200
        body = response.json()
        assert len(body["results"]) == 1
        assert body["results"][0]["title"] == "Example Track"


class TestLibrary:
    """User library lists and item browsing."""

    def test_library_lists_requires_auth(self, web_client: tuple[TestClient, FakeEngine, FakeEngine, Any]) -> None:
        client, fake_tdlng, _, _ = web_client
        fake_tdlng.authenticated = False
        response = client.get("/api/library/lists")
        assert response.status_code == 401

    def test_library_lists_success(self, web_client: tuple[TestClient, FakeEngine, FakeEngine, Any]) -> None:
        client, fake_tdlng, _, _ = web_client
        fake_tdlng.authenticated = True
        fake_tdlng.library_lists_response = {
            "playlists": [{"id": "pl-1", "title": "My Playlist"}],
            "mixes": [],
            "favorites": [{"id": "fav_tracks", "title": "Favorite Tracks"}],
        }
        response = client.get("/api/library/lists")
        assert response.status_code == 200
        body = response.json()
        assert body["playlists"][0]["title"] == "My Playlist"
        assert body["favorites"][0]["id"] == "fav_tracks"

    def test_library_items_success(self, web_client: tuple[TestClient, FakeEngine, FakeEngine, Any]) -> None:
        client, fake_tdlng, _, _ = web_client
        fake_tdlng.authenticated = True
        fake_tdlng.library_items_response = {
            "items": [{"id": "t-1", "title": "Song One", "type": "Track"}]
        }
        response = client.get("/api/library/items/pl-1")
        assert response.status_code == 200
        assert response.json()["items"][0]["title"] == "Song One"

    def test_library_items_not_found(self, web_client: tuple[TestClient, FakeEngine, FakeEngine, Any]) -> None:
        client, fake_tdlng, _, _ = web_client
        fake_tdlng.authenticated = True
        response = client.get("/api/library/items/missing")
        assert response.status_code == 404

    def test_library_items_bad_request(self, web_client: tuple[TestClient, FakeEngine, FakeEngine, Any]) -> None:
        client, fake_tdlng, _, _ = web_client
        fake_tdlng.authenticated = True
        response = client.get("/api/library/items/bad")
        assert response.status_code == 400


class TestDownloadQueue:
    """Add items to queue, start processing, and clear."""

    def test_download_add_requires_auth(self, web_client: tuple[TestClient, FakeEngine, FakeEngine, Any]) -> None:
        client, fake_tdlng, _, _ = web_client
        fake_tdlng.authenticated = False
        response = client.post(
            "/api/download/add",
            json={"media_id": "123", "media_type": "Track"},
        )
        assert response.status_code == 401

    def test_download_add_single_item(self, web_client: tuple[TestClient, FakeEngine, FakeEngine, Any]) -> None:
        client, fake_tdlng, _, main = web_client
        fake_tdlng.authenticated = True
        fake_tdlng.resolve_map = {
            "123": {"id": "123", "title": "Track One", "type": "Track"},
        }
        response = client.post(
            "/api/download/add",
            json={"media_id": "123", "media_type": "Track"},
        )
        assert response.status_code == 200
        body = response.json()
        assert body["added"] == 1
        assert body["queue_size"] == 1
        assert main.download_queue[0]["status"] == "waiting"
        assert main.download_queue[0]["title"] == "Track One"

    def test_download_add_multiple_comma_separated(
        self, web_client: tuple[TestClient, FakeEngine, FakeEngine, Any]
    ) -> None:
        client, fake_tdlng, _, _ = web_client
        fake_tdlng.authenticated = True
        fake_tdlng.resolve_map = {
            "1": {"id": "1", "title": "A", "type": "Track"},
            "2": {"id": "2", "title": "B", "type": "Track"},
        }
        response = client.post(
            "/api/download/add",
            json={"media_id": "1, 2", "media_type": "Track"},
        )
        body = response.json()
        assert body["added"] == 2
        assert body["queue_size"] == 2

    def test_download_add_unknown_engine(self, web_client: tuple[TestClient, FakeEngine, FakeEngine, Any]) -> None:
        client, fake_tdlng, _, _ = web_client
        fake_tdlng.authenticated = True
        response = client.post(
            "/api/download/add",
            json={"media_id": "1", "media_type": "Track", "engine": "unknown"},
        )
        assert response.status_code == 400

    def test_download_queue_get_and_clear(self, web_client: tuple[TestClient, FakeEngine, FakeEngine, Any]) -> None:
        client, fake_tdlng, _, main = web_client
        fake_tdlng.authenticated = True
        fake_tdlng.resolve_map = {"9": {"id": "9", "title": "Queued", "type": "Track"}}
        client.post("/api/download/add", json={"media_id": "9", "media_type": "Track"})
        get_resp = client.get("/api/download/queue")
        assert len(get_resp.json()["queue"]) == 1
        clear_resp = client.delete("/api/download/queue")
        assert clear_resp.json() == {"ok": True}
        assert client.get("/api/download/queue").json()["queue"] == []

    def test_download_start_empty_queue(self, web_client: tuple[TestClient, FakeEngine, FakeEngine, Any]) -> None:
        client, *_ = web_client
        response = client.post("/api/download/start")
        assert response.status_code == 200
        assert response.json()["message"] == "Queue is empty"

    def test_download_start_processes_queue(self, web_client: tuple[TestClient, FakeEngine, FakeEngine, Any]) -> None:
        client, fake_tdlng, _, _ = web_client
        fake_tdlng.authenticated = True
        fake_tdlng.resolve_map = {
            "42": {"id": "42", "title": "Download Me", "type": "Track"},
        }
        client.post("/api/download/add", json={"media_id": "42", "media_type": "Track"})
        response = client.post("/api/download/start")
        assert response.status_code == 200
        assert response.json()["message"] == "Processing started"

        deadline = time.time() + 5.0
        final_status = "waiting"
        while time.time() < deadline:
            queue = client.get("/api/download/queue").json()["queue"]
            if queue and queue[0]["status"] in ("done", "failed", "downloading"):
                final_status = queue[0]["status"]
            if final_status == "done":
                break
            time.sleep(0.05)

        assert final_status == "done"
        assert len(fake_tdlng.download_calls) == 1
        assert fake_tdlng.download_calls[0]["title"] == "Download Me"


class TestSettings:
    """Read and update unified download settings."""

    def test_settings_get_defaults(self, web_client: tuple[TestClient, FakeEngine, FakeEngine, Any]) -> None:
        client, *_ = web_client
        response = client.get("/api/settings")
        assert response.status_code == 200
        body = response.json()
        assert "download_base_path" in body
        assert "quality_audio" in body
        assert body["active_engine"] in ("tidal-dl-ng", "tiddl")

    def test_settings_put_valid(
        self, web_client: tuple[TestClient, FakeEngine, FakeEngine, Any], settings_payload: dict
    ) -> None:
        client, *_ = web_client
        response = client.put("/api/settings", json=settings_payload)
        assert response.status_code == 200
        assert response.json() == {"saved": True}

        saved = client.get("/api/settings").json()
        assert saved["quality_audio"] == "LOSSLESS"
        assert saved["quality_video"] == "720"
        assert saved["downloads_concurrent_max"] == 2
        assert saved["active_engine"] == "tidal-dl-ng"

    def test_settings_put_invalid_audio_quality(
        self, web_client: tuple[TestClient, FakeEngine, FakeEngine, Any], settings_payload: dict
    ) -> None:
        client, *_ = web_client
        settings_payload["quality_audio"] = "NOT_A_REAL_QUALITY"
        response = client.put("/api/settings", json=settings_payload)
        assert response.status_code == 400


class TestWebSocket:
    """Real-time download progress channel."""

    def test_websocket_accepts_connection(self, web_client: tuple[TestClient, FakeEngine, FakeEngine, Any]) -> None:
        client, *_ = web_client
        with client.websocket_connect("/ws") as ws:
            ws.send_text("ping")
