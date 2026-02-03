from __future__ import annotations

from marketplace_pricer.config import Settings
from marketplace_pricer.connectors.base import Listing
from marketplace_pricer.db import WatchlistRow


class NextdoorConnector:
    """
    Placeholder for Nextdoor Marketplace via official API (requires access + token).

    For single-user MVP: keep this connector stubbed until keys/access are configured.
    """

    source = "nextdoor"

    def __init__(self, settings: Settings):
        self._settings = settings

    def scan(self, watchlist: WatchlistRow) -> list[Listing]:
        if not self._settings.nextdoor_access_token:
            raise RuntimeError("Nextdoor connector requires MP_NEXTDOOR_ACCESS_TOKEN to be set.")
        raise NotImplementedError("Nextdoor Search API integration not wired yet.")

