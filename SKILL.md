---
name: polymarket_trader
user-invocable: true
description: >
  A full-featured Polymarket trading skill. Enables the agent to fetch account
  info, browse markets, analyse orderbooks, detect arbitrage, run LLM-powered
  research, execute trades, and check geographic restrictions — all via natural language instructions.
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
11. **Geo-block Check** — verify whether your current IP is permitted to trade on Polymarket (official API, no credentials required)
12. **Trade Notifications** — all auto bots push open/close events with macOS desktop banners, optional Telegram push (`TELEGRAM_BOT_TOKEN` + `TELEGRAM_CHAT_ID`), and a persistent JSON log readable by the agent
13. **Master Supervisor** — `master_bot.py` runs all strategies as supervised subprocesses with auto crash-restart, heartbeat notifications, and a single STRATEGY_REGISTRY to register new strategies
14. **Automated Setup** — `setup_all.py` is an idempotent 8-step wizard that configures the entire skill from scratch in one command
15. **Emergency Stop** — `stopall.py` kills every running bot (3-layer: state-file PIDs + scheduler PID file + pgrep zombie scan) and activates the kill switch
15. **Input Guards** — `_guards.py` enforces hard minimum order sizes and API rate limits across all bots; mis-configured values are caught at startup before any order is placed
16. **Time Decay Arbitrage** — `time_decay.py` buys NO (FADE) when a market won't resolve YES before deadline, or buys YES (RUSH) when a near-certain outcome is still underpriced
17. **Logical Constraint Arb** — `logical_arb.py` detects implication and mutex violations across related markets (e.g. P(Trump wins primary) > P(Republican wins presidency)) and trades both legs
18. **Resolution Arbitrage** — `resolution_arb.py` captures guaranteed profit when YES+NO > 1 in markets within days of settlement
19. **News Latency Trading** — `news_latency.py` targets < 10 s from headline to order using an RSS-only path and a pre-cached keyword→market map
20. **Strategy Evaluator** — `strategy_evaluator.py` measures ROI/win-rate/Sharpe per strategy and can auto-disable underperformers in `master_state.json`

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

Optional variables:
```
NEWSAPI_KEY=                    # newsapi.org free-tier key — enriches news pipeline article metadata
POLYMARKET_PROXY=               # proxy URL to bypass geo-blocking (http://, https://, socks5://, socks5h://)
                                # Example — reverse SSH SOCKS5 tunnel:
                                #   ssh -D 1080 -N user@unrestricted-server
                                #   POLYMARKET_PROXY=socks5h://127.0.0.1:1080
                                # Routes ALL traffic: CLOB orders, Gamma API, Data API, geoblock check
TELEGRAM_BOT_TOKEN=             # Telegram bot token from @BotFather — enables Telegram push notifications
TELEGRAM_CHAT_ID=               # your Telegram chat or group ID (find via /getUpdates after messaging the bot)
                                # Verify: poly notify --test-telegram
```

If credentials are missing, tell the user to add them and show the above format.

---

## How to Invoke Skills

All capabilities are available through the `poly` CLI, installed at `~/.local/bin/poly`.

**In OpenClaw (slash command — calls the skill directly):**
```
/polymarket_trader <command> [args...]
```

**From any terminal or shell block:**
```bash
poly <command> [args...]
```

**See all commands:**
```bash
poly help
```

> **First-time setup:** `pip install py-clob-client requests python-dotenv web3 --quiet --break-system-packages`
> If `poly` is not found: `ln -sf ~/.openclaw/workspace/skills/polymarket/poly ~/.local/bin/poly`

---

## Capabilities & Instructions

### 1. Portfolio Overview

When the user asks "what's my portfolio", "show my positions", "what do I have open", etc.:

```bash
poly portfolio
```

Output: USDC balance, open positions (market name, side, size, current value, P&L), total portfolio value.

---

### 2. Browse / Search Markets

When the user asks to find markets, browse topics, or list active markets:

```bash
poly markets --query "YOUR SEARCH TERM" --limit 10
# omit --query to list top markets by volume
```

Output: Table with market question, current YES price, NO price, 24h volume, close date.

---

### 3. Orderbook & Pricing

When the user wants to see the orderbook or current price for a specific market:

```bash
poly orderbook --token-id TOKEN_ID --depth 5
```

Output: Top bids and asks with price/size, mid price, spread.

---

### 4. Arbitrage Scanner

When the user says "find arbitrage", "scan for mispriced markets", "where can I make risk-free profit":

```bash
poly arb --min-gap 0.03 --limit 50
```

Logic: For binary YES/NO markets, YES price + NO price should equal ~1.00 minus fees. Any gap > `--min-gap` (default 3%) is flagged. For multi-outcome markets, the sum of all outcome prices should equal 1.00.

Output: Sorted list of arbitrage opportunities with expected profit % and suggested trade.

---

### 5. LLM Research Agent

When the user says "research this market", "what do you think about X", "analyse and suggest a trade":

```bash
poly research --market-id MARKET_ID_OR_SLUG
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

**Before placing — run a preflight check first:**
```bash
poly trade --token-id TOKEN_ID --side BUY --price 0.55 --size 10 --dry-run
```
This verifies credentials, balance, market status, and geoblock access **without submitting anything**.
Run this whenever the user asks "can I trade?", "am I blocked?", or "do I have enough balance?"

**Limit order (GTC — default):**
```bash
poly trade --token-id TOKEN_ID --side BUY --price 0.55 --size 10 --type GTC
```

**Limit with expiry (GTD):**
```bash
poly trade --token-id TOKEN_ID --side SELL --price 0.70 --size 5 --type GTD --expiry 3600
```

- `--side`: BUY or SELL
- `--price`: price in USDC (0.01–0.99)
- `--size`: amount in USDC
- `--type`: GTC (default, good-till-cancelled) or GTD (good-till-date, min 60s expiry)
- `--dry-run`: preflight only — checks credentials, balance, market active, geoblock, local signing

> **Note:** Polymarket enforces a minimum 1-minute order lifetime. FOK (fill-or-kill) and immediate market orders are not supported — all orders rest on the book.

⚠️ **ALWAYS confirm with the user before executing a trade.** Show the order details (market name, side, price, size, estimated cost) and ask "Shall I place this order?" before running.

---

### 7. Cancel Orders

```bash
poly cancel --order-id ORDER_ID
# or cancel all open orders:
poly cancel --all
# or cancel all orders for a market:
poly cancel --market-id MARKET_ID
```

---

### 8. Trade History

```bash
poly history --limit 20
```

---

### 9. Open Orders

When the user asks "show my open orders", "what orders do I have pending", "list unfilled orders":

```bash
poly open-orders
poly open-orders --market-id TOKEN_ID   # filter by market
poly open-orders --side BUY             # filter by side
poly open-orders --json                 # machine-readable output
```

Output: Table of open orders with age, fill %, price, size, and total exposure sum.

---

### 10. Price History

When the user asks about price trend, historical price, how price has moved, price chart:

```bash
poly price --token-id TOKEN_ID
poly price --token-id TOKEN_ID --interval 1h   # 1m 5m 15m 1h 6h 1d 1w max
poly price --token-id TOKEN_ID --start 2024-01-01 --end 2024-02-01
poly price --token-id TOKEN_ID --raw           # print all data points
```

Output: ASCII sparkline chart, price statistics (change %, range, volatility), recent price points.

---

### 11. Redeem Winnings

When the user asks to "redeem", "collect winnings", "claim resolved positions", "cash out resolved markets":

```bash
poly redeem                            # scan all resolved positions and redeem
poly redeem --market-id CONDITION_ID   # single market
poly redeem --dry-run                  # preview without transacting
```

⚠️ This sends an on-chain transaction on Polygon. **Always show dry-run output first and confirm with the user.** Requires `web3` package. Uses `POLYGON_RPC_URL` env var (defaults to `https://polygon-rpc.com`).

