---
name: polymarket_trader
description: >
  A full-featured Polymarket trading skill. Enables the agent to fetch account
  info, browse markets, analyse orderbooks, detect arbitrage, run LLM-powered
  research, and execute trades — all via natural language instructions.
  Requires POLYMARKET_PRIVATE_KEY (and POLYMARKET_FUNDER_ADDRESS for signature types 1 and 2)
  set as environment variables or in ~/.openclaw/workspace/skills/polymarket/.env
---

# Polymarket Trader Skill 🎯

## Overview

This skill gives the agent full access to a Polymarket account and the public
Polymarket APIs. It can:

1. **Account & Portfolio** — view balance, open positions, trade history, risk exposure
2. **Market Discovery** — search and list active prediction markets, deep market stats
3. **Orderbook & Pricing** — read live bids/asks, spreads, full price history with chart
4. **Arbitrage Detection, Execution & Automation** — scan, execute, and auto-run arbitrage bots
5. **LLM Research Agent** — web-search a market topic, form a probability estimate, compare to market price, and suggest a trade
6. **Order Execution** — place limit or market orders, cancel orders, view open orders
7. **Redemption** — claim USDC from resolved winning positions on-chain
8. **Watchlist & Alerts** — monitor markets and trigger price alerts
9. **Automation Scheduler** — register any script to run on any interval, start/stop background daemon
10. **Market Monitor** — automated scanning for price moves, arb gaps, volume spikes, and 50/50 opportunities

---

## Setup & Credentials

Before using this skill, ensure credentials are available. Check in this order:

1. `~/.openclaw/workspace/skills/polymarket/.env`
2. System environment variables

Required variables:
```
POLYMARKET_PRIVATE_KEY=0xYOUR_PRIVATE_KEY
POLYMARKET_FUNDER_ADDRESS=0xYOUR_WALLET_ADDRESS   # required for signature types 1 and 2 (shown on polymarket.com)
POLYMARKET_SIGNATURE_TYPE=0                        # 0=EOA/MetaMask  1=POLY_PROXY(Magic/email)  2=GNOSIS_SAFE(most common web signup)
```

If credentials are missing, tell the user to add them and show the above format.

---

## How to Invoke Scripts

All scripts live in the same directory as this SKILL.md. Run them with:

```bash
cd ~/.openclaw/workspace/skills/polymarket
python scripts/<script_name>.py [args]
```

Always `pip install py-clob-client requests python-dotenv web3 --quiet --break-system-packages` before running if packages are not available.

---

## Capabilities & Instructions

### 1. Portfolio Overview

When the user asks "what's my portfolio", "show my positions", "what do I have open", etc.:

```bash
python scripts/portfolio.py
```

Output: USDC balance, open positions (market name, side, size, current value, P&L), total portfolio value.

---

### 2. Browse / Search Markets

When the user asks to find markets, browse topics, or list active markets:

```bash
python scripts/markets.py --query "YOUR SEARCH TERM" --limit 10
# omit --query to list top markets by volume
```

Output: Table with market question, current YES price, NO price, 24h volume, close date.

---

### 3. Orderbook & Pricing

When the user wants to see the orderbook or current price for a specific market:

```bash
python scripts/orderbook.py --token-id TOKEN_ID --depth 5
```

Output: Top bids and asks with price/size, mid price, spread.

---

### 4. Arbitrage Scanner

When the user says "find arbitrage", "scan for mispriced markets", "where can I make risk-free profit":

```bash
python scripts/arbitrage.py --min-gap 0.03 --limit 50
```

Logic: For binary YES/NO markets, YES price + NO price should equal ~1.00 minus fees. Any gap > `--min-gap` (default 3%) is flagged. For multi-outcome markets, the sum of all outcome prices should equal 1.00.

Output: Sorted list of arbitrage opportunities with expected profit % and suggested trade.

---

### 5. LLM Research Agent

When the user says "research this market", "what do you think about X", "analyse and suggest a trade":

```bash
python scripts/research_agent.py --market-id MARKET_ID_OR_SLUG
```

