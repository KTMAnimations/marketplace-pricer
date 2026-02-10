# Marketplace Pricer

Watches Facebook Marketplace and Craigslist for stuff selling well under its eBay price, and pings me when something good shows up.

The idea: the same used item goes for very different prices depending on where it's listed, and nobody selling an old camera on Facebook is checking what it closes for on eBay. Even on a price comparison site, where you can see every offer at once, the two cheapest prices for identical electronics still differ by about 23% on average ([paper](https://ideas.repec.org/a/bla/jindec/v52y2004i4p463-496.html)). Where nobody's comparing, the gaps are wider.

So it scans listings, looks each one up against the eBay median, and flags anything priced under 60% of it.

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

eBay comps and the Discord/Telegram pings read their keys from `.env` (copy `.env.example`). Heads up: scraping can break a site's terms and get an account banned, so I keep it to my own use and stick to official APIs where I can.
