"""
BTC/USD 5-Minute Data Fetcher
==============================
Two sources — use whichever works:

  --source binance    (default) Binance public API, no key, instant
  --source chainlink  On-chain Chainlink rounds via Ethereum RPC

Binance BTC/USDT 5-min klines are the fastest and most reliable option.
Chainlink is the actual Polymarket resolution source but requires a
working Ethereum RPC (free RPCs sometimes block eth_call).

Resolution: price_at_close >= price_at_open → UP, else DOWN

Usage:
    python chainlink_fetcher.py                        # 7 days, Binance
    python chainlink_fetcher.py --days 30              # 30 days
    python chainlink_fetcher.py --source chainlink     # on-chain Chainlink
    python chainlink_fetcher.py --output data/btc.csv
"""

import argparse
import csv
import logging
import time
import urllib.request
import urllib.parse
import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import List, Optional, Tuple

logger = logging.getLogger(__name__)

# ── Chainlink constants ───────────────────────────────────────────────────────

CHAINLINK_BTC_USD = "0xF4030086522a5bEEa4988F8cA5B36dbC97BeE88b"
DECIMALS = 8

FREE_RPCS = [
    "https://eth.llamarpc.com",
    "https://rpc.ankr.com/eth",
    "https://ethereum.publicnode.com",
    "https://cloudflare-eth.com",
    "https://1rpc.io/eth",
]

CHAINLINK_ABI = [
    {
        "inputs": [],
        "name": "latestRoundData",
        "outputs": [
            {"name": "roundId",         "type": "uint80"},
            {"name": "answer",          "type": "int256"},
            {"name": "startedAt",       "type": "uint256"},
            {"name": "updatedAt",       "type": "uint256"},
            {"name": "answeredInRound", "type": "uint80"},
        ],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [{"name": "_roundId", "type": "uint80"}],
        "name": "getRoundData",
        "outputs": [
            {"name": "roundId",         "type": "uint80"},
            {"name": "answer",          "type": "int256"},
            {"name": "startedAt",       "type": "uint256"},
            {"name": "updatedAt",       "type": "uint256"},
            {"name": "answeredInRound", "type": "uint80"},
        ],
        "stateMutability": "view",
        "type": "function",
    },
]


# ── Data models ───────────────────────────────────────────────────────────────

@dataclass
class FiveMinWindow:
    window_start: datetime
    window_end:   datetime
    open_price:   float
    close_price:  float
    outcome:      str       # "UP" or "DOWN"
    rounds_used:  int


# ── Binance source (primary — no key needed) ──────────────────────────────────

def fetch_binance_windows(days: int) -> List[FiveMinWindow]:
    """
    Fetch BTC/USDT 5-min klines from Binance public API.
    No API key required. Returns up to `days` days of data.
    Binance limit = 1000 candles per request → paginate to get more.
    """
    BINANCE_URL = "https://api.binance.com/api/v3/klines"
    INTERVAL    = "5m"
    LIMIT       = 1000      # max per request
    MS_PER_5MIN = 5 * 60 * 1000

    end_ms   = int(time.time() * 1000)
    start_ms = end_ms - days * 24 * 3600 * 1000

    all_klines = []
    current_start = start_ms

    print(f"  Fetching {days} days of BTC/USDT 5-min klines from Binance...")

    while current_start < end_ms:
        params = urllib.parse.urlencode({
            "symbol":    "BTCUSDT",
            "interval":  INTERVAL,
            "startTime": current_start,
            "endTime":   end_ms,
            "limit":     LIMIT,
        })
        url = f"{BINANCE_URL}?{params}"

        try:
            with urllib.request.urlopen(url, timeout=15) as resp:
                klines = json.loads(resp.read())
        except Exception as e:
            print(f"\n  ❌ Binance request failed: {e}")
            break

        if not klines:
            break

        all_klines.extend(klines)
        last_open_ms = klines[-1][0]
        current_start = last_open_ms + MS_PER_5MIN

        fetched_days = (last_open_ms - start_ms) / (24 * 3600 * 1000)
        print(f"\r  Progress: {fetched_days:.1f}/{days} days ({len(all_klines):,} candles)...", end="", flush=True)

        if len(klines) < LIMIT:
            break

    print(f"\r  Fetched {len(all_klines):,} candles total.                    ")

    windows = []
    for k in all_klines:
        open_time  = datetime.fromtimestamp(k[0] / 1000, tz=timezone.utc)
        close_time = datetime.fromtimestamp(k[6] / 1000, tz=timezone.utc)
        open_price  = float(k[1])
        close_price = float(k[4])
        outcome     = "UP" if close_price >= open_price else "DOWN"
        windows.append(FiveMinWindow(
            window_start = open_time,
            window_end   = close_time,
            open_price   = open_price,
            close_price  = close_price,
            outcome      = outcome,
            rounds_used  = 1,
        ))

    return sorted(windows, key=lambda w: w.window_start)


# ── Chainlink on-chain source ─────────────────────────────────────────────────

@dataclass
class ChainlinkRound:
    round_id:  int
    price:     float
    timestamp: datetime


def connect_web3():
    from web3 import Web3
    for rpc in FREE_RPCS:
        try:
            w3 = Web3(Web3.HTTPProvider(rpc, request_kwargs={"timeout": 12}))
            # Test with a real call, not just is_connected()
            _ = w3.eth.block_number
            logger.info(f"Connected via {rpc}")
            return w3
        except Exception:
            continue
    raise ConnectionError("No working Ethereum RPC found. Try --source binance instead.")


