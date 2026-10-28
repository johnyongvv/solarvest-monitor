# Solarvest Bursa Monitor

Public daily log of Solarvest Holdings (Bursa: 0215) announcements and closing prices, updated automatically on weekdays by Claude scheduled tasks running in the cloud (no computer needs to be on): a check every hour 9:37am–4:37pm MYT and the closing price at about 7:37pm MYT. `data/status.json` records the time of the latest check.

- `index.html` is the page
- `scripts/update.py` and `.github/workflows/update.yml` update the website every 15 minutes during trading hours (weekdays 9:07am–5:07pm MYT) without Claude; the page reloads itself every 5 minutes
- `data/` holds the data files (announcements, prices, daily checks) refreshed by the scheduled update

Prices come from a market-data service (KLSE Screener), not an exchange-certified feed. Dated facts only; no causes are attributed to price moves.
