from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from fastapi import Body, FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from marketplace_pricer.config import Settings
from marketplace_pricer.db import DB, json_loads_or_empty


ALLOWED_LISTING_STATUSES: set[str] = {"active", "saved", "dismissed"}


def _fmt_money(cents: int | None, *, currency: str = "USD") -> str | None:
    if cents is None:
        return None
    if currency != "USD":
        return f"{cents} {currency}"
    sign = "-" if cents < 0 else ""
    cents_abs = abs(int(cents))
    return f"{sign}${cents_abs // 100:,}.{cents_abs % 100:02d}"


def _first_non_empty(*values: Any) -> Any:
    for value in values:
        if value is None:
            continue
        if isinstance(value, str) and not value.strip():
            continue
        if isinstance(value, list) and not value:
            continue
        return value
    return None


def _extract_image_url(raw: dict[str, Any]) -> str | None:
    def _normalize(value: str) -> str | None:
        v = value.strip()
        if not v:
            return None
        if v.startswith(("http://", "https://", "data:", "/")):
            return v
        return "/" + v.lstrip("/")

    value = _first_non_empty(
        raw.get("image_local_url"),
        raw.get("image_local_path"),
        raw.get("image_url"),
        raw.get("image"),
        raw.get("thumbnail_url"),
        raw.get("thumbnail"),
    )
    if isinstance(value, str):
        return _normalize(value)

    for key in ("images", "image_urls", "photos", "photo_urls"):
        maybe = raw.get(key)
        if isinstance(maybe, list) and maybe:
            first = maybe[0]
            if isinstance(first, str) and first.strip():
                return _normalize(first) or first
            if isinstance(first, dict):
                nested = _first_non_empty(first.get("url"), first.get("src"))
                if isinstance(nested, str) and nested.strip():
                    return _normalize(nested) or nested

    return None


def _extract_description(raw: dict[str, Any], *, title: str | None) -> str | None:
    desc = _first_non_empty(raw.get("description"), raw.get("details"), raw.get("text"), raw.get("subject"), raw.get("name"))
    if not isinstance(desc, str):
        return None

    desc = desc.replace("\r", "").strip()
    if not desc:
        return None

    # If it's the same as the title, don't bother.
    if title and desc.strip() == title.strip():
        return None

    # Keep it compact for list rendering.
    if len(desc) > 320:
        return desc[:317].rstrip() + "…"
    return desc


@dataclass(frozen=True)
class MispricingRow:
    unique_key: str
    source: str
    url: str
    title: str | None
    price_cents: int | None
    currency: str
    location: str | None
    seller: str | None
    first_seen_at: str
    last_seen_at: str
    status: str
    raw: dict[str, Any]
    market_price_cents: int | None
    estimated_resale_price_cents: int | None
    pricing_method: str | None
    pricing_computed_at: str | None
    alerts_count: int
    last_alert_at: str | None
    watchlist_id: int | None
    watchlist_name: str | None

    @property
    def spread_cents(self) -> int | None:
        if self.price_cents is None or self.market_price_cents is None:
            return None
        return int(self.market_price_cents) - int(self.price_cents)

    @property
    def pct_of_market(self) -> float | None:
        if self.price_cents is None or self.market_price_cents in (None, 0):
            return None
        return float(self.price_cents) / float(self.market_price_cents)

    def to_api_dict(self) -> dict[str, Any]:
        spread = self.spread_cents
        pct = self.pct_of_market
        discount_pct = None if pct is None else (1.0 - pct) * 100.0

        image_url = _extract_image_url(self.raw)
        description = _extract_description(self.raw, title=self.title)

        return {
            "unique_key": self.unique_key,
            "source": self.source,
            "url": self.url,
            "title": self.title,
            "description": description,
            "image_url": image_url,
            "price_cents": self.price_cents,
            "market_price_cents": self.market_price_cents,
            "estimated_resale_price_cents": self.estimated_resale_price_cents,
            "spread_cents": spread,
            "pct_of_market": pct,
            "discount_pct": discount_pct,
            "currency": self.currency,
            "location": self.location,
            "seller": self.seller,
            "first_seen_at": self.first_seen_at,
            "last_seen_at": self.last_seen_at,
            "status": self.status,
            "alerts_count": self.alerts_count,
            "last_alert_at": self.last_alert_at,
            "watchlist_id": self.watchlist_id,
            "watchlist_name": self.watchlist_name,
            "pricing_method": self.pricing_method,
            "pricing_computed_at": self.pricing_computed_at,
            # Convenience strings for UI rendering
            "price": _fmt_money(self.price_cents, currency=self.currency),
            "market_price": _fmt_money(self.market_price_cents, currency=self.currency),
            "spread": _fmt_money(spread, currency=self.currency),
        }