---

### 12. Market Stats

When the user asks for deep analysis, full stats, volume data, liquidity data, or holder info on a specific market:

```bash
poly stats --market-id MARKET_ID_OR_SLUG
```

Output: Price changes (1h/24h/7d), orderbook depth per outcome, open interest, top holders, recent trades, full Gamma metadata.

---

### 13. Execute Arbitrage

When the user wants to execute arbitrage (not just find it), "take the arb", "execute the arb trade":

```bash
poly arb-exec --scan --budget 100         # auto-find best opportunity and ask to execute
poly arb-exec --market-id ID --budget 50  # specific market
poly arb-exec --min-gap 0.04              # minimum gap threshold
```

Math: `shares = budget / (p_yes + p_no)`, `profit = shares − budget`.

Before executing, shows: gap %, expected profit, cost per leg, liquidity depth check. Requires user confirmation.

---

### 14. Portfolio Risk / Exposure

When the user asks about risk, "how exposed am I", "portfolio concentration", "what's my max loss", "how much is at risk":

```bash
poly exposure
poly exposure --warn-threshold 0.30   # flag positions > 30% of portfolio
```

Output: Concentration % per position, correlated positions grouped by tag, max loss / max gain, cash ratio, bar chart visualization.

---

### 15. Watchlist & Price Alerts

When the user wants to monitor a market, "watch this market", "alert me when price hits X", "set a price alert":

```bash
poly watch add --token-id TOKEN_ID [--above 0.70] [--below 0.30]
poly watch list                          # show all watched markets
poly watch check                         # check all alerts once
poly watch check --loop --interval 60   # poll every 60 seconds
poly watch remove --token-id TOKEN_ID
```

Alerts are stored in `watchlist.json` in the skill root. When an alert fires, the script outputs the suggested trade command.

---

### 16. Automated Arbitrage Bot

When the user says "run auto arbitrage", "start arbitrage bot", "scan and execute arb every X minutes", "auto arbitrage at Y% threshold":

**One-shot (run now, then stop):**
```bash
poly auto-arb --once --min-gap 0.005 --budget-pct 0.05
```

**Self-contained loop (keeps running):**
```bash
poly auto-arb --interval 15m --min-gap 0.005 --budget-pct 0.10
poly auto-arb --interval 1h  --min-gap 0.01  --budget-pct 0.05 --dry-run
poly auto-arb --interval 30s --min-gap 0.003 --budget-pct 0.20 --max-budget 200
```

**Check status/history:**
```bash
poly auto-arb --status
```

Parameters:
- `--interval`: how often to scan (30s / 5m / 15m / 1h / 1d)
- `--min-gap`: minimum arb gap to execute (e.g. 0.005 = 0.5%)
- `--budget-pct`: fraction of current balance to risk per round (e.g. 0.10 = 10%)
- `--max-budget`: hard USDC cap per round (default 1; 0 = no cap)
- `--tag`: only scan markets with this tag (e.g. politics, crypto)
- `--dry-run`: simulate only, no orders placed

Logs to `logs/auto_arbitrage_YYYY-MM-DD.log`. State (runs, profits) saved to `auto_arbitrage_state.json`.

⚠️ **Always ask the user for `--min-gap`, `--budget-pct`, and `--interval` before starting.** Show a dry-run first if they are new to auto arbitrage.

---

### 17. Automation Scheduler

When the user wants to automate ANY script on a recurring schedule — "run X every Y minutes", "schedule the arb bot", "set up automated monitoring", "run portfolio check every hour":

**Register jobs:**
```bash
# Auto arbitrage bot every 15 minutes at 0.5% gap, risking 5% of balance
poly schedule add \
  --name auto_arbitrage \
  --script auto_arbitrage.py \
  --args "--min-gap 0.005 --budget-pct 0.05 --once" \
  --interval 15m

# Market monitor every hour
poly schedule add \
  --name monitor \
  --script auto_monitor.py \
  --args "--once" \
  --interval 1h

# Exposure check every 6 hours
poly schedule add \
  --name exposure \
  --script exposure.py \
  --args "" \
  --interval 6h

# Watchlist alerts every 5 minutes
poly schedule add \
  --name watchlist \
  --script watchlist.py \
  --args "check" \
  --interval 5m
```

**Start the scheduler:**
```bash
poly schedule start --background    # detach, run forever
poly schedule start                 # foreground (blocking)
```

**Manage:**
```bash
poly schedule list                  # all jobs + next run times
poly schedule status               # daemon status + job list
poly schedule stop                 # stop background daemon
poly schedule disable --name auto_arbitrage
poly schedule enable  --name auto_arbitrage
poly schedule remove  --name auto_arbitrage
```

Job logs are written to `logs/job_<name>_YYYY-MM-DD.log`. Scheduler log at `logs/scheduler_YYYY-MM-DD.log`.

**Typical full setup when user says "run auto arbitrage every 15 minutes at 0.5%":**
1. `scheduler.py add --name auto_arbitrage --script auto_arbitrage.py --args "--min-gap 0.005 --budget-pct 0.05 --once" --interval 15m`
2. `scheduler.py start --background`
3. Confirm with `scheduler.py status`

---

### 18. Automated Market Monitor

When the user asks to "monitor markets", "alert me on price moves", "watch for opportunities", "auto-detect arb gaps":

**One-shot scan:**
```bash
poly monitor --once
poly monitor --once --price-move 0.08 --min-arb-gap 0.02
```

**Continuous loop:**
```bash
poly monitor --loop --interval 1h
poly monitor --loop --interval 30m --limit 200
```

**Read alert history:**
```bash
poly monitor --alerts              # last 20 alerts
poly monitor --alerts --since 6h   # last 6 hours
poly monitor --alerts --since 24h  # last day
```

