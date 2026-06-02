"""
Execution Realism Module
========================
Implements quote freshness tracking and realistic slippage modeling
based on findings from the Reddit thread:
  - p95 quote freshness exploding to ~67s in tail scenarios
  - Edge dying at 0.01 additional slippage
  - Bimodal fill distribution: either no-fill or adverse fill
"""

import random
import logging
import numpy as np
from datetime import datetime
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field


logger = logging.getLogger(__name__)


# ============================================================================
# Quote Freshness
# ============================================================================

@dataclass
class QuoteSnapshot:
    """A single quote observation with a timestamp"""
    market_id: str
    outcome: str
    price: float
    captured_at: datetime  # when WE received this quote

    @property
    def age_seconds(self) -> float:
        return (datetime.now() - self.captured_at).total_seconds()


class QuoteFreshnessTracker:
    """
    Tracks how stale our quotes are at the moment we act on them.

    Key insight from the Reddit thread:
      - Median freshness looked fine (~1.5s)
      - p95 exploded to ~67s — this is where all the losses come from
      - Trading on stale quotes = adverse selection against people with fresh data
    """

    def __init__(self, max_acceptable_age_seconds: float = 5.0):
        self.max_acceptable_age = max_acceptable_age_seconds
        self._history: List[float] = []          # rolling log of ages at fill time
        self._stale_blocks: int = 0              # trades blocked due to staleness
        self._total_checks: int = 0

    def record_quote(self, snapshot: QuoteSnapshot):
        """Log the age of a quote at the moment we evaluated it"""
        age = snapshot.age_seconds
        self._history.append(age)
        self._total_checks += 1
        # Keep last 500 observations
        if len(self._history) > 500:
            self._history = self._history[-500:]

    def is_fresh(self, snapshot: QuoteSnapshot) -> Tuple[bool, float]:
        """
        Returns (fresh, age_seconds).
        Gate trades on this — stale quotes are where losses concentrate.
        """
        age = snapshot.age_seconds
        self.record_quote(snapshot)
        if age > self.max_acceptable_age:
            self._stale_blocks += 1
            return False, age
        return True, age

    def percentile(self, p: float) -> float:
        """Return the p-th percentile of observed quote ages"""
        if not self._history:
            return 0.0
        return float(np.percentile(self._history, p))

    def stats(self) -> Dict:
        if not self._history:
            return {"count": 0}
        return {
            "count": len(self._history),
            "p50_seconds": round(self.percentile(50), 2),
            "p90_seconds": round(self.percentile(90), 2),
            "p95_seconds": round(self.percentile(95), 2),
            "p99_seconds": round(self.percentile(99), 2),
            "max_seconds": round(max(self._history), 2),
            "stale_blocks": self._stale_blocks,
            "stale_block_rate": (
                round(self._stale_blocks / self._total_checks, 3)
                if self._total_checks else 0
            ),
        }

    def log_report(self):
        s = self.stats()
        logger.info(
            f"[QuoteFreshness] p50={s.get('p50_seconds')}s "
            f"p95={s.get('p95_seconds')}s "
            f"p99={s.get('p99_seconds')}s "
            f"stale_blocks={s.get('stale_blocks')} "
            f"({s.get('stale_block_rate', 0)*100:.1f}% blocked)"
        )


# ============================================================================
# Slippage Model
# ============================================================================

@dataclass
class FillResult:
    """Result of a simulated order fill"""
    filled: bool
    fill_price: float          # actual price paid/received
    quoted_price: float        # price we expected
    slippage: float            # fill_price - quoted_price (positive = worse for buyer)
    slippage_pct: float        # slippage as % of quoted price
    quote_age_seconds: float
    reason: str                # "filled", "no_fill", "adverse_fill"
    cost_including_fees: float = 0.0