def _fetch_watchlists(db: DB) -> dict[int, str]:
    watchlists = db.list_watchlists(active_only=False)
    return {w.id: w.name for w in watchlists}


def query_mispricings(
    db: DB,
    *,
    status: str | None,
    only_deals: bool,
    include_unpriced: bool,
    limit: int,
) -> list[MispricingRow]:
    if status is not None and status != "any" and status not in ALLOWED_LISTING_STATUSES:
        raise HTTPException(400, f"Unsupported status filter: {status!r}")

    limit = max(min(int(limit), 2000), 1)

    where_clauses: list[str] = []
    params: list[Any] = []

    if status and status != "any":
        where_clauses.append("l.status=?")
        params.append(status)

    where_sql = ""
    if where_clauses:
        where_sql = "WHERE " + " AND ".join(where_clauses)

    with db.connect() as conn:
        rows = conn.execute(
            f"""
            WITH latest_estimate AS (
              SELECT pe.listing_unique_key,
                     pe.method,
                     pe.computed_at,
                     pe.market_price_cents,
                     pe.estimated_resale_price_cents,
                     pe.details_json
              FROM price_estimates pe
              JOIN (
                SELECT listing_unique_key, MAX(computed_at) AS computed_at
                FROM price_estimates
                GROUP BY listing_unique_key
              ) latest
                ON latest.listing_unique_key = pe.listing_unique_key
               AND latest.computed_at = pe.computed_at
            ),
            alert_rollup AS (
              SELECT listing_unique_key,
                     COUNT(*) AS alerts_count,
                     MAX(sent_at) AS last_alert_at
              FROM alerts
              GROUP BY listing_unique_key
            )
            SELECT
              l.unique_key,
              l.source,
              l.url,
              l.title,
              l.price_cents,
              l.currency,
              l.location,
              l.seller,
              l.first_seen_at,
              l.last_seen_at,
              l.status,
              l.raw_json,
              le.market_price_cents,
              le.estimated_resale_price_cents,
              le.method AS pricing_method,
              le.computed_at AS pricing_computed_at,
              COALESCE(ar.alerts_count, 0) AS alerts_count,
              ar.last_alert_at
            FROM listings l
            LEFT JOIN latest_estimate le ON le.listing_unique_key = l.unique_key
            LEFT JOIN alert_rollup ar ON ar.listing_unique_key = l.unique_key
            {where_sql}
            ORDER BY l.last_seen_at DESC
            LIMIT ?
            """,
            (*params, limit),
        ).fetchall()

    watchlist_names = _fetch_watchlists(db)

    out: list[MispricingRow] = []
    for row in rows:
        raw = json_loads_or_empty(row["raw_json"])
        watchlist_id = raw.get("watchlist_id")
        if isinstance(watchlist_id, str) and watchlist_id.isdigit():
            watchlist_id = int(watchlist_id)
        if not isinstance(watchlist_id, int):
            watchlist_id = None

        market = row["market_price_cents"]
        price = row["price_cents"]
        spread = None
        if market is not None and price is not None:
            spread = int(market) - int(price)

        is_deal = spread is not None and spread > 0
        is_priced = market is not None and price is not None

        if only_deals and not is_deal:
            continue
        if not include_unpriced and not is_priced:
            continue

        out.append(
            MispricingRow(
                unique_key=str(row["unique_key"]),
                source=str(row["source"]),
                url=str(row["url"]),
                title=None if row["title"] is None else str(row["title"]),
                price_cents=None if row["price_cents"] is None else int(row["price_cents"]),
                currency=str(row["currency"] or "USD"),
                location=None if row["location"] is None else str(row["location"]),
                seller=None if row["seller"] is None else str(row["seller"]),
                first_seen_at=str(row["first_seen_at"]),
                last_seen_at=str(row["last_seen_at"]),
                status=str(row["status"] or "active"),
                raw=raw,
                market_price_cents=None if row["market_price_cents"] is None else int(row["market_price_cents"]),
                estimated_resale_price_cents=(
                    None
                    if row["estimated_resale_price_cents"] is None
                    else int(row["estimated_resale_price_cents"])
                ),
                pricing_method=None if row["pricing_method"] is None else str(row["pricing_method"]),
                pricing_computed_at=None if row["pricing_computed_at"] is None else str(row["pricing_computed_at"]),
                alerts_count=int(row["alerts_count"] or 0),
                last_alert_at=None if row["last_alert_at"] is None else str(row["last_alert_at"]),
                watchlist_id=watchlist_id,
                watchlist_name=watchlist_names.get(watchlist_id) if watchlist_id is not None else None,
            )
        )

    return out


