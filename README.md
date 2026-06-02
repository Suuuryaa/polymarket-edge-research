# polymarket-edge-research

> **Work in Progress** — Building a bot that trades Polymarket's 5-minute BTC prediction markets profitably.

![Status](https://img.shields.io/badge/Status-Work%20In%20Progress-yellow)
![Python](https://img.shields.io/badge/Python-3.9%2B-blue?logo=python)
![License](https://img.shields.io/badge/License-MIT-green)

---

## The Problem

Every 5 minutes, Polymarket opens a market with one question:

> **"Will BTC be higher or lower than it was 5 minutes ago?"**

If you're right, your token pays $1.00. If you're wrong, you lose what you paid.

Sounds simple. But 92% of traders lose money on these markets. Most bots look profitable in testing, then fail in real trading. This project figures out exactly why — and builds something that doesn't fail.

---

## Why Most Bots Fail

**Problem 1 — Wrong token pricing in backtests**
When you test a strategy, you assume you can buy a token for $0.50. But by the time you have a clear signal (10 seconds before close), the market already knows what you know. The winning token costs $0.70–$0.92. That changes everything.

**Problem 2 — Wrong signal**
Most bots use momentum — "BTC went up 3 times in a row, bet UP." That has basically zero edge. The only signal that works is: *is BTC right now higher or lower than it was when this 5-minute window opened?* That directly answers the market's question.

**Problem 3 — Execution reality**
Real orders face a 250ms delay, stale prices, and unpredictable fills. A bot that wins 68% in simulation can lose money live because of these hidden costs.

---

## What We Built

### The Signal
A 7-indicator composite score. One indicator dominates everything else:

**Window Delta** = `(current BTC price − window open price) / window open price`

At 10 seconds before the window closes, if BTC is already up 0.10% from the open — it almost never reverses in 10 seconds. That's a near-certain win. The bot weights this signal 5–7× more than anything else.

The other 6 indicators (momentum, EMA crossover, RSI, volume, tick trend) add small supporting evidence but never override a clear window delta.

### The Timing
```
Every 5 minutes, a new window opens on Polymarket.
The bot sleeps until exactly 10 seconds before it closes.
Then it polls BTC price every 2 seconds.
At 5 seconds before close — it fires, no matter what.
```
This is called a **snipe**. Enter late, when direction is certain. Accept a higher token price in exchange for much higher accuracy.

### The Pricing Model
The bot knows that confident signals = expensive tokens. It never assumes $0.50.

| How clear the signal is | Token costs | You need to win |
|---|---|---|
| Barely any move | $0.50 | 50% of the time |
| Small move (0.02%) | $0.55 | 55% of the time |
| Medium move (0.05%) | $0.65 | 65% of the time |
| Strong move (0.10%) | $0.80 | 80% of the time |
| Decisive move (0.15%+) | $0.92 | 92% of the time |

### The Oracle
Polymarket resolves markets using **Chainlink** — a specific crypto price feed, not Binance. The bot connects directly to Polymarket's live Chainlink WebSocket to get the exact same price the market resolves against.

---

## Current Results

Backtested on 7 days of real BTC/USD data (2,016 five-minute windows):

- **Win rate: 88.6%** — needs 67.6% to break even ✅
- **Positive EV: +$0.21 per dollar risked** ✅  
- **Execution costs eat 32%** of naive profits ⚠️

The weak spot: these results are simulated. The win rate model is calibrated against community data (~68–72% real win rate). We need 30 days of live data to confirm.

---

## Current Status

| What | Status |
|---|---|
| Signal engine (7 indicators) | ✅ Built |
| Realistic token pricing | ✅ Built |
| Backtest engine | ✅ Built |
| Chainlink oracle connection | ✅ Built |
| Clock-based snipe bot | ✅ Built |
| 30-day live data collection | 🔄 Running now on cloud |
| Live dry-run validation | 📋 After data collection |
| Auto-claim wins | 📋 Planned |

---

## How to Run

```bash
git clone https://github.com/Suuuryaa/polymarket-edge-research
cd polymarket-edge-research
pip install -r requirements.txt

# Get BTC data
python chainlink_fetcher.py --days 7

# Run backtest
python backtest.py --compare

# Dry run — real data, no real money
python bot.py --dry-run --mode safe
```

Copy `.env.example` → `.env` and add your Polymarket credentials for live trading.

---

## Files

| File | What it does |
|---|---|
| `bot.py` | Main snipe bot — clock timing, signal, order execution |
| `strategy.py` | 7-indicator signal with window delta dominant |
| `backtest.py` | Replay historical data through the strategy |
| `chainlink_fetcher.py` | Fetch BTC/USD 5-min candles from Binance or on-chain |
| `collect_data.py` | Live data collector — runs 24/7, one row per 5 minutes |
| `execution_realism.py` | Models real fill costs: slippage, staleness, adverse fills |
| `paper_trading.py` | Paper trading simulator |
