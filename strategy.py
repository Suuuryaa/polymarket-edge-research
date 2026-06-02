"""
Composite Signal Strategy for Polymarket 5-min BTC Up/Down Markets
===================================================================
Seven weighted indicators. Window delta dominates — it directly answers
the market's question. All other indicators are supporting evidence.

Signal score: positive → UP (buy YES), negative → DOWN (buy NO)
Confidence:   min(abs(score) / 7.0, 1.0)

Window delta weights:
  >0.10% move  → weight 7 (nearly certain, market will price it in)
  >0.02% move  → weight 5 (strong signal)
  >0.005% move → weight 3 (moderate signal)
  >0.001% move → weight 1 (slight lean)

Token pricing model (piecewise linear, matches observed Polymarket spreads):
  delta <0.005% → $0.50  (coin flip)
  delta ~0.02%  → $0.55
  delta ~0.05%  → $0.65
  delta ~0.10%  → $0.80
  delta ~0.15%+ → $0.92
"""

from dataclasses import dataclass
from typing import List, Optional
import math


@dataclass
class Candle:
    """One 5-min candle (or 1-min candle — callers set the interval)."""
    open:   float
    high:   float
    low:    float
    close:  float
    volume: float


@dataclass
class Signal:
    direction:  str    # "UP" or "DOWN"
    side:       str    # "BUY_YES" or "BUY_NO"
    score:      float  # raw composite score (positive=UP)
    confidence: float  # 0.0–1.0
    token_price: float # estimated Polymarket token cost (0.50–0.97)
    window_delta_pct: float
    reasons:    List[str]


def token_price_from_delta(abs_delta_pct: float) -> float:
    """
    Piecewise linear model mapping |window delta %| to token cost.
    When direction is clear to us, market makers also know — tokens cost more.
    """
    if abs_delta_pct >= 0.15:
        return 0.92 + min(0.05, (abs_delta_pct - 0.15) * 0.33)
    if abs_delta_pct >= 0.10:
        t = (abs_delta_pct - 0.10) / 0.05
        return 0.80 + t * 0.12
    if abs_delta_pct >= 0.05:
        t = (abs_delta_pct - 0.05) / 0.05
        return 0.65 + t * 0.15
    if abs_delta_pct >= 0.02:
        t = (abs_delta_pct - 0.02) / 0.03
        return 0.55 + t * 0.10
    if abs_delta_pct >= 0.005:
        t = (abs_delta_pct - 0.005) / 0.015
        return 0.50 + t * 0.05
    return 0.50


def _ema(values: List[float], period: int) -> List[float]:
    if not values:
        return []
    k = 2.0 / (period + 1)
    result = [values[0]]
    for v in values[1:]:
        result.append(v * k + result[-1] * (1 - k))
    return result


def _rsi(closes: List[float], period: int = 14) -> Optional[float]:
    if len(closes) < period + 1:
        return None
    gains, losses = [], []
    for i in range(1, len(closes)):
        delta = closes[i] - closes[i - 1]
        gains.append(max(0.0, delta))
        losses.append(max(0.0, -delta))
    avg_gain = sum(gains[-period:]) / period
    avg_loss = sum(losses[-period:]) / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))


