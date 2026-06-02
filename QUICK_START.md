# QUICK START CHEAT SHEET 📝
## Polymarket Trading Agent - macOS

### 🚀 FIRST TIME SETUP (Do Once)

```bash
# 1. Install Homebrew
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"

# 2. Install Python
brew install python@3.11

# 3. Go to your project folder
cd ~/Desktop/polymarket-agent

# 4. Create virtual environment
python3.11 -m venv venv

# 5. Activate virtual environment
source venv/bin/activate

# 6. Install packages
pip install -r requirements.txt

# 7. Verify setup
python check_setup.py
```

---

### 🎮 DAILY USAGE

```bash
# Navigate to project
cd ~/Desktop/polymarket-agent

# Activate environment (MUST DO EVERY TIME!)
source venv/bin/activate

# Run paper trading (safe testing)
python paper_trading.py

# Or run real bot (after API setup)
python polymarket_agent.py

# Stop the bot
Press Ctrl + C

# Check logs
tail -f polymarket_agent.log

# When done, deactivate
deactivate
```

---

### 📊 PAPER TRADING (Recommended First!)

```bash
# Start simulation (no API needed)
python paper_trading.py

# It will:
# - Simulate 5-minute markets
# - Generate trading signals
# - Execute fake trades
# - Track performance
# - Save results to JSON file

# Let it run for 30-60 minutes
# Press Ctrl+C to stop early
```

---

### ⚙️ CONFIGURATION FILES

**Conservative** (Start Here):
```python
# In polymarket_agent.py, use:
from config import CONSERVATIVE_CONFIG
agent = PolymarketAgent(CONSERVATIVE_CONFIG)
```

**Aggressive** (After Experience):
```python
from config import AGGRESSIVE_CONFIG
agent = PolymarketAgent(AGGRESSIVE_CONFIG)
```

**Custom**:
Edit `config.py` and create your own!

---

### 🔍 TROUBLESHOOTING

**"Command not found: python3.11"**
```bash
brew install python@3.11
```

**"No module named 'aiohttp'"**
```bash
source venv/bin/activate
pip install -r requirements.txt
```

**"Permission denied"**
```bash
chmod +x polymarket_agent.py
chmod +x paper_trading.py
```

**Virtual environment not active?**
```bash
# Your terminal should show (venv) at the start
# If not:
source venv/bin/activate
```

---

### 📁 FILE OVERVIEW

- **polymarket_agent.py** - Main bot
- **paper_trading.py** - Simulation mode ⭐ START HERE
- **custom_strategies.py** - Additional strategies
- **config.py** - Pre-made configs
- **check_setup.py** - Verify installation
- **SETUP_GUIDE.md** - Detailed guide
- **README.md** - Documentation

---

### 🎯 LEARNING PATH

**Week 1: Learn**
```bash
# Read documentation
open README.md
open SETUP_GUIDE.md

# Run simulations
python paper_trading.py

# Experiment with configs
# Edit config.py values
# Re-run simulations
```

**Week 2-3: Test**
```bash
# Run longer simulations
# Track performance
# Refine strategy
# Study the results JSON files
```

**Week 4+: Live (Optional)**
```bash
# Get API credentials
# Update config with real keys
# Start with TINY positions
# Monitor constantly
```

---

### 📈 MONITORING PERFORMANCE

```bash
# Check logs
tail -f polymarket_agent.log

# View last 50 lines
tail -50 polymarket_agent.log

# Search logs for errors
grep "ERROR" polymarket_agent.log

# View simulation results
cat simulation_results_*.json
```

---

### 🛡️ SAFETY CHECKLIST

Before going live:
- [ ] Tested in paper mode for 2+ weeks
- [ ] Win rate > 50%
- [ ] Max daily loss set conservatively
- [ ] Starting with < $100
- [ ] Have monitoring plan
- [ ] Understand every config setting

---

### 💡 PRO TIPS

1. **Always activate venv first!**
   ```bash
   source venv/bin/activate
   ```

2. **Start in paper mode**
   - No risk
   - Learn how it works
   - Test strategies

3. **Keep a journal**
   ```bash
   echo "$(date): Strategy X results..." >> notes.txt
   ```

4. **Monitor the bot**
   - Don't set and forget
   - Check every hour minimum
   - Have kill switch ready

5. **Start small**
   - First week: $5-10 max
   - Learn from small mistakes

---

### 🆘 GETTING HELP

**Check setup:**
```bash
python check_setup.py
```

**View full guide:**
```bash
open SETUP_GUIDE.md
```

**Documentation:**
```bash
open README.md
```

**Polymarket docs:**
https://docs.polymarket.com

---

### 🎓 UNDERSTANDING CONFIGS

```python
'max_daily_loss': 100.0        # Stop if you lose $100 today
'max_position_size': 50.0      # Max $50 per trade
'max_total_exposure': 500.0    # Max $500 total in all trades
'stop_loss_pct': 0.20          # Exit position at 20% loss
'momentum_buy_threshold': 0.05 # Buy if price up 5%
```

**Conservative = Small numbers**
**Aggressive = Large numbers**

Start conservative!

---

### 📅 DAILY ROUTINE

```bash
# Morning
cd ~/Desktop/polymarket-agent
source venv/bin/activate
python check_setup.py
python paper_trading.py  # or polymarket_agent.py

# During day
# - Check logs every hour
# - Monitor performance
# - Take notes

# Evening
# - Review results
# - Adjust strategy if needed
# - Plan tomorrow

deactivate
```

---

### 🔐 SECURITY

**NEVER share:**
- API keys
- API secrets
- Seed phrases
- Private keys

**DO share:**
- Strategy ideas
- Code improvements
- Questions

---

### ✅ QUICK CHECKLIST

Starting paper trading?
- [ ] Installed Python 3.11
- [ ] Created virtual environment
- [ ] Installed requirements
- [ ] Ran check_setup.py
- [ ] Read SETUP_GUIDE.md

Ready for live trading?
- [ ] Paper traded for 2+ weeks
- [ ] Positive P&L in simulation
- [ ] Have API credentials
- [ ] Set conservative limits
- [ ] Understand all risks

---

**Remember**: Start slow, test thoroughly, never risk more than you can afford to lose!

**Questions?** Check SETUP_GUIDE.md (detailed) or README.md (overview)

---

Last Updated: April 2026
Made with ❤️ for beginners