Alert types fired:
- `PRICE_MOVE` — price moved ≥5pp since last check → suggests `research_agent.py`
- `NEAR_5050`  — market within 5pp of 50/50 → prime research candidate
- `EXTREME_LOW/HIGH` — price ≤4% or ≥96% → potential contrarian play
- `ARB_GAP`    — YES+NO gap above threshold → suggests `arbitrage_execute.py`
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
   - `auto_arbitrage.py --once` every 15–30m (captures arb)
   - `auto_monitor.py --once` every 1h (surface opportunities)
   - `watchlist.py check` every 5m (fire price alerts)
   - `exposure.py` every 6h (risk check)
2. Start the scheduler: `scheduler.py start --background`
3. Periodically review: `scheduler.py status` and `auto_monitor.py --alerts --since 24h`
4. When `auto_monitor.py` fires an ARB_GAP or PRICE_MOVE alert, investigate and act

### Auto Arbitrage Quick Start
When a user says "set up auto arbitrage at X% threshold, risking Y% every Z minutes":
```bash
poly schedule add --name auto_arbitrage --script auto_arbitrage.py \
  --args "--min-gap X --budget-pct Y --once --dry-run" --interval Zm
# Have user review dry-run output first, then:
poly schedule add --name auto_arbitrage --script auto_arbitrage.py \
  --args "--min-gap X --budget-pct Y --once" --interval Zm
poly schedule start --background
```

---

## 19. execution_simulator.py — Slippage Estimation & Optimal Sizing

**Purpose**: Simulate an order against the live orderbook before placing it.
Estimates average fill price, slippage, and whether the trade is still profitable
after fees. Also finds the optimal order size for a given edge.

**Decision rule**: `net = edge - slippage - fees`. If `net >= min_net_profit` → TRADE; else → SKIP.

**When to use**:
- Any time you're about to place a large order and want to know what fill price to expect
- Before executing arbitrage: "is the edge big enough to survive the slippage?"
- When a user asks "how much slippage will I get?"
- Imported by other scripts (`auto_arbitrage.py`, `correlation_arbitrage.py`) automatically

**Commands**:
```bash
poly simulate --token-id TOKEN --size 50 --edge 0.07
poly simulate --token-id TOKEN --size 100 --edge 0.05 --side SELL
poly simulate --token-id TOKEN --optimal-size --edge 0.06 --budget 200
poly simulate --token-id TOKEN --size 50 --edge 0.07 --json
```

**Output**: Slippage %, average fill price, fill breakdown by price level, decision: TRADE or SKIP.

---

## 20. correlation_arbitrage.py — Cross-Market Correlated-Pair Arbitrage

**Purpose**: Find and exploit pricing gaps between logically linked markets.
Examples: "Trump wins election" ↔ "Republican wins election"; "Fed raises in March" ↔ "Fed raises in Q1".
If YES(A) + NO(B) < 1.0, buying both guarantees profit (assuming A and B are truly equivalent).

**When to use**:
- When user asks about "correlation arbitrage", "cross-market arbitrage", or "linked market gaps"
- Broader opportunity set than single-market arb — usually more gaps available
- Pairs `--once` with `scheduler.py` for continuous scanning

**Commands**:
```bash
poly corr-arb --scan                    # scan all detected pairs
poly corr-arb --scan --min-edge 0.03    # 3%+ net edge only
poly corr-arb --scan --tag politics      # filter by tag
poly corr-arb --scan --execute --budget 100  # execute best gap
poly corr-arb --graph                   # print full correlation graph
poly corr-arb --once                    # single-shot for scheduler
```

**Arguments**:
- `--min-edge` float (default 0.03): minimum net profit threshold
- `--limit` int (default 150): number of markets to scan
- `--tag` str: restrict to a Gamma API tag (politics, crypto, etc.)
- `--execute`: execute the best opportunity found
- `--budget` float: USDC for execution (default 1)
- `--confirm`: skip interactive confirmation prompt
- `--json`: raw JSON output

---

## 21. news_trader.py — News-Driven Probability Trading (4-layer pipeline)

**Purpose**: Full event-driven trading pipeline. Ingests GDELT + NewsAPI + RSS feeds,
deduplicates stories by fingerprint, clusters near-identical reports, maps each cluster to
active Polymarket markets, scores impact on 5 factors, and gates execution on edge vs
orderbook slippage.

**Pipeline layers** (in `scripts/news/`):
- `sources/gdelt.py` — GDELT DOC 2.0 API (no API key, ~15-min index lag)
- `sources/newsapi.py` — NewsAPI.org articles (free key: 100 req/day)
- `sources/rss.py` — 15 default high-trust RSS feeds (White House, Fed, Reuters, AP, etc.)
- `normalize.py` — fingerprint dedup + source trust weights (~60 domains)
- `cluster.py` — Jaccard token-set clustering; one representative per event
- `mapper.py` — keyword extraction + Gamma API search → story↔market relevance
- `score.py` — 5-factor impact: trust × novelty × relevance × specificity × urgency
- `pipeline.py` — orchestrate all layers; slippage gate via `execution_simulator`

**When to use**:
- When user asks to "trade on news", "monitor news feeds", or "event-driven trading"
- When user wants real-time probability shift detection
- Pairs with `scheduler.py --once` every 3–5 minutes

**Commands**:
```bash
poly news --once                          # single pipeline cycle
poly news --loop --interval 5             # poll every 5 minutes
poly news --loop --interval 5 --dry-run   # simulate only
poly news --sources                        # list active RSS feeds
poly news --add-source "URL" --source-label "Name" --source-trust 0.8
poly news --history --limit 20            # show recent trades
poly news --history --json                # JSON output
```

**Key arguments**:
- `--budget` float (default 1): USDC per trade
- `--min-edge` float (default 0.06): minimum estimated price gap to trade
- `--min-relevance` float (default 0.15): minimum story↔market token overlap
- `--min-impact` float (default 0.15): minimum 5-factor impact score
- `--safety-buffer` float (default 0.02): extra edge required above fees+slippage
- `--max-age` float (default 60): max story age in minutes
- `--newsapi-key` str: NewsAPI.org key (or set `NEWSAPI_KEY` env var)
- `--skip-slippage`: bypass execution_simulator gate

**State files**: `news_trader_state.json` (seen IDs, trade log), `news_sources.json` (feed URLs).
**GDELT**: free, no key, covers 65+ languages. Best for breaking political/macro events.
**NewsAPI**: optional. Set `NEWSAPI_KEY` in `.env` for richer article metadata.

---

## 22. market_maker.py — Automated Market Making

**Purpose**: Earn the bid-ask spread by posting a bid slightly below mid and an ask slightly
above mid. When both sides fill, profit ≈ spread minus fees. Inventory control adjusts
quote sizes when net position becomes skewed to avoid directional risk.

**Best target markets**: High 24h volume AND near-50/50 price (tightest natural spread).

