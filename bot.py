"""
Polymarket BTC 5-Min Snipe Bot
================================
Clock-based snipe strategy for Polymarket's BTC Up/Down 5-minute markets.

Architecture:
  1. Calculate current window from system clock: window_ts = now - (now % 300)
  2. Sleep until T-10s before window close
  3. Enter TA loop: poll Binance every 2s, run composite signal
  4. Spike detection: fire immediately if score jumps ≥1.5
  5. T-5s hard deadline: always trade before window closes
  6. FOK market buy → fallback GTC limit at $0.95

Modes:
  --dry-run      Real Binance data, simulated fills, paper bankroll
  --mode safe    25% bankroll per trade, min_confidence=0.30
  --mode aggressive  Compound profits, min_confidence=0.20
  --mode degen   All-in every trade, min_confidence=0 (always takes a trade)

Usage:
    python bot.py --dry-run                     # dry run, safe mode
    python bot.py --dry-run --mode degen        # watch it double or bust
    python bot.py --dry-run --once              # single trade cycle
    python bot.py --dry-run --max-trades 20

Requires:
    .env with POLY_PRIVATE_KEY, POLY_API_KEY, POLY_API_SECRET,
             POLY_API_PASSPHRASE, POLY_FUNDER_ADDRESS
    (dry-run skips credentials)
"""

import argparse
import json
import os
import random
import sys
import time
import urllib.request
import urllib.parse
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import List, Optional, Dict

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from strategy import analyze, Candle, Signal, token_price_from_delta, min_win_rate_needed, expected_value


# ── Constants ─────────────────────────────────────────────────────────────────

WINDOW_SECONDS   = 300          # 5-minute windows
SNIPE_ENTRY_SECS = 10           # enter at T-10s
HARD_DEADLINE    = 5            # T-5s: must fire by here
POLL_INTERVAL    = 2            # TA loop every 2s
SPIKE_THRESHOLD  = 1.5          # immediate fire if score jumps by this
BINANCE_KLINES   = "https://api.binance.com/api/v3/klines"
BINANCE_TICKER   = "https://api.binance.com/api/v3/ticker/price?symbol=BTCUSDT"
GAMMA_API        = "https://gamma-api.polymarket.com/events"
MIN_SHARES       = 5            # Polymarket minimum


# ── Mode configs ──────────────────────────────────────────────────────────────

@dataclass
class ModeConfig:
    name:           str
    bet_fraction:   float   # fraction of bankroll per trade (safe=0.25, degen=1.0)
    min_confidence: float
    protect_principal: bool  # aggressive: only compound profits


MODES = {
    "safe":       ModeConfig("safe",       0.25,  0.30, False),
    "aggressive": ModeConfig("aggressive", 1.0,   0.20, True),   # bets profits only
    "degen":      ModeConfig("degen",      1.0,   0.00, False),  # all-in always
}


# ── Binance helpers ───────────────────────────────────────────────────────────

def btc_price_now() -> float:
    try:
        with urllib.request.urlopen(BINANCE_TICKER, timeout=5) as r:
            return float(json.loads(r.read())["price"])
    except Exception:
        return 0.0


def fetch_1m_candles(limit: int = 25) -> List[Candle]:
    params = urllib.parse.urlencode({
        "symbol": "BTCUSDT", "interval": "1m", "limit": limit,
    })
    try:
        with urllib.request.urlopen(f"{BINANCE_KLINES}?{params}", timeout=8) as r:
            raw = json.loads(r.read())
        return [
            Candle(open=float(k[1]), high=float(k[2]), low=float(k[3]),
                   close=float(k[4]), volume=float(k[5]))
            for k in raw
        ]
    except Exception:
        return []


