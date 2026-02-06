from __future__ import annotations

import base64
import json
from dataclasses import dataclass
from pathlib import Path
import time
from typing import Any

import requests

from marketplace_pricer.config import Settings


@dataclass(frozen=True)
class EbayItem:
    item_id: str | None
    title: str | None
    url: str | None
    price_cents: int | None
    currency: str | None
    image_url: str | None
    location: str | None
    seller: str | None


class EbayBrowseClient:
    """
    Lightweight wrapper for eBay application auth and basic keyword search.

    Notes:
    - This is intended for *market price estimation* (comps), not necessarily arbitrage on eBay itself.
    - Uses application credentials; you must provide your own client id/secret via env vars.
    """

    def __init__(self, settings: Settings):
        self._settings = settings
        self._token_cache_path = Path(settings.data_dir) / "ebay_app_token.json"

    def _token_cached(self) -> str | None:
        if not self._token_cache_path.exists():
            return None
        try:
            raw = json.loads(self._token_cache_path.read_text("utf-8"))
        except Exception:
            return None
        token = raw.get("access_token")
        expires_at = raw.get("expires_at")
        if not token or not expires_at:
            return None
        if time.time() + 60 >= float(expires_at):
            return None
        return str(token)

    def _token_save(self, token: str, *, expires_in: int) -> None:
        self._token_cache_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "access_token": token,
            "expires_at": time.time() + int(expires_in),
        }
        self._token_cache_path.write_text(json.dumps(payload, separators=(",", ":")), encoding="utf-8")

    def get_app_token(self) -> str:
        cached = self._token_cached()
        if cached:
            return cached

        if not self._settings.ebay_client_id or not self._settings.ebay_client_secret:
            raise RuntimeError("Set MP_EBAY_CLIENT_ID and MP_EBAY_CLIENT_SECRET to use eBay comps.")

        auth = base64.b64encode(
            f"{self._settings.ebay_client_id}:{self._settings.ebay_client_secret}".encode("utf-8")
        ).decode("ascii")

        resp = requests.post(
            "https://api.ebay.com/identity/v1/oauth2/token",
            headers={
                "Authorization": f"Basic {auth}",
                "Content-Type": "application/x-www-form-urlencoded",
            },
            data={
                "grant_type": "client_credentials",
                "scope": "https://api.ebay.com/oauth/api_scope",
            },
            timeout=20,
        )
        resp.raise_for_status()
        body = resp.json()
        token = body["access_token"]
        expires_in = int(body.get("expires_in", 7200))
        self._token_save(token, expires_in=expires_in)
        return token

    def search(self, *, query: str, limit: int = 20) -> list[EbayItem]:
        token = self.get_app_token()
        resp = requests.get(
            "https://api.ebay.com/buy/browse/v1/item_summary/search",
            headers={
                "Authorization": f"Bearer {token}",
                "X-EBAY-C-MARKETPLACE-ID": "EBAY_US",
            },
            params={"q": query, "limit": str(int(limit))},
            timeout=20,
        )
        resp.raise_for_status()
        data: dict[str, Any] = resp.json()

        out: list[EbayItem] = []
        for item in data.get("itemSummaries", []) or []:
            price = item.get("price") or {}
            value = price.get("value")
            currency = price.get("currency")
            cents = None
            if value is not None:
                try:
                    cents = int(round(float(value) * 100))
                except Exception:
                    cents = None

            image_url = None
            image = item.get("image")
            if isinstance(image, dict):
                image_url = image.get("imageUrl") or image.get("url")
            if not image_url:
                thumbs = item.get("thumbnailImages")
                if isinstance(thumbs, list) and thumbs:
                    first = thumbs[0]
                    if isinstance(first, dict):
                        image_url = first.get("imageUrl") or first.get("url")

            location = None
            loc = item.get("itemLocation")
            if isinstance(loc, dict):
                city = loc.get("city")
                region = loc.get("stateOrProvince")
                country = loc.get("country")
                if city and region:
                    location = f"{city}, {region}"
                elif city and country:
                    location = f"{city}, {country}"
                elif region and country:
                    location = f"{region}, {country}"
                elif country:
                    location = str(country)

            seller = None
            seller_info = item.get("seller") or {}
            if isinstance(seller_info, dict):
                seller = seller_info.get("username") or seller_info.get("sellerUsername")
            out.append(
                EbayItem(
                    item_id=item.get("itemId"),
                    title=item.get("title"),
                    url=item.get("itemWebUrl"),
                    price_cents=cents,
                    currency=currency,
                    image_url=image_url,
                    location=location,
                    seller=seller,
                )
            )
        return out


def estimate_market_price_cents(items: list[EbayItem]) -> int | None:
    prices = [i.price_cents for i in items if i.price_cents is not None and i.price_cents > 0]
    if not prices:
        return None
    prices.sort()
    return prices[len(prices) // 2]
