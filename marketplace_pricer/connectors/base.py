from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from marketplace_pricer.db import WatchlistRow


@dataclass(frozen=True)
class Listing:
    source: str
    external_id: str | None
    url: str
    title: str | None
    price_cents: int | None
    currency: str
    location: str | None
    seller: str | None
    raw: dict[str, Any]

    @property
    def unique_key(self) -> str:
        stable_id = self.external_id or self.url
        return f"{self.source}:{stable_id}"


class Connector(Protocol):
    source: str

    def scan(self, watchlist: WatchlistRow) -> list[Listing]:
        """Return 0..n listings currently matching the watchlist."""