**When to use**:
- When user asks to "make markets", "earn the spread", or "provide liquidity"
- When user asks for passive income from Polymarket activity

**Commands**:
```bash
poly mm --scan-targets                  # find best markets to make
poly mm --market-id TOKEN               # make a specific token (auto-params)
poly mm --market-id TOKEN --spread 0.02 --size 10 --max-inventory 50
poly mm --once                          # single quote refresh
poly mm --loop --interval 30            # refresh every 30s
poly mm --status                        # inventory + active orders
poly mm --close --market-id TOKEN       # cancel all quotes
```

**Arguments**:
- `--spread` float (default 0.02): total spread as fraction (0.02 = 2%)
- `--size` float (default 1): USDC per side per quote
- `--max-inventory` float (default 50): max net YES exposure before skewing quotes
- `--interval` float (default 30): seconds between quote refreshes

**State file**: `market_maker_state.json` (inventory, fill count, P&L estimate per token).

---

## 23. ai_automation.py — AI Signal Generation

**Purpose**: Systematically researches Polymarket's top markets and produces structured
buy/sell signals. Applies momentum, volume, and mean-reversion heuristics (designed as
a plug-in slot for real LLM analysis in an OpenClaw context). Saves signals to
`ai_signals.json` consumed by `omni_strategy.py` and other scripts.

**Signal schema**: `{ direction: YES|NO|PASS, confidence: 0-1, edge_estimate: 0-1, rationale: "..." }`

**When to use**:
- When user asks for "AI-driven trading", "automated analysis", or "buy/sell signals"
- As a scheduled job alongside `auto_arbitrage.py` for full automation

**Commands**:
```bash
poly signals --once                          # research top 20 markets
poly signals --research-top 50 --once        # scan top 50
poly signals --signals                        # print current signals
poly signals --once --execute --min-confidence 0.7  # execute top signals
poly signals --loop --interval 30            # refresh every 30 min
```

**Arguments**:
- `--research-top` int (default 20): markets to analyze per run
- `--min-edge` float (default 0.03): minimum edge to generate a signal
- `--min-confidence` float (default 0.60): minimum confidence to execute
- `--budget` float (default 1): USDC per executed signal

**State file**: `ai_signals.json`

---

## 24. omni_strategy.py — All-in-One Strategy Orchestrator

**Purpose**: Launches ALL strategies simultaneously as background subprocesses with a
single command. Splits a total USDC budget across strategies, monitors process health,
and aggregates P&L from all strategy state files.

**When to use**:
- When user asks to "run everything", "start all strategies", or "go full auto"
- Best starting point for a user who wants a fully automated Polymarket account

**Commands**:
```bash
poly omni --start --budget 1000          # start all, $1000 total
poly omni --start --budget 1000 --dry-run
poly omni --start --split "arb:30,corr:25,mm:25,news:10,ai:10"
poly omni --start --only "arb,mm"        # subset of strategies
poly omni --once                         # one cycle of all, then exit
poly omni --status                        # running processes + PIDs
poly omni --pnl                           # combined P&L report
poly omni --stop                          # terminate all
```

**Budget aliases for --split**: `arb` = auto_arbitrage, `corr` = correlation_arbitrage,
`mm` = market_maker, `news` = news_trader, `ai` = ai_automation.

**State file**: `omni_state.json` (PIDs, budgets, start times).
**Logs**: `logs/omni_<strategy>_<date>.log` for each running strategy.

---

## 25. backtest.py — Historical Signal Backtesting

**Purpose**: Fetch Polymarket price history for recently resolved markets and replay
momentum or mean-reversion signals to measure expected performance before risking
live capital. Reports hit rate, total PnL, Sharpe ratio, and max drawdown.

**When to use**:
- When user says "test this strategy", "how would X have done", or "backtest momentum"
- Before turning on a new automation to validate expected edge
- When comparing strategies to decide on capital allocation

**Commands**:
```bash
poly backtest --strategy momentum --limit 25
poly backtest --strategy mean-revert --limit 25 --tag politics
poly backtest --token-id TOKEN_ID --strategy momentum
poly backtest --start 2024-06-01 --position-size 20
poly backtest --results                          # show last saved run
poly backtest --results --json                   # machine-readable
```

**Arguments**:
- `--strategy` (momentum|mean-revert): signal logic to apply
- `--limit` int (default 25): number of resolved markets to test
- `--tag` str: filter by Gamma tag (politics, crypto, sports…)
- `--start` YYYY-MM-DD: ignore history before this date
- `--position-size` float (default 10): simulated USD per trade
- `--fidelity` int (default 3600): price bar size in seconds

**State file**: `backtest_results.json`

---

## 26. eval.py — Post-Resolution Evaluation Loop

**Purpose**: After markets resolve, score every signal and trade OpenPoly generated
against the actual outcome. Tracks hit rate by source (news/AI/arb), signal
direction accuracy, and which strategies made money. Builds a running evaluation
log to measure improvement over time.

**When to use**:
- After markets close: "how accurate were my signals this week?"
- When user asks "are the news signals actually working?"
- To diagnose which strategies are producing alpha vs noise
- Run weekly alongside the scheduler to maintain an ongoing feedback loop

**Commands**:
```bash
poly eval                     # evaluate all pending signals
poly eval --since 7d          # last 7 days only
poly eval --source news        # filter by source (news|ai|arb|all)
poly eval --report             # print full accuracy report from saved log
poly eval --report --json      # machine-readable report
poly eval --reset              # clear eval_log.json and start fresh
```

**State files read**: `news_trader_state.json`, `ai_signals.json`, `auto_arbitrage_state.json`
**State file written**: `eval_log.json`

**Output**: hit rate by source, per-signal hit/miss table, overall accuracy trend.

---

## 27. risk_guard.py — Daily Loss Limits + Kill Switch

**Purpose**: Safety layer that enforces: max daily loss (as % of day-start balance),
max single position size, max open orders, and a manual kill switch. Importable
by other scripts so they can check limits before placing any order.

**When to use**:
- When user wants to set a loss limit: "stop trading if I lose 5% in a day"
- When user wants to pause all trading: "halt everything"
- After a loss event: check status and reset when ready to resume
- Proactively: set limits before running any automation

**Key limits (configurable)**:
- `max_daily_loss_pct` (default 5%): auto-fires kill switch when breached
- `max_position_pct` (default 20%): max trade size as fraction of balance
- `max_open_orders` (default 50): cap on simultaneously open orders

**Commands**:
```bash
poly risk                                        # show current risk status
poly risk status                                 # same
poly risk kill                                   # activate kill switch (halt all trading)
poly risk reset                                  # clear kill switch, start new day
poly risk set --max-daily-loss 0.05              # configure 5% daily loss limit
poly risk set --max-position-pct 0.20            # max 20% of balance per trade
poly risk set --max-open-orders 20               # cap at 20 open orders
poly risk record --pnl -12.50 --balance 500      # log a trade's PnL
poly risk history                                # last 30 days PnL history
poly risk check --size 50 --balance 400          # check if a trade is allowed
```