def create_app(*, settings: Settings, db: DB) -> FastAPI:
    assets_dir = Path(__file__).parent / "assets"
    if not assets_dir.exists():
        raise RuntimeError(f"UI assets directory missing: {assets_dir}")

    images_dir = Path(settings.data_dir) / "images"
    images_dir.mkdir(parents=True, exist_ok=True)

    app = FastAPI(
        title="Marketplace Pricer UI",
        version="0.1.0",
    )

    app.mount("/assets", StaticFiles(directory=str(assets_dir)), name="assets")
    app.mount("/images", StaticFiles(directory=str(images_dir)), name="images")

    @app.get("/", include_in_schema=False)
    def index() -> FileResponse:
        return FileResponse(str(assets_dir / "index.html"))

    @app.get("/api/meta")
    def api_meta() -> dict[str, Any]:
        return {
            "sqlite_path": str(settings.sqlite_path),
            "allowed_statuses": sorted(ALLOWED_LISTING_STATUSES),
        }

    @app.get("/api/mispricings")
    def api_mispricings(
        status: str | None = "active",
        only_deals: bool = True,
        include_unpriced: bool = False,
        limit: int = 500,
    ) -> dict[str, Any]:
        rows = query_mispricings(
            db,
            status=status,
            only_deals=bool(only_deals),
            include_unpriced=bool(include_unpriced),
            limit=limit,
        )
        return {
            "items": [r.to_api_dict() for r in rows],
            "count": len(rows),
        }

    @app.get("/api/watchlists")
    def api_watchlists() -> dict[str, Any]:
        watchlists = db.list_watchlists(active_only=False)
        return {
            "watchlists": [
                {"id": w.id, "name": w.name, "source": w.source, "active": bool(w.active)} for w in watchlists
            ]
        }

    @app.post("/api/listings/{unique_key:path}/status")
    def api_set_listing_status(
        unique_key: str,
        payload: dict[str, Any] = Body(...),
    ) -> dict[str, Any]:
        status = payload.get("status")
        if not isinstance(status, str) or not status.strip():
            raise HTTPException(400, "Missing required field: status")
        status = status.strip().lower()
        if status not in ALLOWED_LISTING_STATUSES:
            raise HTTPException(400, f"Unsupported status: {status!r}")

        with db.connect() as conn:
            cur = conn.execute(
                "UPDATE listings SET status=? WHERE unique_key=?",
                (status, unique_key),
            )
            if cur.rowcount == 0:
                raise HTTPException(404, f"Listing not found: {unique_key!r}")

        return {"ok": True, "unique_key": unique_key, "status": status}

    return app


def build_default_app() -> FastAPI:
    settings = Settings()
    db = DB(Path(settings.sqlite_path))
    db.init_schema()
    return create_app(settings=settings, db=db)
