# Marketplace Pricer

Watches Facebook Marketplace and Craigslist for stuff selling well under its eBay price, and pings me when something good shows up.

It scans listings, looks each one up against the eBay median, and flags anything priced under 60% of it.

![Asking price against eBay median](docs/images/price-gap.png)

Each dot is a listing. Most sit near the line where the asking price matches the eBay median. The ones below the dashed line are cheap enough to be worth a message.

## Running it

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
playwright install chromium
python -m marketplace_pricer init-db

python -m marketplace_pricer facebook-login   # opens a browser, sign in once
python -m marketplace_pricer watchlist add --name "iPhone 14 (Boston)" \
  --source facebook --query "iphone 14" \
  --filters '{"city":"boston","max_price":600,"alert_under_market_pct":0.6}'
python -m marketplace_pricer scan run
python -m marketplace_pricer ui --open
```
