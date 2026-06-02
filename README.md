# Polymarket Trading Agent 🤖📊

An automated trading agent for Polymarket's 5-minute prediction markets. Built with modular architecture for easy strategy customization and robust risk management.

## 🚀 Features

- **Automated Trading**: Monitors markets and executes trades automatically
- **Modular Strategy System**: Easy to add custom trading strategies
- **Risk Management**: Built-in position limits, stop losses, and daily loss caps
- **Real-time Monitoring**: Continuous market data updates
- **Testnet Support**: Test strategies without real money
- **Comprehensive Logging**: Track all trades and decisions

## 📋 Prerequisites

1. **Python 3.9+**
2. **Polymarket Account** with API access
3. **Ethereum Wallet** (for transaction signing)
4. **USDC** for trading (testnet or mainnet)

## 🛠️ Installation

### 1. Clone and Install Dependencies

```bash
pip install -r requirements.txt
```

### 2. Get Polymarket API Credentials

1. Go to [Polymarket](https://polymarket.com)
2. Create an account or log in
3. Navigate to API settings
4. Generate API key and secret
5. Save your credentials securely

### 3. Configure the Agent

Edit `polymarket_agent.py` and update the config section:

```python
config = {
    'api_key': 'YOUR_API_KEY_HERE',      # Replace with your API key
    'api_secret': 'YOUR_API_SECRET_HERE', # Replace with your secret
    'testnet': True,                      # Set False for real trading
    
    # ... rest of config
}
```

## 🏃 Quick Start

### Test Mode (Recommended First)

```bash
python polymarket_agent.py
```

The agent will:
1. Connect to Polymarket testnet
2. Monitor 5-minute markets
3. Generate trading signals
4. Execute trades (with testnet USDC)

### Production Mode

⚠️ **WARNING**: Only use after thorough testing!

```python
config = {
    'testnet': False,  # Enable real trading
    # ... adjust risk limits
}
```

## ⚙️ Configuration Guide

### Strategy Configuration

```python
'strategy_config': {
    'momentum_buy_threshold': 0.05,   # Buy when price rises 5%
    'momentum_sell_threshold': -0.05, # Sell when price falls 5%
    'min_confidence': 0.6,            # Minimum confidence to trade
    'base_position_size': 10.0,       # Base position $10
    'max_position_size': 50.0,        # Max position $50
}
```

### Risk Management

```python
'risk_config': {
    'max_daily_loss': 100.0,      # Stop trading after $100 daily loss
    'max_total_exposure': 500.0,  # Max $500 across all positions
    'max_per_market': 100.0,      # Max $100 in any single market
    'max_position_size': 50.0,    # Max $50 per trade
    'stop_loss_pct': 0.20,        # Exit at 20% loss
}
```

### Execution Settings

```python
'update_interval_seconds': 10,  # Check markets every 10 seconds
```

## 📊 Built-in Strategy: Momentum

The default strategy trades based on price momentum:

**Buy Signal**: Price rises > 5% over recent candles
- Buys the outcome with increasing confidence
- Position size scales with momentum strength

**Sell Signal**: Price falls > 5% over recent candles  
- Sells the outcome before further decline
- Position size scales with momentum strength

## 🔧 Adding Custom Strategies

Create a new strategy class:

```python
class MyCustomStrategy(BaseStrategy):
    def generate_signals(self, markets: List[MarketData]) -> List[TradeSignal]:
        signals = []
        
        for market in markets:
            # Your strategy logic here
            # Example: arbitrage, mean reversion, news-based, etc.
            
            if should_buy:
                signal = TradeSignal(
                    market_id=market.market_id,
                    outcome="YES",
                    action=OrderSide.BUY,
                    confidence=0.8,
                    size=25.0,
                    target_price=0.55,
                    reason="My custom signal",
                    timestamp=datetime.now()
                )
                signals.append(signal)
        
        return signals
```

Then update the config:

```python
config = {
    'strategy': 'custom',
    # ... 
}

# In __init__:
if strategy_name == 'custom':
    self.strategy = MyCustomStrategy(config.get('strategy_config', {}))
```

## 🎯 Strategy Ideas

Here are some strategies you could implement:

1. **Mean Reversion**: Buy when price overshoots fundamentals
2. **Arbitrage**: Exploit price differences across markets
3. **News Trading**: React to external events/catalysts
4. **Order Book Imbalance**: Trade based on bid/ask pressure
5. **Volume Analysis**: Follow unusual volume spikes
6. **Multi-Market Correlation**: Trade based on related market movements

## 📈 Monitoring & Logging

Logs are saved to `polymarket_agent.log`:

```
2026-04-12 15:30:01 - INFO - Starting Polymarket Trading Agent
2026-04-12 15:30:02 - INFO - Monitoring 12 markets
2026-04-12 15:30:05 - INFO - Generated 3 trading signals
2026-04-12 15:30:06 - INFO - Executing signal: Momentum buy: 6.2% price increase
2026-04-12 15:30:07 - INFO - Order placed: order_1712934607123
```

## ⚠️ Important Warnings

### Before Going Live

- [ ] Test extensively on testnet
- [ ] Start with small position sizes
- [ ] Monitor for at least 24 hours
- [ ] Verify API credentials are secure
- [ ] Understand all risk parameters
- [ ] Have a kill switch plan

### Risk Considerations

1. **5-minute markets are HIGH FREQUENCY**
   - Losses can accumulate quickly
   - Transaction fees matter more
   - Need fast execution

2. **Market Risks**
   - Low liquidity = high slippage
   - Market manipulation possible
   - Resolution uncertainty

3. **Technical Risks**
   - API downtime
   - Network latency
   - Bugs in strategy code

4. **Regulatory Risks**
   - Check local gambling/prediction market laws
   - Understand tax implications

## 🔐 Security Best Practices

1. **Never commit API keys to git**
2. Use environment variables:
   ```python
   import os
   config = {
       'api_key': os.getenv('POLYMARKET_API_KEY'),
       'api_secret': os.getenv('POLYMARKET_API_SECRET'),
   }
   ```
3. Use a dedicated wallet for trading
4. Enable 2FA on Polymarket account
5. Monitor logs for suspicious activity

## 📊 Performance Tracking

Add this to track performance:

```python
# In your trading loop
total_trades = 0
winning_trades = 0
total_pnl = 0.0

# After each trade closes
total_trades += 1
if trade_pnl > 0:
    winning_trades += 1
total_pnl += trade_pnl

win_rate = winning_trades / total_trades
print(f"Win Rate: {win_rate:.1%}, Total P&L: ${total_pnl:.2f}")
```

## 🐛 Troubleshooting

### "Failed to place order"
- Check API credentials
- Verify sufficient USDC balance
- Check network connection
- Review Polymarket API status

### "Order rejected: Daily loss limit reached"
- Risk manager stopped trading
- Check `max_daily_loss` setting
- Review recent trades in logs

### "No markets found"
- Verify 5-minute markets are active
- Check market filtering logic
- Try adjusting update interval

## 🚧 TODO / Improvements

- [ ] Add actual Polymarket API integration (currently placeholder)
- [ ] Implement order signing with web3
- [ ] Add WebSocket support for real-time data
- [ ] Create backtesting framework
- [ ] Add Telegram/Discord notifications
- [ ] Build web dashboard for monitoring
- [ ] Add more strategies (mean reversion, arbitrage)
- [ ] Implement order book analysis
- [ ] Add position management (scaling in/out)
- [ ] Create database for trade history

## 📚 Resources

- [Polymarket Docs](https://docs.polymarket.com/)
- [CLOB API Docs](https://docs.polymarket.com/api/clob-api)
- [py-clob-client](https://github.com/Polymarket/py-clob-client)

## ⚖️ License

MIT License - Use at your own risk

## ⚠️ Disclaimer

**This software is for educational purposes only. Trading prediction markets carries significant risk. You can lose money. The authors are not responsible for any financial losses. Always do your own research and trade responsibly.**

---

## 🤝 Contributing

Ideas for improvements:

1. Fork the repo
2. Create a feature branch
3. Add your strategy/feature
4. Test thoroughly
5. Submit a pull request

## 💬 Questions?

- Review the code comments
- Check Polymarket documentation
- Test on testnet first
- Start with small positions

**Happy Trading! 🚀**
