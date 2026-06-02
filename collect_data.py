"""
30-Day Live Data Collector
===========================
Runs continuously, collecting one data point every 5 minutes:
  - BTC/USD price from Binance (open, close, volume, pct_change, outcome)
  - Polymarket market data (yes_price, no_price, volume, slug)
  - Timestamp aligned to window boundary

Saves to data/live_collection.csv — appends one row per window.
Sends a notification when 30-day collection is complete (8,640 rows).

Usage:
    python collect_data.py              # run forever
    python collect_data.py --days 30    # stop after 30 days
    python collect_data.py --test       # collect 3 windows then exit
"""

import argparse
import csv
import json
import os
import time
import urllib.request
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path

WINDOW_SECONDS = 300
BINANCE_KLINES = "https://api.binance.com/api/v3/klines"
GAMMA_API      = "https://gamma-api.polymarket.com/events"
OUTPUT_FILE    = "data/live_collection.csv"
NOTIFY_WEBHOOK = os.environ.get("DISCORD_WEBHOOK", "")  # optional Discord notification

CSV_HEADERS = [
    "collected_at_utc",
    "window_ts",
    "window_start_utc",
    "window_end_utc",
    "btc_open",
    "btc_close",
    "btc_high",
    "btc_low",
    "btc_volume",
    "pct_change",
    "outcome",
    "poly_yes_price",
    "poly_no_price",
    "poly_volume",
    "poly_slug",
    "poly_found",
]


def current_window_ts() -> int:
    now = int(time.time())
    return now - (now % WINDOW_SECONDS)


def fetch_btc_candle(window_ts: int) -> dict:
    params = urllib.parse.urlencode({
        "symbol":    "BTCUSDT",
        "interval":  "5m",
        "startTime": window_ts * 1000,
        "limit":     1,
    })
    try:
        with urllib.request.urlopen(f"{BINANCE_KLINES}?{params}", timeout=10) as r:
            raw = json.loads(r.read())
        if raw:
            k = raw[0]
            open_p  = float(k[1])
            high_p  = float(k[2])
            low_p   = float(k[3])
            close_p = float(k[4])
            volume  = float(k[5])
            pct     = (close_p - open_p) / open_p * 100
            return {
                "btc_open":   open_p,
                "btc_close":  close_p,
                "btc_high":   high_p,
                "btc_low":    low_p,
                "btc_volume": volume,
                "pct_change": pct,
                "outcome":    "UP" if close_p >= open_p else "DOWN",
            }
    except Exception as e:
        print(f"  ⚠️  Binance fetch error: {e}")
    return {}


def fetch_poly_market(window_ts: int) -> dict:
    slug   = f"btc-updown-5m-{window_ts}"
    params = urllib.parse.urlencode({"slug": slug})
    try:
        with urllib.request.urlopen(f"{GAMMA_API}?{params}", timeout=10) as r:
            events = json.loads(r.read())
        if events:
            m      = events[0].get("markets", [{}])[0]
            prices = m.get("outcomePrices", ["0.5", "0.5"])
            return {
                "poly_yes_price": float(prices[0]) if prices else 0.5,
                "poly_no_price":  float(prices[1]) if len(prices) > 1 else 0.5,
                "poly_volume":    float(m.get("volume", 0)),
                "poly_slug":      slug,
                "poly_found":     True,
            }
    except Exception as e:
        print(f"  ⚠️  Polymarket fetch error: {e}")
    return {
        "poly_yes_price": 0.0,
        "poly_no_price":  0.0,
        "poly_volume":    0.0,
        "poly_slug":      slug,
        "poly_found":     False,
    }


def save_row(row: dict):
    path = Path(OUTPUT_FILE)
    path.parent.mkdir(parents=True, exist_ok=True)
    write_header = not path.exists() or path.stat().st_size == 0
    with open(path, "a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_HEADERS)
        if write_header:
            writer.writeheader()
        writer.writerow({k: row.get(k, "") for k in CSV_HEADERS})


def count_rows() -> int:
    path = Path(OUTPUT_FILE)
    if not path.exists():
        return 0
    with open(path) as f:
        return sum(1 for _ in f) - 1  # subtract header


def send_discord_notification(message: str):
    if not NOTIFY_WEBHOOK:
        return
    try:
        payload = json.dumps({"content": message}).encode()
        req = urllib.request.Request(
            NOTIFY_WEBHOOK,
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        urllib.request.urlopen(req, timeout=10)
    except Exception:
        pass


def collect_one_window(window_ts: int) -> dict:
    window_start = datetime.fromtimestamp(window_ts, tz=timezone.utc)
    window_end   = datetime.fromtimestamp(window_ts + WINDOW_SECONDS, tz=timezone.utc)

    print(f"  Collecting window {window_start.strftime('%Y-%m-%d %H:%M')} UTC...", end=" ", flush=True)

    btc  = fetch_btc_candle(window_ts)
    poly = fetch_poly_market(window_ts)

    row = {
        "collected_at_utc": datetime.now(tz=timezone.utc).isoformat(),
        "window_ts":        window_ts,
        "window_start_utc": window_start.isoformat(),
        "window_end_utc":   window_end.isoformat(),
        **btc,
        **poly,
    }

    outcome = btc.get("outcome", "?")
    pct     = btc.get("pct_change", 0)
    yes_p   = poly.get("poly_yes_price", 0)
    found   = "✅" if poly.get("poly_found") else "❌ not found"
    print(f"{outcome} ({pct:+.3f}%)  YES=${yes_p:.2f}  poly={found}")

    return row


def main():
    parser = argparse.ArgumentParser(description="30-day live data collector")
    parser.add_argument("--days",  type=int, default=30, help="Days to collect (default: 30)")
    parser.add_argument("--test",  action="store_true",  help="Collect 3 windows then exit")
    args = parser.parse_args()

    target_windows = 3 if args.test else args.days * 24 * 12  # 12 windows/hour
    already = count_rows()

    print(f"\n{'='*60}")
    print(f"  30-DAY LIVE DATA COLLECTOR")
    print(f"  Target: {target_windows:,} windows ({args.days} days)")
    print(f"  Already collected: {already:,} rows")
    print(f"  Output: {OUTPUT_FILE}")
    print(f"{'='*60}\n")

    collected = 0

    while True:
        window_ts   = current_window_ts()
        close_ts    = window_ts + WINDOW_SECONDS

        # Wait for window to close + 15s buffer for Binance candle to finalize
        wait = close_ts - time.time() + 15
        if wait > 0:
            mins = int(wait // 60)
            secs = int(wait % 60)
            print(f"  Next window closes in {mins}m {secs}s — waiting...")
            time.sleep(wait)

        # Collect the window that just closed
        row = collect_one_window(window_ts)
        save_row(row)
        collected += 1
        total = count_rows()

        print(f"  Total collected: {total:,} / {target_windows:,} ({total/target_windows*100:.1f}%)")

        # Notify at milestones
        if total % (24 * 12) == 0:  # every 24 hours
            days_done = total // (24 * 12)
            msg = f"✅ BTC data collector: {days_done} day(s) complete — {total:,} windows collected."
            send_discord_notification(msg)
            print(f"  📣 {msg}")

        # Done
        if total >= target_windows or (args.test and collected >= 3):
            msg = f"🎉 30-day data collection complete! {total:,} windows saved to {OUTPUT_FILE}"
            print(f"\n  {msg}")
            send_discord_notification(msg)
            break

        # Small buffer before next window check
        time.sleep(5)


if __name__ == "__main__":
    main()
