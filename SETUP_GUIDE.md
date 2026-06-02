# Complete Setup Guide for Polymarket Trading Agent (macOS)
## For Complete Beginners 🚀

This guide assumes you've never done this before. Follow every step carefully.

---

## Part 1: Install Required Software (30 minutes)

### Step 1: Install Homebrew (Package Manager)

1. **Open Terminal**
   - Press `Cmd + Space` to open Spotlight
   - Type "Terminal" and press Enter
   - A black/white window will open

2. **Install Homebrew** (copy-paste this entire command):
   ```bash
   /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
   ```
   - Press Enter
   - It will ask for your Mac password (you won't see it typing - that's normal)
   - Wait 5-10 minutes for installation
   - When it says "Installation successful!", continue

3. **Verify Homebrew installed**:
   ```bash
   brew --version
   ```
   - Should show something like "Homebrew 4.x.x"

---

### Step 2: Install Python 3.11

1. **Install Python**:
   ```bash
   brew install python@3.11
   ```
   - Wait 3-5 minutes

2. **Verify Python installed**:
   ```bash
   python3.11 --version
   ```
   - Should show "Python 3.11.x"

3. **Make Python 3.11 your default** (optional but recommended):
   ```bash
   echo 'export PATH="/opt/homebrew/opt/python@3.11/bin:$PATH"' >> ~/.zshrc
   source ~/.zshrc
   ```

---

### Step 3: Install Git (Version Control)

1. **Install Git**:
   ```bash
   brew install git
   ```

2. **Verify Git installed**:
   ```bash
   git --version
   ```

---

## Part 2: Set Up Your Trading Agent (15 minutes)

### Step 4: Create Project Folder

1. **Create a folder for your project**:
   ```bash
   cd ~/Desktop
   mkdir polymarket-agent
   cd polymarket-agent
   ```
   - This creates a folder called "polymarket-agent" on your Desktop

2. **Verify you're in the right place**:
   ```bash
   pwd
   ```
   - Should show: `/Users/YourName/Desktop/polymarket-agent`

---

### Step 5: Move Your Downloaded Files

1. **Find your downloaded files**:
   - Open Finder
   - Go to Downloads folder
   - Look for these files:
     - `polymarket_agent.py`
     - `custom_strategies.py`
     - `config.py`
     - `requirements.txt`
     - `README.md`

2. **Move files to your project folder**:
   - **Option A (Easy)**: Drag all 5 files from Downloads to the `polymarket-agent` folder on Desktop
   
   - **Option B (Terminal)**:
     ```bash
     mv ~/Downloads/polymarket_agent.py ~/Desktop/polymarket-agent/
     mv ~/Downloads/custom_strategies.py ~/Desktop/polymarket-agent/
     mv ~/Downloads/config.py ~/Desktop/polymarket-agent/
     mv ~/Downloads/requirements.txt ~/Desktop/polymarket-agent/
     mv ~/Downloads/README.md ~/Desktop/polymarket-agent/
     ```

3. **Verify files are there**:
   ```bash
   ls -la
   ```
   - You should see all 5 files listed

---

### Step 6: Install Python Dependencies

1. **Create a virtual environment** (keeps things isolated):
   ```bash
   python3.11 -m venv venv
   ```
   - Creates a folder called `venv`

2. **Activate the virtual environment**:
   ```bash
   source venv/bin/activate
   ```
   - Your terminal prompt should now show `(venv)` at the start

3. **Install required packages**:
   ```bash
   pip install --upgrade pip
   pip install -r requirements.txt
   ```
   - Wait 2-3 minutes
   - You'll see packages installing

4. **Verify installation**:
   ```bash
   pip list
   ```
   - Should show `aiohttp`, `web3`, `eth-account`, etc.

---

## Part 3: Get Polymarket API Access (20-30 minutes)

### Step 7: Create Polymarket Account

1. **Go to Polymarket**:
   - Open browser → https://polymarket.com
   
