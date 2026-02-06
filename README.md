# marketplace-pricer

Local-first deal scanner + pricing pipeline with a path to a multi-user web app.

This repo currently provides:
- A SQLite-backed pipeline (`marketplace_pricer/`) for **watchlists → scans → stored listings → alerts → weekly reporting**
- A Facebook Marketplace connector (Playwright) that uses **manual login + saved storage state** (no hard-coded passwords)
- An eBay connector for **basic market-price estimation** (median of keyword search results)
- A Craigslist connector that ingests **Craigslist saved-search email alerts** via IMAP (compliance-friendly)
- A stub for Nextdoor Marketplace via **official API** (requires access + token)

Important: Scraping and automated access can violate site terms and may risk account bans. Use at your own risk and prefer official APIs where available.

## Quickstart (single-user, local)

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
playwright install chromium

python -m marketplace_pricer init-db
```

### 1) Facebook login (one-time)

This opens a real browser; log in manually; then hit Enter in the terminal to save cookies/session state.

```bash
python -m marketplace_pricer facebook-login
```

Storage state is saved to `data/facebook_storage_state.json` by default (override with `MP_FACEBOOK_STORAGE_STATE_PATH`).

### 2) Add a watchlist

Example: Boston iPhone 14 scan, cap FB results at $600, and only alert when ≤ 60% of eBay median.

```bash
python -m marketplace_pricer watchlist add \
  --name "iPhone 14 (Boston)" \
  --source facebook \
  --query "iphone 14" \
  --filters '{"city":"boston","max_price":600,"alert_under_market_pct":0.6,"alert_without_market_price":false}' \
  --interval 300
```

List watchlists:

```bash
python -m marketplace_pricer watchlist list
```

### 3) Configure pricing + alerts

Copy `.env.example` to `.env` and fill what you want to enable:

- eBay comps: `MP_EBAY_CLIENT_ID`, `MP_EBAY_CLIENT_SECRET`
- Discord alerts: `MP_DISCORD_WEBHOOK_URL`
- Telegram alerts: `MP_TELEGRAM_BOT_TOKEN`, `MP_TELEGRAM_CHAT_ID`
- Craigslist email ingestion: `MP_IMAP_HOST`, `MP_IMAP_USERNAME`, `MP_IMAP_PASSWORD` (+ optional `MP_IMAP_FOLDER`)

### 4) Run the scanner

Run continuously:

```bash
python -m marketplace_pricer scan run
```

Or once:

```bash
python -m marketplace_pricer scan once
```

## Local dashboard UI (mispricings)

After you’ve run some scans (and ideally enabled eBay comps), launch the local dashboard:

```bash
python -m marketplace_pricer ui --open
```

This starts on `http://127.0.0.1:7331` by default (override with `--host` / `--port`).

The UI shows deal cards with thumbnails (when available), listing title/summary, pricing spread vs market, plus quick
actions (Open, eBay search, Copy link, Save, Dismiss). Save/Dismiss state is persisted in the `listings.status` column
in SQLite.

## Weekly sells / P&L reporting

Record a buy:

```bash
python -m marketplace_pricer inventory add --kind buy --amount-cents 50000 --fees-cents 0 --notes "FB pickup"
```

Record a sell:

```bash
python -m marketplace_pricer inventory add --kind sell --amount-cents 75000 --fees-cents 7000 --notes "eBay sale"
```

Print weekly rollups:

```bash
python -m marketplace_pricer report weekly --weeks 8
```

## Scaling path (website with user accounts + locations)

When you’re ready to go multi-user:
- Replace SQLite with Postgres, add `users` + `watchlists.user_id`
- Move scans to a worker queue (Celery/RQ + Redis), per-user rate limits
- Add auth (OAuth) + a UI to manage watchlists, locations, and alert channels
- Add a “closed loop” outcomes table (contacted/bought/sold) to train pricing models and measure true ROI
