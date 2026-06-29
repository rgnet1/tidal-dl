from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Callable


class Engine(ABC):
    """Pluggable TIDAL backend (tidal-dl-ng vs tiddl)."""

    name: str
    on_token_refresh: Callable[[dict[str, Any]], None] | None = None

    @abstractmethod
    def is_authenticated(self) -> bool: ...

    @abstractmethod
    def start_login(self) -> dict[str, Any]:
        """Return {authenticated?, login_url?, expires_in?}."""

    @abstractmethod
    def finalize_login(self) -> bool: ...

    @abstractmethod
    def logout(self) -> None: ...

    @abstractmethod
    def library_lists(self) -> dict[str, Any]: ...

    @abstractmethod
    def library_items(self, list_id: str) -> dict[str, Any]: ...

    @abstractmethod
    def search(self, query: str, media_type: str) -> dict[str, Any]: ...

    @abstractmethod
    def resolve_media(self, media_id: str, media_type: str) -> dict[str, Any] | None:
        """Return a queue-ready dict {id,title,type} or None."""

    @abstractmethod
    def download_entry(self, entry: dict[str, Any], abort: Callable[[], bool]) -> None:
        """Mutate entry status/progress/error and emit websocket events via inject."""