def analyze(
    window_open_price: float,
    current_price: float,
    candles_1m: List[Candle],        # recent 1-min candles for momentum/ema/rsi
    tick_prices: List[float],         # 2-second poll prices from this window
    min_confidence: float = 0.30,
) -> Optional[Signal]:
    """
    Composite signal from 7 weighted indicators.

    Args:
        window_open_price: Chainlink oracle price at window boundary
        current_price:     Latest BTC price (Binance or WebSocket)
        candles_1m:        Last 21+ 1-min candles for EMA/RSI
        tick_prices:       Prices polled every 2s this window (for micro-trend)
        min_confidence:    Skip signal if below this threshold

    Returns Signal or None if no trade.
    """
    score   = 0.0
    reasons = []

    # ── 1. Window Delta (weight 5–7) ─────────────────────────────────────────
    delta_pct = (current_price - window_open_price) / window_open_price * 100
    abs_delta = abs(delta_pct)
    direction = 1 if delta_pct > 0 else -1

    if abs_delta > 0.10:
        w = 7
    elif abs_delta > 0.02:
        w = 5
    elif abs_delta > 0.005:
        w = 3
    elif abs_delta > 0.001:
        w = 1
    else:
        w = 0

    if w > 0:
        score += direction * w
        reasons.append(f"window_delta={delta_pct:+.4f}% (w={w})")

    # ── 2. Micro Momentum (weight 2) — last 2 candles direction ─────────────
    if len(candles_1m) >= 2:
        c1, c2 = candles_1m[-2], candles_1m[-1]
        m1 = 1 if c1.close > c1.open else -1
        m2 = 1 if c2.close > c2.open else -1
        momentum = m1 + m2   # -2, -1, 0, 1, 2
        if momentum != 0:
            score += (momentum / 2) * 2
            reasons.append(f"micro_mom={momentum:+d}/2 (w=2)")

    # ── 3. Acceleration (weight 1.5) — is momentum building or fading? ──────
    if len(candles_1m) >= 3:
        c_prev = candles_1m[-3]
        move_prev = (candles_1m[-2].close - c_prev.close) / c_prev.close * 100
        move_last = (candles_1m[-1].close - candles_1m[-2].close) / candles_1m[-2].close * 100
        if abs(move_last) > 0 and abs(move_prev) > 0:
            accel = math.copysign(1, move_last) * (abs(move_last) > abs(move_prev))
            if accel != 0:
                score += accel * 1.5
                reasons.append(f"accel={'building' if accel > 0 == move_last > 0 else 'fading'} (w=1.5)")

    # ── 4. EMA Crossover 9/21 (weight 1) ────────────────────────────────────
    if len(candles_1m) >= 21:
        closes = [c.close for c in candles_1m]
        ema9  = _ema(closes, 9)
        ema21 = _ema(closes, 21)
        if ema9 and ema21:
            cross = 1 if ema9[-1] > ema21[-1] else -1
            score += cross * 1
            reasons.append(f"ema_cross={'bull' if cross > 0 else 'bear'} (w=1)")

    # ── 5. RSI 14 (weight 1–2) ───────────────────────────────────────────────
    if len(candles_1m) >= 15:
        closes = [c.close for c in candles_1m]
        rsi = _rsi(closes)
        if rsi is not None:
            if rsi > 75:
                score -= 2    # overbought → lean DOWN
                reasons.append(f"rsi={rsi:.0f} overbought (w=-2)")
            elif rsi < 25:
                score += 2    # oversold → lean UP
                reasons.append(f"rsi={rsi:.0f} oversold (w=+2)")

    # ── 6. Volume Surge (weight 1) ───────────────────────────────────────────
    if len(candles_1m) >= 6:
        recent_vol = sum(c.volume for c in candles_1m[-3:]) / 3
        prior_vol  = sum(c.volume for c in candles_1m[-6:-3]) / 3
        if prior_vol > 0 and recent_vol >= prior_vol * 1.5:
            # Volume surge confirms current direction
            score += direction * 1
            reasons.append(f"vol_surge={recent_vol/prior_vol:.1f}x (w=1)")

    # ── 7. Real-Time Tick Trend (weight 2) ───────────────────────────────────
    if len(tick_prices) >= 5:
        # 60%+ directional consistency + >0.005% move
        tick_deltas = [tick_prices[i] - tick_prices[i-1] for i in range(1, len(tick_prices))]
        up_ticks = sum(1 for d in tick_deltas if d > 0)
        tick_dir_ratio = up_ticks / len(tick_deltas)
        tick_move_pct = (tick_prices[-1] - tick_prices[0]) / tick_prices[0] * 100

        if tick_dir_ratio >= 0.60 and tick_move_pct > 0.005:
            score += 2
            reasons.append(f"tick_trend=up {tick_dir_ratio:.0%} (w=2)")
        elif tick_dir_ratio <= 0.40 and tick_move_pct < -0.005:
            score -= 2
            reasons.append(f"tick_trend=down {1-tick_dir_ratio:.0%} (w=2)")

    # ── Confidence + Signal ───────────────────────────────────────────────────
    confidence = min(abs(score) / 7.0, 1.0)
    if confidence < min_confidence or score == 0:
        return None

    final_dir = "UP" if score > 0 else "DOWN"
    token_price = token_price_from_delta(abs_delta)
    token_price = min(0.97, token_price)   # cap at $0.97 — below that we can still profit

    return Signal(
        direction       = final_dir,
        side            = "BUY_YES" if final_dir == "UP" else "BUY_NO",
        score           = score,
        confidence      = confidence,
        token_price     = token_price,
        window_delta_pct = delta_pct,
        reasons         = reasons,
    )


def min_win_rate_needed(token_price: float) -> float:
    """
    Break-even win rate at a given token price.
    Win pays $1.00, lose forfeits cost.
    EV = 0  →  win_rate * (1 - price) = (1 - win_rate) * price
    Solve: win_rate = price
    """
    return token_price


def expected_value(token_price: float, win_rate: float) -> float:
    """EV per dollar risked."""
    return win_rate * (1.0 - token_price) - (1.0 - win_rate) * token_price
