"""
Backtest Engine — Chainlink BTC/USD 5-Min Markets
===================================================
Replays real Chainlink BTC/USD windows through the strategy + execution
realism layer. Shows what a strategy ACTUALLY would have made vs what a
naive paper bot would have reported.

Usage:
    python backtest.py --data data/btc_usd_chainlink.csv
    python backtest.py --data data/btc_usd_chainlink.csv --naive
    python backtest.py --data data/btc_usd_chainlink.csv --compare
"""

import argparse
import csv
import random
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Dict, Optional, Tuple

import numpy as np

from execution_realism import SlippageModel, QuoteFreshnessTracker, FreshnessBucketAnalyser, QuoteSnapshot


# ── Data loading ──────────────────────────────────────────────────────────────

@dataclass
class Window:
    window_start: datetime
    open_price:   float
    close_price:  float
    pct_change:   float    # % move in 5-min window
    outcome:      str      # "UP" or "DOWN"
    rounds_used:  int


def load_windows(path: str) -> List[Window]:
    windows = []
    with open(path, newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            windows.append(Window(
                window_start = datetime.fromisoformat(row["window_start_utc"]),
                open_price   = float(row["open_price_usd"]),
                close_price  = float(row["close_price_usd"]),
                pct_change   = float(row["pct_change"]),
                outcome      = row["outcome"],
                rounds_used  = int(row["rounds_used"]),
            ))
    return windows


# ── Prediction market price model ─────────────────────────────────────────────

def estimate_market_price(
    window: Window,
    lookahead_windows: List[Window],
    history_windows: List[Window],
) -> Dict[str, float]:
    """
    Estimate what the Polymarket YES/NO prices would be just before resolution.

    In a perfectly efficient market, YES price = P(BTC goes UP in 5 min).
    We estimate this from recent momentum:
      - Base rate: ~50% (BTC is roughly 50/50 short term)
      - Adjusted by recent momentum signal
    """
    # Base probability from last 20 windows
    recent = history_windows[-20:] if len(history_windows) >= 20 else history_windows
    if not recent:
        up_prob = 0.50
    else:
        up_count = sum(1 for w in recent if w.outcome == "UP")
        up_prob  = up_count / len(recent)
        # Momentum: last 3 windows all same direction → slight edge
        last3 = recent[-3:]
        if len(last3) == 3 and all(w.outcome == "UP" for w in last3):
            up_prob = min(0.65, up_prob + 0.05)
        elif len(last3) == 3 and all(w.outcome == "DOWN" for w in last3):
            up_prob = max(0.35, up_prob - 0.05)

    yes_price = round(max(0.05, min(0.95, up_prob)), 3)
    no_price  = round(1.0 - yes_price, 3)
    return {"YES": yes_price, "NO": no_price}


# ── Strategy ──────────────────────────────────────────────────────────────────

@dataclass
class Signal:
    side:       str      # "BUY_YES", "BUY_NO"
    price:      float
    confidence: float
    reason:     str


def momentum_signal(
    window: Window,
    history: List[Window],
    buy_threshold: float = 0.05,
    min_confidence: float = 0.55,
) -> Optional[Signal]:
    """
    Momentum signal based on recent 5-min windows.
    If last 3 windows are all UP → buy YES
    If last 3 windows are all DOWN → buy NO
    """
    if len(history) < 3:
        return None

    last3     = history[-3:]
    prices    = [w.pct_change for w in last3]
    avg_move  = sum(prices) / len(prices)
    all_up    = all(w.outcome == "UP"   for w in last3)
    all_down  = all(w.outcome == "DOWN" for w in last3)

    market_prices = estimate_market_price(window, [], history)

    if all_up and avg_move > buy_threshold / 10:
        confidence = min(0.80, 0.50 + abs(avg_move) * 20)
        if confidence >= min_confidence:
            return Signal(
                side="BUY_YES",
                price=market_prices["YES"],
                confidence=confidence,
                reason=f"3× UP streak, avg move={avg_move:+.4f}%",
            )

    elif all_down and avg_move < -buy_threshold / 10:
        confidence = min(0.80, 0.50 + abs(avg_move) * 20)
        if confidence >= min_confidence:
            return Signal(
                side="BUY_NO",
                price=market_prices["NO"],
                confidence=confidence,
                reason=f"3× DOWN streak, avg move={avg_move:+.4f}%",
            )

    return None


# ── Trade result ──────────────────────────────────────────────────────────────

@dataclass
class TradeResult:
    window_start:  datetime
    signal_side:   str
    quoted_price:  float
    fill_price:    float
    outcome:       str       # actual Chainlink outcome
    won:           bool
    pnl:           float
    fill_reason:   str
    quote_age_s:   float
    slippage_pct:  float
    position_size: float


# ── Backtest runner ───────────────────────────────────────────────────────────

@dataclass
class BacktestConfig:
    starting_balance:  float = 1000.0
    position_size:     float = 20.0      # $ per trade
    max_exposure:      float = 200.0     # max $ at risk at once
    naive_mode:        bool  = False
    max_quote_age_s:   float = 3.0       # freshness gate
    seed:              int   = 42


def run_backtest(windows: List[Window], cfg: BacktestConfig) -> Tuple[List[TradeResult], Dict]:
    random.seed(cfg.seed)

    slippage_model   = SlippageModel() if not cfg.naive_mode else None
    freshness_tracker = QuoteFreshnessTracker(cfg.max_quote_age_s) if not cfg.naive_mode else None
    bucket_analyser  = FreshnessBucketAnalyser()

    balance      = cfg.starting_balance
    trades       = []
    history      = []

    for i, window in enumerate(windows):
        history.append(window)

        signal = momentum_signal(window, history[:-1])
        if not signal:
            continue

        if cfg.naive_mode:
            # Naive: always fills at quoted price, zero fees, no staleness
            fill_price   = signal.price
            fill_reason  = "filled"
            quote_age    = 0.0
            slip_pct     = 0.0
            filled       = True
        else:
            # Realistic: quote age simulated, staleness gate, slippage model
            # Simulate quote age: mostly fresh, occasionally stale
            r = random.random()
            if r < 0.05:
                quote_age = random.uniform(20, 90)   # p5 tail — toxic
            elif r < 0.20:
                quote_age = random.uniform(5, 20)    # moderate delay
            else:
                quote_age = random.uniform(0, 2)     # fresh

            snapshot = QuoteSnapshot(
                market_id   = f"window_{i}",
                outcome     = "YES",
                price       = signal.price,
                captured_at = datetime.now(tz=timezone.utc),
            )
            # Manually set age for simulation (override captured_at effect)
            from datetime import timedelta
            snapshot = QuoteSnapshot(
                market_id   = f"window_{i}",
                outcome     = "YES",
                price       = signal.price,
                captured_at = datetime.now(tz=timezone.utc).__class__.now(tz=timezone.utc) - timedelta(seconds=quote_age),
            )

            fresh, age = freshness_tracker.is_fresh(snapshot)
            quote_age  = age

            if not fresh:
                continue   # blocked by freshness gate

            fill = slippage_model.simulate_fill(
                quoted_price    = signal.price,
                side            = "BUY",
                size            = cfg.position_size,
                quote_age_seconds = quote_age,
                is_market_order = True,
            )
            fill_price  = fill.fill_price
            fill_reason = fill.reason
            slip_pct    = fill.slippage_pct
            filled      = fill.filled

            if not filled:
                continue

        # Determine if trade won
        # BUY_YES wins if outcome is UP; BUY_NO wins if outcome is DOWN
        won = (signal.side == "BUY_YES" and window.outcome == "UP") or \
              (signal.side == "BUY_NO"  and window.outcome == "DOWN")

        # P&L: binary market — if win, profit = (1 - fill_price) * size
        #                       if lose, loss  = fill_price * size
        if won:
            pnl = (1.0 - fill_price) * cfg.position_size
        else:
            pnl = -fill_price * cfg.position_size

        balance += pnl
        bucket_analyser.record_trade(quote_age if not cfg.naive_mode else 0.0, pnl)

        trades.append(TradeResult(
            window_start  = window.window_start,
            signal_side   = signal.side,
            quoted_price  = signal.price,
            fill_price    = fill_price,
            outcome       = window.outcome,
            won           = won,
            pnl           = pnl,
            fill_reason   = fill_reason,
            quote_age_s   = quote_age if not cfg.naive_mode else 0.0,
            slippage_pct  = slip_pct,
            position_size = cfg.position_size,
        ))

    # Summary stats
    total_pnl    = sum(t.pnl for t in trades)
    win_rate     = sum(1 for t in trades if t.won) / len(trades) if trades else 0
    adverse      = sum(1 for t in trades if t.fill_reason == "adverse_fill")
    avg_slip     = np.mean([t.slippage_pct for t in trades]) * 100 if trades else 0
    p95_slip     = float(np.percentile([t.slippage_pct for t in trades], 95)) * 100 if trades else 0
    freshness_stats = freshness_tracker.stats() if freshness_tracker else {}

    summary = {
        "starting_balance":  cfg.starting_balance,
        "final_balance":     balance,
        "total_pnl":         total_pnl,
        "total_trades":      len(trades),
        "win_rate":          win_rate,
        "adverse_fills":     adverse,
        "avg_slippage_pct":  avg_slip,
        "p95_slippage_pct":  p95_slip,
        "stale_blocks":      freshness_stats.get("stale_blocks", 0),
        "bucket_report":     bucket_analyser.report(),
    }
    return trades, summary


# ── Comparison printer ────────────────────────────────────────────────────────

def print_comparison(naive_summary: Dict, real_summary: Dict, windows: List[Window]):
    n = naive_summary
    r = real_summary
    gap = r["total_pnl"] - n["total_pnl"]

    up_pct = sum(1 for w in windows if w.outcome == "UP") / len(windows) * 100

    print("\n")
    print("╔" + "═"*76 + "╗")
    print("║  BACKTEST: REAL CHAINLINK BTC/USD DATA — NAIVE vs REALISTIC" + " "*16 + "║")
    print("╠" + "═"*76 + "╣")
    print(f"║  Windows: {len(windows):,}  |  Date range: {windows[0].window_start.date()} → {windows[-1].window_start.date()}" + " "*20 + "║")
    print(f"║  BTC UP%: {up_pct:.1f}%  (base rate — random guessing wins {up_pct:.1f}% of the time)" + " "*5 + "║")
    print("╠" + "═"*76 + "╣")
    print(f"║  {'Metric':<34} {'Naive':>16}  {'Realistic':>16}  ║")
    print("╠" + "═"*76 + "╣")

    rows = [
        ("Final balance",       f"${n['final_balance']:>12.2f}",    f"${r['final_balance']:>12.2f}"),
        ("Total P&L",           f"${n['total_pnl']:>+12.2f}",       f"${r['total_pnl']:>+12.2f}"),
        ("P&L %",               f"{n['total_pnl']/n['starting_balance']*100:>+11.2f}%",
                                f"{r['total_pnl']/r['starting_balance']*100:>+11.2f}%"),
        ("Trades taken",        f"{n['total_trades']:>16}",          f"{r['total_trades']:>16}"),
        ("Win rate",            f"{n['win_rate']*100:>15.1f}%",      f"{r['win_rate']*100:>15.1f}%"),
        ("Stale quotes blocked",f"{'0':>16}",                        f"{r['stale_blocks']:>16}"),
        ("Adverse fills",       f"{'0':>16}",                        f"{r['adverse_fills']:>16}"),
        ("Avg slippage",        f"{'0.000%':>16}",                   f"{r['avg_slippage_pct']:>15.3f}%"),
        ("p95 slippage",        f"{'0.000%':>16}",                   f"{r['p95_slippage_pct']:>15.3f}%"),
    ]

    for label, nv, rv in rows:
        print(f"║  {label:<34} {nv:>16}  {rv:>16}  ║")

    print("╠" + "═"*76 + "╣")
    pct_of_naive = (gap / abs(n["total_pnl"]) * 100) if n["total_pnl"] != 0 else 0
    print(f"║  {'EXECUTION COST (gap)':<34} {'':>16}  {gap:>+15.2f}  ║")
    print(f"║  {'  as % of naive P&L':<34} {'':>16}  {pct_of_naive:>+14.1f}%  ║")
    print("╚" + "═"*76 + "╝")

    has_edge = n["win_rate"] > 0.52
    print(f"\n  Strategy verdict: ", end="")
    if has_edge and r["total_pnl"] > 0:
        print("✅ Edge survives execution costs — strategy is viable")
    elif has_edge and r["total_pnl"] <= 0:
        print("⚠️  Naive edge exists but execution costs kill it — needs improvement")
    else:
        print("❌ No edge — win rate too close to base rate (50%)")

    print(r["bucket_report"])


def print_single(summary: Dict, mode: str, windows: List[Window]):
    s = summary
    print(f"\n{'='*60}")
    print(f"  BACKTEST RESULTS — {mode.upper()}")
    print(f"  {len(windows):,} real Chainlink 5-min windows")
    print(f"{'='*60}")
    print(f"  Final balance:   ${s['final_balance']:.2f}")
    print(f"  Total P&L:       ${s['total_pnl']:+.2f} ({s['total_pnl']/s['starting_balance']*100:+.2f}%)")
    print(f"  Trades:          {s['total_trades']}")
    print(f"  Win rate:        {s['win_rate']*100:.1f}%")
    if mode == "realistic":
        print(f"  Stale blocks:    {s['stale_blocks']}")
        print(f"  Adverse fills:   {s['adverse_fills']}")
        print(f"  Avg slippage:    {s['avg_slippage_pct']:.3f}%")
    print(s["bucket_report"])


# ── Entry point ───────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Backtest on real Chainlink BTC/USD data")
    parser.add_argument("--data",    default="data/btc_usd_chainlink.csv", help="Path to windows CSV")
    parser.add_argument("--naive",   action="store_true",  help="Run naive mode only")
    parser.add_argument("--compare", action="store_true",  help="Side-by-side comparison (default)")
    parser.add_argument("--size",    type=float, default=20.0, help="Position size $ (default: 20)")
    parser.add_argument("--balance", type=float, default=1000.0, help="Starting balance (default: 1000)")
    args = parser.parse_args()

    data_path = Path(args.data)
    if not data_path.exists():
        print(f"\n❌  Data file not found: {data_path}")
        print("   Run first:  python chainlink_fetcher.py")
        return

    print(f"\n  Loading {data_path}...")
    windows = load_windows(str(data_path))
    print(f"  Loaded {len(windows):,} windows")

    cfg_base = BacktestConfig(
        starting_balance = args.balance,
        position_size    = args.size,
    )

    if args.naive:
        cfg = BacktestConfig(**{**cfg_base.__dict__, "naive_mode": True})
        _, summary = run_backtest(windows, cfg)
        print_single(summary, "naive", windows)

    else:
        # Default: compare mode
        print("  Running naive backtest...")
        cfg_naive = BacktestConfig(**{**cfg_base.__dict__, "naive_mode": True,  "seed": 42})
        _, naive_summary = run_backtest(windows, cfg_naive)

        print("  Running realistic backtest (same seed)...")
        cfg_real = BacktestConfig(**{**cfg_base.__dict__, "naive_mode": False, "seed": 42})
        _, real_summary = run_backtest(windows, cfg_real)

        print_comparison(naive_summary, real_summary, windows)


if __name__ == "__main__":
    main()