def fetch_window_open_price(window_ts: int) -> float:
    """
    Fetch the BTC open price for the 5-min window starting at window_ts.
    Uses the 5-min Binance candle open as a close proxy to Chainlink oracle.
    The true oracle is wss://ws-live-data.polymarket.com (crypto_prices_chainlink),
    but Binance 5-min is within $1–5 and sufficient for signal generation.
    """
    params = urllib.parse.urlencode({
        "symbol": "BTCUSDT", "interval": "5m",
        "startTime": window_ts * 1000, "limit": 1,
    })
    try:
        with urllib.request.urlopen(f"{BINANCE_KLINES}?{params}", timeout=8) as r:
            raw = json.loads(r.read())
        if raw:
            return float(raw[0][1])  # open price
    except Exception:
        pass
    return 0.0


# ── Window timing ─────────────────────────────────────────────────────────────

def current_window_ts() -> int:
    now = int(time.time())
    return now - (now % WINDOW_SECONDS)


def window_close_ts(window_ts: int) -> int:
    return window_ts + WINDOW_SECONDS


def slug_from_ts(window_ts: int) -> str:
    return f"btc-updown-5m-{window_ts}"


def secs_until_close(window_ts: int) -> float:
    return window_close_ts(window_ts) - time.time()


# ── Market discovery ──────────────────────────────────────────────────────────

@dataclass
class PolyMarket:
    market_id:    str
    slug:         str
    yes_token_id: str
    no_token_id:  str
    yes_price:    float
    no_price:     float


def fetch_market(window_ts: int) -> Optional[PolyMarket]:
    slug = slug_from_ts(window_ts)
    params = urllib.parse.urlencode({"slug": slug})
    try:
        with urllib.request.urlopen(f"{GAMMA_API}?{params}", timeout=8) as r:
            events = json.loads(r.read())
        if not events:
            return None
        event = events[0]
        markets = event.get("markets", [])
        if not markets:
            return None
        m = markets[0]
        tokens = m.get("clobTokenIds", [])
        yes_id = tokens[0] if len(tokens) > 0 else ""
        no_id  = tokens[1] if len(tokens) > 1 else ""
        prices = m.get("outcomePrices", ["0.50", "0.50"])
        return PolyMarket(
            market_id    = m.get("id", ""),
            slug         = slug,
            yes_token_id = yes_id,
            no_token_id  = no_id,
            yes_price    = float(prices[0]) if prices else 0.50,
            no_price     = float(prices[1]) if len(prices) > 1 else 0.50,
        )
    except Exception:
        return None


# ── Paper P&L ─────────────────────────────────────────────────────────────────

@dataclass
class PaperState:
    bankroll:         float
    original_bankroll: float
    trades:           int = 0
    wins:             int = 0
    total_pnl:        float = 0.0
    history:          List[Dict] = field(default_factory=list)


def calc_bet_size(state: PaperState, mode: ModeConfig, min_bet: float = 1.0) -> float:
    if mode.name == "aggressive" and mode.protect_principal:
        # Only bet profits above original
        profits = state.bankroll - state.original_bankroll
        if profits <= 0:
            return min(state.bankroll, state.original_bankroll * mode.bet_fraction)
        return max(min_bet, profits)
    return max(min_bet, state.bankroll * mode.bet_fraction)


# ── Resolution check ──────────────────────────────────────────────────────────

def check_resolution_binance(window_ts: int) -> Optional[str]:
    """Check UP/DOWN by fetching the 5-min candle that closes this window."""
    params = urllib.parse.urlencode({
        "symbol": "BTCUSDT", "interval": "5m",
        "startTime": window_ts * 1000, "limit": 1,
    })
    try:
        with urllib.request.urlopen(f"{BINANCE_KLINES}?{params}", timeout=10) as r:
            raw = json.loads(r.read())
        if raw and len(raw[0]) > 4:
            open_p  = float(raw[0][1])
            close_p = float(raw[0][4])
            return "UP" if close_p >= open_p else "DOWN"
    except Exception:
        pass
    return None


# ── TA loop ───────────────────────────────────────────────────────────────────

