"""
Example Custom Strategies for Polymarket Trading Agent
========================================================
Add these to polymarket_agent.py or import them
"""

from polymarket_agent import BaseStrategy, TradeSignal, OrderSide, MarketData
from typing import List, Optional
from datetime import datetime
import statistics


class MeanReversionStrategy(BaseStrategy):
    """
    Mean reversion strategy for 5-minute markets
    
    Theory: Prices that move too far from average tend to revert back
    - Sells when price is significantly above recent average
    - Buys when price is significantly below recent average
    """
    
    def generate_signals(self, markets: List[MarketData]) -> List[TradeSignal]:
        signals = []
        
        for market in markets:
            self.update_market_data(market)
            
            # Need sufficient history
            if len(self.market_history.get(market.market_id, [])) < 10:
                continue
            
            history = self.market_history[market.market_id]
            
            for outcome in market.outcomes:
                signal = self._check_mean_reversion(market, outcome, history)
                if signal:
                    signals.append(signal)
        
        return signals
    
    def _check_mean_reversion(self, market: MarketData, outcome: str,
                              history: List[MarketData]) -> Optional[TradeSignal]:
        """Check for mean reversion opportunity"""
        
        # Get price history
        prices = [m.prices.get(outcome, 0) for m in history[-20:]]
        
        if len(prices) < 10:
            return None
        
        # Calculate statistics
        mean_price = statistics.mean(prices)
        std_dev = statistics.stdev(prices) if len(prices) > 1 else 0
        current_price = prices[-1]
        
        # How many standard deviations from mean?
        if std_dev > 0:
            z_score = (current_price - mean_price) / std_dev
        else:
            return None
        
        # Thresholds
        buy_threshold = self.config.get('buy_z_score', -1.5)  # 1.5 std below mean
        sell_threshold = self.config.get('sell_z_score', 1.5)  # 1.5 std above mean
        min_confidence = self.config.get('min_confidence', 0.6)
        
        # Price too high - expect reversion down (sell)
        if z_score > sell_threshold:
            confidence = min(0.9, 0.5 + abs(z_score) * 0.2)
            if confidence >= min_confidence:
                return TradeSignal(
                    market_id=market.market_id,
                    outcome=outcome,
                    action=OrderSide.SELL,
                    confidence=confidence,
                    size=self._calculate_position_size(confidence),
                    target_price=current_price * 0.99,
                    reason=f"Mean reversion SELL: price {z_score:.1f}σ above mean",
                    timestamp=datetime.now()
                )
        
        # Price too low - expect reversion up (buy)
        elif z_score < buy_threshold:
            confidence = min(0.9, 0.5 + abs(z_score) * 0.2)
            if confidence >= min_confidence:
                return TradeSignal(
                    market_id=market.market_id,
                    outcome=outcome,
                    action=OrderSide.BUY,
                    confidence=confidence,
                    size=self._calculate_position_size(confidence),
                    target_price=current_price * 1.01,
                    reason=f"Mean reversion BUY: price {z_score:.1f}σ below mean",
                    timestamp=datetime.now()
                )
        
        return None
    
    def _calculate_position_size(self, confidence: float) -> float:
        """Calculate position size based on confidence"""
        base_size = self.config.get('base_position_size', 10.0)
        max_size = self.config.get('max_position_size', 50.0)
        
        size = base_size * (1 + confidence)
        return min(size, max_size)


