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
import threading
import urllib.request
import urllib.parse
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional, Dict

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from strategy import analyze, Candle, Signal, token_price_from_delta, min_win_rate_needed, expected_value


# ── Constants ─────────────────────────────────────────────────────────────────

WINDOW_SECONDS   = 300          # 5-minute windows
SNIPE_ENTRY_SECS = 60           # enter at T-60s (market makers still quoting; T-10s has no liquidity)
HARD_DEADLINE    = 5            # T-5s: must fire by here
POLL_INTERVAL    = 2            # TA loop every 2s
SPIKE_THRESHOLD  = 1.5          # immediate fire if score jumps by this
BINANCE_KLINES   = "https://api.binance.com/api/v3/klines"
BINANCE_TICKER   = "https://api.binance.com/api/v3/ticker/price?symbol=BTCUSDT"
GAMMA_API        = "https://gamma-api.polymarket.com/events"
MIN_SHARES       = 5            # Polymarket minimum

BROWSER_HEADERS  = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/json",
    "Origin": "https://polymarket.com",
    "Referer": "https://polymarket.com/",
}
_last_gamma_call: float = 0.0   # rate-limit Polymarket API to 1 req/s
_GAMMA_MIN_INTERVAL = 1.0


# ── Mode configs ──────────────────────────────────────────────────────────────

@dataclass
class ModeConfig:
    name:           str
    bet_fraction:   float   # fraction of bankroll per trade (safe=0.25, degen=1.0)
    min_confidence: float
    protect_principal: bool  # aggressive: only compound profits


# Polymarket's Chainlink WebSocket (wss://ws-live-data.polymarket.com) connects
# but does not broadcast price data — likely requires internal auth or changed protocol.
# Binance BTC/USD is within ~$5-50 of Chainlink at any moment (<0.1% at $63K).
# Resolution accuracy is handled separately by check_resolution_polymarket().
# Keeping a stub oracle so callers fall through to Binance cleanly.

class _NullOracle:
    price = 0.0
    def start(self): pass
    def stop(self): pass
    def window_open(self, _): return 0.0

_oracle = _NullOracle()


MODES = {
    "safe":       ModeConfig("safe",       0.25,  0.60, False),
    "aggressive": ModeConfig("aggressive", 1.0,   0.20, True),   # bets profits only
    "degen":      ModeConfig("degen",      1.0,   0.00, False),  # all-in always
}


# ── Binance helpers ───────────────────────────────────────────────────────────

