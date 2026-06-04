"""
Backtest Engine — Chainlink BTC/USD 5-Min Markets
===================================================
Replays real 5-min windows through the composite strategy with:
  - Window delta dominant signal (weight 5–7)
  - Delta-based token pricing (not fixed $0.50 — reflects real market cost)
  - Realistic fill simulation (slippage, staleness, adverse fills)

The pricing model is critical: at T-10s, tokens cost $0.70–0.95 when the
direction is clear. A fixed $0.50 backtest is misleading.

Usage:
    python backtest.py --data data/btc_usd_chainlink.csv
    python backtest.py --data data/btc_usd_chainlink.csv --compare
    python backtest.py --data data/btc_usd_chainlink.csv --min-conf 0.4
"""

import argparse
import csv
import random
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import List, Dict, Optional, Tuple

import numpy as np

from strategy import Signal, analyze, Candle, token_price_from_delta, min_win_rate_needed, expected_value
from execution_realism import SlippageModel, QuoteFreshnessTracker, FreshnessBucketAnalyser, QuoteSnapshot


# ── Data loading ──────────────────────────────────────────────────────────────

@dataclass
class Window:
    window_start: datetime
    window_end:   datetime
    open_price:   float
    close_price:  float
    pct_change:   float
    outcome:      str      # "UP" or "DOWN"
    rounds_used:  int