class VolumeBreakoutStrategy(BaseStrategy):
    """
    Volume breakout strategy
    
    Theory: Unusual volume spikes often precede price moves
    - Tracks volume patterns
    - Enters when volume spike + directional move
    """
    
    def generate_signals(self, markets: List[MarketData]) -> List[TradeSignal]:
        signals = []
        
        for market in markets:
            self.update_market_data(market)
            
            if len(self.market_history.get(market.market_id, [])) < 5:
                continue
            
            history = self.market_history[market.market_id]
            
            for outcome in market.outcomes:
                signal = self._check_volume_breakout(market, outcome, history)
                if signal:
                    signals.append(signal)
        
        return signals
    
    def _check_volume_breakout(self, market: MarketData, outcome: str,
                               history: List[MarketData]) -> Optional[TradeSignal]:
        """Check for volume breakout signal"""
        
        # Get recent volumes
        volumes = [m.volumes.get(outcome, 0) for m in history[-10:]]
        prices = [m.prices.get(outcome, 0) for m in history[-5:]]
        
        if len(volumes) < 5 or len(prices) < 3:
            return None
        
        # Calculate average volume
        avg_volume = statistics.mean(volumes[:-1])  # Exclude current
        current_volume = volumes[-1]
        
        # Volume spike threshold
        volume_threshold = self.config.get('volume_spike_multiplier', 2.0)
        
        # Is there a volume spike?
        if current_volume < avg_volume * volume_threshold:
            return None
        
        # What's the price direction?
        price_change = (prices[-1] - prices[0]) / prices[0] if prices[0] > 0 else 0
        
        min_price_move = self.config.get('min_price_move', 0.02)  # 2%
        min_confidence = self.config.get('min_confidence', 0.6)
        
        # Volume spike + upward price = buy
        if price_change > min_price_move:
            confidence = min(0.9, 0.6 + price_change * 5)
            if confidence >= min_confidence:
                return TradeSignal(
                    market_id=market.market_id,
                    outcome=outcome,
                    action=OrderSide.BUY,
                    confidence=confidence,
                    size=self._calculate_position_size(confidence),
                    target_price=prices[-1] * 1.01,
                    reason=f"Volume breakout BUY: {current_volume/avg_volume:.1f}x avg volume",
                    timestamp=datetime.now()
                )
        
        # Volume spike + downward price = sell
        elif price_change < -min_price_move:
            confidence = min(0.9, 0.6 + abs(price_change) * 5)
            if confidence >= min_confidence:
                return TradeSignal(
                    market_id=market.market_id,
                    outcome=outcome,
                    action=OrderSide.SELL,
                    confidence=confidence,
                    size=self._calculate_position_size(confidence),
                    target_price=prices[-1] * 0.99,
                    reason=f"Volume breakout SELL: {current_volume/avg_volume:.1f}x avg volume",
                    timestamp=datetime.now()
                )
        
        return None
    
    def _calculate_position_size(self, confidence: float) -> float:
        base_size = self.config.get('base_position_size', 10.0)
        max_size = self.config.get('max_position_size', 50.0)
        size = base_size * (1 + confidence)
        return min(size, max_size)


class CombinedStrategy(BaseStrategy):
    """
    Combines multiple strategies with weighted voting
    
    Uses both momentum and mean reversion signals
    Only trades when multiple strategies agree
    """
    
    def __init__(self, config):
        super().__init__(config)
        self.momentum = MomentumStrategy(config)
        self.mean_reversion = MeanReversionStrategy(config)
        
    def generate_signals(self, markets: List[MarketData]) -> List[TradeSignal]:
        # Get signals from both strategies
        momentum_signals = self.momentum.generate_signals(markets)
        reversion_signals = self.mean_reversion.generate_signals(markets)
        
        # Build signal map
        signal_map = {}
        
        for sig in momentum_signals:
            key = (sig.market_id, sig.outcome, sig.action)
            if key not in signal_map:
                signal_map[key] = []
            signal_map[key].append(('momentum', sig))
        
        for sig in reversion_signals:
            key = (sig.market_id, sig.outcome, sig.action)
            if key not in signal_map:
                signal_map[key] = []
            signal_map[key].append(('reversion', sig))
        
        # Combine signals - require agreement from both
        combined_signals = []
        min_strategies = self.config.get('min_strategies_agree', 2)
        
        for key, sigs in signal_map.items():
            if len(sigs) >= min_strategies:
                # Average confidence
                avg_confidence = statistics.mean([s[1].confidence for s in sigs])
                
                # Use first signal as template
                base_signal = sigs[0][1]
                
                combined_signal = TradeSignal(
                    market_id=base_signal.market_id,
                    outcome=base_signal.outcome,
                    action=base_signal.action,
                    confidence=avg_confidence,
                    size=base_signal.size,
                    target_price=base_signal.target_price,
                    reason=f"Combined: {', '.join([s[0] for s in sigs])}",
                    timestamp=datetime.now()
                )
                combined_signals.append(combined_signal)
        
        return combined_signals


# To use these strategies, add to polymarket_agent.py __init__:
"""
if strategy_name == 'mean_reversion':
    self.strategy = MeanReversionStrategy(config.get('strategy_config', {}))
elif strategy_name == 'volume_breakout':
    self.strategy = VolumeBreakoutStrategy(config.get('strategy_config', {}))
elif strategy_name == 'combined':
    self.strategy = CombinedStrategy(config.get('strategy_config', {}))
"""
