# Solarvest Bursa Monitor

Public daily log of Solarvest Holdings (Bursa: 0215) announcements and closing prices, updated automatically on weekdays by GitHub Actions: announcements hourly 9:37am–4:37pm MYT, closing price about 7:37pm MYT. Runs on GitHub's servers, so no computer needs to be on.

- `index.html` is the page
- `scripts/update.py` and `.github/workflows/update.yml` do the updates
- `data/` holds the data files (announcements, prices, daily checks) refreshed by the scheduled update

Prices come from a market-data service (KLSE Screener), not an exchange-certified feed. Dated facts only; no causes are attributed to price moves.