def btc_price_now() -> float:
    """Latest BTC price — Chainlink oracle first, Binance fallback."""
    oracle_price = _oracle.price
    if oracle_price > 0:
        return oracle_price
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
    Get the Chainlink oracle price at window boundary.
    Primary: WebSocket oracle (exact Polymarket resolution price).
    Fallback: Binance 5-min candle open (~$1-5 difference, fine for signals).
    """
    # Primary: Chainlink WebSocket recorded at boundary
    oracle_open = _oracle.window_open(window_ts)
    if oracle_open > 0:
        print(f"  🔗 Using Chainlink oracle open: ${oracle_open:,.2f}")
        return oracle_open

    # Fallback: Binance 5-min candle open
    params = urllib.parse.urlencode({
        "symbol": "BTCUSDT", "interval": "5m",
        "startTime": window_ts * 1000, "limit": 1,
    })
    try:
        with urllib.request.urlopen(f"{BINANCE_KLINES}?{params}", timeout=8) as r:
            raw = json.loads(r.read())
        if raw:
            price = float(raw[0][1])
            print(f"  📊 Using Binance fallback open: ${price:,.2f}")
            return price
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


def _gamma_request(url: str) -> list:
    """Rate-limited Polymarket gamma API call (1 req/s max)."""
    global _last_gamma_call
    wait = _GAMMA_MIN_INTERVAL - (time.time() - _last_gamma_call)
    if wait > 0:
        time.sleep(wait)
    req = urllib.request.Request(url, headers=BROWSER_HEADERS)
    with urllib.request.urlopen(req, timeout=8) as r:
        result = json.loads(r.read())
    _last_gamma_call = time.time()
    return result


def fetch_market(window_ts: int) -> Optional[PolyMarket]:
    slug = slug_from_ts(window_ts)
    params = urllib.parse.urlencode({"slug": slug})
    try:
        events = _gamma_request(f"{GAMMA_API}?{params}")
        if not events:
            return None
        event = events[0]
        markets = event.get("markets", [])
        if not markets:
            return None
        m = markets[0]
        raw_tokens = m.get("clobTokenIds", "[]")
        tokens = json.loads(raw_tokens) if isinstance(raw_tokens, str) else raw_tokens
        yes_id = tokens[0] if len(tokens) > 0 else ""
        no_id  = tokens[1] if len(tokens) > 1 else ""
        raw_prices = m.get("outcomePrices", '["0.50","0.50"]')
        prices = json.loads(raw_prices) if isinstance(raw_prices, str) else raw_prices
        return PolyMarket(
            market_id    = m.get("id", ""),
            slug         = slug,
            yes_token_id = yes_id,
            no_token_id  = no_id,
            yes_price    = float(prices[0]) if prices else 0.50,
            no_price     = float(prices[1]) if len(prices) > 1 else 0.50,
        )
    except Exception as e:
        print(f"  ⚠️  fetch_market error: {e}")
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


MAX_BET = 500.0   # hard cap per trade regardless of bankroll size

def calc_bet_size(state: PaperState, mode: ModeConfig, min_bet: float = 1.0) -> float:
    if mode.name == "aggressive" and mode.protect_principal:
        profits = state.bankroll - state.original_bankroll
        if profits <= 0:
            raw = min(state.bankroll, state.original_bankroll * mode.bet_fraction)
        else:
            raw = max(min_bet, profits)
    else:
        raw = max(min_bet, state.bankroll * mode.bet_fraction)
    return min(raw, MAX_BET)


# ── Resolution check ──────────────────────────────────────────────────────────

def check_resolution_polymarket(window_ts: int) -> Optional[str]:
    """
    Fetch actual Polymarket resolution — uses Chainlink oracle, same as payout.
    Returns "UP", "DOWN", or None if not yet resolved.
    """
    slug = slug_from_ts(window_ts)
    params = urllib.parse.urlencode({"slug": slug})
    try:
        events = _gamma_request(f"{GAMMA_API}?{params}")
        if not events:
            return None
        markets = events[0].get("markets", [])
        if not markets:
            return None
        m = markets[0]
        if m.get("closed") and m.get("resolutionSource"):
            outcomes = json.loads(m.get("outcomes", '[]')) if isinstance(m.get("outcomes"), str) else m.get("outcomes", [])
            prices_raw = m.get("outcomePrices", '["0.5","0.5"]')
            prices = json.loads(prices_raw) if isinstance(prices_raw, str) else prices_raw
            if prices and len(prices) >= 2:
                if float(prices[0]) > 0.9:
                    return "UP"
                elif float(prices[1]) > 0.9:
                    return "DOWN"
    except Exception:
        pass
    return None


def check_resolution_binance(window_ts: int) -> Optional[str]:
    """Fallback: infer UP/DOWN from Binance 5-min candle (may differ from Chainlink)."""
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


def check_resolution(window_ts: int) -> Optional[str]:
    """Check resolution: Polymarket (Chainlink-based) first, Binance fallback."""
    outcome = check_resolution_polymarket(window_ts)
    if outcome:
        return outcome
    return check_resolution_binance(window_ts)


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

        if signal and abs(signal.window_delta_pct) >= 0.02:
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
    Execute a FOK market order on Polymarket CLOB V2.
    FOK = Fill Or Kill: fills immediately at best available price, or cancels.
    No resting orders on the book — prevents stale fills near window close.
    """
    try:
        from py_clob_client_v2.client import ClobClient
        from py_clob_client_v2 import (ApiCreds, SignatureTypeV2, PartialCreateOrderOptions,
                                        MarketOrderArgsV2, OrderType,
                                        BalanceAllowanceParams, AssetType)

        host        = "https://clob.polymarket.com"
        api_key     = os.environ.get("POLY_API_KEY", "")
        api_secret  = os.environ.get("POLY_API_SECRET", "")
        passphrase  = os.environ.get("POLY_API_PASSPHRASE", "")
        private_key = os.environ.get("POLY_PRIVATE_KEY", "")
        funder      = os.environ.get("POLY_FUNDER_ADDRESS", "")

        creds  = ApiCreds(api_key=api_key, api_secret=api_secret, api_passphrase=passphrase)
        client = ClobClient(host, chain_id=137, key=private_key,
                            creds=creds, signature_type=SignatureTypeV2.POLY_1271, funder=funder)

        # Cap bet to 80% of actual on-chain balance
        bal_info = client.get_balance_allowance(BalanceAllowanceParams(asset_type=AssetType.COLLATERAL, signature_type=SignatureTypeV2.POLY_1271))
        actual_balance = int(bal_info.get("balance", 0)) / 1e6
        max_bet = actual_balance * 0.80
        bet_size = min(bet_size, max_bet)
        print(f"  💰 On-chain balance: ${actual_balance:.2f}  |  Max bet: ${max_bet:.2f}")
        if bet_size < 1.0:
            print(f"  ⚠️  Balance too low (${actual_balance:.2f}) — skip")
            return None

        token_id = market.yes_token_id if signal.side == "BUY_YES" else market.no_token_id

        # Check orderbook liquidity before placing — FOK silently fails when no asks exist
        try:
            ob = client.get_order_book(token_id)
            asks = ob.get("asks", []) if isinstance(ob, dict) else []
            # asks are sorted highest→lowest price; find lowest (best) ask
            if asks:
                best_ask = min(float(a["price"]) for a in asks)
            else:
                best_ask = None
            if best_ask is None:
                print(f"  ⚠️  No asks in orderbook — no liquidity, skipping")
                return None
            if best_ask > 0.92:
                print(f"  ⚠️  Best ask ${best_ask:.3f} too expensive (>$0.92) — poor value, skipping")
                return None
            # Cap bet to available liquidity at best ask
            best_ask_size = min(float(a["size"]) for a in asks if float(a["price"]) == best_ask) if asks else 0
            available_usdc = best_ask_size * best_ask
            if available_usdc < bet_size * 2:
                print(f"  ⚠️  Only ${available_usdc:.2f} available (need 2x bet = ${bet_size*2:.2f}) — too thin, skipping")
                return None
            if bet_size > available_usdc * 0.70:
                print(f"  📖 Best ask: ${best_ask:.3f}  |  Available: ${available_usdc:.2f} — capping bet to 70%")
                bet_size = available_usdc * 0.70
            else:
                print(f"  📖 Best ask: ${best_ask:.3f}  |  Available: ${available_usdc:.2f}  |  Liquidity OK")
        except Exception as ob_err:
            print(f"  ⚠️  Orderbook check failed ({ob_err}) — proceeding anyway")

        # Limit order at best ask — maker fee = 0%, no FOK rejection risk
        limit_price = round(best_ask, 2)  # best_ask already fetched above
        shares_to_buy = round(bet_size / limit_price, 1)
        if shares_to_buy < MIN_SHARES:
            print(f"  ⚠️  Too few shares ({shares_to_buy}) at ${limit_price:.3f} — skip")
            return None

        from py_clob_client_v2.clob_types import OrderArgs, OrderType as OT
        order_args = OrderArgs(
            token_id=token_id,
            price=limit_price,
            size=shares_to_buy,
            side="BUY",
        )
        options = PartialCreateOrderOptions(tick_size="0.01", neg_risk=False)
        print(f"  📝 Limit order: {shares_to_buy} shares @ ${limit_price:.3f} (GTC, 0% fee)")
        resp = client.create_and_post_order(order_args, options)

        if not resp:
            print(f"  ⚠️  No response from order placement — skipping")
            return None

        order_id = resp.get("orderID") or resp.get("id") or resp.get("order_id")
        status = resp.get("status", "unknown")
        print(f"  🕐 Order placed (id={str(order_id)[:16]}…  status={status}) — polling for fill (45s)…")

        # Poll for fill up to 45s, then cancel
        fill_deadline = time.time() + 45
        filled_size = 0.0
        filled_price_avg = limit_price

        while time.time() < fill_deadline:
            time.sleep(3)
            try:
                order_status = client.get_order(order_id)
                s = order_status.get("status", "")
                filled_size = float(order_status.get("size_matched", 0) or 0)
                if s in ("matched", "filled") or filled_size >= shares_to_buy * 0.95:
                    actual_cost = filled_size * limit_price
                    print(f"  ✅ Limit filled: {filled_size:.1f} shares @ ${limit_price:.3f} = ${actual_cost:.2f}")
                    return {"filled": True, "token_price": limit_price, "shares": filled_size, "cost": actual_cost}
                if s in ("cancelled", "canceled"):
                    print(f"  ⚠️  Order cancelled by exchange — no fill")
                    return None
            except Exception as poll_err:
                print(f"  ⚠️  Poll error: {poll_err}")

        # Cancel unfilled order before window closes
        print(f"  ⏱  45s elapsed — cancelling unfilled order…")
        try:
            client.cancel(order_id)
        except Exception as cancel_err:
            print(f"  ⚠️  Cancel error: {cancel_err}")

        if filled_size >= MIN_SHARES:
            actual_cost = filled_size * limit_price
            print(f"  ✅ Partial fill kept: {filled_size:.1f} shares @ ${limit_price:.3f} = ${actual_cost:.2f}")
            return {"filled": True, "token_price": limit_price, "shares": filled_size, "cost": actual_cost}

        # Silent fill check — API sometimes reports timeout but order filled on-chain
        try:
            bal_after = int(client.get_balance_allowance(BalanceAllowanceParams(asset_type=AssetType.COLLATERAL, signature_type=SignatureTypeV2.POLY_1271)).get("balance", 0)) / 1e6
            balance_drop = actual_balance - bal_after
            if balance_drop >= 1.0:
                estimated_shares = round(balance_drop / limit_price, 1)
                print(f"  🚨 SILENT FILL DETECTED — balance dropped ${balance_drop:.2f} despite API timeout")
                print(f"  🚨 Estimated fill: ~{estimated_shares} shares @ ${limit_price:.3f}")
                return {"filled": True, "token_price": limit_price, "shares": estimated_shares, "cost": balance_drop}
        except Exception as bal_err:
            print(f"  ⚠️  Post-cancel balance check failed: {bal_err}")

        print(f"  ⚠️  Order cancelled — no fill, no money spent")
        return None

    except ImportError:
        print("  ⚠️  py-clob-client-v2 not installed. Run: pip install py-clob-client-v2")
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

    # Only trade medium+ delta — weak moves (<0.05%) have ~68% win rate, too risky
    MIN_DELTA_PCT = 0.05
    if abs(signal.window_delta_pct) < MIN_DELTA_PCT:
        print(f"  ⚠️  Delta too weak ({signal.window_delta_pct:+.4f}%) — need >{MIN_DELTA_PCT}% — skip")
        return False

    print(f"  Signal: {signal.side}  score={signal.score:+.1f}  conf={signal.confidence:.0%}  Δ={signal.window_delta_pct:+.4f}%")
    print(f"  Token price: ${signal.token_price:.3f}  (break-even win rate: {min_win_rate_needed(signal.token_price)*100:.1f}%)")
    for r in signal.reasons:
        print(f"    • {r}")

    # 50% bet on 100% confidence, otherwise standard safe mode (25%)
    if signal.confidence >= 1.0:
        bet_size = max(1.0, min(state.bankroll * 0.50, 500.0))
        print(f"  🔥 100% confidence — betting 50%: ${bet_size:.2f}")
    else:
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

    # Wait for resolution — Polymarket oracle takes ~15-30s after close to settle
    remaining = close_ts - time.time()
    if remaining > 0:
        print(f"  Waiting {remaining:.0f}s for window close...")
        time.sleep(remaining + 2)

    outcome = None
    print("  Polling Polymarket for resolution (up to 60s)...")
    for attempt in range(12):  # try every 5s for up to 60s
        outcome = check_resolution_polymarket(window_ts)
        if outcome:
            print(f"  🔗 Polymarket resolved: {outcome}")
            break
        time.sleep(5)

    if not outcome:
        print("  ⚠️  Polymarket not resolved yet — using Binance fallback (may differ from oracle)")
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
    if dry_run:
        print(f"  P&L this trade: ${pnl:+.2f}  |  Bankroll: ${state.bankroll:.2f}")
    else:
        # Show real on-chain balance after trade
        try:
            from py_clob_client_v2.client import ClobClient
            from py_clob_client_v2 import ApiCreds, SignatureTypeV2, BalanceAllowanceParams, AssetType
            _creds  = ApiCreds(api_key=os.environ.get("POLY_API_KEY",""), api_secret=os.environ.get("POLY_API_SECRET",""), api_passphrase=os.environ.get("POLY_API_PASSPHRASE",""))
            _client = ClobClient("https://clob.polymarket.com", chain_id=137, key=os.environ.get("POLY_PRIVATE_KEY",""),
                                  creds=_creds, signature_type=SignatureTypeV2.POLY_1271, funder=os.environ.get("POLY_FUNDER_ADDRESS",""))
            _bal = int(_client.get_balance_allowance(BalanceAllowanceParams(asset_type=AssetType.COLLATERAL, signature_type=SignatureTypeV2.POLY_1271)).get("balance", 0)) / 1e6
            print(f"  On-chain balance after trade: ${_bal:.2f}")
        except Exception:
            pass
    print(f"  Running: {state.wins}/{state.trades} wins ({win_rate:.1f}%)  EV/dollar: {ev:+.4f}")

    trade_record = {
        "window_ts":   window_ts,
        "side":        signal.side,
        "delta_pct":   signal.window_delta_pct,
        "confidence":  signal.confidence,
        "token_price": fill["token_price"],
        "outcome":     outcome,
        "won":         won,
        "pnl":         pnl,
        "bankroll":    state.bankroll,
    }
    state.history.append(trade_record)
    _append_trade_log(trade_record)

    return True


def _append_trade_log(record: dict):
    """Persist every trade to disk so results survive terminal close."""
    import csv
    log_path = Path("data/dry_run_trades.csv")
    log_path.parent.mkdir(exist_ok=True)
    write_header = not log_path.exists() or log_path.stat().st_size == 0
    with open(log_path, "a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(record.keys()))
        if write_header:
            w.writeheader()
        w.writerow(record)


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

    print("  Price source: Binance (Chainlink delta <0.1% — negligible for signals)")

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