class SlippageModel:
    """
    Realistic slippage model based on the Reddit finding:

    The realized fill distribution is BIMODAL:
      1. No fill   — you posted but nobody took the other side
      2. Adverse fill — you filled exactly when you shouldn't have
         (the counterparty had fresher data and was happy to trade with you)

    Paper bots assume mid ± a tick and completely miss this.

    Parameters tunable via config:
      base_slippage      — normal market-order slippage (default 0.005 = 0.5%)
      spread_half        — half the bid-ask spread you cross (default 0.003)
      no_fill_prob       — probability of non-fill when posting (default 0.25)
      adverse_fill_prob  — probability of filling adversely (default 0.15)
      adverse_multiplier — extra slippage on adverse fill (default 3x)
      taker_fee          — exchange fee for market orders (default 0.002 = 0.2%)
      maker_fee          — exchange fee for limit orders (default 0.001)
    """

    def __init__(self, config: Dict = None):
        cfg = config or {}
        self.base_slippage      = cfg.get("base_slippage",      0.005)
        self.spread_half        = cfg.get("spread_half",        0.003)
        self.no_fill_prob       = cfg.get("no_fill_prob",       0.25)
        self.adverse_fill_prob  = cfg.get("adverse_fill_prob",  0.15)
        self.adverse_multiplier = cfg.get("adverse_multiplier", 3.0)
        self.taker_fee          = cfg.get("taker_fee",          0.002)
        self.maker_fee          = cfg.get("maker_fee",          0.001)

        # Metrics
        self._fills:          List[FillResult] = []
        self._total_slippage: float = 0.0

    def simulate_fill(
        self,
        quoted_price: float,
        side: str,               # "BUY" or "SELL"
        size: float,
        quote_age_seconds: float,
        is_market_order: bool = True,
    ) -> FillResult:
        """
        Simulate a realistic fill for one order.

        Staleness amplifies both no-fill and adverse-fill probabilities:
        the older the quote, the more likely the market has moved against us.
        """
        # ── Staleness multiplier ──────────────────────────────────────────
        # Fresh quote (< 2s): no adjustment
        # Stale quote (> 10s): probabilities scale up significantly
        staleness_factor = max(1.0, quote_age_seconds / 2.0)

        # ── No-fill check ─────────────────────────────────────────────────
        no_fill_p = min(0.85, self.no_fill_prob * staleness_factor)
        if random.random() < no_fill_p and not is_market_order:
            result = FillResult(
                filled=False,
                fill_price=quoted_price,
                quoted_price=quoted_price,
                slippage=0.0,
                slippage_pct=0.0,
                quote_age_seconds=quote_age_seconds,
                reason="no_fill",
                cost_including_fees=0.0,
            )
            self._fills.append(result)
            return result

        # ── Adverse fill check ────────────────────────────────────────────
        adverse_p = min(0.70, self.adverse_fill_prob * staleness_factor)
        is_adverse = random.random() < adverse_p

        # ── Base slippage (spread crossing + market impact) ───────────────
        spread_cost   = self.spread_half if is_market_order else 0.0
        market_impact = random.gauss(self.base_slippage, self.base_slippage * 0.5)
        market_impact = max(0.0, market_impact)

        if is_adverse:
            # Adverse fill: much worse slippage
            slippage_magnitude = (
                (spread_cost + market_impact) * self.adverse_multiplier
                + random.uniform(0.005, 0.02)   # extra adverse move
            )
            reason = "adverse_fill"
        else:
            slippage_magnitude = spread_cost + market_impact
            reason = "filled"

        # Direction: BUY pays more, SELL receives less
        direction = 1 if side == "BUY" else -1
        fill_price = quoted_price + direction * slippage_magnitude

        # Keep in [0.01, 0.99] for prediction market prices
        fill_price = max(0.01, min(0.99, fill_price))
        actual_slippage = fill_price - quoted_price

        # Fees
        fee_rate = self.taker_fee if is_market_order else self.maker_fee
        fee = size * fee_rate
        cost = size + fee if side == "BUY" else -(size - fee)

        result = FillResult(
            filled=True,
            fill_price=fill_price,
            quoted_price=quoted_price,
            slippage=actual_slippage,
            slippage_pct=actual_slippage / quoted_price if quoted_price else 0,
            quote_age_seconds=quote_age_seconds,
            reason=reason,
            cost_including_fees=abs(cost),
        )

        self._fills.append(result)
        self._total_slippage += actual_slippage
        return result

    def stats(self) -> Dict:
        if not self._fills:
            return {"count": 0}

        filled = [f for f in self._fills if f.filled]
        no_fills = [f for f in self._fills if not f.filled]
        adverse = [f for f in self._fills if f.reason == "adverse_fill"]
        slippages = [f.slippage_pct for f in filled]

        return {
            "total_orders":      len(self._fills),
            "filled":            len(filled),
            "no_fills":          len(no_fills),
            "adverse_fills":     len(adverse),
            "fill_rate":         round(len(filled) / len(self._fills), 3),
            "adverse_fill_rate": round(len(adverse) / max(len(filled), 1), 3),
            "avg_slippage_pct":  round(np.mean(slippages) * 100, 4) if slippages else 0,
            "p50_slippage_pct":  round(float(np.percentile(slippages, 50)) * 100, 4) if slippages else 0,
            "p95_slippage_pct":  round(float(np.percentile(slippages, 95)) * 100, 4) if slippages else 0,
            "total_slippage_cost": round(self._total_slippage, 4),
        }

    def log_report(self):
        s = self.stats()
        logger.info(
            f"[Slippage] fills={s.get('filled')}/{s.get('total_orders')} "
            f"fill_rate={s.get('fill_rate')} "
            f"adverse_rate={s.get('adverse_fill_rate')} "
            f"avg_slip={s.get('avg_slippage_pct')}% "
            f"p95_slip={s.get('p95_slippage_pct')}%"
        )


