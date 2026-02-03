from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import time
from typing import Any

from marketplace_pricer.alerts.base import AlertChannel, AlertMessage
from marketplace_pricer.alerts.console import ConsoleAlert
from marketplace_pricer.alerts.discord import DiscordWebhookAlert
from marketplace_pricer.alerts.telegram import TelegramBotAlert
from marketplace_pricer.comps.ebay import EbayBrowseClient, estimate_market_price_cents
from marketplace_pricer.config import Settings
from marketplace_pricer.connectors.base import Connector, Listing
from marketplace_pricer.connectors.craigslist_email import CraigslistSavedSearchEmailConnector, ImapConfig
from marketplace_pricer.connectors.facebook import FacebookMarketplaceConnector
from marketplace_pricer.connectors.nextdoor import NextdoorConnector
from marketplace_pricer.db import DB, WatchlistRow
from marketplace_pricer.timeutil import utcnow_iso


@dataclass(frozen=True)
class ScanSummary:
    watchlists_scanned: int
    listings_seen: int
    listings_new: int
    alerts_sent: int


def _iso_to_dt(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def build_alert_channels(settings: Settings) -> list[AlertChannel]:
    channels: list[AlertChannel] = [ConsoleAlert()]

    if settings.discord_webhook_url:
        channels.append(DiscordWebhookAlert(settings.discord_webhook_url))

    if settings.telegram_bot_token and settings.telegram_chat_id:
        channels.append(TelegramBotAlert(settings.telegram_bot_token, settings.telegram_chat_id))

    return channels


def build_connectors(settings: Settings) -> dict[str, Connector]:
    connectors: dict[str, Connector] = {
        "facebook": FacebookMarketplaceConnector(settings),
        "nextdoor": NextdoorConnector(settings),
    }

    if settings.imap_host and settings.imap_username and settings.imap_password:
        connectors["craigslist_email"] = CraigslistSavedSearchEmailConnector(
            ImapConfig(
                host=settings.imap_host,
                username=settings.imap_username,
                password=settings.imap_password,
                folder=settings.imap_folder,
            )
        )

    return connectors


class Scanner:
    def __init__(self, *, settings: Settings, db: DB):
        self._settings = settings
        self._db = db
        self._channels = build_alert_channels(settings)
        self._connectors = build_connectors(settings)

        self._ebay_client: EbayBrowseClient | None = None
        if settings.ebay_client_id and settings.ebay_client_secret:
            self._ebay_client = EbayBrowseClient(settings)

    def scan_due_watchlists_once(self) -> ScanSummary:
        now = datetime.now(timezone.utc)

        watchlists = self._db.list_watchlists(active_only=True)
        scanned = 0
        listings_seen = 0
        listings_new = 0
        alerts_sent = 0

        for watchlist in watchlists:
            if not self._is_due(watchlist, now=now):
                continue
            scanned += 1
            try:
                connector = self._connectors.get(watchlist.source)
                if connector is None:
                    raise RuntimeError(
                        f"No connector configured for source={watchlist.source!r}. "
                        f"(Missing env vars, or not implemented yet.)"
                    )
                listings = connector.scan(watchlist)
            except Exception as exc:
                print(f"[scan] watchlist id={watchlist.id} source={watchlist.source} failed: {exc}")
                self._db.set_watchlist_last_scan_at(watchlist.id)
                continue

            listings_seen += len(listings)

            for listing in listings:
                upsert = self._db.upsert_listing(
                    unique_key=listing.unique_key,
                    source=listing.source,
                    external_id=listing.external_id,
                    url=listing.url,
                    title=listing.title,
                    price_cents=listing.price_cents,
                    currency=listing.currency,
                    location=listing.location,
                    seller=listing.seller,
                    raw=listing.raw,
                )
                if upsert.is_new:
                    listings_new += 1

                if not upsert.is_new:
                    continue
                if self._db.has_alert_for_listing(listing.unique_key, watchlist_id=watchlist.id):
                    continue

                decision = self._should_alert(listing, watchlist)
                if not decision["should_alert"]:
                    continue

                message = self._format_alert(listing, watchlist, decision)
                for channel in self._channels:
                    try:
                        channel.send(message)
                        self._db.record_alert(
                            listing_unique_key=listing.unique_key,
                            watchlist_id=watchlist.id,
                            channel=channel.name,
                            message=message.render_text(),
                        )
                        alerts_sent += 1
                    except Exception as exc:
                        print(f"[alert] channel={channel.name} failed: {exc}")

            self._db.set_watchlist_last_scan_at(watchlist.id)

        return ScanSummary(
            watchlists_scanned=scanned,
            listings_seen=listings_seen,
            listings_new=listings_new,
            alerts_sent=alerts_sent,
        )

    def run_forever(self, *, sleep_seconds: int = 10) -> None:
        print("[scan] running. Ctrl+C to stop.")
        while True:
            summary = self.scan_due_watchlists_once()
            if summary.watchlists_scanned:
                print(
                    f"[scan] watchlists={summary.watchlists_scanned} listings={summary.listings_seen} "
                    f"new={summary.listings_new} alerts={summary.alerts_sent}"
                )
            time.sleep(max(sleep_seconds, 1))

    def _is_due(self, watchlist: WatchlistRow, *, now: datetime) -> bool:
        if not watchlist.last_scan_at:
            return True
        try:
            last = _iso_to_dt(watchlist.last_scan_at)
        except Exception:
            return True
        delta = now - last.astimezone(timezone.utc)
        return delta.total_seconds() >= max(int(watchlist.scan_interval_seconds), 1)

    def _should_alert(self, listing: Listing, watchlist: WatchlistRow) -> dict[str, Any]:
        filters = watchlist.filters
        under_market_pct = float(filters.get("alert_under_market_pct", 0.6))
        alert_without_market = bool(filters.get("alert_without_market_price", False))

        market_price_cents = None
        ebay_items = []
        if self._ebay_client and listing.title:
            try:
                ebay_items = self._ebay_client.search(query=listing.title, limit=int(filters.get("ebay_limit", 20)))
                market_price_cents = estimate_market_price_cents(ebay_items)
                self._db.record_price_estimate(
                    listing_unique_key=listing.unique_key,
                    method="ebay_browse_median",
                    market_price_cents=market_price_cents,
                    estimated_resale_price_cents=market_price_cents,
                    details={"items_used": len(ebay_items)},
                )
            except Exception as exc:
                print(f"[pricing] eBay comps failed: {exc}")

        if listing.price_cents is None:
            return {"should_alert": False, "reason": "no_price", "market_price_cents": market_price_cents}

        if market_price_cents is None:
            return {
                "should_alert": alert_without_market,
                "reason": "no_market_price",
                "market_price_cents": None,
            }

        threshold = int(market_price_cents * under_market_pct)
        return {
            "should_alert": listing.price_cents <= threshold,
            "reason": "under_market" if listing.price_cents <= threshold else "not_under_market",
            "market_price_cents": market_price_cents,
            "threshold_cents": threshold,
        }

    def _format_alert(self, listing: Listing, watchlist: WatchlistRow, decision: dict[str, Any]) -> AlertMessage:
        price = _fmt_money(listing.price_cents)
        title = listing.title or "(no title)"
        market = _fmt_money(decision.get("market_price_cents"))
        profit = None
        if listing.price_cents is not None and decision.get("market_price_cents") is not None:
            profit = decision["market_price_cents"] - listing.price_cents

        lines = [
            f"Watchlist: {watchlist.name} (id={watchlist.id}, source={watchlist.source})",
            f"Title: {title}",
            f"Price: {price}",
        ]
        if market is not None:
            lines.append(f"Market (eBay median): {market}")
        if profit is not None:
            lines.append(f"Potential spread: {_fmt_money(profit)}")
        if listing.location:
            lines.append(f"Location: {listing.location}")
        lines.append(f"Link: {listing.url}")

        return AlertMessage(
            title="🔥 Deal Alert",
            body="\n".join(lines),
        )


def _fmt_money(cents: int | None) -> str | None:
    if cents is None:
        return None
    sign = "-" if cents < 0 else ""
    cents_abs = abs(cents)
    return f"{sign}${cents_abs // 100:,}.{cents_abs % 100:02d}"
