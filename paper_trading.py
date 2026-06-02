"""
Paper Trading Simulator for Polymarket Agent
============================================
Simulates market data and trading without needing real API access.
Perfect for learning and testing strategies.
"""

import argparse
import asyncio
import random
import logging
from datetime import datetime, timedelta
from typing import List, Dict
import json

# Import from main agent
from polymarket_agent import (
    MarketData, MarketStatus, Position, Order, OrderSide,
    MomentumStrategy, RiskManager, TradeSignal
)

# Execution realism
from execution_realism import (
    QuoteSnapshot, QuoteFreshnessTracker, SlippageModel, FreshnessBucketAnalyser
)


class PaperTradingSimulator:
    """
    Simulates Polymarket markets and trading
    Generates realistic market data for testing
    """
    
    def __init__(self, config: Dict, seed: int = None):
        self.config = config
        self.naive_mode = config.get('naive_mode', False)
        self.logger = logging.getLogger(__name__)

        if seed is not None:
            random.seed(seed)

        # Simulated markets
        self.markets = self._generate_markets()

        # Trading state
        self.positions: List[Position] = []
        self.orders: List[Order] = []
        self.balance = config.get('starting_balance', 1000.0)
        self.initial_balance = self.balance

        # Performance tracking
        self.total_trades = 0
        self.winning_trades = 0
        self.total_pnl = 0.0
        self.daily_pnl = 0.0
        self.trade_history = []

        # Strategy and risk
        self.strategy = MomentumStrategy(config.get('strategy_config', {}))
        self.risk_manager = RiskManager(config.get('risk_config', {}))

        # Execution realism
        freshness_cfg = config.get('freshness_config', {})
        slippage_cfg  = config.get('slippage_config', {})
        self.freshness_tracker  = QuoteFreshnessTracker(
            max_acceptable_age_seconds=freshness_cfg.get('max_age_seconds', 5.0)
        )
        self.slippage_model     = SlippageModel(slippage_cfg)
        self.bucket_analyser    = FreshnessBucketAnalyser()

        # Track trades blocked by freshness gate
        self.freshness_blocked  = 0
    
    def _generate_markets(self) -> List[MarketData]:
        """Generate simulated 5-minute markets"""
        
        market_questions = [
            "Will BTC be above $70,000 in 5 minutes?",
            "Will ETH rise in next 5 minutes?",
            "Will stock market be green in 5 min?",
            "Will next tweet mention crypto?",
            "Will price increase in 5 minutes?",
        ]
        
        markets = []
        for i, question in enumerate(market_questions):
            market = MarketData(
                market_id=f"sim_market_{i}",
                question=question,
                outcomes=["YES", "NO"],
                prices={"YES": 0.5 + random.uniform(-0.1, 0.1), 
                       "NO": 0.5 + random.uniform(-0.1, 0.1)},
                volumes={"YES": random.uniform(100, 1000),
                        "NO": random.uniform(100, 1000)},
                liquidity=random.uniform(1000, 10000),
                end_time=datetime.now() + timedelta(minutes=5),
                status=MarketStatus.ACTIVE,
                last_update=datetime.now()
            )
            markets.append(market)
        
        return markets
    
    def _update_market_prices(self):
        """Simulate realistic price movements"""
        
        for market in self.markets:
            for outcome in market.outcomes:
                current_price = market.prices[outcome]
                
                # Random walk with momentum
                change = random.gauss(0, 0.02)  # 2% std dev
                
                # Add some momentum (trend continuation)
                if hasattr(market, '_last_change'):
                    change += market._last_change.get(outcome, 0) * 0.3
                
                new_price = current_price + change
                
                # Keep in valid range [0.01, 0.99]
                new_price = max(0.01, min(0.99, new_price))
                
                market.prices[outcome] = new_price
                
                # Store last change for momentum
                if not hasattr(market, '_last_change'):
                    market._last_change = {}
                market._last_change[outcome] = change
            
            # Update volumes
            for outcome in market.outcomes:
                volume_change = random.uniform(-50, 100)
                market.volumes[outcome] = max(0, market.volumes[outcome] + volume_change)
            
            # Simulate realistic quote staleness:
            # Most updates arrive quickly, but occasionally (p5) they are very delayed
            # This replicates the p95=67s finding from the Reddit thread
            if random.random() < 0.05:
                # Tail scenario: quote is 20–90 seconds old
                stale_seconds = random.uniform(20, 90)
                market.last_update = datetime.now() - timedelta(seconds=stale_seconds)
            elif random.random() < 0.15:
                # Moderate delay: 5–20 seconds
                stale_seconds = random.uniform(5, 20)
                market.last_update = datetime.now() - timedelta(seconds=stale_seconds)
            else:
                market.last_update = datetime.now()
    
    def _execute_order(self, order: Order) -> bool:
        """Simulate order execution — realistic or naive depending on config"""

        # ── Find market ───────────────────────────────────────────────────
        market = next((m for m in self.markets if m.market_id == order.market_id), None)
        if not market:
            self.logger.error(f"Market {order.market_id} not found")
            return False

        if self.naive_mode:
            # ── NAIVE MODE: fill instantly at quoted price, zero fees ─────
            actual_price = order.price
            actual_cost  = order.size
            age          = 0.0
            fill_reason  = "filled"
            slip_pct     = 0.0
        else:
            # ── Quote freshness gate ──────────────────────────────────────
            snapshot = QuoteSnapshot(
                market_id=market.market_id,
                outcome=order.outcome,
                price=market.prices[order.outcome],
                captured_at=market.last_update,
            )
            fresh, age = self.freshness_tracker.is_fresh(snapshot)
            if not fresh:
                self.freshness_blocked += 1
                self.logger.warning(
                    f"🕐 STALE QUOTE BLOCKED: {order.market_id}/{order.outcome} "
                    f"age={age:.1f}s > max={self.freshness_tracker.max_acceptable_age}s"
                )
                return False

            # ── Simulate realistic fill ───────────────────────────────────
            fill = self.slippage_model.simulate_fill(
                quoted_price=order.price,
                side=order.side.value,
                size=order.size,
                quote_age_seconds=age,
                is_market_order=True,
            )

            if not fill.filled:
                self.logger.info(
                    f"📭 NO FILL: {order.side.value} {order.market_id}/{order.outcome} "
                    f"@ ${order.price:.3f} (age={age:.1f}s)"
                )
                return False

            if fill.reason == "adverse_fill":
                self.logger.warning(
                    f"⚠️  ADVERSE FILL: {order.side.value} {order.market_id}/{order.outcome} "
                    f"quoted=${order.price:.4f} filled=${fill.fill_price:.4f} "
                    f"slip={fill.slippage_pct*100:+.3f}% age={age:.1f}s"
                )
            else:
                self.logger.info(
                    f"✅ FILL: {order.side.value} {order.market_id}/{order.outcome} "
                    f"quoted=${order.price:.4f} filled=${fill.fill_price:.4f} "
                    f"slip={fill.slippage_pct*100:+.3f}% age={age:.1f}s"
                )

            actual_price = fill.fill_price
            actual_cost  = fill.cost_including_fees
            fill_reason  = fill.reason
            slip_pct     = fill.slippage_pct

        # ── Check balance ─────────────────────────────────────────────────
        if order.side == OrderSide.BUY and actual_cost > self.balance:
            self.logger.warning(f"Insufficient balance: ${self.balance:.2f} < ${actual_cost:.2f}")
            return False

        # ── BUY ───────────────────────────────────────────────────────────
        if order.side == OrderSide.BUY:
            self.balance -= actual_cost

            existing_pos = next(
                (p for p in self.positions
                 if p.market_id == order.market_id and p.outcome == order.outcome),
                None
            )
            shares_bought = order.size / actual_price

            if existing_pos:
                total_cost = (existing_pos.avg_price * existing_pos.shares) + actual_cost
                existing_pos.shares += shares_bought
                existing_pos.avg_price = total_cost / existing_pos.shares
            else:
                self.positions.append(Position(
                    market_id=order.market_id,
                    outcome=order.outcome,
                    shares=shares_bought,
                    avg_price=actual_price,
                    current_price=market.prices[order.outcome],
                    unrealized_pnl=0.0,
                    timestamp=datetime.now(),
                ))

        # ── SELL ──────────────────────────────────────────────────────────
        else:
            position = next(
                (p for p in self.positions
                 if p.market_id == order.market_id and p.outcome == order.outcome),
                None
            )
            if not position:
                self.logger.warning(f"No position to sell in {order.market_id}")
                return False

            shares_to_sell = min(order.size / actual_price, position.shares)
            fee_rate       = self.slippage_model.taker_fee if not self.naive_mode else 0.0
            sell_value     = shares_to_sell * actual_price - (shares_to_sell * actual_price * fee_rate)

            cost_basis = shares_to_sell * position.avg_price
            pnl        = sell_value - cost_basis

            self.balance    += sell_value
            self.total_pnl  += pnl
            self.daily_pnl  += pnl

            position.shares -= shares_to_sell

            self.total_trades += 1
            if pnl > 0:
                self.winning_trades += 1

            # Record in bucket analyser
            self.bucket_analyser.record_trade(age, pnl)

            self.trade_history.append({
                'timestamp':      datetime.now().isoformat(),
                'market':         order.market_id,
                'outcome':        order.outcome,
                'shares':         shares_to_sell,
                'quoted_price':   order.price,
                'fill_price':     actual_price,
                'slippage_pct':   slip_pct,
                'quote_age_s':    age,
                'fill_reason':    fill_reason,
                'pnl':            pnl,
            })

            if position.shares < 0.01 and position in self.positions:
                self.positions.remove(position)

            self.logger.info(
                f"💰 SELL RESULT: {shares_to_sell:.2f} shares "
                f"fill=${actual_price:.4f} P&L=${pnl:+.2f}"
            )

        return True
    
    def _update_positions(self):
        """Update position values with current market prices"""
        
        for position in self.positions:
            market = next((m for m in self.markets if m.market_id == position.market_id), None)
            if market:
                position.current_price = market.prices[position.outcome]
                position.unrealized_pnl = (position.current_price - position.avg_price) * position.shares
    
    def _print_status(self):
        """Print current status"""
        
        print("\n" + "="*80)
        print(f"📊 PAPER TRADING STATUS - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print("="*80)
        
        # Account summary
        total_value = self.balance
        for pos in self.positions:
            total_value += pos.shares * pos.current_price
        
        pnl_pct = ((total_value - self.initial_balance) / self.initial_balance * 100)
        
        print(f"\n💰 Account:")
        print(f"   Cash:          ${self.balance:.2f}")
        print(f"   Position Value: ${total_value - self.balance:.2f}")
        print(f"   Total Value:    ${total_value:.2f}")
        print(f"   P&L:           ${total_value - self.initial_balance:+.2f} ({pnl_pct:+.2f}%)")
        print(f"   Daily P&L:     ${self.daily_pnl:+.2f}")
        
        # Trading stats
        if self.total_trades > 0:
            win_rate = (self.winning_trades / self.total_trades) * 100
            print(f"\n📈 Performance:")
            print(f"   Total Trades:   {self.total_trades}")
            print(f"   Win Rate:       {win_rate:.1f}%")
            print(f"   Avg P&L:        ${self.total_pnl / self.total_trades:.2f}")
        
        # Active positions
        if self.positions:
            print(f"\n📍 Positions ({len(self.positions)}):")
            for i, pos in enumerate(self.positions, 1):
                market = next((m for m in self.markets if m.market_id == pos.market_id), None)
                question = market.question[:50] if market else pos.market_id
                print(f"   {i}. {question}")
                print(f"      {pos.outcome}: {pos.shares:.2f} shares @ ${pos.avg_price:.3f}")
                print(f"      Current: ${pos.current_price:.3f} | P&L: ${pos.unrealized_pnl:+.2f}")
        
        # Recent markets
        print(f"\n📊 Active Markets ({len(self.markets)}):")
        for market in self.markets[:3]:
            print(f"   • {market.question[:60]}")
            print(f"     YES: ${market.prices['YES']:.3f} | NO: ${market.prices['NO']:.3f}")

        # Execution realism stats
        fs = self.freshness_tracker.stats()
        ss = self.slippage_model.stats()
        print(f"\n⏱  Quote Freshness:")
        print(f"   p50: {fs.get('p50_seconds', 0)}s  "
              f"p95: {fs.get('p95_seconds', 0)}s  "
              f"p99: {fs.get('p99_seconds', 0)}s")
        print(f"   Stale blocks: {fs.get('stale_blocks', 0)} "
              f"({fs.get('stale_block_rate', 0)*100:.1f}% of checks)")
        print(f"   Freshness-blocked trades: {self.freshness_blocked}")
        if ss.get("total_orders", 0):
            print(f"\n📉 Slippage:")
            print(f"   Fill rate:    {ss.get('fill_rate', 0)*100:.1f}%")
            print(f"   Adverse rate: {ss.get('adverse_fill_rate', 0)*100:.1f}%")
            print(f"   Avg slip:     {ss.get('avg_slippage_pct', 0):.3f}%")
            print(f"   p95 slip:     {ss.get('p95_slippage_pct', 0):.3f}%")
            print(f"   Total slip $: ${ss.get('total_slippage_cost', 0):.4f}")

        print("="*80)
    
    async def run_simulation(self, duration_minutes: int = 60):
        """Run paper trading simulation"""
        
        self.logger.info("🎯 Starting Paper Trading Simulation")
        self.logger.info(f"Duration: {duration_minutes} minutes")
        self.logger.info(f"Starting Balance: ${self.balance:.2f}")
        self.logger.info(f"Update Interval: {self.config.get('update_interval_seconds', 10)}s")
        
        start_time = datetime.now()
        end_time = start_time + timedelta(minutes=duration_minutes)
        iteration = 0
        
        try:
            while datetime.now() < end_time:
                iteration += 1
                
                # Update market prices
                self._update_market_prices()
                
                # Update position values
                self._update_positions()
                
                # Generate trading signals
                signals = self.strategy.generate_signals(self.markets)
                
                # Execute approved signals
                for signal in signals:
                    order = Order(
                        market_id=signal.market_id,
                        outcome=signal.outcome,
                        side=signal.action,
                        size=signal.size,
                        price=signal.target_price,
                        timestamp=datetime.now()
                    )
                    
                    # Risk check
                    approved, reason = self.risk_manager.check_order(order, self.positions)
                    
                    if approved:
                        self.logger.info(f"🎯 Signal: {signal.reason}")
                        self._execute_order(order)
                    else:
                        self.logger.warning(f"❌ Rejected: {reason}")
                
                # Print status every 10 iterations
                if iteration % 10 == 0:
                    self._print_status()
                
                # Wait before next iteration
                await asyncio.sleep(self.config.get('update_interval_seconds', 10))
        
        except KeyboardInterrupt:
            print("\n\n🛑 Simulation stopped by user")
        
        # Final summary
        print("\n" + "="*80)
        print("🏁 SIMULATION COMPLETE")
        print("="*80)
        self._print_status()
        
        # Freshness bucket breakdown
        print(self.bucket_analyser.report())

        # Final execution realism logs
        self.freshness_tracker.log_report()
        self.slippage_model.log_report()

        # Export results
        self._export_results()
    
    def _export_results(self):
        """Export simulation results to JSON"""

        results = {
            'start_time': datetime.now().isoformat(),
            'initial_balance': self.initial_balance,
            'final_balance': self.balance,
            'total_pnl': self.total_pnl,
            'total_trades': self.total_trades,
            'winning_trades': self.winning_trades,
            'win_rate': (self.winning_trades / self.total_trades * 100) if self.total_trades > 0 else 0,
            'freshness_stats': self.freshness_tracker.stats(),
            'slippage_stats': self.slippage_model.stats(),
            'trade_history': [
                {
                    'timestamp':    t['timestamp'],
                    'market':       t['market'],
                    'outcome':      t['outcome'],
                    'shares':       round(t['shares'], 4),
                    'quoted_price': round(t['quoted_price'], 4),
                    'fill_price':   round(t['fill_price'], 4),
                    'slippage_pct': round(t['slippage_pct'] * 100, 4),
                    'quote_age_s':  round(t['quote_age_s'], 2),
                    'fill_reason':  t['fill_reason'],
                    'pnl':          round(t['pnl'], 4),
                }
                for t in self.trade_history
            ]
        }

        filename = f"simulation_results_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        with open(filename, 'w') as f:
            json.dump(results, f, indent=2)

        print(f"\n💾 Results saved to: {filename}")


def _base_config(interval: float) -> Dict:
    return {
        'starting_balance': 1000.0,
        'update_interval_seconds': interval,
        'strategy_config': {
            'momentum_buy_threshold': 0.05,
            'momentum_sell_threshold': -0.05,
            'min_confidence': 0.6,
            'base_position_size': 10.0,
            'max_position_size': 50.0,
        },
        'risk_config': {
            'max_daily_loss': 100.0,
            'max_total_exposure': 500.0,
            'max_per_market': 100.0,
            'max_position_size': 50.0,
            'stop_loss_pct': 0.20,
        },
        'freshness_config': {'max_age_seconds': 5.0},
        'slippage_config': {
            'base_slippage':      0.005,
            'spread_half':        0.003,
            'no_fill_prob':       0.25,
            'adverse_fill_prob':  0.15,
            'adverse_multiplier': 3.0,
            'taker_fee':          0.002,
            'maker_fee':          0.001,
        },
    }


def _print_comparison(naive_sim: 'PaperTradingSimulator', real_sim: 'PaperTradingSimulator'):
    """Side-by-side comparison: naive paper trading vs execution realism"""

    def total_value(sim):
        v = sim.balance
        for p in sim.positions:
            v += p.shares * p.current_price
        return v

    n_val  = total_value(naive_sim)
    r_val  = total_value(real_sim)
    n_pnl  = n_val - naive_sim.initial_balance
    r_pnl  = r_val - real_sim.initial_balance
    gap    = r_pnl - n_pnl

    ns = real_sim.slippage_model.stats()
    nf = real_sim.freshness_tracker.stats()

    print("\n")
    print("╔" + "═"*78 + "╗")
    print("║  NAIVE PAPER TRADING  vs  EXECUTION REALISM — SIDE BY SIDE" + " "*18 + "║")
    print("╠" + "═"*78 + "╣")
    print(f"║  {'Metric':<32} {'Naive (paper bot)':>18}  {'Realistic':>18}  ║")
    print("╠" + "═"*78 + "╣")

    rows = [
        ("Final balance",      f"${n_val:>10.2f}",       f"${r_val:>10.2f}"),
        ("Total P&L",          f"${n_pnl:>+10.2f}",      f"${r_pnl:>+10.2f}"),
        ("P&L %",              f"{n_pnl/naive_sim.initial_balance*100:>+9.2f}%",
                               f"{r_pnl/real_sim.initial_balance*100:>+9.2f}%"),
        ("Trades closed",      f"{naive_sim.total_trades:>18}",  f"{real_sim.total_trades:>18}"),
        ("Win rate",           f"{naive_sim.winning_trades/max(naive_sim.total_trades,1)*100:>18.1f}%",
                               f"{real_sim.winning_trades/max(real_sim.total_trades,1)*100:>18.1f}%"),
        ("Avg P&L per trade",  f"${naive_sim.total_pnl/max(naive_sim.total_trades,1):>+9.2f}",
                               f"${real_sim.total_pnl/max(real_sim.total_trades,1):>+9.2f}"),
        ("Stale quotes blocked", "             0",
                               f"{nf.get('stale_blocks',0):>18}"),
        ("Adverse fills",      "             0",
                               f"{ns.get('adverse_fills',0):>18}"),
        ("Avg slippage",       "         0.000%",
                               f"{ns.get('avg_slippage_pct',0):>17.3f}%"),
        ("p95 slippage",       "         0.000%",
                               f"{ns.get('p95_slippage_pct',0):>17.3f}%"),
    ]

    for label, naive_val, real_val in rows:
        print(f"║  {label:<32} {naive_val:>18}  {real_val:>18}  ║")

    print("╠" + "═"*78 + "╣")
    print(f"║  {'EXECUTION COST (gap)':<32} {' ':>18}  {gap:>+17.2f}  ║")
    pct_of_naive = (gap / abs(n_pnl) * 100) if n_pnl != 0 else 0
    print(f"║  {'  as % of naive P&L':<32} {' ':>18}  {pct_of_naive:>+16.1f}%  ║")
    print("╚" + "═"*78 + "╝")

    print("\n  ↑ The execution cost is the hidden drag that paper bots never see.")
    print("  ↑ If naive P&L is positive but realistic is negative: strategy has NO edge.")
    print()

    print(real_sim.bucket_analyser.report())


async def main():
    """Main entry point for paper trading"""

    parser = argparse.ArgumentParser(description="Polymarket Paper Trading Simulator")
    parser.add_argument("--fast",    action="store_true", help="Demo mode (~30s runtime)")
    parser.add_argument("--naive",   action="store_true", help="Run naive mode only (no realism)")
    parser.add_argument("--compare", action="store_true", help="Run both modes and show side-by-side")
    parser.add_argument("--duration", type=int, default=60, help="Duration in minutes (default: 60)")
    args = parser.parse_args()

    duration = 3   if args.fast else args.duration
    interval = 0.05 if args.fast else 5.0

    logging.basicConfig(
        level=logging.WARNING,   # quieter in compare mode so table stands out
        format='%(asctime)s - %(levelname)s - %(message)s'
    )

    if args.compare:
        seed = random.randint(0, 999999)
        print("\n" + "="*80)
        print("🔬 STRATEGY DIAGNOSTICS — NAIVE vs REALISTIC  (seed={})".format(seed))
        print("="*80)
        print(f"Running {duration}-minute sim twice with identical market data...")
        print("Ctrl+C to abort\n")

        naive_cfg = {**_base_config(interval), 'naive_mode': True}
        real_cfg  = {**_base_config(interval), 'naive_mode': False}

        print("  [1/2] Running naive simulation...")
        naive_sim = PaperTradingSimulator(naive_cfg, seed=seed)
        await naive_sim.run_simulation(duration_minutes=duration)

        print("  [2/2] Running realistic simulation (same seed)...")
        real_sim = PaperTradingSimulator(real_cfg, seed=seed)
        await real_sim.run_simulation(duration_minutes=duration)

        _print_comparison(naive_sim, real_sim)

    else:
        mode_label = "NAIVE" if args.naive else ("FAST / DEMO" if args.fast else "REALISTIC")
        print("\n" + "="*80)
        print(f"🎮 PAPER TRADING SIMULATOR  [{mode_label}]")
        print("="*80)
        print(f"Simulating {duration} minutes  |  use --compare to see naive vs realistic gap")
        print("="*80 + "\n")

        logging.getLogger().setLevel(logging.INFO)
        cfg = {**_base_config(interval), 'naive_mode': args.naive}
        sim = PaperTradingSimulator(cfg)
        await sim.run_simulation(duration_minutes=duration)


if __name__ == "__main__":
    asyncio.run(main())