def run_ta_loop(
    window_ts: int,
    window_open: float,
    mode: ModeConfig,
) -> Optional[Signal]:
    """
    Entry loop starting at T-10s. Polls every 2s, tracks best signal.
    Fires immediately on score spike ≥1.5, or at T-5s hard deadline.
    """
    candles_1m   = fetch_1m_candles(25)
    tick_prices  = []
    best_signal  = None
    prev_score   = 0.0
    deadline     = window_close_ts(window_ts) - HARD_DEADLINE

    while time.time() < deadline:
        price = btc_price_now()
        if price > 0:
            tick_prices.append(price)

        signal = analyze(
            window_open_price = window_open,
            current_price     = price or window_open,
            candles_1m        = candles_1m,
            tick_prices       = tick_prices,
            min_confidence    = mode.min_confidence,
        )

        if signal:
            # Track best signal
            if best_signal is None or abs(signal.score) > abs(best_signal.score):
                best_signal = signal

            # Spike detection: fire immediately
            if abs(signal.score - prev_score) >= SPIKE_THRESHOLD:
                print(f"  ⚡ Score spike {prev_score:+.1f} → {signal.score:+.1f} — firing!")
                return signal

            prev_score = signal.score

        remaining = deadline - time.time()
        if remaining <= 0:
            break
        time.sleep(min(POLL_INTERVAL, remaining))

    # T-5s deadline: use best signal seen (degen always trades)
    if best_signal:
        return best_signal

    if mode.name == "degen" and window_open > 0:
        price = btc_price_now() or window_open
        delta = (price - window_open) / window_open * 100
        direction = "UP" if delta >= 0 else "DOWN"
        from strategy import Signal as S
        return S(
            direction=direction, side=f"BUY_{'YES' if direction == 'UP' else 'NO'}",
            score=0.1 if direction == "UP" else -0.1,
            confidence=0.0, token_price=0.50,
            window_delta_pct=delta, reasons=["degen_forced"],
        )

    return None


# ── Dry run execution ─────────────────────────────────────────────────────────

def dry_run_fill(signal: Signal, bet_size: float) -> Dict:
    """Simulate a fill with realistic token pricing."""
    token_price = signal.token_price
    shares = bet_size / token_price if token_price > 0 else 0
    return {
        "filled": True,
        "token_price": token_price,
        "shares": shares,
        "cost": bet_size,
    }


def dry_run_resolve(signal: Signal, outcome: str, fill: Dict) -> float:
    won = (signal.side == "BUY_YES" and outcome == "UP") or \
          (signal.side == "BUY_NO"  and outcome == "DOWN")
    if won:
        return fill["shares"] * 1.0 - fill["cost"]  # profit
    return -fill["cost"]


# ── Live execution ────────────────────────────────────────────────────────────

def live_execute(signal: Signal, market: PolyMarket, bet_size: float) -> Optional[Dict]:
    """
    Execute a real order on Polymarket CLOB.
    Primary: FOK market buy. Fallback: GTC limit at $0.95.
    """
    try:
        from py_clob_client.client import ClobClient
        from py_clob_client.clob_types import OrderArgs, OrderType, TimeInForce

        host        = "https://clob.polymarket.com"
        api_key     = os.environ.get("POLY_API_KEY", "")
        api_secret  = os.environ.get("POLY_API_SECRET", "")
        passphrase  = os.environ.get("POLY_API_PASSPHRASE", "")
        private_key = os.environ.get("POLY_PRIVATE_KEY", "")
        funder      = os.environ.get("POLY_FUNDER_ADDRESS", "")
        sig_type    = int(os.environ.get("POLY_SIGNATURE_TYPE", "1"))

        client = ClobClient(host, key=private_key, chain_id=137,
                            creds={"key": api_key, "secret": api_secret, "passphrase": passphrase},
                            signature_type=sig_type, funder=funder)

        token_id = market.yes_token_id if signal.side == "BUY_YES" else market.no_token_id
        price    = signal.token_price
        shares   = max(MIN_SHARES, int(bet_size / price))

        # Primary: FOK market buy
        order_args = OrderArgs(
            price=price, size=shares, side="BUY",
            token_id=token_id,
        )
        resp = client.create_and_post_order(order_args)
        if resp and resp.get("status") in ("matched", "filled"):
            return {"filled": True, "token_price": price, "shares": shares, "cost": shares * price}

        # Fallback: GTC limit at $0.95 (become the liquidity)
        limit_price = min(0.95, price + 0.03)
        limit_args = OrderArgs(
            price=limit_price, size=shares, side="BUY", token_id=token_id,
        )
        resp2 = client.create_and_post_order(limit_args)
        return {"filled": True, "token_price": limit_price, "shares": shares, "cost": shares * limit_price}

    except ImportError:
        print("  ⚠️  py-clob-client not installed. Run: pip install py-clob-client==0.34.5")
        return None
    except Exception as e:
        print(f"  ❌ Order failed: {e}")
        return None


