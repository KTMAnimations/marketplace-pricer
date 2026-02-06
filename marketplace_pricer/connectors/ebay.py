from __future__ import annotations

from marketplace_pricer.comps.ebay import EbayBrowseClient
from marketplace_pricer.config import Settings
from marketplace_pricer.connectors.base import Listing
from marketplace_pricer.db import WatchlistRow


class EbayMarketplaceConnector:
    source = "ebay"

    def __init__(self, settings: Settings):
        self._client = EbayBrowseClient(settings)

    def scan(self, watchlist: WatchlistRow) -> list[Listing]:
        filters = watchlist.filters
        limit = int(filters.get("max_results", 60))
        min_price = filters.get("min_price")
        max_price = filters.get("max_price")

        items = self._client.search(query=watchlist.query, limit=limit)

        out: list[Listing] = []
        for item in items:
            if not item.url:
                continue

            if min_price is not None and item.price_cents is not None and item.price_cents < int(min_price) * 100:
                continue
            if max_price is not None and item.price_cents is not None and item.price_cents > int(max_price) * 100:
                continue

            out.append(
                Listing(
                    source=self.source,
                    external_id=item.item_id,
                    url=item.url,
                    title=item.title,
                    price_cents=item.price_cents,
                    currency=item.currency or "USD",
                    location=item.location,
                    seller=item.seller,
                    raw={
                        "watchlist_id": watchlist.id,
                        "item_id": item.item_id,
                        "image_url": item.image_url,
                        "location": item.location,
                        "seller": item.seller,
                    },
                )
            )

        return out

