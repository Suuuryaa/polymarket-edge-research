# polymarket-edge-research

> **Work in Progress** — Active research into execution realism for Polymarket 5-minute prediction markets.

[![Status](https://img.shields.io/badge/Status-Work%20In%20Progress-yellow?style=flat-square)]()
[![Python](https://img.shields.io/badge/Python-3.9+-3776AB?style=flat-square&logo=python&logoColor=white)]()
[![License](https://img.shields.io/badge/License-MIT-22c55e?style=flat-square)]()

---

## What This Is

Most Polymarket bots look profitable in paper trading and bleed money live. This project investigates **why** — and builds the infrastructure to close the gap.

The core insight: paper bots assume you fill at mid ± a tick. Real fills are bimodal:
- **No fill** — you posted a limit order and nobody took the other side
- **Adverse fill** — you filled exactly when you shouldn't have (the counterparty had fresher data)

This repo researches and implements the missing layer: **execution realism**.

---

## Research Status

| Topic | Status | Finding |
|---|---|---|
| Quote freshness distribution | ✅ Done | p95 freshness explodes to ~67s in tail scenarios |
| Slippage modeling | ✅ Done | Bimodal: no-fill or adverse-fill, not gaussian |
| PnL by freshness bucket | ✅ Done | Stale quotes account for majority of losses |
| Live CLOB integration | 🔄 In Progress | — |
| Strategy backtesting | 📋 Planned | — |
| Order book imbalance signals | 📋 Planned | — |

---

## Architecture

```
polymarket-agent/
├── execution_realism.py      # Quote freshness + slippage engine  ← core research
├── paper_trading.py          # Paper trading simulator with realism layer
├── polymarket_agent.py       # Live agent (CLOB integration)
├── requirements.txt
└── README.md
```

---

## Execution Realism Engine

The key module is `execution_realism.py`. It has three components:

### 1. Quote Freshness Tracker

Tracks how old your quotes are at the moment you act on them. The problem isn't the median — it's the tail.

```
Median freshness: ~1.5s  (looks fine)
p95 freshness:    ~67s   (this is where losses live)
```

Trading on a 67-second-old quote means you're providing liquidity to someone with a 67-second informational advantage.

```python
tracker = QuoteFreshnessTracker(max_acceptable_age_seconds=5.0)
fresh, age = tracker.is_fresh(snapshot)
if not fresh:
    skip_trade()  # don't fight someone with better data
```

### 2. Slippage Model

Replaces the naive `mid ± tick` assumption with a realistic bimodal distribution:

| Scenario | Probability | What Happens |
|---|---|---|
| No fill (limit orders) | 25% base | Order sits, market moves away |
| Normal fill | 60% | Base slippage + spread crossing |
| Adverse fill | 15% base | 3× extra slippage — you filled when you shouldn't have |

Both probabilities scale with quote staleness. A 30-second-old quote has ~15× higher adverse fill risk.

```python
model = SlippageModel({
    "no_fill_prob": 0.25,
    "adverse_fill_prob": 0.15,
    "adverse_multiplier": 3.0,
    "taker_fee": 0.002,
})
result = model.simulate_fill(quoted_price=0.55, side="BUY", size=10.0, quote_age_seconds=age)
```

### 3. PnL Bucket Analyser

Buckets closed trades by quote age at fill time and reports PnL concentration:

```
── PnL by Quote Freshness Bucket ──────────────────────
  fresh   (0–2s)      | trades= 142 (71.0%) | PnL=$ +48.20 (+22.1%) | win=64.1%
  ok      (2–5s)      | trades=  38 (19.0%) | PnL=$ +12.10 ( +5.5%) | win=55.3%
  stale   (5–15s)     | trades=  14 ( 7.0%) | PnL=$ -38.40 (-17.6%) | win=28.6%
  very_stale (15–60s) | trades=   5 ( 2.5%) | PnL=$ -88.20 (-40.4%) | win=20.0%
  toxic   (60s+)      | trades=   1 ( 0.5%) | PnL=$ -52.10 (-23.9%) | win= 0.0%
─────────────────────────────────────────────────────────────────────────────────
  ⚠️  Stale quotes account for 81.9% of total losses. Consider freshness gating.
```

If stale quotes (5% of trades) account for 80%+ of losses — that's a **filter problem**, not a strategy problem.

---

## Quick Start

```bash
git clone https://github.com/Suuuryaa/polymarket-edge-research.git
cd polymarket-edge-research
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
```

### Run the paper trader (with execution realism)

```bash
python paper_trading.py
```

The simulator will show freshness stats, slippage breakdown, and PnL by freshness bucket at the end of each session.

### Run the live agent

```bash
# Set credentials first
export POLYMARKET_API_KEY="..."
export POLYMARKET_API_SECRET="..."
export POLYMARKET_WALLET_PRIVATE_KEY="..."

python polymarket_agent.py
```

---

## Configuration

Key parameters in `execution_realism.py` and the agent config:

| Parameter | Default | Description |
|---|---|---|
| `max_acceptable_age_seconds` | `5.0` | Gate: refuse to trade on quotes older than this |
| `no_fill_prob` | `0.25` | Base probability a limit order doesn't fill |
| `adverse_fill_prob` | `0.15` | Base probability of adverse selection |
| `adverse_multiplier` | `3.0` | How much worse an adverse fill is vs normal |
| `taker_fee` | `0.002` | Exchange fee for market orders (0.2%) |
| `base_slippage` | `0.005` | Normal market-order slippage |

---

## Strategies (Implemented)

| Strategy | Description | Status |
|---|---|---|
| Momentum | Trade on price direction over recent candles | ✅ Live |
| Order Book Imbalance | Buy/sell based on bid-ask pressure | 📋 Planned |
| Mean Reversion | Fade overshoots from fundamental value | 📋 Planned |
| Correlation Arb | Exploit mispricing in related markets | 📋 Planned |

---

## Roadmap

- [x] Quote freshness tracking (p50/p95/p99)
- [x] Bimodal fill simulation
- [x] PnL bucketing by quote age
- [ ] Live CLOB order book integration
- [ ] WebSocket feed for real-time quotes
- [ ] Backtesting framework against historical fills
- [ ] Notification system (Telegram/Discord)
- [ ] Dashboard for live session monitoring

---

## Important Notes

- **Testnet first.** The agent runs against Polymarket testnet by default (`testnet: True`). Don't touch mainnet until you've watched it run for days.
- **The edge is thin.** Adding 0.01 in slippage kills most strategies. The realism layer exists to find this out before real money does.
- **This is research, not a product.** Expect rough edges, breaking changes, and honest failure modes.

---

## Disclaimer

This software is for research and educational purposes only. Trading prediction markets carries significant financial risk. You may lose your entire investment. The authors accept no responsibility for financial losses. Do your own research. Trade responsibly.

---

**Built by [Suuuryaa](https://github.com/Suuuryaa)**