def fetch_round(contract, round_id: int) -> Optional[ChainlinkRound]:
    try:
        _, answer, _, updated_at, _ = contract.functions.getRoundData(round_id).call()
        if answer <= 0 or updated_at == 0:
            return None
        return ChainlinkRound(
            round_id  = round_id,
            price     = answer / (10 ** DECIMALS),
            timestamp = datetime.fromtimestamp(updated_at, tz=timezone.utc),
        )
    except Exception:
        return None


def fetch_chainlink_windows(days: int, workers: int = 20) -> List[FiveMinWindow]:
    from web3 import Web3

    print("  Connecting to Ethereum mainnet...")
    w3 = connect_web3()

    contract = w3.eth.contract(
        address=Web3.to_checksum_address(CHAINLINK_BTC_USD),
        abi=CHAINLINK_ABI,
    )

    latest      = contract.functions.latestRoundData().call()
    latest_id   = latest[0]
    n_rounds    = int(days * 24 * 3600 / 70)
    start_id    = max(1, latest_id - n_rounds)
    round_ids   = list(range(start_id, latest_id + 1))

    print(f"  Fetching {len(round_ids):,} rounds with {workers} workers...")
    rounds = []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(fetch_round, contract, rid): rid for rid in round_ids}
        done = 0
        for future in as_completed(futures):
            done += 1
            if done % 500 == 0:
                print(f"\r  {done}/{len(round_ids)} rounds...", end="", flush=True)
            r = future.result()
            if r:
                rounds.append(r)
    print()

    rounds.sort(key=lambda r: r.timestamp)

    # Build 5-min windows from raw rounds
    if not rounds:
        return []

    windows = []
    first_ts = rounds[0].timestamp.replace(second=0, microsecond=0)
    first_ts = first_ts.replace(minute=(first_ts.minute // 5) * 5)
    last_ts  = rounds[-1].timestamp
    current  = first_ts

    while current + timedelta(minutes=5) <= last_ts:
        wend      = current + timedelta(minutes=5)
        in_window = [r for r in rounds if current <= r.timestamp < wend]
        if len(in_window) >= 2:
            op = in_window[0].price
            cp = in_window[-1].price
            windows.append(FiveMinWindow(
                window_start = current,
                window_end   = wend,
                open_price   = op,
                close_price  = cp,
                outcome      = "UP" if cp >= op else "DOWN",
                rounds_used  = len(in_window),
            ))
        current = wend

    return windows


# ── CSV export ────────────────────────────────────────────────────────────────

def save_windows_csv(windows: List[FiveMinWindow], path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow([
            "window_start_utc", "window_end_utc",
            "open_price_usd", "close_price_usd",
            "pct_change", "outcome", "rounds_used",
        ])
        for w in windows:
            pct = (w.close_price - w.open_price) / w.open_price * 100
            writer.writerow([
                w.window_start.isoformat(),
                w.window_end.isoformat(),
                f"{w.open_price:.2f}",
                f"{w.close_price:.2f}",
                f"{pct:+.4f}",
                w.outcome,
                w.rounds_used,
            ])
    print(f"  Saved {len(windows):,} windows → {path}")


# ── Stats ─────────────────────────────────────────────────────────────────────

def print_stats(windows: List[FiveMinWindow], source: str):
    if not windows:
        return
    up      = sum(1 for w in windows if w.outcome == "UP")
    down    = len(windows) - up
    changes = [(w.close_price - w.open_price) / w.open_price * 100 for w in windows]
    prices  = [w.open_price for w in windows]

    print("\n" + "="*60)
    print(f"  BTC/USD 5-MIN DATA — {source.upper()}")
    print("="*60)
    print(f"  Windows:             {len(windows):,}")
    print(f"  Date range:          {windows[0].window_start.date()} → {windows[-1].window_start.date()}")
    print(f"  Price range:         ${min(prices):,.0f} → ${max(prices):,.0f}")
    print(f"  UP windows:          {up:,} ({up/len(windows)*100:.1f}%)")
    print(f"  DOWN windows:        {down:,} ({down/len(windows)*100:.1f}%)")
    print(f"  Avg |move| per 5min: {sum(abs(c) for c in changes)/len(changes):.4f}%")
    print(f"  Max move per 5min:   {max(abs(c) for c in changes):.4f}%")
    print("="*60)


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    logging.basicConfig(level=logging.WARNING, format="%(message)s")

    parser = argparse.ArgumentParser(description="Fetch BTC/USD 5-min data for backtesting")
    parser.add_argument("--days",    type=int,  default=7,
                        help="Days of history (default: 7)")
    parser.add_argument("--source",  choices=["binance", "chainlink"], default="binance",
                        help="Data source: binance (default, no key) or chainlink (on-chain)")
    parser.add_argument("--output",  default="data/btc_usd_chainlink.csv",
                        help="Output CSV path")
    parser.add_argument("--workers", type=int,  default=20,
                        help="Parallel workers for Chainlink fetching")
    args = parser.parse_args()

    print("\n" + "="*60)
    print("  BTC/USD 5-MIN DATA FETCHER")
    print(f"  Source: {args.source.upper()}")
    print("="*60 + "\n")

    if args.source == "binance":
        windows = fetch_binance_windows(args.days)
    else:
        windows = fetch_chainlink_windows(args.days, workers=args.workers)

    if not windows:
        print("  ❌ No data fetched.")
        return

    print_stats(windows, args.source)
    print("\n  Saving...")
    save_windows_csv(windows, Path(args.output))

    print(f"\n  ✅ Done. Run the backtest:")
    print(f"     python backtest.py --data {args.output}\n")


if __name__ == "__main__":
    main()