# ============================================================================
# PnL Bucketing by Quote Freshness
# ============================================================================

class FreshnessBucketAnalyser:
    """
    Buckets closed trades by quote freshness at fill time and reports
    PnL concentration per bucket.

    As u/hypersignals suggested: if 5% of trades (stale bucket) account
    for 80% of losses, you have a FILTER problem not a STRATEGY problem.
    """

    BUCKETS = [
        (0,    2,   "fresh   (0–2s)"),
        (2,    5,   "ok      (2–5s)"),
        (5,    15,  "stale   (5–15s)"),
        (15,   60,  "very_stale (15–60s)"),
        (60,   999, "toxic   (60s+)"),
    ]

    def __init__(self):
        # bucket_label -> list of pnl values
        self._data: Dict[str, List[float]] = {b[2]: [] for b in self.BUCKETS}

    def record_trade(self, quote_age_seconds: float, pnl: float):
        for low, high, label in self.BUCKETS:
            if low <= quote_age_seconds < high:
                self._data[label].append(pnl)
                return
        self._data["toxic   (60s+)"].append(pnl)

    def report(self) -> str:
        lines = ["\n── PnL by Quote Freshness Bucket ──────────────────────"]
        total_pnl = sum(v for bucket in self._data.values() for v in bucket)
        total_trades = sum(len(v) for v in self._data.values())

        for label in [b[2] for b in self.BUCKETS]:
            vals = self._data[label]
            if not vals:
                continue
            bucket_pnl   = sum(vals)
            pnl_share    = (bucket_pnl / total_pnl * 100) if total_pnl else 0
            trade_share  = (len(vals) / total_trades * 100) if total_trades else 0
            win_rate     = sum(1 for v in vals if v > 0) / len(vals) * 100
            lines.append(
                f"  {label:25s} | trades={len(vals):4d} ({trade_share:4.1f}%) "
                f"| PnL=${bucket_pnl:+8.2f} ({pnl_share:+5.1f}%) "
                f"| win={win_rate:4.1f}%"
            )

        lines.append("─" * 80)

        # Highlight if stale buckets dominate losses
        stale_pnl = sum(
            v
            for label in ["stale   (5–15s)", "very_stale (15–60s)", "toxic   (60s+)"]
            for v in self._data[label]
        )
        if total_pnl < 0 and stale_pnl < 0 and total_pnl != 0:
            pct = stale_pnl / total_pnl * 100
            lines.append(
                f"  ⚠️  Stale quotes account for {pct:.1f}% of total losses. "
                f"Consider freshness gating."
            )

        return "\n".join(lines)