2. **Sign up**:
   - Click "Sign Up" or "Connect Wallet"
   - You'll need a **crypto wallet**:
     - **Option A**: Use MetaMask (browser extension)
       - Install MetaMask: https://metamask.io
       - Create new wallet
       - **SAVE YOUR SEED PHRASE SOMEWHERE SAFE!**
     - **Option B**: Use WalletConnect with Rainbow/Coinbase Wallet

3. **Complete KYC** (if required):
   - Upload ID
   - Wait for approval (can take 1-24 hours)

---

### Step 8: Get Testnet Access & API Keys

⚠️ **IMPORTANT**: Start with testnet (fake money) first!

1. **Polymarket doesn't have a public testnet API yet** 😕
   
   This means you have two options:

   **Option A: Paper Trading Mode (Recommended for beginners)**
   - Run the bot in "simulation mode"
   - It will generate signals but NOT place real trades
   - You manually review signals and learn
   - **Skip to Step 9 below**

   **Option B: Real Trading with Small Amounts**
   - Start with tiny positions ($1-5)
   - Get API access from Polymarket
   - Contact support@polymarket.com for API credentials
   - ⚠️ Only do this after you understand how it works!

---

### Step 9: Set Up Paper Trading (Safe Testing)

Since Polymarket's testnet access is limited, let's set up paper trading first:

1. **Create a test configuration**:
   ```bash
   nano test_config.py
   ```

