"""
Configuration Template for Polymarket Trading Agent
====================================================
Copy this file and customize for your needs
"""

import os

# Example configs for different trading styles

# CONSERVATIVE CONFIG - Low risk, small positions
CONSERVATIVE_CONFIG = {
    # API Credentials
    'api_key': os.getenv('POLYMARKET_API_KEY', 'YOUR_API_KEY'),
    'api_secret': os.getenv('POLYMARKET_API_SECRET', 'YOUR_API_SECRET'),
    'testnet': True,
    
    # Strategy: Momentum
    'strategy': 'momentum',
    'strategy_config': {
        'momentum_buy_threshold': 0.08,      # Require 8% move (more selective)
        'momentum_sell_threshold': -0.08,
        'min_confidence': 0.7,               # Higher confidence required
        'base_position_size': 5.0,           # Small $5 base
        'max_position_size': 20.0,           # Max $20 per trade
    },
    
    # Risk Management - Conservative
    'risk_config': {
        'max_daily_loss': 50.0,              # Stop at $50 daily loss
        'max_total_exposure': 200.0,         # Max $200 total
        'max_per_market': 50.0,              # Max $50 per market
        'max_position_size': 20.0,           # Max $20 per position
        'stop_loss_pct': 0.15,               # 15% stop loss
    },
    
    'update_interval_seconds': 15,           # Check every 15s (less aggressive)
}


# AGGRESSIVE CONFIG - Higher risk, larger positions
AGGRESSIVE_CONFIG = {
    'api_key': os.getenv('POLYMARKET_API_KEY', 'YOUR_API_KEY'),
    'api_secret': os.getenv('POLYMARKET_API_SECRET', 'YOUR_API_SECRET'),
    'testnet': True,
    
    # Strategy: Momentum
    'strategy': 'momentum',
    'strategy_config': {
        'momentum_buy_threshold': 0.03,      # Trigger on 3% moves
        'momentum_sell_threshold': -0.03,
        'min_confidence': 0.5,               # Lower bar
        'base_position_size': 25.0,          # $25 base
        'max_position_size': 100.0,          # Up to $100 per trade
    },
    
    # Risk Management - Aggressive
    'risk_config': {
        'max_daily_loss': 500.0,             # Allow $500 daily loss
        'max_total_exposure': 2000.0,        # $2000 total exposure
        'max_per_market': 500.0,             # $500 per market
        'max_position_size': 100.0,          # $100 per position
        'stop_loss_pct': 0.25,               # 25% stop loss (wider)
    },
    
    'update_interval_seconds': 5,            # Check every 5s (very active)
}


# MEAN REVERSION CONFIG
MEAN_REVERSION_CONFIG = {
    'api_key': os.getenv('POLYMARKET_API_KEY', 'YOUR_API_KEY'),
    'api_secret': os.getenv('POLYMARKET_API_SECRET', 'YOUR_API_SECRET'),
    'testnet': True,
    
    # Strategy: Mean Reversion
    'strategy': 'mean_reversion',
    'strategy_config': {
        'buy_z_score': -1.5,                 # Buy at 1.5 std below mean
        'sell_z_score': 1.5,                 # Sell at 1.5 std above mean
        'min_confidence': 0.6,
        'base_position_size': 15.0,
        'max_position_size': 60.0,
    },
    
    'risk_config': {
        'max_daily_loss': 200.0,
        'max_total_exposure': 800.0,
        'max_per_market': 200.0,
        'max_position_size': 60.0,
        'stop_loss_pct': 0.20,
    },
    
    'update_interval_seconds': 10,
}


# VOLUME BREAKOUT CONFIG
VOLUME_BREAKOUT_CONFIG = {
    'api_key': os.getenv('POLYMARKET_API_KEY', 'YOUR_API_KEY'),
    'api_secret': os.getenv('POLYMARKET_API_SECRET', 'YOUR_API_SECRET'),
    'testnet': True,
    
    # Strategy: Volume Breakout
    'strategy': 'volume_breakout',
    'strategy_config': {
        'volume_spike_multiplier': 2.5,      # 2.5x average volume
        'min_price_move': 0.03,              # 3% price move required
        'min_confidence': 0.65,
        'base_position_size': 20.0,
        'max_position_size': 80.0,
    },
    
    'risk_config': {
        'max_daily_loss': 300.0,
        'max_total_exposure': 1000.0,
        'max_per_market': 300.0,
        'max_position_size': 80.0,
        'stop_loss_pct': 0.20,
    },
    
    'update_interval_seconds': 8,
}


# COMBINED STRATEGY CONFIG - Uses multiple strategies
COMBINED_CONFIG = {
    'api_key': os.getenv('POLYMARKET_API_KEY', 'YOUR_API_KEY'),
    'api_secret': os.getenv('POLYMARKET_API_SECRET', 'YOUR_API_SECRET'),
    'testnet': True,
    
    # Strategy: Combined (requires multiple signals)
    'strategy': 'combined',
    'strategy_config': {
        'min_strategies_agree': 2,           # Require 2+ strategies to agree
        
        # Momentum sub-strategy params
        'momentum_buy_threshold': 0.05,
        'momentum_sell_threshold': -0.05,
        
        # Mean reversion sub-strategy params
        'buy_z_score': -1.5,
        'sell_z_score': 1.5,
        
        'min_confidence': 0.65,              # Higher bar for combined
        'base_position_size': 30.0,
        'max_position_size': 100.0,
    },
    
    'risk_config': {
        'max_daily_loss': 400.0,
        'max_total_exposure': 1500.0,
        'max_per_market': 400.0,
        'max_position_size': 100.0,
        'stop_loss_pct': 0.18,
    },
    
    'update_interval_seconds': 10,
}


# TESTNET CONFIG - For safe testing
TESTNET_CONFIG = {
    'api_key': 'testnet_key',
    'api_secret': 'testnet_secret',
    'testnet': True,                         # Always testnet
    
    'strategy': 'momentum',
    'strategy_config': {
        'momentum_buy_threshold': 0.05,
        'momentum_sell_threshold': -0.05,
        'min_confidence': 0.6,
        'base_position_size': 1.0,           # Tiny positions for testing
        'max_position_size': 5.0,
    },
    
    'risk_config': {
        'max_daily_loss': 20.0,              # Very conservative for testing
        'max_total_exposure': 50.0,
        'max_per_market': 20.0,
        'max_position_size': 5.0,
        'stop_loss_pct': 0.10,
    },
    
    'update_interval_seconds': 20,           # Slower for testing
}


# How to use:
"""
In polymarket_agent.py, replace the config dict with:

from config import CONSERVATIVE_CONFIG  # or any other config

async def main():
    agent = PolymarketAgent(CONSERVATIVE_CONFIG)
    await agent.start()

Or create your own custom config by copying one of the above
"""


# Environment variables approach (recommended for production)
"""
Create a .env file:

POLYMARKET_API_KEY=your_api_key_here
POLYMARKET_API_SECRET=your_secret_here
TRADING_MODE=conservative

Then in your code:

from dotenv import load_dotenv
load_dotenv()

mode = os.getenv('TRADING_MODE', 'conservative')
config = {
    'conservative': CONSERVATIVE_CONFIG,
    'aggressive': AGGRESSIVE_CONFIG,
    'mean_reversion': MEAN_REVERSION_CONFIG,
}[mode]
"""
