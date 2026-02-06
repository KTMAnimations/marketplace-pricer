from __future__ import annotations

import random
import re
import time
from urllib.parse import quote_plus

from playwright.sync_api import sync_playwright

from marketplace_pricer.config import Settings
from marketplace_pricer.connectors.base import Listing
from marketplace_pricer.db import WatchlistRow
from marketplace_pricer.normalization import normalize_whitespace, parse_usd_to_cents


_FB_ITEM_RE = re.compile(r"/marketplace/item/(?P<id>\d+)")


def _best_src_from_srcset(srcset: str | None) -> str | None:
    if not srcset:
        return None
    # srcset format: "url1 240w, url2 480w, ..."
    best_url = None
    best_w = -1
    for part in srcset.split(","):
        part = part.strip()
        if not part:
            continue
        fields = part.split()
        url = fields[0].strip()
        if not url:
            continue
        w = -1
        if len(fields) >= 2 and fields[1].endswith("w"):
            try:
                w = int(fields[1][:-1])
            except Exception:
                w = -1
        if w >= best_w:
            best_w = w
            best_url = url
    return best_url


def _city_to_slug(city: str) -> str:
    # Mirrors the legacy example mapping from the bundled scraper; extend as needed.
    mapping = {
        "new york": "nyc",
        "los angeles": "la",
        "las vegas": "vegas",
        "chicago": "chicago",
        "houston": "houston",
        "san antonio": "sanantonio",
        "miami": "miami",
        "orlando": "orlando",
        "san diego": "sandiego",
        "arlington": "arlington",
        "baltimore": "baltimore",
        "cincinnati": "cincinnati",
        "denver": "denver",
        "fort worth": "fortworth",
        "jacksonville": "jacksonville",
        "memphis": "memphis",
        "nashville": "nashville",
        "philadelphia": "philly",
        "portland": "portland",
        "san jose": "sanjose",
        "tucson": "tucson",
        "atlanta": "atlanta",
        "boston": "boston",
        "columbus": "columbus",
        "detroit": "detroit",
        "honolulu": "honolulu",
        "kansas city": "kansascity",
        "new orleans": "neworleans",
        "phoenix": "phoenix",
        "seattle": "seattle",
        "washington dc": "dc",
        "milwaukee": "milwaukee",
        "sacramento": "sac",
        "austin": "austin",
        "charlotte": "charlotte",
        "dallas": "dallas",
        "el paso": "elpaso",
        "indianapolis": "indianapolis",
        "louisville": "louisville",
        "minneapolis": "minneapolis",
        "oklahoma city": "oklahoma",
        "pittsburgh": "pittsburgh",
        "san francisco": "sanfrancisco",
        "tampa": "tampa",
    }

    key = city.strip().lower()
    if key in mapping:
        return mapping[key]
    if re.fullmatch(r"[a-z0-9]+", key):
        # already looks like a slug
        return key
    raise ValueError(f"Unsupported Facebook city/slug: {city!r}")


class FacebookMarketplaceConnector:
    source = "facebook"

    def __init__(self, settings: Settings):
        self._settings = settings

    def scan(self, watchlist: WatchlistRow) -> list[Listing]:
        filters = watchlist.filters
        city = filters.get("city") or filters.get("city_slug")
        if not city:
            raise ValueError("Facebook watchlist requires filters.city (e.g. 'boston' or 'Boston')")
        city_slug = _city_to_slug(str(city))

        max_price = filters.get("max_price")
        query = quote_plus(watchlist.query)

        url = f"https://www.facebook.com/marketplace/{city_slug}/search?query={query}"
        if max_price is not None:
            url += f"&maxPrice={int(max_price)}"

        state_path = self._settings.facebook_storage_state_path
        if not state_path.exists():
            raise RuntimeError(
                f"Facebook storage state not found at {state_path}. Run: "
                f"`python -m marketplace_pricer facebook-login` and complete login in the browser."
            )

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=self._settings.facebook_headless)
            context = browser.new_context(storage_state=str(state_path))
            page = context.new_page()

            page.goto(url, wait_until="domcontentloaded")
            time.sleep(random.uniform(2.0, 4.0))

            scrolls = int(filters.get("scrolls", 3))
            for _ in range(max(scrolls, 0)):
                page.mouse.wheel(0, 2500)
                time.sleep(random.uniform(1.5, 3.5))

            anchors = page.locator("a[href*='/marketplace/item/']")
            count = anchors.count()

            seen_ids: set[str] = set()
            out: list[Listing] = []
            for i in range(min(count, int(filters.get("max_results", 60)))):
                a = anchors.nth(i)
                href = a.get_attribute("href")
                if not href:
                    continue

                match = _FB_ITEM_RE.search(href)
                external_id = match.group("id") if match else None
                if external_id and external_id in seen_ids:
                    continue

                text = a.inner_text(timeout=1000) or ""
                lines = [normalize_whitespace(line) for line in text.splitlines()]
                lines = [line for line in lines if line]

                price_cents = None
                title = None
                location = None

                for line in lines:
                    if price_cents is None:
                        maybe = parse_usd_to_cents(line)
                        if maybe is not None:
                            price_cents = maybe
                            continue
                    if title is None and "$" not in line and "·" not in line:
                        title = line
                        continue

                if lines:
                    location = lines[-1]

                image_url = None
                try:
                    img = a.locator("img").first
                    image_url = img.get_attribute("src")
                    if not image_url:
                        image_url = _best_src_from_srcset(img.get_attribute("srcset"))
                except Exception:
                    image_url = None

                full_url = href
                if href.startswith("/"):
                    full_url = f"https://www.facebook.com{href}"

                listing = Listing(
                    source=self.source,
                    external_id=external_id,
                    url=full_url,
                    title=title,
                    price_cents=price_cents,
                    currency="USD",
                    location=location,
                    seller=None,
                    raw={"href": href, "text": text, "watchlist_id": watchlist.id, "image_url": image_url},
                )
                out.append(listing)
                if external_id:
                    seen_ids.add(external_id)

            context.close()
            browser.close()

        return out
