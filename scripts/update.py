#!/usr/bin/env python3
"""Solarvest (Bursa: 0215) monitor updater, run by GitHub Actions.

Modes:
  intraday  - add new announcements; add a check row only on a >=5% intraday move
  evening   - add new announcements, today's end-of-day price row and a check row
Add --dry-run to print what would change without writing files.

Records dated facts only. Never attributes a cause to a price move.
"""
import json
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests
from bs4 import BeautifulSoup

MYT = timezone(timedelta(hours=8))
ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
ANN_URL = "https://www.klsescreener.com/v2/announcements/stock/0215"
PRICE_URL = "https://mobapp-bak.klsescreener.com/v2/stocks/view/0215"
VIEW_URL = "https://www.klsescreener.com/v2/announcements/view/{}"
BASIS = "End-of-day; KLSE Screener; not an exchange-certified feed"
ALERT_PCT = 0.05

# Bursa Malaysia market holidays (weekdays). Extend each year.
HOLIDAYS = {
    "2026-11-09",  # Deepavali (replacement, falls on Sunday 8 Nov)
    "2026-12-25",  # Christmas
}

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36",
    "Accept-Language": "en-US,en;q=0.9",
}
MONTHS = {m: i for i, m in enumerate(
    ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"], 1)}
DATE_RE = re.compile(r"\b(\d{1,2})\s+(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\b")
TIME_RE = re.compile(r"\b(\d{1,2}):(\d{2})\s*([ap]m)\b", re.I)


def load(name):
    return json.loads((DATA / f"{name}.json").read_text(encoding="utf-8"))


def save(name, rows):
    (DATA / f"{name}.json").write_text(
        json.dumps(rows, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")


def get(url):
    r = requests.get(url, headers=HEADERS, timeout=30)
    r.raise_for_status()
    return BeautifulSoup(r.text, "html.parser")


def fetch_announcements(today):
    soup = get(ANN_URL)
    out, seen = [], set()
    for a in soup.find_all("a", href=re.compile(r"/v2/announcements/view/(\d+)")):
        num = re.search(r"/view/(\d+)", a["href"]).group(1)
        if num in seen:
            continue
        node = a
        for _ in range(6):  # climb to the element holding the whole row
            text = " ".join(node.stripped_strings)
            if DATE_RE.search(text) and TIME_RE.search(text):
                break
            node = node.parent
        else:
            continue
        tokens = [t.strip() for t in node.stripped_strings if t.strip()]
        text = " ".join(tokens)
        dm, tm = DATE_RE.search(text), TIME_RE.search(text)
        if not dm or not tm:
            continue
        seen.add(num)
        day, mon = int(dm.group(1)), MONTHS[dm.group(2)]
        year = today.year
        if (mon, day) > (today.month, today.day):
            year -= 1
        hh = int(tm.group(1)) % 12 + (12 if tm.group(3).lower() == "pm" else 0)
        junk = re.compile(r"\d{1,2}|\d{1,2}:\d{2}|[ap]m|" + "|".join(MONTHS), re.I)
        rest = [t for t in tokens
                if not DATE_RE.fullmatch(t) and not TIME_RE.fullmatch(t)
                and not junk.fullmatch(t) and "SOLARVEST HOLDINGS" not in t.upper()]
        # Category is the short label before the title; title is the longest token.
        title_raw = max(rest, key=len) if rest else ""
        others = [t for t in rest if t != title_raw]
        category = others[0] if others else ""
        title, filer = title_raw, ""
        if " - " in title_raw:
            title, filer = [s.strip() for s in title_raw.rsplit(" - ", 1)]
        out.append({
            "id": num,
            "date": f"{year:04d}-{mon:02d}-{day:02d}",
            "time": f"{hh:02d}:{tm.group(2)}",
            "category": category,
            "title": title,
            "filer": filer,
            "shareholding": "Yes" if category == "Changes in Shareholdings" else "No",
            "url": VIEW_URL.format(num),
            "first_seen": today.isoformat(),
        })
    if not out:
        raise RuntimeError("no announcements parsed from page")
    return out


def num(s):
    return float(s.replace(",", "").replace("+", ""))


def fetch_price(ref_close=None):
    soup = get(PRICE_URL)
    tokens = [t.strip() for t in soup.stripped_strings if t.strip()]
    text = " ".join(tokens)
    price = change = volume = None
    # Main quote: "<price> [arrow] <signed change> (<pct>%)"; take the first change+pct
    # and pick the preceding price that is consistent with it.
    for cm in re.finditer(r"([+-]\d+\.\d{3}|0\.000)\s*\(\s*([+-]?\d+(?:\.\d+)?)\s*%\s*\)", text):
        ch, pct = num(cm.group(1)), num(cm.group(2)) / 100
        window = text[max(0, cm.start() - 200):cm.start()]
        arrowed = re.findall(r"(?<![\d.+-])(\d+\.\d{3})\s*[↑↓▲▼]", window)
        before = re.findall(r"(?<![\d.+-])(\d+\.\d{3})(?![\d])", window)
        # Prefer the price shown with an up/down arrow, then the nearest numbers.
        for cand in arrowed[-1:] + list(reversed(before[-6:])):
            p = num(cand)
            prev = p - ch
            if prev > 0 and abs(ch / prev - pct) <= 0.0006:
                price, change = p, ch
                break
        if price is not None:
            break
    for i, t in enumerate(tokens):
        if t.lower() == "volume" and i + 1 < len(tokens):
            if re.fullmatch(r"[\d,]+", tokens[i + 1]):
                volume = int(tokens[i + 1].replace(",", ""))
                break
    if price is None:
        print("DEBUG numeric tokens:", [t for t in tokens if re.search(r"\d", t)][:40])
        raise RuntimeError("price not parsed from page")
    if ref_close and not (0.6 * ref_close <= price <= 1.4 * ref_close):
        raise RuntimeError(f"parsed price {price} implausible vs last close {ref_close}")
    return {"price": price, "change": change, "prev_close": round(price - change, 3),
            "volume": volume}


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "intraday"
    dry = "--dry-run" in sys.argv
    now = datetime.now(MYT)
    today = now.date()
    tstr = today.isoformat()

    if today.weekday() >= 5 or tstr in HOLIDAYS:
        print("Market holiday - no check")
        return

    anns, prices, checks = load("announcements"), load("prices"), load("checks")
    failed = []

    known = {r["id"] for r in anns}
    new = []
    try:
        new = [r for r in fetch_announcements(today) if r["id"] not in known]
    except Exception as e:  # noqa: BLE001
        failed.append(f"announcements ({e})")
    new.sort(key=lambda r: (r["date"], r["time"]), reverse=True)
    n_sh = sum(r["shareholding"] == "Yes" for r in new)
    filings = "; ".join(f"{r['date']} {r['title']}" + (f" – {r['filer']}" if r["filer"] else "")
                        for r in new)

    q = None
    try:
        q = fetch_price(prices[-1]["close"] if prices else None)
    except Exception as e:  # noqa: BLE001
        failed.append(f"price ({e})")

    latest = prices[-1] if prices else None
    # If the quote is identical to the latest stored day, the market did not trade today.
    stale = bool(q and latest and latest["date"] < tstr and latest.get("volume")
                 and q["volume"] == latest["volume"] and q["price"] == latest["close"])

    price_row = check = None
    if q and not stale:
        pct = round(q["change"] / q["prev_close"], 4) if q["prev_close"] else None
        if mode == "evening" and tstr not in {p["date"] for p in prices}:
            price_row = {"date": tstr, "close": q["price"], "prev_close": q["prev_close"],
                         "change": round(q["change"], 3), "change_pct": pct,
                         "volume": q["volume"],
                         "alert": "Yes" if pct is not None and abs(pct) >= ALERT_PCT else "",
                         "basis": BASIS}
        if mode == "intraday" and pct is not None and abs(pct) >= ALERT_PCT:
            check = {"checked_at": now.isoformat(timespec="seconds"), "trading_date": tstr,
                     "close": q["price"], "change_pct": pct, "new_announcements": len(new),
                     "new_shareholding": n_sh, "alert": "Yes",
                     "status": "Intraday" + (f" – partial: {', '.join(failed)}" if failed else ""),
                     "note": f"Last traded price at {now:%H:%M}, not the official close."
                             + (f" New filings: {filings}." if filings else "")}

    if mode == "evening":
        ref = price_row or (prices[-1] if prices else {})
        status = "OK"
        if failed:
            status = "Partial – " + ", ".join(failed)
        elif stale:
            status = "No trading"
        note = (f"New filings: {filings}." if filings else "No new filings.")
        check = {"checked_at": now.isoformat(timespec="seconds"),
                 "trading_date": ref.get("date"), "close": ref.get("close"),
                 "change_pct": ref.get("change_pct"), "new_announcements": len(new),
                 "new_shareholding": n_sh,
                 "alert": "Yes" if price_row and price_row["alert"] == "Yes" else "No",
                 "status": status, "note": note}

    if new:
        anns = new + anns  # newest first; existing rows untouched
    if price_row:
        prices.append(price_row)
    if check:
        checks.append(check)

    summary = {"mode": mode, "time": now.isoformat(timespec="minutes"), "quote": q,
               "stale": stale, "new_announcements": new, "price_row": price_row,
               "check": check, "failed": failed}
    print(json.dumps(summary, indent=1, ensure_ascii=False))

    if not dry:
        if new:
            save("announcements", anns)
        if price_row:
            save("prices", prices)
        if check:
            save("checks", checks)
    if failed and not (new or price_row or check):
        sys.exit(1)  # make total failures visible as a red run


if __name__ == "__main__":
    main()
