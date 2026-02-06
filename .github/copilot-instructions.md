# Marketplace Pricer – AI Coding Instructions

## Project Overview
Local-first deal scanner + pricing pipeline for tracking marketplace listings (Facebook, Craigslist, Nextdoor). SQLite-backed with watchlists → scans → listings → alerts → reporting. Path to multi-user web app.

## Architecture

### Entry Points & CLI
- Run via `python -m marketplace_pricer <cmd>` ([`__main__.py`](../marketplace_pricer/__main__.py) → [`cli.py`](../marketplace_pricer/cli.py))
- Commands: `init-db`, `facebook-login`, `watchlist add/list`, `scan once/run`, `ui`, `inventory add`, `report weekly`
- CLI uses argparse with subcommands; see [`build_parser()`](../marketplace_pricer/cli.py) for full command structure

### Configuration ([`config.py`](../marketplace_pricer/config.py))
- All settings via `MP_*` environment variables (loaded by python-dotenv)
- `Settings` dataclass is frozen; never mutate
- Key paths: `MP_DATA_DIR` (default `data/`), `MP_SQLITE_PATH` (default `data/mp.db`)
- Facebook auth: `MP_FACEBOOK_STORAGE_STATE_PATH` stores Playwright session after manual login
- Always check env var existence before using optional features (eBay API, Discord/Telegram alerts, IMAP)

### Database ([`db.py`](../marketplace_pricer/db.py))
- SQLite with WAL mode; schema in `SCHEMA_SQL` string executed by `init_schema()`
- Tables: `watchlists`, `listings`, `listing_observations`, `price_estimates`, `alerts`, `inventory`
- `unique_key` pattern: `{source}:{external_id or url}` (see [`Listing.unique_key`](../marketplace_pricer/connectors/base.py))
- Upsert pattern: check existing by `unique_key`, update `last_seen_at` if exists, insert if new
- Return frozen dataclasses from queries (e.g., `WatchlistRow`, `ListingUpsertResult`)

### Plugin Architecture

**Connectors** ([`connectors/`](../marketplace_pricer/connectors/)):
- Protocol: [`Connector`](../marketplace_pricer/connectors/base.py) with `source: str` and `scan(watchlist) -> list[Listing]`
- Return `Listing` dataclass (source, external_id, url, title, price_cents, currency, location, seller, raw dict)
- Built in [`scanner.py:build_connectors()`](../marketplace_pricer/scanner.py): facebook, nextdoor, craigslist_email (conditional on IMAP config)
- Facebook uses Playwright with saved storage state; never hardcode credentials

**Alert Channels** ([`alerts/`](../marketplace_pricer/alerts/)):
- Protocol: [`AlertChannel`](../marketplace_pricer/alerts/base.py) with `name: str` and `send(AlertMessage)`
- `AlertMessage` has `title`, `body`, `render_text()` method
- Built in [`scanner.py:build_alert_channels()`](../marketplace_pricer/scanner.py): console (always), discord, telegram (conditional)
- Always include console alerts; optional channels check env vars

### Scanner Pipeline ([`scanner.py`](../marketplace_pricer/scanner.py))
1. Fetch due watchlists (where `last_scan_at + scan_interval_seconds < now`)
2. For each: call connector's `scan()`, upsert listings to DB
3. Compute price estimates (eBay comps if configured)
4. Check alert conditions (`alert_under_market_pct`, `alert_without_market_price` from watchlist filters)
5. Send alerts via all channels; record in `alerts` table
6. Update watchlist `last_scan_at`

### Local UI ([`ui/app.py`](../marketplace_pricer/ui/app.py))
- FastAPI serving static HTML/JS from [`assets/`](../marketplace_pricer/ui/assets/)
- API endpoints: `GET /api/listings` (filter by status, sort by spread), `POST /api/listings/{key}/status`
- Frontend: vanilla JS, no framework; interacts with SQLite via API
- Launch: `python -m marketplace_pricer ui --open` (default port 7331)

## Development Patterns

### Data Flow
Query string → cents: Use [`parse_usd_to_cents()`](../marketplace_pricer/normalization.py) for parsing "$123.45" → 12345
- Handle "free", "$0", negative signs
- Always store money as integer cents in DB; use `_fmt_money()` in UI for display

### Time Handling ([`timeutil.py`](../marketplace_pricer/timeutil.py))
- All timestamps: ISO 8601 strings in UTC (`utcnow_iso()` returns `datetime.now(UTC).isoformat()`)
- Never use naive datetimes; always `timezone.utc`

### Error Handling
- Connectors should catch exceptions and return empty list on failure (scanner continues with other watchlists)
- CLI commands return int exit codes (0 success, non-zero error)

### Adding New Connectors
1. Create `marketplace_pricer/connectors/your_source.py`
2. Implement `Connector` protocol with `source` and `scan(watchlist) -> list[Listing]`
3. Add to `build_connectors()` in [`scanner.py`](../marketplace_pricer/scanner.py)
4. Use watchlist.filters dict for source-specific params (city, max_price, etc.)

### Adding New Alert Channels
1. Create `marketplace_pricer/alerts/your_channel.py`
2. Implement `AlertChannel` protocol with `name` and `send(AlertMessage)`
3. Add to `build_alert_channels()` in [`scanner.py`](../marketplace_pricer/scanner.py)
4. Gate on env var check in Settings

## Key Commands

```bash
# Setup
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
playwright install chromium
python -m marketplace_pricer init-db

# Facebook (one-time manual login)
python -m marketplace_pricer facebook-login

# Add watchlist with filters (JSON must be valid)
python -m marketplace_pricer watchlist add \
  --name "iPhone 14 (Boston)" \
  --source facebook \
  --query "iphone 14" \
  --filters '{"city":"boston","max_price":600,"alert_under_market_pct":0.6}'

# Run scanner
python -m marketplace_pricer scan run  # continuous
python -m marketplace_pricer scan once # one iteration

# Local UI
python -m marketplace_pricer ui --open
```

## Testing & Debugging
- No test suite yet; manual testing via CLI commands
- Check logs in console output (alerts always print)
- Playwright debug: set `MP_FACEBOOK_HEADLESS=false` to see browser
- SQLite inspection: `sqlite3 data/mp.db` then `.schema`, `SELECT * FROM listings LIMIT 10;`

## Dependencies
Core: beautifulsoup4, playwright, python-dotenv, requests, fastapi, uvicorn
- Playwright requires `playwright install chromium` post-pip-install
- eBay comps require API keys (client_id, client_secret) from eBay developer program
- IMAP for Craigslist requires email provider supporting IMAP (Gmail, Outlook, etc.)