**Importable API** (used by other strategy scripts):
```python
from risk_guard import check_limits, is_killed

ok, reason = check_limits(trade_size_usd=50, current_balance=400)
if not ok:
    print(f"Trade blocked: {reason}")
    return
```

**State file**: `risk_state.json`

---

## 28. db.py — SQLite Data Layer

**Purpose**: Unified SQLite store (`openpoly.db`) that replaces scattered JSON state files.
Persists articles, trade signals, executed trades, resolved outcomes, and market metadata.
Also scores each signal against known outcomes to build per-source accuracy statistics that
feed the probability model.

**When to use**:
- When user asks "what trades have I made?", "what's my signal history?", "how accurate have my news signals been?"
- Before running an eval cycle — migrate existing JSON files first
- When debugging — `poly db status` shows all row counts instantly

**Commands**:
```bash
poly db status               # row counts for all tables
poly db migrate              # absorb JSON state files → DB
poly db vacuum               # reclaim disk space
poly db schema               # print CREATE TABLE statements
poly db articles [--limit N] # recent ingested news articles
poly db signals  [--limit N] # recent trade signals
poly db trades   [--limit N] # recent executed trades
poly db outcomes [--limit N] # resolved market outcomes
poly db accuracy             # per-source hit rate (only sources with ≥5 scored signals)
```

**Importable API**:
```python
from db import DB

with DB() as db:
    db.insert_signal(source="news", market_id="0xabc", direction="YES",
                     confidence=0.72, edge_estimate=0.09)
    signals = db.recent_signals(limit=20, market_id="0xabc")
    accuracy = db.accuracy_by_source()

# accuracy → {"news": {"hit": 14, "miss": 6, "hit_rate": 0.70}, ...}
```

**Schema**: `articles`, `signals`, `trades`, `outcomes`, `signal_outcomes`, `markets_cache`

**State file**: `openpoly.db` (WAL mode, single-writer, safe to read concurrently)

---

## 29. prob_model.py — Calibrated Probability Estimation

**Purpose**: Converts available market data and recent signals into a **calibrated fair probability**
before Kelly sizing. Uses the current market price as a Bayesian prior, then updates it with
news/AI/arb signals weighted by their historical accuracy (from `db.py`). Applies shrinkage toward
the market price when signal evidence is thin, exponential time-decay on old signals, and outputs
a full factor breakdown.

**When to use**:
- When user asks "what's the fair value of X?", "is there edge in this market?", "how much should I bet?"
- Before placing any sizeable trade — run `poly prob` first to sanity-check the edge
- When calibrating signal quality: "are my news signals actually adding alpha?"

**Output fields**:
| Field | Meaning |
|---|---|
| `fair_prob` | Calibrated P(YES) after all signal updates |
| `market_price` | Current mid-price (consensus) |
| `edge` | `fair_prob − market_price` (positive = BUY YES) |
| `direction` | Which token to buy (YES or NO) |
| `kelly_full` | Full Kelly fraction (theoretical maximum) |
| `kelly_quarter` | Quarter-Kelly (recommended; more conservative) |
| `suggested_size` | USDC amount (quarter-Kelly × balance) |
| `confidence` | 0–1 trust in estimate (more signals = higher) |
| `factors` | Per-signal breakdown: source, prior→posterior shift |

**Commands**:
```bash
poly prob --market-id ID                         # basic estimate (fetches live price)
poly prob --market-id ID --balance 500           # include Kelly sizing
poly prob --market-id ID --show-signals          # per-signal factor breakdown
poly prob --market-id ID --json                  # machine-readable output
poly prob --market-id ID --save                  # save estimate to DB signals table
poly prob --market-id ID --max-age 24            # only use signals < 24 hours old
```

**Importable API**:
```python
from prob_model import estimate

result = estimate(
    market_id="0xabc...",
    balance=500,
    max_age_hours=48,
    extra_signals=[{"source": "manual", "direction": "YES", "confidence": 0.8,
                    "created_at": time.time()}],
)

print(result["fair_prob"])        # 0.61
print(result["edge"])             # 0.09
print(result["kelly_quarter"])    # 0.045
print(result["suggested_size"])   # 22.50  (USDC)
```

**Algorithm**:
1. Fetch market mid-price from CLOB → use as Bayesian prior P(YES)
2. Load recent signals from DB (falling back to JSON state files)
3. Pull per-source hit rates from DB → convert to calibration weights
4. For each signal: Bayesian update scaled by source credibility × time decay
5. Shrink toward market price proportional to N_signals / (N_signals + 4)
6. Compute Kelly: `f* = (p×b − q) / b` where `b = (1−price) / price`

---

## 30. geoblock.py — Geographic Restriction Check

**Purpose**: Check whether your current IP address is permitted to trade on Polymarket.
Uses the official `GET https://polymarket.com/api/geoblock` endpoint — no credentials required.
Returns exact country/region and a clear blocked / close-only / ok status.

**When to use**:
- When user asks "am I geo-blocked?", "can I trade from here?", "is my location blocked?"
- Before starting any bot, to ensure the region is permitted
- When a trade fails with HTTP 403 or 451

**Status meanings**:
| Status | Meaning |
|---|---|
| `ok` | Trading fully permitted from your IP |
| `close_only` | Can close existing positions only (PL, SG, TH, TW) |
| `blocked` | Region is restricted — no trading allowed |

> **Geo-bypass**: Set `POLYMARKET_PROXY=socks5h://127.0.0.1:1080` (or any HTTP/SOCKS5 proxy) in `.env` to route the geoblock check — and all subsequent trades — through that proxy. Useful when travelling or accessing from a restricted region via a reverse SSH tunnel.

**Commands**:
```bash
poly geoblock          # check and print result
poly geoblock --json   # machine-readable {blocked, ip, country, region}
```

**Aliases**: `poly geo` · `poly blocked` · `poly geo-check`

**Blocked countries** (partial list): AU, BE, DE, FR, GB, IR, IT, NL, RU, US and others.
Full list: https://docs.polymarket.com/api-reference/geoblock

---

## 31. notifier.py — Trade Notifications

**Purpose**: Central notification hub called by every auto bot when it opens or closes a trade.
Fires a macOS Notification Center banner, appends a structured record to `logs/trade_notifications.json`,
and prints a `🔔` summary line to stdout / log files.
Optionally forwards every event to **Telegram** if `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` are set in `.env`.
All hooks are wrapped in `try/except` — a notification failure will never crash a live bot.

**Bots that push notifications**:
| Bot | Events pushed |
|---|---|
| `auto_arbitrage` | Trade opened (arb legs placed) |
| `news_trader` | Trade opened (order placed) |
| `ai_automation` | Trade opened (signal executed) |
| `market_maker` | Trade opened (quotes placed) + trade closed (SELL fill detected with P&L) |
| `correlation_arbitrage` | Trade opened (hedge legs placed) |