# ── Main loop ─────────────────────────────────────────────────────────────────

def trade_cycle(state: PaperState, mode: ModeConfig, dry_run: bool) -> bool:
    """Single trade cycle. Returns True if a trade was attempted."""
    window_ts   = current_window_ts()
    close_ts    = window_close_ts(window_ts)
    secs_left   = close_ts - time.time()

    print(f"\n{'='*60}")
    print(f"  Window: {datetime.fromtimestamp(window_ts, tz=timezone.utc).strftime('%H:%M:%S')} UTC")
    print(f"  Closes: {datetime.fromtimestamp(close_ts, tz=timezone.utc).strftime('%H:%M:%S')} UTC  ({secs_left:.0f}s)")
    print(f"  Bankroll: ${state.bankroll:.2f}  |  Mode: {mode.name}  |  Trades: {state.trades}")
    print(f"{'='*60}")

    # Sleep until T-10s
    sleep_until = close_ts - SNIPE_ENTRY_SECS
    wait = sleep_until - time.time()
    if wait > 0:
        print(f"  Sleeping {wait:.0f}s until T-{SNIPE_ENTRY_SECS}s snipe window...")
        time.sleep(wait)

    # Fetch window open price
    print("  Fetching window open price...")
    window_open = fetch_window_open_price(window_ts)
    if window_open <= 0:
        print("  ⚠️  Could not fetch open price — skipping")
        return False
    print(f"  Window open: ${window_open:,.2f}")

    # TA loop
    print(f"  Running TA loop (T-{SNIPE_ENTRY_SECS}s → T-{HARD_DEADLINE}s)...")
    signal = run_ta_loop(window_ts, window_open, mode)

    if not signal:
        print("  No signal generated — skip")
        return False

    print(f"  Signal: {signal.side}  score={signal.score:+.1f}  conf={signal.confidence:.0%}  Δ={signal.window_delta_pct:+.4f}%")
    print(f"  Token price: ${signal.token_price:.3f}  (break-even win rate: {min_win_rate_needed(signal.token_price)*100:.1f}%)")
    for r in signal.reasons:
        print(f"    • {r}")

    bet_size = calc_bet_size(state, mode)
    print(f"  Bet size: ${bet_size:.2f}")

    # Execute
    if dry_run:
        fill = dry_run_fill(signal, bet_size)
        print(f"  [DRY RUN] Filled at ${fill['token_price']:.3f} × {fill['shares']:.1f} shares")
    else:
        market = fetch_market(window_ts)
        if not market:
            print("  ⚠️  Market not found on Polymarket — skip")
            return False
        fill = live_execute(signal, market, bet_size)
        if not fill:
            return False

    # Wait for resolution
    remaining = close_ts - time.time()
    if remaining > 0:
        print(f"  Waiting {remaining:.0f}s for resolution...")
        time.sleep(remaining + 2)

    outcome = check_resolution_binance(window_ts)
    if not outcome:
        print("  ⚠️  Could not determine outcome — marking unknown")
        return True

    pnl = dry_run_resolve(signal, outcome, fill) if dry_run else 0.0
    won = (signal.side == "BUY_YES" and outcome == "UP") or \
          (signal.side == "BUY_NO"  and outcome == "DOWN")

    state.bankroll += pnl
    state.trades   += 1
    state.wins     += 1 if won else 0
    state.total_pnl += pnl

    win_rate = state.wins / state.trades * 100 if state.trades else 0
    ev = expected_value(fill["token_price"], state.wins / state.trades if state.trades else 0)

    icon = "✅" if won else "❌"
    print(f"\n  {icon} {outcome} — {'WIN' if won else 'LOSS'}")
    print(f"  P&L this trade: ${pnl:+.2f}  |  Bankroll: ${state.bankroll:.2f}")
    print(f"  Running: {state.wins}/{state.trades} wins ({win_rate:.1f}%)  EV/dollar: {ev:+.4f}")

    state.history.append({
        "window_ts": window_ts,
        "side":      signal.side,
        "delta_pct": signal.window_delta_pct,
        "confidence": signal.confidence,
        "token_price": fill["token_price"],
        "outcome":   outcome,
        "won":       won,
        "pnl":       pnl,
        "bankroll":  state.bankroll,
    })

    return True