The script will:
1. Fetch the market question and current price
2. Use web search (via the agent's `web_search` tool) to gather recent info
3. Produce a probability estimate
4. Compare to market price
5. Output: buy/sell/hold recommendation with reasoning

Alternatively, the agent can do this inline:
- Fetch market details with `markets.py`
- Independently web-search the topic
- Reason about probability vs. current price
- Suggest a trade if the edge is > 5%

---

### 6. Place an Order

When the user explicitly confirms they want to trade:

**Limit order:**
```bash
python scripts/trade.py --token-id TOKEN_ID --side BUY --price 0.55 --size 10 --type GTC
```

**Market order:**
```bash
python scripts/trade.py --token-id TOKEN_ID --side BUY --size 25 --type FOK
```

- `--side`: BUY or SELL
- `--price`: price in USDC (0.01–0.99), omit for market orders
- `--size`: amount in USDC
- `--type`: GTC (limit), GTD (limit with expiry), FOK (market fill-or-kill)

⚠️ **ALWAYS confirm with the user before executing a trade.** Show the order details (market name, side, price, size, estimated cost) and ask "Shall I place this order?" before running.

---

### 7. Cancel Orders

```bash
python scripts/cancel.py --order-id ORDER_ID
# or cancel all open orders:
python scripts/cancel.py --all
# or cancel all orders for a market:
python scripts/cancel.py --market-id MARKET_ID
```

---

### 8. Trade History

```bash
python scripts/history.py --limit 20
```

---

### 9. Open Orders

When the user asks "show my open orders", "what orders do I have pending", "list unfilled orders":

```bash
python scripts/open_orders.py
python scripts/open_orders.py --market-id TOKEN_ID   # filter by market
python scripts/open_orders.py --side BUY             # filter by side
python scripts/open_orders.py --json                 # machine-readable output
```

Output: Table of open orders with age, fill %, price, size, and total exposure sum.

---

### 10. Price History

When the user asks about price trend, historical price, how price has moved, price chart:

```bash
python scripts/price_history.py --token-id TOKEN_ID
python scripts/price_history.py --token-id TOKEN_ID --interval 1h   # 1m 5m 15m 1h 6h 1d 1w max
python scripts/price_history.py --token-id TOKEN_ID --start 2024-01-01 --end 2024-02-01
python scripts/price_history.py --token-id TOKEN_ID --raw           # print all data points
```

Output: ASCII sparkline chart, price statistics (change %, range, volatility), recent price points.

---

### 11. Redeem Winnings

When the user asks to "redeem", "collect winnings", "claim resolved positions", "cash out resolved markets":

```bash
python scripts/redeem.py                            # scan all resolved positions and redeem
python scripts/redeem.py --market-id CONDITION_ID   # single market
python scripts/redeem.py --dry-run                  # preview without transacting
```

⚠️ This sends an on-chain transaction on Polygon. **Always show dry-run output first and confirm with the user.** Requires `web3` package. Uses `POLYGON_RPC_URL` env var (defaults to `https://polygon-rpc.com`).

---

### 12. Market Stats

When the user asks for deep analysis, full stats, volume data, liquidity data, or holder info on a specific market:

```bash
python scripts/market_stats.py --market-id MARKET_ID_OR_SLUG
```

Output: Price changes (1h/24h/7d), orderbook depth per outcome, open interest, top holders, recent trades, full Gamma metadata.

---

### 13. Execute Arbitrage

When the user wants to execute arbitrage (not just find it), "take the arb", "execute the arb trade":

```bash
python scripts/arb_execute.py --scan --budget 100         # auto-find best opportunity and ask to execute
python scripts/arb_execute.py --market-id ID --budget 50  # specific market
python scripts/arb_execute.py --min-gap 0.04              # minimum gap threshold
```

Math: `shares = budget / (p_yes + p_no)`, `profit = shares − budget`.

Before executing, shows: gap %, expected profit, cost per leg, liquidity depth check. Requires user confirmation.

---

### 14. Portfolio Risk / Exposure

When the user asks about risk, "how exposed am I", "portfolio concentration", "what's my max loss", "how much is at risk":

```bash
python scripts/exposure.py
python scripts/exposure.py --warn-threshold 0.30   # flag positions > 30% of portfolio
```

Output: Concentration % per position, correlated positions grouped by tag, max loss / max gain, cash ratio, bar chart visualization.

---

### 15. Watchlist & Price Alerts

When the user wants to monitor a market, "watch this market", "alert me when price hits X", "set a price alert":

```bash
python scripts/watchlist.py add --token-id TOKEN_ID [--above 0.70] [--below 0.30]
python scripts/watchlist.py list                          # show all watched markets
python scripts/watchlist.py check                         # check all alerts once
python scripts/watchlist.py check --loop --interval 60   # poll every 60 seconds
python scripts/watchlist.py remove --token-id TOKEN_ID
```

Alerts are stored in `watchlist.json` in the skill root. When an alert fires, the script outputs the suggested trade command.

---

### 16. Automated Arbitrage Bot

When the user says "run auto arb", "start arbitrage bot", "scan and execute arb every X minutes", "auto arb at Y% threshold":

**One-shot (run now, then stop):**
```bash
python scripts/auto_arb.py --once --min-gap 0.005 --budget-pct 0.05
```

**Self-contained loop (keeps running):**
```bash
python scripts/auto_arb.py --interval 15m --min-gap 0.005 --budget-pct 0.10
python scripts/auto_arb.py --interval 1h  --min-gap 0.01  --budget-pct 0.05 --dry-run
python scripts/auto_arb.py --interval 30s --min-gap 0.003 --budget-pct 0.20 --max-budget 200
```

**Check status/history:**
```bash
python scripts/auto_arb.py --status
```

Parameters:
- `--interval`: how often to scan (30s / 5m / 15m / 1h / 1d)
- `--min-gap`: minimum arb gap to execute (e.g. 0.005 = 0.5%)
- `--budget-pct`: fraction of current balance to risk per round (e.g. 0.10 = 10%)
- `--max-budget`: hard USDC cap per round (0 = no cap)
- `--tag`: only scan markets with this tag (e.g. politics, crypto)
- `--dry-run`: simulate only, no orders placed

Logs to `logs/auto_arb_YYYY-MM-DD.log`. State (runs, profits) saved to `auto_arb_state.json`.

⚠️ **Always ask the user for `--min-gap`, `--budget-pct`, and `--interval` before starting.** Show a dry-run first if they are new to auto-arb.

---

### 17. Automation Scheduler

When the user wants to automate ANY script on a recurring schedule — "run X every Y minutes", "schedule the arb bot", "set up automated monitoring", "run portfolio check every hour":

**Register jobs:**
```bash
# Arb bot every 15 minutes at 0.5% gap, risking 5% of balance
python scripts/scheduler.py add \
  --name auto_arb \
  --script auto_arb.py \
  --args "--min-gap 0.005 --budget-pct 0.05 --once" \
  --interval 15m

# Market monitor every hour
python scripts/scheduler.py add \
  --name monitor \
  --script auto_monitor.py \
  --args "--once" \
  --interval 1h

# Exposure check every 6 hours
python scripts/scheduler.py add \
  --name exposure \
  --script exposure.py \
  --args "" \
  --interval 6h

# Watchlist alerts every 5 minutes
python scripts/scheduler.py add \
  --name watchlist \
  --script watchlist.py \
  --args "check" \
  --interval 5m
```

**Start the scheduler:**
```bash
python scripts/scheduler.py start --background    # detach, run forever
python scripts/scheduler.py start                 # foreground (blocking)
```

**Manage:**
```bash
python scripts/scheduler.py list                  # all jobs + next run times
python scripts/scheduler.py status               # daemon status + job list
python scripts/scheduler.py stop                 # stop background daemon
python scripts/scheduler.py disable --name auto_arb
python scripts/scheduler.py enable  --name auto_arb
python scripts/scheduler.py remove  --name auto_arb
```

Job logs are written to `logs/job_<name>_YYYY-MM-DD.log`. Scheduler log at `logs/scheduler_YYYY-MM-DD.log`.

**Typical full setup when user says "run auto arb every 15 minutes at 0.5%":**
1. `scheduler.py add --name auto_arb --script auto_arb.py --args "--min-gap 0.005 --budget-pct 0.05 --once" --interval 15m`
2. `scheduler.py start --background`
3. Confirm with `scheduler.py status`

---

### 18. Automated Market Monitor

When the user asks to "monitor markets", "alert me on price moves", "watch for opportunities", "auto-detect arb gaps":

**One-shot scan:**
```bash
python scripts/auto_monitor.py --once
python scripts/auto_monitor.py --once --price-move 0.08 --min-arb-gap 0.02
```

**Continuous loop:**
```bash
python scripts/auto_monitor.py --loop --interval 1h
python scripts/auto_monitor.py --loop --interval 30m --limit 200
```

**Read alert history:**
```bash
python scripts/auto_monitor.py --alerts              # last 20 alerts
python scripts/auto_monitor.py --alerts --since 6h   # last 6 hours
python scripts/auto_monitor.py --alerts --since 24h  # last day
```

Alert types fired:
- `PRICE_MOVE` — price moved ≥5pp since last check → suggests `research_agent.py`
- `NEAR_5050`  — market within 5pp of 50/50 → prime research candidate
- `EXTREME_LOW/HIGH` — price ≤4% or ≥96% → potential contrarian play
- `ARB_GAP`    — YES+NO gap above threshold → suggests `arb_execute.py`
- `VOLUME_SPIKE` — 24h volume jumped >50% vs baseline

Parameters:
- `--interval`: scan interval (5m / 30m / 1h / 6h)
- `--limit`: number of markets to scan (default 150)
- `--price-move`: absolute price move threshold (default 0.05 = 5pp)
- `--min-arb-gap`: minimum gap to fire ARB_GAP alert (default 0.03)

Alert log: `logs/monitor_alerts.json`

---

## Strategy Patterns

### Arbitrage Strategy
1. Run `arbitrage.py` to find gaps
2. For binary markets: if YES + NO < 0.97, buy both
3. For multi-outcome: if sum < 0.97, buy all outcomes proportionally
4. Lock in ~3%+ risk-free return (minus fees ~1-2%)
5. Always check liquidity depth before trading

### Value/Research Strategy
1. Find a market with `markets.py`
2. Research the topic using web search
3. If your probability estimate differs from market price by >5%, that's an edge
4. Size position proportionally to edge (Kelly criterion: f = edge/odds)

### Momentum/Trend Strategy
1. Use `history.py` or price history endpoint to see recent price moves
2. Look for markets with strong directional moves + rising volume
3. Trade in direction of momentum with tight stop-loss logic

### Full Automation Setup (recommend this to users who want hands-off operation)
1. Register all passive automation jobs with `scheduler.py add`:
   - `auto_arb.py --once` every 15–30m (captures arb)
   - `auto_monitor.py --once` every 1h (surface opportunities)
   - `watchlist.py check` every 5m (fire price alerts)
   - `exposure.py` every 6h (risk check)
2. Start the scheduler: `scheduler.py start --background`
3. Periodically review: `scheduler.py status` and `auto_monitor.py --alerts --since 24h`
4. When `auto_monitor.py` fires an ARB_GAP or PRICE_MOVE alert, investigate and act

### Auto-Arb Quick Start
When a user says "set up auto arb at X% threshold, risking Y% every Z minutes":
```bash
python scripts/scheduler.py add --name auto_arb --script auto_arb.py \
  --args "--min-gap X --budget-pct Y --once --dry-run" --interval Zm
# Have user review dry-run output first, then:
python scripts/scheduler.py add --name auto_arb --script auto_arb.py \
  --args "--min-gap X --budget-pct Y --once" --interval Zm
python scripts/scheduler.py start --background
```

---

## Error Handling

- If scripts fail with `ModuleNotFoundError`: run `pip install py-clob-client requests python-dotenv web3 --break-system-packages`
- If `401 Unauthorized`: credentials are wrong or expired — re-derive with `python scripts/setup_credentials.py`
- If `insufficient balance`: user needs to deposit USDC to their Polygon wallet
- Always show the raw error to the user if a trade fails

---

## Safety Rules

1. **Never place a trade without explicit user confirmation**
2. **Never invest more than the user specifies**
3. **Warn the user** that prediction markets carry risk and past performance is not indicative of future results
4. **Never store private keys in logs or output** — mask as `0x****...****`