**When to use**:
- When user asks "what trades have the bots made?", "show recent bot activity", "did any bots trade?"
- To review trade history from automated strategies
- To check P&L from market_maker fills

**Commands**:
```bash
poly notify                        # last 20 notifications
poly notify --limit 50             # more history
poly notify --since 2h             # last 2 hours (also: 30m, 1d)
poly notify --bot auto_arbitrage   # filter by bot
poly notify --event trade_opened   # filter by event type
poly notify --json                 # raw JSON output
poly notify --clear                # wipe history
poly notify --test-telegram        # send test message to verify Telegram credentials
```

**Telegram setup** (optional):
1. Message `@BotFather` on Telegram → `/newbot` → copy the token
2. Message your new bot once, then visit `https://api.telegram.org/bot<TOKEN>/getUpdates` — copy the `id` from `result[0].message.chat.id`
3. Add to `.env`: `TELEGRAM_BOT_TOKEN=...` and `TELEGRAM_CHAT_ID=...`
4. Verify with `poly notify --test-telegram`

Works with personal chats and group chats. Works through `POLYMARKET_PROXY` if set.

**Aliases**: `poly notifs` · `poly notifications` · `poly trades`

**Notification record schema**:
```json
{
  "id":         "a1b2c3d4e5f6",
  "ts":         "2026-03-10T09:30:00+00:00",
  "event":      "trade_opened",
  "bot":        "auto_arbitrage",
  "market":     "Will the Fed cut rates in March?",
  "market_id":  "0xabc...",
  "direction":  "ARB",
  "amount_usd": 50.0,
  "price":      null,
  "pnl_est":    null,
  "order_ids":  ["order-aaa", "order-bbb"],
  "legs":       2,
  "gap_pct":    1.5,
  "profit_est_usd": 0.23
}
```

**Log file**: `logs/trade_notifications.json` (capped at 2000 records)

---

## 32. master_bot.py — Master Supervisor

**Purpose**: True all-in-one supervised runner. Spawns every registered strategy as a subprocess, monitors health, auto-restarts crashes, sends heartbeat + lifecycle notifications to OpenClaw, and honours the kill switch.

Prefer this over `omni_strategy.py` for production use.

**Commands**:
```bash
poly master --start --budget 1000           # start all strategies splitting $1000
poly master --start --budget 500 --dry-run  # dry run (no real orders)
poly master --start --only arb,mm,news      # subset via alias names
poly master --once                          # run one cycle of each, then exit
poly master --status                        # show each strategy's process state
poly master --pnl                           # combined P&L across all strategies
poly master --stop                          # gracefully stop all subprocesses
poly master --list-strategies              # list registry with aliases + budget %
poly master --heartbeat 60                  # custom heartbeat interval (minutes)
poly master --evaluate                      # performance report + recommendations
```

**Aliases**: `poly bot` · `poly supervisor` · `poly run-all` · `poly master-bot`

**STRATEGY_REGISTRY** (single source of truth — edit when adding a new strategy):
Location: `scripts/master_bot.py`, top-level `STRATEGY_REGISTRY` dict.
Each entry defines: `script`, `loop_flags`, `once_flags`, `budget_flag`, `budget_pct`, `alias`, `description`.

To add a new strategy:
1. Open `scripts/master_bot.py`
2. Add a new key to `STRATEGY_REGISTRY` following the template in the `# Add new strategies below this line` comment
3. Set `budget_pct` so all entries total ≤ 100
4. `master_bot` will automatically supervise it, restart on crash, include it in `--status` and `--pnl`

**Current registry**:
| Name | Alias | Budget % | Description |
|---|---|---|---|
| `auto_arbitrage` | `arb` | 25% | YES/NO same-market arbitrage |
| `correlation_arbitrage` | `corr` | 10% | Cross-market correlated-pair arb |
| `market_maker` | `mm` | 15% | Bid/ask spread capture |
| `news_trader` | `news` | 10% | News-driven momentum trades |
| `ai_automation` | `ai` | 5% | AI/heuristic signal trading |
| `time_decay` | `td`, `decay` | 15% | Resolution-timing FADE/RUSH edge |
| `logical_arb` | `la`, `logic` | 10% | Logical constraint violation arb |
| `resolution_arb` | `res`, `resarb` | 5% | Near-settlement YES+NO>1 arb |
| `news_latency` | `nl`, `fast-news` | 5% | Sub-10s RSS news trading |
| `auto_monitor` | `mon`, `monitor` | 0% | Market anomaly alerts (no trading) |

**Restart behaviour**: up to `MAX_RESTARTS=5` per strategy with `RESTART_DELAY=10s`. After 5 failures the strategy is abandoned and an OpenClaw notification is sent.

**Heartbeat**: every `HEARTBEAT_MIN=30` minutes (overridable with `--heartbeat N`) a system_event notification is pushed with live status of all strategies.

**Lifecycle notifications** (via `notify_event`):
- `master_bot started` — all strategies spawned
- `strategy restarted` — crash detected, re-spawning
- `strategy gave up` — MAX_RESTARTS exceeded
- `heartbeat` — periodic status ping
- `master_bot stopped` — graceful shutdown

**State file**: `master_state.json` in the skill root.

**When to use**:
- User asks "start all my bots", "run everything", "launch all strategies"
- User wants the system to self-heal if a strategy crashes
- User wants to be notified when the system is running or a strategy fails

---

## 33. setup_all.py — Automated Setup Wizard

**Purpose**: One-command idempotent setup. Configures the entire skill from scratch or verifies an existing setup. Safe to re-run at any time — already-correct steps are skipped with ✔.

**Commands**:
```bash
poly setup                       # interactive (prompts for defaults)
poly setup --yes                 # non-interactive, accept all defaults
poly setup --dry-run --yes       # preview only — no files written, no network calls
poly setup --skip-creds          # skip API credential derivation (step 4)
```

**Aliases**: `poly init` · `poly install` · `poly configure`

**8 steps**:
| # | Step | What it does |
|---|---|---|
| 1 | Dependencies | Checks/installs `py-clob-client`, `requests`, `python-dotenv` |
| 2 | .env file | Copies `.env.example` → `.env` if missing |
| 3 | Private key | Validates `POLYMARKET_PRIVATE_KEY` is set and not a placeholder |
| 4 | API credentials | Runs `setup_credentials.py` if API key not yet derived |
| 5 | Risk guard defaults | Sets `max_daily_loss=5%` and `max_position_pct=20%` |
| 6 | Scheduler jobs | Registers 8 default cron-style jobs if not already present |
| 7 | Database | Runs `db.py migrate` to create/update `openpoly.db` |
| 8 | Geo-block | Warns if current IP is in a restricted region |