2. **Copy-paste this** (I'll create this file for you below):
   - See `paper_trading_config.py` (creating now...)

3. **Save and exit**:
   - Press `Ctrl + X`
   - Press `Y` (for yes)
   - Press Enter

---

## Part 4: Configure Your Bot (10 minutes)

### Step 10: Edit Configuration

1. **Open the main agent file**:
   ```bash
   nano polymarket_agent.py
   ```

2. **Scroll to the bottom** (use arrow keys):
   - Find the `config = {` section around line 500

3. **Update these values**:
   ```python
   config = {
       'api_key': 'TESTNET_MODE',      # Leave as is for now
       'api_secret': 'TESTNET_MODE',   # Leave as is for now
       'testnet': True,                # Keep this True!
       
       # ... rest stays the same
   }
   ```

4. **Save**: `Ctrl + X`, then `Y`, then Enter

---

## Part 5: First Test Run (5 minutes)

### Step 11: Test the Bot

1. **Make sure virtual environment is active**:
   ```bash
   source venv/bin/activate
   ```
   - Should show `(venv)` in prompt

2. **Run the bot in dry-run mode**:
   ```bash
   python polymarket_agent.py
   ```

3. **What you'll see**:
   ```
   2026-04-12 10:30:01 - INFO - Starting Polymarket Trading Agent
   2026-04-12 10:30:01 - INFO - Strategy: momentum
   2026-04-12 10:30:01 - INFO - Testnet: True
   2026-04-12 10:30:02 - INFO - Monitoring 0 markets (API not connected)
   ```

4. **Stop the bot**:
   - Press `Ctrl + C`

✅ **If you see output like above, everything is installed correctly!**

---

## Part 6: Understanding What You Have

### What Each File Does:

1. **polymarket_agent.py**
   - Main bot code
   - Connects to Polymarket
   - Places trades
   - Manages risk

2. **custom_strategies.py**
   - Different trading strategies
   - Mean reversion, volume breakout, etc.
   - You can create your own!

3. **config.py**
   - Pre-set configurations
   - Conservative, aggressive, etc.
   - Risk limits

4. **requirements.txt**
   - List of Python packages needed
   - Already installed in Step 6

---

## Part 7: Next Steps - Choose Your Path

### Path A: Learn First (Recommended)

**Week 1-2: Learn Without Trading**
1. Read about prediction markets
2. Watch Polymarket markets manually
3. Study the code
4. Modify strategy parameters
5. Run simulations

**Week 3-4: Paper Trading**
1. Run bot in simulation mode
2. Track hypothetical performance
3. Refine your strategy
4. Build confidence

**Month 2+: Live Trading**
1. Start with $10-20 maximum
2. Use conservative config
3. Monitor closely
4. Scale up slowly

---

### Path B: Get API Access & Trade Small

1. **Email Polymarket**: support@polymarket.com
   - Subject: "API Access Request"
   - Explain you want to build a trading bot
   - Ask for API credentials

2. **Wait for Response** (can take 3-7 days)

3. **Once you have credentials**:
   - Update config with real API key/secret
   - Start with `CONSERVATIVE_CONFIG`
   - Deposit only $50-100 to start
   - Set `max_daily_loss: 10.0` (lose max $10/day)

---

## Common Issues & Solutions

### "Command not found: python3.11"
**Solution**: 
```bash
brew install python@3.11
```

### "Permission denied"
**Solution**: 
```bash
chmod +x polymarket_agent.py
```

### "Module not found: aiohttp"
**Solution**: 
```bash
source venv/bin/activate
pip install -r requirements.txt
```

### "No markets found"
**Solution**: 
- You need real API credentials
- Or use simulation mode (coming next)

---

## What to Learn Next

### Understanding Trading Strategies

1. **Momentum Strategy** (default):
   - Buys when price rising fast
   - Sells when price falling fast
   - Best for: Trending markets

2. **Mean Reversion**:
   - Buys when price too low
   - Sells when price too high
   - Best for: Range-bound markets

3. **Volume Breakout**:
   - Trades on unusual volume
   - Follows big money moves
   - Best for: Event-driven markets

### Risk Management Concepts

- **Position Sizing**: How much to bet per trade
- **Stop Loss**: Exit when losing X%
- **Daily Loss Limit**: Stop trading after losing X total
- **Exposure Limits**: Max $ in all positions

---

## Safety Checklist Before Going Live

- [ ] Tested on paper/simulation for 2+ weeks
- [ ] Understand all config parameters
- [ ] Set conservative risk limits
- [ ] Have API credentials secured
- [ ] Only using money you can afford to lose
- [ ] Monitoring bot at least once per hour
- [ ] Have a kill switch plan
- [ ] Understand tax implications

---

## Getting Help

### If Something Breaks:

1. **Check the logs**:
   ```bash
   tail -f polymarket_agent.log
   ```

2. **Search the error message** on Google

3. **Polymarket Documentation**:
   - https://docs.polymarket.com

4. **Python Help**:
   - https://stackoverflow.com

---

## Pro Tips

### Tip 1: Start Small
- First month: Max $50 total, $5 per trade
- Learn from mistakes when stakes are low

### Tip 2: Keep a Trading Journal
```bash
echo "$(date): Tried strategy X, result Y" >> trading_journal.txt
```

### Tip 3: Monitor Performance
- Track win rate
- Track average profit/loss
- Adjust strategy based on data

### Tip 4: Don't Get Emotional
- If bot loses, don't immediately change everything
- Give strategies time (50+ trades minimum)
- Data > feelings

---

## Summary of Commands You'll Use Daily

```bash
# Activate environment
cd ~/Desktop/polymarket-agent
source venv/bin/activate

# Run the bot
python polymarket_agent.py

# Stop the bot
Ctrl + C

# Check logs
tail -f polymarket_agent.log

# Deactivate environment when done
deactivate
```

---

## What's Next?

I'll create some additional files for you:
1. **Simulation mode** - Test without API
2. **Performance tracker** - Monitor your results
3. **Setup checker** - Verify everything installed correctly

Ready? Let me know which path you want to take:
- **Path A**: Learn & simulate first (recommended)
- **Path B**: Get API access ASAP
- **Path C**: Something else?

---

**Last Updated**: April 2026
**Questions?** Check README.md or re-read this guide.

**Remember**: Start slow, learn continuously, and never risk more than you can afford to lose! 🚀
