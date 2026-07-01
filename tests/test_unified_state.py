"""Tests for unified settings/auth persistence used by the web UI."""

from __future__ import annotations

from typing import Any

import pytest

from web import unified_state


class TestUnifiedState:
    """Settings and auth round-trip through unified JSON files."""

    def test_settings_save_and_load(self, config_dir: Any) -> None:
        settings = unified_state.UnifiedSettings(
            download_base_path="/downloads/music",
            quality_audio="LOSSLESS",
            quality_video="1080",
            active_engine="tiddl",
            downloads_concurrent_max=4,
        )
        auth = unified_state.UnifiedAuth()
        unified_state.save_settings(settings)
        unified_state.save_auth(auth)

        loaded = unified_state.load_settings()
        assert loaded.download_base_path == "/downloads/music"
        assert loaded.quality_audio == "LOSSLESS"
        assert loaded.quality_video == "1080"
        assert loaded.active_engine == "tiddl"
        assert loaded.downloads_concurrent_max == 4

    def test_auth_save_and_clear(self, config_dir: Any) -> None:
        auth = unified_state.UnifiedAuth(
            access_token="access-123",
            refresh_token="refresh-456",
            expires_at=9999999999,
            user_id="user-1",
            country_code="US",
        )
        unified_state.save_auth(auth)
        loaded = unified_state.load_auth()
        assert loaded.access_token == "access-123"
        assert loaded.user_id == "user-1"

        unified_state.clear_auth()
        cleared = unified_state.load_auth()
        assert cleared.access_token is None
        assert cleared.refresh_token is None

    def test_mirror_to_disk_writes_engine_files(self, config_dir: Any) -> None:
        settings = unified_state.UnifiedSettings(download_base_path="/downloads")
        auth = unified_state.UnifiedAuth(
            access_token="tok",
            refresh_token="ref",
            expires_at=9999999999,
            user_id="u1",
            country_code="US",
        )
        unified_state.mirror_to_disk(settings, auth)

        assert unified_state.unified_settings_path().exists()
        assert unified_state.unified_auth_path().exists()
        assert unified_state.tidal_settings_path().exists()
        assert unified_state.tidal_token_path().exists()
        assert unified_state.tiddl_config_path().exists()
        assert unified_state.tiddl_auth_path().exists()

    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            (None, 0),
            (0, 0),
            (1705330200, 1705330200),
            (1705330200123, 1705330200),
        ],
    )
    def test_oauth_expiry_to_unix_seconds(self, value: Any, expected: int) -> None:
        assert unified_state.oauth_expiry_to_unix_seconds(value) == expected