def load_windows(path: str) -> List[Window]:
    windows = []
    with open(path, newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            windows.append(Window(
                window_start = datetime.fromisoformat(row["window_start_utc"]),
                window_end   = datetime.fromisoformat(row["window_end_utc"]),
                open_price   = float(row["open_price_usd"]),
                close_price  = float(row["close_price_usd"]),
                pct_change   = float(row["pct_change"]),
                outcome      = row["outcome"],
                rounds_used  = int(row["rounds_used"]),
            ))
    return windows


def windows_to_candles(history: List[Window]) -> List[Candle]:
    """Convert Window history to Candle list for strategy.analyze()."""
    return [
        Candle(
            open=w.open_price, high=max(w.open_price, w.close_price),
            low=min(w.open_price, w.close_price), close=w.close_price,
            volume=1.0,
        )
        for w in history
    ]


# ── Snipe signal (T-10s simulation) ──────────────────────────────────────────

def simulate_t10_price(window: Window) -> float:
    """
    Realistic T-10s price simulation based on community-observed win rates.

    Key insight: at T-10s, price hasn't always "committed" to the final direction.
    Reversal probability depends on how decisive the final move was:
      delta > 0.10%  → 3%  chance wrong direction (nearly locked in)
      delta 0.05-0.10% → 8%  chance wrong direction
      delta 0.02-0.05% → 18% chance wrong direction
      delta < 0.02%  → 40% chance wrong direction (coin flip territory)

    This produces ~68-72% win rate matching real community data vs fake 97%.
    """
    close = window.close_price
    open_ = window.open_price
    final_delta = close - open_
    abs_delta_pct = abs(final_delta / open_ * 100)

    # Reversal probability: chance that T-10 price points OPPOSITE to final outcome
    if abs_delta_pct >= 0.10:
        reversal_prob = 0.03
    elif abs_delta_pct >= 0.05:
        reversal_prob = 0.08
    elif abs_delta_pct >= 0.02:
        reversal_prob = 0.18
    else:
        reversal_prob = 0.40

    # Decide if this window has a reversal at T-10
    if random.random() < reversal_prob:
        # T-10 price points the WRONG direction — small counter-move
        counter_move = abs(final_delta) * random.uniform(0.1, 0.5)
        t10_delta = -final_delta * 0.3 + (1 if final_delta < 0 else -1) * counter_move
    else:
        # Normal: T-10 at ~75-90% of final move
        progress = random.uniform(0.70, 0.92)
        noise = random.gauss(0, abs(final_delta) * 0.04 + open_ * 0.00003)
        t10_delta = final_delta * progress + noise

    return open_ + t10_delta


def snipe_signal(
    window: Window,
    history: List[Window],
    min_confidence: float = 0.30,
) -> Optional[Signal]:
    """
    Simulate T-10s snipe with realistic price uncertainty.
    Uses reversal probability model calibrated to community-observed ~68-72% win rate.
    """
    open_ = window.open_price
    close = window.close_price
    price_at_t10 = simulate_t10_price(window)

    candles = windows_to_candles(history[-21:]) if history else []

    # Simulate tick trajectory leading to T-10
    t10_progress = (price_at_t10 - open_) / (close - open_) if close != open_ else 0
    tick_prices = [
        open_ + (close - open_) * max(0, t10_progress * 0.6),
        open_ + (close - open_) * max(0, t10_progress * 0.8),
        price_at_t10,
    ]

    return analyze(
        window_open_price = open_,
        current_price     = price_at_t10,
        candles_1m        = candles,
        tick_prices       = tick_prices,
        min_confidence    = min_confidence,
    )


# ── Trade result ──────────────────────────────────────────────────────────────

@dataclass
class TradeResult:
    window_start:    datetime
    signal_side:     str
    window_delta_pct: float
    token_price:     float
    fill_price:      float
    outcome:         str
    won:             bool
    pnl:             float
    fill_reason:     str
    quote_age_s:     float
    slippage_pct:    float
    confidence:      float
    position_size:   float


# ── Backtest config ───────────────────────────────────────────────────────────

@dataclass
class BacktestConfig:
    starting_balance: float = 1000.0
    position_size:    float = 20.0
    max_exposure:     float = 200.0
    naive_mode:       bool  = False
    max_quote_age_s:  float = 3.0
    min_confidence:   float = 0.30
    seed:             int   = 42


# ── Backtest runner ───────────────────────────────────────────────────────────

def run_backtest(windows: List[Window], cfg: BacktestConfig) -> Tuple[List[TradeResult], Dict]:
    random.seed(cfg.seed)

    slippage_model    = SlippageModel() if not cfg.naive_mode else None
    freshness_tracker = QuoteFreshnessTracker(cfg.max_quote_age_s) if not cfg.naive_mode else None
    bucket_analyser   = FreshnessBucketAnalyser()

    balance = cfg.starting_balance
    trades  = []
    history: List[Window] = []

    for i, window in enumerate(windows):
        history.append(window)

        signal = snipe_signal(window, history[:-1], cfg.min_confidence)
        if not signal:
            continue

        # Delta-based token pricing (not fixed $0.50)
        quoted_price = signal.token_price

        if cfg.naive_mode:
            fill_price  = quoted_price
            fill_reason = "filled"
            quote_age   = 0.0
            slip_pct    = 0.0
            filled      = True
        else:
            # Simulate quote age distribution (matches execution_realism model)
            r = random.random()
            if r < 0.05:
                quote_age = random.uniform(20, 90)
            elif r < 0.20:
                quote_age = random.uniform(5, 20)
            else:
                quote_age = random.uniform(0, 2)

            snapshot = QuoteSnapshot(
                market_id   = f"window_{i}",
                outcome     = "YES",
                price       = quoted_price,
                captured_at = datetime.now(tz=timezone.utc) - timedelta(seconds=quote_age),
            )

            fresh, age = freshness_tracker.is_fresh(snapshot)
            quote_age  = age
            if not fresh:
                continue

            fill = slippage_model.simulate_fill(
                quoted_price      = quoted_price,
                side              = "BUY",
                size              = cfg.position_size,
                quote_age_seconds = quote_age,
                is_market_order   = True,
            )
            fill_price  = fill.fill_price
            fill_reason = fill.reason
            slip_pct    = fill.slippage_pct
            filled      = fill.filled

            if not filled:
                continue

        won = (signal.side == "BUY_YES" and window.outcome == "UP") or \
              (signal.side == "BUY_NO"  and window.outcome == "DOWN")

        # Binary market P&L (2% taker fee applied to cost)
        from strategy import TAKER_FEE
        fee = fill_price * cfg.position_size * TAKER_FEE
        if won:
            pnl = (1.0 - fill_price) * cfg.position_size - fee
        else:
            pnl = -fill_price * cfg.position_size - fee

        balance += pnl
        bucket_analyser.record_trade(quote_age if not cfg.naive_mode else 0.0, pnl)

        trades.append(TradeResult(
            window_start     = window.window_start,
            signal_side      = signal.side,
            window_delta_pct = signal.window_delta_pct,
            token_price      = quoted_price,
            fill_price       = fill_price,
            outcome          = window.outcome,
            won              = won,
            pnl              = pnl,
            fill_reason      = fill_reason,
            quote_age_s      = quote_age if not cfg.naive_mode else 0.0,
            slippage_pct     = slip_pct,
            confidence       = signal.confidence,
            position_size    = cfg.position_size,
        ))

    total_pnl = sum(t.pnl for t in trades)
    win_rate  = sum(1 for t in trades if t.won) / len(trades) if trades else 0
    adverse   = sum(1 for t in trades if t.fill_reason == "adverse_fill")
    avg_slip  = float(np.mean([t.slippage_pct for t in trades]) * 100) if trades else 0
    p95_slip  = float(np.percentile([t.slippage_pct for t in trades], 95) * 100) if trades else 0
    avg_token = float(np.mean([t.token_price for t in trades])) if trades else 0
    avg_conf  = float(np.mean([t.confidence for t in trades])) if trades else 0
    freshness_stats = freshness_tracker.stats() if freshness_tracker else {}

    # Delta bucket breakdown
    delta_buckets: Dict[str, Dict] = {}
    for t in trades:
        ad = abs(t.window_delta_pct)
        if ad >= 0.10:
            bucket = ">0.10% (decisive)"
        elif ad >= 0.05:
            bucket = "0.05-0.10% (strong)"
        elif ad >= 0.02:
            bucket = "0.02-0.05% (moderate)"
        else:
            bucket = "<0.02% (weak)"
        b = delta_buckets.setdefault(bucket, {"trades": 0, "wins": 0, "pnl": 0.0, "avg_price": []})
        b["trades"] += 1
        b["wins"]   += 1 if t.won else 0
        b["pnl"]    += t.pnl
        b["avg_price"].append(t.token_price)

    summary = {
        "starting_balance": cfg.starting_balance,
        "final_balance":    balance,
        "total_pnl":        total_pnl,
        "total_trades":     len(trades),
        "win_rate":         win_rate,
        "adverse_fills":    adverse,
        "avg_slippage_pct": avg_slip,
        "p95_slippage_pct": p95_slip,
        "avg_token_price":  avg_token,
        "avg_confidence":   avg_conf,
        "stale_blocks":     freshness_stats.get("stale_blocks", 0),
        "bucket_report":    bucket_analyser.report(),
        "delta_buckets":    delta_buckets,
    }
    return trades, summary


# ── Printers ──────────────────────────────────────────────────────────────────

def print_delta_breakdown(summary: Dict):
    print("\n── Delta Bucket Breakdown ───────────────────────────────────────────")
    print(f"  {'Bucket':<24} {'Trades':>6}  {'Win%':>6}  {'Avg Token':>10}  {'PnL':>9}  {'Min WR':>7}")
    print("  " + "-"*70)
    for bucket, b in sorted(summary["delta_buckets"].items()):
        wr    = b["wins"] / b["trades"] * 100 if b["trades"] else 0
        avg_p = sum(b["avg_price"]) / len(b["avg_price"]) if b["avg_price"] else 0
        needed = min_win_rate_needed(avg_p) * 100
        ev    = expected_value(avg_p, b["wins"] / b["trades"] if b["trades"] else 0)
        flag  = "✅" if ev > 0 else "❌"
        print(f"  {bucket:<24} {b['trades']:>6}  {wr:>5.1f}%  ${avg_p:>8.3f}  {b['pnl']:>+8.2f}  {needed:>6.1f}% {flag}")
    print()


def print_comparison(naive_summary: Dict, real_summary: Dict, windows: List[Window], min_conf: float):
    n = naive_summary
    r = real_summary
    gap = r["total_pnl"] - n["total_pnl"]
    up_pct = sum(1 for w in windows if w.outcome == "UP") / len(windows) * 100

    W = 78
    def row(label, nv, rv):
        print(f"║  {label:<36} {nv:>16}  {rv:>16}  ║")

    print("\n")
    print("╔" + "═"*W + "╗")
    print("║  BACKTEST: REAL CHAINLINK BTC/USD — NAIVE vs REALISTIC (DELTA PRICING)" + " "*(W-72) + "║")
    print("╠" + "═"*W + "╣")
    print(f"║  Windows: {len(windows):,}  |  {windows[0].window_start.date()} → {windows[-1].window_start.date()}  |  min_conf={min_conf:.0%}  |  BTC UP%={up_pct:.1f}%" + " "*(W-72) + "║")
    print("╠" + "═"*W + "╣")
    print(f"║  {'Metric':<36} {'Naive':>16}  {'Realistic':>16}  ║")
    print("╠" + "═"*W + "╣")
    row("Final balance",        f"${n['final_balance']:>12.2f}", f"${r['final_balance']:>12.2f}")
    row("Total P&L",            f"${n['total_pnl']:>+12.2f}",   f"${r['total_pnl']:>+12.2f}")
    row("P&L %",                f"{n['total_pnl']/n['starting_balance']*100:>+11.2f}%",
                                f"{r['total_pnl']/r['starting_balance']*100:>+11.2f}%")
    row("Trades taken",         f"{n['total_trades']:>16}",      f"{r['total_trades']:>16}")
    row("Win rate",             f"{n['win_rate']*100:>15.1f}%",  f"{r['win_rate']*100:>15.1f}%")
    row("Avg token price",      f"${n['avg_token_price']:>11.3f}",f"${r['avg_token_price']:>11.3f}")
    row("Min WR needed (avg)",  f"{n['avg_token_price']*100:>15.1f}%",f"{r['avg_token_price']*100:>15.1f}%")
    row("Avg confidence",       f"{n['avg_confidence']*100:>15.1f}%",f"{r['avg_confidence']*100:>15.1f}%")
    row("Stale quotes blocked", f"{'0':>16}",                    f"{r['stale_blocks']:>16}")
    row("Adverse fills",        f"{'0':>16}",                    f"{r['adverse_fills']:>16}")
    row("Avg slippage",         f"{'0.000%':>16}",               f"{r['avg_slippage_pct']:>15.3f}%")
    print("╠" + "═"*W + "╣")
    pct_of_naive = (gap / abs(n["total_pnl"]) * 100) if n["total_pnl"] != 0 else 0
    print(f"║  {'EXECUTION COST (gap)':<36} {'':>16}  {gap:>+15.2f}  ║")
    print(f"║  {'  as % of naive P&L':<36} {'':>16}  {pct_of_naive:>+13.1f}%  ║")
    print("╚" + "═"*W + "╝")

    # Verdict
    ev = expected_value(n["avg_token_price"], n["win_rate"])
    print(f"\n  Strategy verdict (naive): ", end="")
    if ev > 0:
        print(f"✅ Positive EV = {ev:+.4f} per $ risked")
    else:
        print(f"❌ Negative EV = {ev:+.4f} per $ risked")
        print(f"     Win rate {n['win_rate']*100:.1f}% < token cost {n['avg_token_price']*100:.1f}% break-even")

    print_delta_breakdown(n)
    print(n["bucket_report"])


# ── Entry point ───────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Backtest on real Chainlink BTC/USD data")
    parser.add_argument("--data",     default="data/btc_usd_chainlink.csv")
    parser.add_argument("--compare",  action="store_true", help="Naive vs realistic side-by-side")
    parser.add_argument("--naive",    action="store_true", help="Naive mode only")
    parser.add_argument("--size",     type=float, default=20.0)
    parser.add_argument("--balance",  type=float, default=1000.0)
    parser.add_argument("--min-conf", type=float, default=0.30, help="Min confidence to trade (default: 0.30)")
    args = parser.parse_args()

    data_path = Path(args.data)
    if not data_path.exists():
        print(f"\n❌  Data file not found: {data_path}")
        print("   Run first:  python chainlink_fetcher.py")
        return

    print(f"\n  Loading {data_path}...")
    windows = load_windows(str(data_path))
    print(f"  Loaded {len(windows):,} windows")

    cfg_base = {
        "starting_balance": args.balance,
        "position_size":    args.size,
        "min_confidence":   args.min_conf,
    }

    if args.naive:
        cfg = BacktestConfig(**cfg_base, naive_mode=True)
        _, summary = run_backtest(windows, cfg)
        print_delta_breakdown(summary)
        print(summary["bucket_report"])
    else:
        print("  Running naive backtest...")
        _, naive_summary = run_backtest(windows, BacktestConfig(**cfg_base, naive_mode=True, seed=42))

        print("  Running realistic backtest...")
        _, real_summary  = run_backtest(windows, BacktestConfig(**cfg_base, naive_mode=False, seed=42))

        print_comparison(naive_summary, real_summary, windows, args.min_conf)


if __name__ == "__main__":
    main()
