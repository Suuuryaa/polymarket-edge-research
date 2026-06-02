# polymarket-edge-research

> **Work in Progress** — Building and backtesting a clock-based snipe bot for Polymarket 5-minute BTC Up/Down markets.

![Status](https://img.shields.io/badge/Status-Work%20In%20Progress-yellow)
![Python](https://img.shields.io/badge/Python-3.9%2B-blue?logo=python)
![License](https://img.shields.io/badge/License-MIT-green)

---

## What This Is

Most Polymarket bots look profitable in paper trading and bleed money live. This project investigates **why** — and builds the infrastructure to close the gap.

The core insight: paper bots assume you fill at mid ± a tick. Real fills are bimodal:

- **No fill** — you posted a limit order and nobody took the other side
- **Adverse fill** — you filled exactly when you shouldn't have (the counterparty had fresher data)

This repo researches and implements the missing layers: **execution realism + realistic signal design**.

---

## Key Findings So Far

| Finding | Detail |
|---|---|
| Fixed $0.50 token pricing = fake profits | At T-10s, tokens cost $0.65–$0.92 depending on delta |
| 3-candle momentum has no edge | 50.7% win rate vs 49.3% base rate — statistically noise |
| Window delta is the dominant signal | `(current - window_open) / window_open` with weight 5-7x |
| T-10s is optimal entry | Direction locked in, tokens not yet at max price |
| 250ms taker delay on BTC markets | Hardcoded by Polymarket — affects all taker orders |
| Execution costs eat 20-30% of naive P&L | Slippage + stale quotes + adverse fills |

---

## Research Status

| Topic | Status | Finding |
|---|---|---|
| Quote freshness distribution | ✅ Done | p95 freshness explodes to ~67s in tail scenarios |
| Slippage modeling | ✅ Done | Bimodal: no-fill or adverse-fill, not gaussian |
| PnL by freshness bucket | ✅ Done | Stale quotes account for majority of losses |
| Strategy backtesting | ✅ Done | Composite signal: +0.21 EV/dollar, 88.6% win rate |
| Delta-based token pricing | ✅ Done | Piecewise linear model matching live Polymarket spreads |
| Composite signal (7 indicators) | ✅ Done | Window delta dominant, T-10s snipe loop |
| Chainlink WebSocket oracle | ✅ Done | `wss://ws-live-data.polymarket.com` connected |
| 30-day live data collection | 🔄 In Progress | Deploying to cloud VM |
| Live dry-run validation | 📋 Planned | Compare simulated vs actual token prices |
| Auto-claim wins | 📋 Planned | Playwright-based background claimer |

---

## Architecture

```
chainlink_fetcher.py   — Fetch BTC/USD 5-min data (Binance or Chainlink on-chain)
strategy.py            — Composite 7-indicator signal with window delta dominant
backtest.py            — Backtest engine with delta-based token pricing
bot.py                 — Clock-based snipe bot (T-10s entry, Chainlink WebSocket)
execution_realism.py   — Quote freshness + slippage + adverse fill modeling
paper_trading.py       — Paper trading simulator with naive vs realistic comparison
```

---

## Strategy: Composite Signal

Seven weighted indicators. **Window delta dominates** — it directly answers the market question.

| Indicator | Weight | Why |
|---|---|---|
| Window delta | 5–7 | `(current - window_open) / window_open` — the exact market question |
| Micro momentum | 2 | Last 2 candles direction |
| Acceleration | 1.5 | Is momentum building or fading? |
| EMA 9/21 crossover | 1 | Short-term trend |
| RSI 14 | 1–2 | Overbought/oversold extremes only |
| Volume surge | 1 | 1.5x recent vs prior volume confirms direction |
| Tick trend | 2 | 2-second poll micro-trend during snipe window |

**Token pricing model** (piecewise linear, matches live Polymarket spreads):

| Delta | Token Cost | Break-even Win Rate |
|---|---|---|
| < 0.005% | $0.50 | 50% |
| ~0.02% | $0.55 | 55% |
| ~0.05% | $0.65 | 65% |
| ~0.10% | $0.80 | 80% |
| ≥ 0.15% | $0.92 | 92% |

---

## Backtest Results (7 days, 2,016 windows)

```
Win rate:          88.6%  (break-even needed: 67.6%)
EV per dollar:    +0.21
Avg token price:   $0.676
Execution cost:    31.9% of naive P&L

Delta breakdown:
  <0.02%  weak:        68.7% win @ $0.519  ✅ slight edge
  0.02-0.05% moderate: 87.6% win @ $0.594  ✅ good edge
  0.05-0.10% strong:   96.2% win @ $0.717  ✅ strong edge
  >0.10%  decisive:    99.4% win @ $0.886  ✅ high win, thin margin
```

> ⚠️ Win rate is simulated with reversal probability model. Real expected: 68–75% based on community reports. 30-day live data collection in progress.

---

## Bot Timing

```
window_ts  = now - (now % 300)             # current 5-min window start
close_ts   = window_ts + 300               # exact close time
slug       = f"btc-updown-5m-{window_ts}"  # deterministic market slug

T-10s → enter TA loop (poll every 2s)
T-5s  → hard deadline: always trade
```

---

## Setup

```bash
git clone https://github.com/Suuuryaa/polymarket-edge-research
cd polymarket-edge-research
pip install -r requirements.txt

# Fetch BTC data
python chainlink_fetcher.py --days 7

# Run backtest
python backtest.py --compare

# Dry run bot (no real trades)
python bot.py --dry-run --mode safe
python bot.py --dry-run --mode degen --once
```

For live trading, copy `.env.example` to `.env` and fill in your Polymarket credentials.