**When to use**:
- User is setting up the skill for the first time
- User asks "set everything up", "configure the bot", "initialize the system"
- After a fresh clone / new machine setup

---

## 34. stopall.py — Emergency Stop (Kill All Bots)

**Purpose**: Nuclear stop command. Finds and kills every running OpenPoly bot process using three layers so nothing can slip through, then activates the risk_guard kill switch to block any new trades.

**Three-layer bot hunt**:
| Layer | Method | Catches |
|---|---|---|
| 1 | `master_state.json` + `omni_state.json` stored PIDs | Bots started via `poly master` / `poly omni` |
| 2 | `scheduler.pid` file | Scheduler daemon |
| 3 | `pgrep -f` over all 13 bot script names | Orphans, zombies, manually started processes |

Kill sequence: SIGTERM → 3-second grace → SIGKILL any survivors.

**Commands**:
```bash
poly stopall                  # stop all bots + activate kill switch
poly stopall --dry-run        # show what would be killed, do nothing
poly stopall --force          # skip grace period — SIGKILL immediately
poly stopall --no-guard       # kill processes but don't flip kill switch
```

**After stopping**: run `poly risk reset` to resume trading.

**When to use**:
- User says "stop everything", "kill all bots", "emergency stop", "panic"
- When bots are stuck, crashing in a loop, or consuming too much budget
- Before maintenance or credential rotation
- When `poly master --stop` doesn't work (processes already detached/orphaned)

**Aliases**: `poly stop-all` · `poly killall` · `poly kill-all` · `poly emergency` · `poly panic`

---

## 35. _guards.py — Hard Runtime Limits

**Purpose**: Module of constants and guard functions that enforce non-negotiable safety limits on user-supplied CLI values. Imported by every trading bot and master_bot. Cannot be overridden by argument flags.

**Constants**:
| Constant | Value | Description |
|---|---|---|
| `MIN_ORDER_USD` | `1.0` | Polymarket minimum order size (USDC) |
| `SUGGESTED_MIN_USD` | `5.0` | Practical floor — covers fees even on small markets |
| `MIN_NEWS_INTERVAL` | `3.0` | Min minutes between `news_trader` cycles |
| `GAMMA_RATE_LIMIT_SEC` | `0.35` | Min seconds between Gamma API calls in the mapper |

**Functions**:

`check_min_order(amount_usd, *, flag, bot, exit_on_fail=False) -> bool`
- Returns `True` if `amount_usd >= MIN_ORDER_USD`
- If below minimum: prints a warning to stderr, fires a `notify_event` with `level="warning"`, and if `exit_on_fail=True` terminates the process
- All trading bots call this with `exit_on_fail=True` at startup so below-minimum runs are caught before any network activity

`enforce_min_interval(interval_min, bot="") -> float`
- Returns the clamped interval (never below `MIN_NEWS_INTERVAL`)
- If clamped, prints a warning explaining the 429-prevention reason
- Used by `news_trader.py` on `--interval`

`gamma_rate_wait() -> None`
- Thread-safe blocking call: waits until `GAMMA_RATE_LIMIT_SEC` has elapsed since the last Gamma API request
- Called inside `news/mapper.py` before every `requests.get()` to Gamma
- Prevents burst 429 errors when many stories are mapped in one pipeline cycle

**Which bots call which guard**:
| Bot | Guard called | Flag checked |
|---|---|---|
| `news_trader` | `check_min_order` + `enforce_min_interval` | `--budget`, `--interval` |
| `market_maker` | `check_min_order` | `--size` |
| `ai_automation` | `check_min_order` | `--budget` |
| `correlation_arbitrage` | `check_min_order` | `--budget` |
| `auto_arbitrage` | `check_min_order` | `--max-budget` |
| `master_bot` | inline budget check per strategy | computed budget_pct % of total |
| `news/mapper.py` | `gamma_rate_wait` | (implicit — every Gamma call) |

**When master_bot warns about budget**:
If `total_budget × strategy_budget_pct% < $1.00`, master_bot prints a warning and sends a notification suggesting the minimum `--budget` needed for that strategy combination.

**How to adjust constants**: Edit `scripts/_guards.py` directly. All bots pick up the new values automatically (they import at runtime).

---

## 36. time_decay.py — Resolution-Timing Edge

**Purpose**: Trade mispricings caused by time running out on prediction markets.

**Location**: `scripts/time_decay.py`

**Key constants**: `DEFAULT_MAX_DAYS=7`, `MIN_EDGE=0.04`, `DECAY_PER_DAY=0.30`, `FEE=0.02`

**Core model**:
```python
def _fair_no_price(yes_price, days):
    fair_yes = yes_price * (1 - DECAY_PER_DAY) ** days
    return round(1.0 - fair_yes, 4)
```

**Sub-strategies**:
- **FADE** — buy NO when `fair_no - live_no - FEE >= min_edge`; markets still priced as if the event *might* occur with days left
- **RUSH** — buy YES when `yes_price >= 0.70` but still underpriced relative to residual time probability

**CLI**:
```bash
poly time-decay --scan [--max-days N] [--min-edge X] [--top N] [--tag KEYWORD]
poly time-decay --scan --execute --budget 1 [--dry-run]
poly time-decay --once
poly time-decay --loop --interval 300
poly time-decay --status
```

**Aliases**: `poly td` · `poly decay`

**State file**: `time_decay_state.json` — `runs`, `trades_executed`, `total_spent`, `total_profit_est`, `history`

**Notifications**: `notify_trade_opened` with `extras={"type": "FADE"|"RUSH", "days_remaining": N, "edge": N}`

**STRATEGY_REGISTRY key**: `"time_decay"`, alias `["td", "decay"]`, `budget_pct=15`

---

## 37. logical_arb.py — Logical Constraint Violation Arbitrage

**Purpose**: Enforce strict mathematical bounds between logically related markets.

**Location**: `scripts/logical_arb.py`

**Key constants**: `DEFAULT_MIN_EDGE=0.03`, `DEFAULT_LIMIT=250`, `MIN_VOLUME_24H=300`

**LOGIC_GROUPS** (7 built-in):
| Group | Type | Rule |
|---|---|---|
| trump→republican | IMPLICATION | P(Trump wins primary) ≤ P(Republican wins presidency) |
| dem_candidate→democrat | IMPLICATION | P(specific Dem wins primary) ≤ P(Democrat wins WH) |
| wins_popular_vote→wins_presidency | IMPLICATION | P(wins popular vote) ≥ P(wins EC) |
| btc_spot_etf→btc_etf | IMPLICATION | P(spot ETF) ≤ P(any ETF) |
| fed_mar→fed_q1 | IMPLICATION | P(March cut) ≤ P(Q1 cut) |
| nba_champ_team | MUTEX_HINT | sum of all team win probs ≤ 1 (per pair) |
| nfl_champ_team | MUTEX_HINT | same for NFL |