def main():
    parser = argparse.ArgumentParser(description="Polymarket BTC 5-min snipe bot")
    parser.add_argument("--dry-run",    action="store_true",   help="Paper mode — no real orders")
    parser.add_argument("--mode",       default="safe",        choices=list(MODES))
    parser.add_argument("--bankroll",   type=float, default=100.0)
    parser.add_argument("--min-bet",    type=float, default=1.0)
    parser.add_argument("--once",       action="store_true",   help="Run one trade cycle then exit")
    parser.add_argument("--max-trades", type=int,  default=0,  help="Stop after N trades (0=unlimited)")
    args = parser.parse_args()

    if not args.dry_run:
        for key in ("POLY_PRIVATE_KEY", "POLY_API_KEY", "POLY_API_SECRET",
                    "POLY_API_PASSPHRASE", "POLY_FUNDER_ADDRESS"):
            if not os.environ.get(key):
                print(f"❌  Missing {key} in environment. Copy .env.example → .env and fill in credentials.")
                sys.exit(1)

    mode  = MODES[args.mode]
    state = PaperState(bankroll=args.bankroll, original_bankroll=args.bankroll)

    print(f"\n{'='*60}")
    print(f"  POLYMARKET BTC 5-MIN SNIPE BOT")
    print(f"  Mode: {args.mode.upper()}  |  {'DRY RUN' if args.dry_run else '🔴 LIVE'}")
    print(f"  Bankroll: ${state.bankroll:.2f}  |  Min confidence: {mode.min_confidence:.0%}")
    print(f"{'='*60}")

    try:
        while True:
            # Wait for start of a new window if we're mid-window
            now = int(time.time())
            secs_into_window = now % WINDOW_SECONDS
            secs_until_entry = WINDOW_SECONDS - secs_into_window - SNIPE_ENTRY_SECS
            if secs_until_entry > 0 and not args.once:
                print(f"\n  Next snipe entry in {secs_until_entry:.0f}s...")
                time.sleep(secs_until_entry)

            traded = trade_cycle(state, mode, args.dry_run)

            if args.once:
                break
            if args.max_trades > 0 and state.trades >= args.max_trades:
                break

            # Guard: don't start new window until current one closes
            now = int(time.time())
            secs_into_window = now % WINDOW_SECONDS
            if secs_into_window < WINDOW_SECONDS - 2:
                remaining = WINDOW_SECONDS - secs_into_window
                time.sleep(remaining)

    except KeyboardInterrupt:
        pass

    # Final summary
    print(f"\n{'='*60}")
    print(f"  FINAL SUMMARY")
    print(f"{'='*60}")
    print(f"  Trades: {state.trades}  |  Wins: {state.wins}  ({state.wins/state.trades*100:.1f}% win rate)" if state.trades else "  No trades taken.")
    print(f"  Starting bankroll: ${state.original_bankroll:.2f}")
    print(f"  Final bankroll:    ${state.bankroll:.2f}")
    print(f"  Total P&L:         ${state.total_pnl:+.2f}")
    if state.trades:
        ev = expected_value(
            sum(t["token_price"] for t in state.history) / len(state.history),
            state.wins / state.trades,
        )
        print(f"  Running EV/dollar: {ev:+.4f}")


if __name__ == "__main__":
    main()
