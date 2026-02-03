from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
import sqlite3
from typing import Any

from marketplace_pricer.timeutil import utcnow_iso


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS watchlists (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL,
  source TEXT NOT NULL,
  query TEXT NOT NULL,
  filters_json TEXT NOT NULL DEFAULT '{}',
  scan_interval_seconds INTEGER NOT NULL DEFAULT 300,
  active INTEGER NOT NULL DEFAULT 1,
  last_scan_at TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_watchlists_active ON watchlists(active);

CREATE TABLE IF NOT EXISTS listings (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  unique_key TEXT NOT NULL UNIQUE,
  source TEXT NOT NULL,
  external_id TEXT,
  url TEXT NOT NULL,
  title TEXT,
  price_cents INTEGER,
  currency TEXT NOT NULL DEFAULT 'USD',
  location TEXT,
  seller TEXT,
  first_seen_at TEXT NOT NULL,
  last_seen_at TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'active',
  raw_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_listings_source_last_seen ON listings(source, last_seen_at);

CREATE TABLE IF NOT EXISTS listing_observations (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  listing_unique_key TEXT NOT NULL,
  observed_at TEXT NOT NULL,
  price_cents INTEGER,
  raw_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_obs_listing ON listing_observations(listing_unique_key);

CREATE TABLE IF NOT EXISTS price_estimates (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  listing_unique_key TEXT NOT NULL,
  computed_at TEXT NOT NULL,
  method TEXT NOT NULL,
  market_price_cents INTEGER,
  estimated_resale_price_cents INTEGER,
  details_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS alerts (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  listing_unique_key TEXT NOT NULL,
  watchlist_id INTEGER NOT NULL,
  channel TEXT NOT NULL,
  sent_at TEXT NOT NULL,
  message TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'sent'
);
CREATE INDEX IF NOT EXISTS idx_alerts_listing ON alerts(listing_unique_key);

CREATE TABLE IF NOT EXISTS inventory (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  listing_unique_key TEXT,
  kind TEXT NOT NULL,
  amount_cents INTEGER NOT NULL,
  fees_cents INTEGER NOT NULL DEFAULT 0,
  occurred_at TEXT NOT NULL,
  notes TEXT
);
CREATE INDEX IF NOT EXISTS idx_inventory_occurred_at ON inventory(occurred_at);
"""


@dataclass(frozen=True)
class WatchlistRow:
    id: int
    name: str
    source: str
    query: str
    filters: dict[str, Any]
    scan_interval_seconds: int
    active: bool
    last_scan_at: str | None


@dataclass(frozen=True)
class ListingUpsertResult:
    unique_key: str
    is_new: bool


class DB:
    def __init__(self, sqlite_path: Path):
        self._sqlite_path = sqlite_path

    def connect(self) -> sqlite3.Connection:
        self._sqlite_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self._sqlite_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA foreign_keys=ON;")
        return conn

    def init_schema(self) -> None:
        with self.connect() as conn:
            conn.executescript(SCHEMA_SQL)

    def add_watchlist(
        self,
        *,
        name: str,
        source: str,
        query: str,
        filters: dict[str, Any] | None = None,
        scan_interval_seconds: int = 300,
        active: bool = True,
    ) -> int:
        now = utcnow_iso()
        filters_json = json.dumps(filters or {}, separators=(",", ":"), sort_keys=True)
        with self.connect() as conn:
            cur = conn.execute(
                """
                INSERT INTO watchlists
                  (name, source, query, filters_json, scan_interval_seconds, active, created_at, updated_at)
                VALUES
                  (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (name, source, query, filters_json, scan_interval_seconds, 1 if active else 0, now, now),
            )
            return int(cur.lastrowid)

    def list_watchlists(self, *, active_only: bool = True) -> list[WatchlistRow]:
        where = "WHERE active=1" if active_only else ""
        with self.connect() as conn:
            rows = conn.execute(
                f"""
                SELECT id, name, source, query, filters_json, scan_interval_seconds, active, last_scan_at
                FROM watchlists
                {where}
                ORDER BY id ASC
                """
            ).fetchall()
        watchlists: list[WatchlistRow] = []
        for row in rows:
            filters = json_loads_or_empty(row["filters_json"])
            watchlists.append(
                WatchlistRow(
                    id=int(row["id"]),
                    name=str(row["name"]),
                    source=str(row["source"]),
                    query=str(row["query"]),
                    filters=filters,
                    scan_interval_seconds=int(row["scan_interval_seconds"]),
                    active=bool(row["active"]),
                    last_scan_at=row["last_scan_at"],
                )
            )
        return watchlists

    def set_watchlist_last_scan_at(self, watchlist_id: int, *, last_scan_at: str | None = None) -> None:
        now = utcnow_iso()
        last_scan_at = last_scan_at or now
        with self.connect() as conn:
            conn.execute(
                "UPDATE watchlists SET last_scan_at=?, updated_at=? WHERE id=?",
                (last_scan_at, now, watchlist_id),
            )

    def get_listing(self, unique_key: str) -> sqlite3.Row | None:
        with self.connect() as conn:
            return conn.execute("SELECT * FROM listings WHERE unique_key=?", (unique_key,)).fetchone()

    def upsert_listing(
        self,
        *,
        unique_key: str,
        source: str,
        external_id: str | None,
        url: str,
        title: str | None,
        price_cents: int | None,
        currency: str = "USD",
        location: str | None,
        seller: str | None,
        raw: dict[str, Any],
        observed_at: str | None = None,
    ) -> ListingUpsertResult:
        observed_at = observed_at or utcnow_iso()
        raw_json = json.dumps(raw, separators=(",", ":"), sort_keys=True)

        with self.connect() as conn:
            existing = conn.execute(
                "SELECT first_seen_at FROM listings WHERE unique_key=?",
                (unique_key,),
            ).fetchone()
            if existing is None:
                conn.execute(
                    """
                    INSERT INTO listings
                      (unique_key, source, external_id, url, title, price_cents, currency, location, seller,
                       first_seen_at, last_seen_at, raw_json)
                    VALUES
                      (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        unique_key,
                        source,
                        external_id,
                        url,
                        title,
                        price_cents,
                        currency,
                        location,
                        seller,
                        observed_at,
                        observed_at,
                        raw_json,
                    ),
                )
                is_new = True
            else:
                conn.execute(
                    """
                    UPDATE listings
                    SET external_id=?,
                        url=?,
                        title=?,
                        price_cents=?,
                        currency=?,
                        location=?,
                        seller=?,
                        last_seen_at=?,
                        raw_json=?
                    WHERE unique_key=?
                    """,
                    (
                        external_id,
                        url,
                        title,
                        price_cents,
                        currency,
                        location,
                        seller,
                        observed_at,
                        raw_json,
                        unique_key,
                    ),
                )
                is_new = False

            conn.execute(
                """
                INSERT INTO listing_observations
                  (listing_unique_key, observed_at, price_cents, raw_json)
                VALUES
                  (?, ?, ?, ?)
                """,
                (unique_key, observed_at, price_cents, raw_json),
            )

        return ListingUpsertResult(unique_key=unique_key, is_new=is_new)

    def record_alert(
        self,
        *,
        listing_unique_key: str,
        watchlist_id: int,
        channel: str,
        message: str,
        sent_at: str | None = None,
    ) -> None:
        sent_at = sent_at or utcnow_iso()
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO alerts (listing_unique_key, watchlist_id, channel, sent_at, message)
                VALUES (?, ?, ?, ?, ?)
                """,
                (listing_unique_key, watchlist_id, channel, sent_at, message),
            )

    def has_alert_for_listing(self, listing_unique_key: str, *, watchlist_id: int) -> bool:
        with self.connect() as conn:
            row = conn.execute(
                """
                SELECT 1 FROM alerts
                WHERE listing_unique_key=? AND watchlist_id=?
                LIMIT 1
                """,
                (listing_unique_key, watchlist_id),
            ).fetchone()
            return row is not None

    def record_price_estimate(
        self,
        *,
        listing_unique_key: str,
        method: str,
        market_price_cents: int | None,
        estimated_resale_price_cents: int | None,
        details: dict[str, Any] | None = None,
        computed_at: str | None = None,
    ) -> None:
        computed_at = computed_at or utcnow_iso()
        details_json = json.dumps(details or {}, separators=(",", ":"), sort_keys=True)
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO price_estimates
                  (listing_unique_key, computed_at, method, market_price_cents, estimated_resale_price_cents, details_json)
                VALUES
                  (?, ?, ?, ?, ?, ?)
                """,
                (
                    listing_unique_key,
                    computed_at,
                    method,
                    market_price_cents,
                    estimated_resale_price_cents,
                    details_json,
                ),
            )

    def record_inventory(
        self,
        *,
        kind: str,
        amount_cents: int,
        fees_cents: int = 0,
        occurred_at: str | None = None,
        listing_unique_key: str | None = None,
        notes: str | None = None,
    ) -> None:
        occurred_at = occurred_at or utcnow_iso()
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO inventory (listing_unique_key, kind, amount_cents, fees_cents, occurred_at, notes)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (listing_unique_key, kind, amount_cents, fees_cents, occurred_at, notes),
            )


def json_loads_or_empty(raw: str | None) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    if isinstance(parsed, dict):
        return parsed
    return {}
