# polymarket-edge-research

> **Work in Progress** — Building a bot that trades Polymarket's 5-minute BTC prediction markets profitably.

![Status](https://img.shields.io/badge/Status-Work%20In%20Progress-yellow)
![Python](https://img.shields.io/badge/Python-3.9%2B-blue?logo=python)
![License](https://img.shields.io/badge/License-MIT-green)

---

## The Problem

Every 5 minutes, Polymarket opens a market with one question:

> **"Will BTC be higher or lower than it was 5 minutes ago?"**

If you're right, your token pays $1.00. If you're wrong, you lose what you paid. Sounds simple. But **92% of traders lose money** on these markets. Most bots look profitable in testing, then fail in real trading. This project figures out exactly why — and builds something that doesn't fail.

---

## How the Bot Works

```mermaid
flowchart LR
    A([🕐 Clock\nTick]) --> B{New 5-min\nwindow?}
    B -- No --> A
    B -- Yes --> C[😴 Sleep until\nT-10s]
    C --> D[📡 Connect\nChainlink Oracle]
    D --> E[🔄 Poll BTC price\nevery 2 seconds]
    E --> F{Score\nstrong enough?}
    F -- No + time left --> E
    F -- Yes OR T-5s --> G[🎯 Fire Order\nFOK Market Buy]
    G --> H[⏳ Wait for\nwindow close]
    H --> I{BTC up\nor down?}
    I -- Correct --> J[✅ WIN\n+$0.08–$0.35]
    I -- Wrong --> K[❌ LOSS\n-$0.65–$0.92]
    J --> A
    K --> A
```

---

## Why Most Bots Fail

```mermaid
pie title Where Bot Profits Go
    "Actual profit kept" : 68
    "Execution costs (slippage + delays)" : 20
    "Stale quote losses" : 8
    "Adverse fills" : 4
```

**The 3 hidden killers:**
- 📉 **Wrong token price in backtests** — assume $0.50, reality is $0.70–$0.92
- 📊 **Wrong signal** — momentum has zero edge. Window delta is everything
- ⏱️ **250ms taker delay** — hardcoded by Polymarket on all BTC market orders

---

## The Signal: Window Delta Dominates

```mermaid
xychart-beta
    title "Signal Weight by Indicator"
    x-axis ["Window Delta", "Tick Trend", "Micro Momentum", "Acceleration", "EMA Cross", "RSI", "Volume"]
    y-axis "Weight" 0 --> 7
    bar [6, 2, 2, 1.5, 1, 1.5, 1]
```

**Window Delta** = `(current BTC price − window open price) / window open price`

At T-10s, if BTC is already up 0.10% from the open — it almost never reverses in 10 seconds. This single number directly answers the market's question and gets weighted 3–4× more than everything else combined.

---

## Token Pricing Reality

```mermaid
xychart-beta
    title "Token Cost vs Signal Strength (what you actually pay)"
    x-axis ["Flat (0%)", "Weak (0.02%)", "Moderate (0.05%)", "Strong (0.10%)", "Decisive (0.15%)"]
    y-axis "Token Price $" 0.4 --> 1.0
    line [0.50, 0.55, 0.65, 0.80, 0.92]
```

Most backtests assume $0.50 per token — that's why they look 2× more profitable than reality. When the signal is clear, **market makers see it too** and price the token accordingly.

---

## Backtest Results (7 days, 2,016 windows)

```mermaid
xychart-beta
    title "Win Rate vs Break-Even by Signal Strength"
    x-axis ["Weak", "Moderate", "Strong", "Decisive"]
    y-axis "%" 40 --> 105
    bar [68.7, 87.6, 96.2, 99.4]
    line [51.9, 59.4, 71.7, 88.6]
```

> 🟦 Bar = actual win rate &nbsp;&nbsp; 🟧 Line = break-even win rate needed

Every bucket clears break-even. Strategy has **+$0.21 EV per dollar risked**.

---

## Current Status

```mermaid
timeline
    title Project Timeline
    Phase 1 : Built execution realism model
            : Slippage + quote freshness + adverse fills
    Phase 2 : Built composite signal
            : Window delta dominant, 7 indicators total
    Phase 3 : Built backtest engine
            : Delta-based token pricing, realistic win rates
    Phase 4 : Built snipe bot
            : Clock timing, Chainlink oracle, 3 trading modes
    Phase 5 : Live data collection
            : Running 24/7 on cloud for 30 days
    Phase 6 : Validate + go live
            : Compare simulation vs reality, then trade
```

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