**Execution**: `execute_violation()` places 2 legs with budget split 50/50.

**CLI**:
```bash
poly logical-arb --scan [--min-edge X] [--limit N] [--top N]
poly logical-arb --scan --execute --budget 1 [--dry-run]
poly logical-arb --once
poly logical-arb --status
```

**Aliases**: `poly la` · `poly logic`

**State file**: `logical_arb_state.json`

**STRATEGY_REGISTRY key**: `"logical_arb"`, alias `["la", "logic"]`, `budget_pct=10`

---

## 38. resolution_arb.py — Near-Settlement Guaranteed-Profit Arbitrage

**Purpose**: Capture risk-free profit when YES + NO prices sum to more than 1 in markets near their resolution date.

**Location**: `scripts/resolution_arb.py`

**Key constants**: `DEFAULT_MAX_DAYS=3`, `DEFAULT_MIN_EDGE=0.01`, `MIN_VOLUME_24H=100`

**Opportunity types**:
| Type | Condition | Action |
|---|---|---|
| `BOTH_SIDES` | YES + NO > 1.0 + FEE + min_edge | Sell both sides (buy NO at 1-yes_price and vice versa) |
| `EXCESS_NO` | YES ≥ 0.93 and NO ≥ 0.04 | Buy YES (NO is mispriced high near certain outcome) |
| `EXCESS_YES` | NO ≥ 0.93 and YES ≥ 0.04 | Buy NO (YES is mispriced high) |

**CLI**:
```bash
poly res-arb --scan [--max-days N] [--min-edge X] [--limit N]
poly res-arb --scan --execute --budget 1
poly res-arb --once
poly res-arb --include-anytime   # also check event-triggered markets
poly res-arb --status
```

**Aliases**: `poly resarb` · `poly resolution`

**State file**: `resolution_arb_state.json`

**STRATEGY_REGISTRY key**: `"resolution_arb"`, alias `["res", "resarb"]`, `budget_pct=5`

---

## 39. news_latency.py — Sub-10-Second RSS News Trading

**Purpose**: Trade on breaking headlines before price discovery catches up — targets < 10 s from news to order.

**Location**: `scripts/news_latency.py`

**Key constants**: `POLL_INTERVAL=10` (hard min), `MAX_STORY_AGE=30`, `MIN_EDGE=0.05`, `CACHE_TTL=300`

**Speed optimisations vs `news_trader`**:
- RSS-only (no GDELT/NewsAPI call overhead)
- Pre-cached `news_latency_map.json`: keyword→token_id, rebuilt every `CACHE_TTL` seconds
- No clustering or full impact scoring pass
- `MIN_EDGE=0.05` buffer compensates for removed slippage gate

**`build_keyword_map()`**: Scans Gamma for active markets, extracts 2-3-word n-grams ≥ 8 chars as keys mapped to `[yes_token_id, no_token_id]`.

**`_direction(title)`**: Classifies story as YES or NO trade using YES_KEYWORDS / NO_KEYWORDS word sets; defaults to YES.

**CLI**:
```bash
poly news-latency --build-map          # must run once first
poly news-latency --loop [--interval 10] [--budget 1]
poly news-latency --once
poly news-latency --dry-run
poly news-latency --status
```

**Aliases**: `poly nl` · `poly fast-news`

**State file**: `news_latency_state.json`, **map file**: `news_latency_map.json`

**STRATEGY_REGISTRY key**: `"news_latency"`, alias `["nl", "fast-news"]`, `budget_pct=5`

---

## 40. strategy_evaluator.py — Performance Tracker with Auto-Disable

**Purpose**: Measure real-world effectiveness of every strategy; auto-disable losers; suggest scaling winners.

**Location**: `scripts/strategy_evaluator.py`

**Metrics computed per strategy**:
| Metric | Description |
|---|---|
| `roi_pct` | `(total_profit / total_spent) × 100` |
| `win_rate` | wins / (wins + losses) from history entries with outcome/profit fields |
| `avg_edge` | mean of `edge` values across history entries |
| `sharpe` | mean daily return / std dev (requires ≥ 5 data points) |
| `total_trades` | from `trades_executed` in state file |

**State sources**:
```
auto_arbitrage_state.json   news_trader_state.json
market_maker_state.json     ai_signals.json
correlation_arb_state.json  time_decay_state.json
logical_arb_state.json      resolution_arb_state.json
news_latency_state.json
```

**`--auto-disable`**: Writes `disabled_strategies` list to `master_state.json`. `master_bot` reads this before spawning each strategy and skips disabled ones.

**CLI**:
```bash
poly strategy-eval --report            # ranked table
poly strategy-eval --report --json     # machine-readable
poly strategy-eval --all               # report + recommend
poly strategy-eval --auto-disable [--min-trades N]
poly strategy-eval --recommend
poly strategy-eval --reset STRATEGY    # clear state file
poly strategy-eval --re-enable STRATEGY
# shortcut:
poly master --evaluate
```

**Aliases**: `poly evaluate` · `poly perf` · `poly performance`

**NL invocations**:
- "How are my strategies performing?" → `--report`
- "Which strategies are making money?" → `--recommend`
- "Auto-disable losing strategies" → `--auto-disable --min-trades 30`
- "Re-enable news_trader" → `--re-enable news_trader`

**State files written**: `evaluator_state.json` (snapshot), modifications to `master_state.json`

**Integration**: `master_bot.py --evaluate` calls `strategy_evaluator.py --report --recommend` via subprocess.

- If commands fail with `ModuleNotFoundError`: run `pip install py-clob-client requests python-dotenv web3 --break-system-packages`
- If `401 Unauthorized`: credentials are wrong or expired — re-derive with `poly setup`
- If `insufficient balance`: user needs to deposit USDC to their Polygon wallet
- Always show the raw error to the user if a trade fails

---

## Safety Rules

1. **Never place a trade without explicit user confirmation**
2. **Never invest more than the user specifies**
3. **Before starting any automation, recommend the user configure `poly risk set --max-daily-loss 0.05`**
4. **If a user sets a budget below $1 per trade**, the guard will reject the run and print a suggested fix — tell the user to raise the budget to at least $5 (covers fees)
5. **If a user sets `news_trader --interval` below 3 minutes**, it is silently clamped to 3 min — explain this to the user if they ask why the interval seems different
6. **Warn the user** that prediction markets carry risk and past performance is not indicative of future results
7. **Never store private keys in logs or output** — mask as `0x****...****`
8. **Before sizing any trade**, run `poly prob --market-id ID --balance N` to get a calibrated fair probability and suggested Kelly size
9. **If asked to evaluate strategy performance**, run `strategy_evaluator.py --report` first — never recommend scaling a strategy without checking its ROI and trade count
10. **Auto-disable threshold**: only invoke `--auto-disable` after at least 30 trades per strategy (the default `--min-trades 30`) — fewer trades have too much variance to draw conclusions
