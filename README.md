<div align="center">

```
 ██████╗ ██████╗ ███████╗███╗   ██╗██████╗  ██████╗ ██╗  ██╗   ██╗
██╔═══██╗██╔══██╗██╔════╝████╗  ██║██╔══██╗██╔═══██╗██║  ╚██╗ ██╔╝
██║   ██║██████╔╝█████╗  ██╔██╗ ██║██████╔╝██║   ██║██║   ╚████╔╝
██║   ██║██╔═══╝ ██╔══╝  ██║╚██╗██║██╔═══╝ ██║   ██║██║    ╚██╔╝
╚██████╔╝██║     ███████╗██║ ╚████║██║     ╚██████╔╝███████╗██║
 ╚═════╝ ╚═╝     ╚══════╝╚═╝  ╚═══╝╚═╝      ╚═════╝ ╚══════╝╚═╝
```

**An [OpenClaw](https://docs.openclaw.ai/tools/creating-skills) skill that gives your AI agent full access to a Polymarket account.**

Trade, research, arbitrage, and run autonomous strategies — all via natural language.

[![Python](https://img.shields.io/badge/Python-3.11+-3776AB?style=flat-square&logo=python&logoColor=white)](https://python.org)
[![Polymarket](https://img.shields.io/badge/Polymarket-CLOB%20API-6C5CE7?style=flat-square)](https://docs.polymarket.com)
[![OpenClaw](https://img.shields.io/badge/OpenClaw-Skill-00B894?style=flat-square)](https://docs.openclaw.ai)
[![License](https://img.shields.io/badge/License-MIT-DFE6E9?style=flat-square)](LICENSE)

</div>

---

## What is this?

OpenPoly connects your OpenClaw AI agent to a live Polymarket account. The agent reads `SKILL.md` to understand every capability, then calls the right Python script for whatever you ask — from a simple portfolio check to running five concurrent trading strategies.

```
You: "Find arbitrage and run the news pipeline in dry-run mode"
       └─► Agent calls correlation_arbitrage.py + news_trader.py
                                        └─► Results printed back to you
```

No intermediary. No dashboard. Just your agent and a full trading toolkit.

---

## Features at a glance

| Category | What's included |
|---|---|
| **Portfolio** | Balance, positions, exposure analysis, P&L |
| **Research** | Market search, orderbook, price history, deep stats, Kelly sizing |
| **Trading** | Limit / GTD orders with confirmation gate — GTC default, 1-min minimum lifetime |
| **Arbitrage** | Scanner, executor, automated bot, slippage simulation |
| **Corr. Arb** | Cross-market keyword graph — finds logically linked mispriced pairs |
| **News trading** | 4-layer pipeline: GDELT + NewsAPI + RSS → dedup → cluster → score → gate |
| **Market making** | Bid/ask spread earning with inventory skew control |
| **AI signals** | Heuristic momentum + mean-reversion signal engine |
| **Omni** | One command to launch all strategies with budget split |
| **Automation** | Scheduler daemon — any script on any interval, background-safe |
| **Alerts** | Watchlist price alerts + market monitor (volume, arb gaps, extremes) |
| **Backtesting** | Replay momentum / mean-reversion signals on resolved market price history |
| **Evaluation** | Post-resolution hit-rate scoring — which sources and strategies made money |
| **Risk guard** | Max daily loss limit, position caps, manual kill switch, daily PnL log |
| **Data layer** | Unified SQLite store — articles, signals, trades, outcomes, per-source accuracy |
| **Prob model** | Calibrated fair-probability engine — Bayesian prior + signal updates + Kelly sizing |
| **On-chain** | Redeem resolved winning positions via Polygon CTF contract |
| **Geo-block check** | Official IP-based check — returns country, region, blocked / close-only status |
| **Notifications** | All auto bots push trade open/close events — macOS banners + persistent JSON log |
| **Master bot** | Supervised all-in-one runner — crash auto-restart, heartbeat alerts, `--only` subset, kill-switch aware |
| **Automated setup** | One-command idempotent setup wizard — deps, .env, key validation, API creds, risk guard, scheduler, DB |
| **Security** | API key entropy check at startup, secret masking in all error output, kill switch wired into every auto bot |
| **Input guards** | Hard minimum order size ($1) enforced at startup in every bot + master_bot; news_trader interval clamped to ≥ 3 min; Gamma API rate-limited to prevent 429 throttling |
| **Time decay arb** | FADE/RUSH sub-strategies on resolution-timing mispricings — exponential decay model, ≤7 day window |
| **Logical arb** | Strictly enforces implication + mutex constraints across related markets — 7 built-in logic groups |
| **Resolution arb** | Near-settlement YES+NO>1 guaranteed-profit arbitrage — lowest-risk strategy in the suite |
| **News latency** | Sub-10-second RSS-only news trading — pre-cached keyword map, no clustering overhead |
| **Strategy evaluator** | Per-strategy ROI/win-rate/Sharpe tracker with auto-disable; integrates with master_bot |
| **Tests & CI** | 100 pytest tests across 5 test files, GitHub Actions CI on every push |

---

## Quickstart

> One-time setup. After this the agent handles everything.

```bash
# 1. Clone into the OpenClaw skills directory
git clone https://github.com/carlemilbograd/OpenPoly.git \
  ~/.openclaw/workspace/skills/polymarket

# 2. Install dependencies
cd ~/.openclaw/workspace/skills/polymarket
pip install -r requirements.txt

# 3. Set your private key  ← the only manual step
cp .env.example .env
#  Open .env and fill in POLYMARKET_PRIVATE_KEY=0xYOUR_KEY

# 4. Derive API credentials (writes to .env automatically)
python scripts/setup_credentials.py

# 5. Reload OpenClaw skills, then just talk to your agent
```

---

## Talk to your agent

These are real examples of what you can say. The agent picks the right script.

```
"Show my Polymarket portfolio"
"Search for crypto prediction markets"
"Find the best arbitrage opportunity right now"
"Execute the arbitrage with a $100 budget"
"Start the news pipeline in dry-run mode"
"Make markets on near-50/50 high-volume markets"
"Run all strategies at once with $500"
"Alert me when this market goes above 0.70"
"What are my open orders?"
"Simulate how much slippage a $200 buy would cause"
"Show me a price chart for this token"
"Redeem my winnings from resolved markets"
```

<details>
<summary><b>Full natural language → script mapping</b></summary>

| Prompt | Script |
|---|---|
| Show my portfolio / balance | `portfolio.py` |
| Search for crypto / election markets | `markets.py --query …` |
| Find arbitrage opportunities | `arbitrage.py` |
| Execute arbitrage with $100 | `arbitrage_execute.py --scan --budget 100` |
| Start auto arbitrage bot | `auto_arbitrage.py --interval 15m` |
| Monitor markets, alert on moves | `auto_monitor.py --loop` |
| Show recent alerts | `auto_monitor.py --alerts --since 24h` |
| Show the orderbook | `orderbook.py --token-id …` |
| Price chart for token | `price_history.py --token-id …` |
| Deep market stats | `market_stats.py --market-id …` |
| Research a market, suggest a trade | `research_agent.py` |
| Buy YES at 0.45 | `trade.py` (confirmation required) |
| Am I geo-blocked? / Check my region | `geoblock.py` |
| What orders do I have open? | `open_orders.py` |
| Cancel all orders | `cancel.py --all` |
| Show trade history | `history.py --limit 20` |
| How exposed is my portfolio? | `exposure.py` |
| Alert above 0.70 | `watchlist.py add --above 0.70` |
| Simulate slippage on $100 | `execution_simulator.py` |
| Find correlated market arb | `correlation_arbitrage.py --scan` |
| Trade on latest news | `news_trader.py --once` |
| Make markets / earn spread | `market_maker.py --scan-targets` |
| Generate AI signals | `ai_automation.py --once --signals` |
| Run all strategies with $500 | `master_bot.py --start --budget 500` |
| Run only arb + market maker | `master_bot.py --start --only arb,mm --budget 300` |
| Scan resolution-timing mispricings | `time_decay.py --scan` |
| Trade logical constraint violations | `logical_arb.py --scan --execute --budget 50` |
| Near-settlement guaranteed arb | `resolution_arb.py --once` |
| Fast RSS news trading (10s) | `news_latency.py --loop --budget 20` |
| How are my strategies performing? | `strategy_evaluator.py --report` |
| Auto-disable losing strategies | `strategy_evaluator.py --auto-disable --min-trades 30` |
| First-time setup (automated) | `setup_all.py --yes` |
| Redeem resolved winnings | `redeem.py --dry-run` |
| Schedule auto arb every 15 min | `scheduler.py add` + `scheduler.py start` |

</details>

---

## Scripts

### Core tools

<details>
<summary><b>portfolio.py</b> — Balance + positions</summary>

```bash
python scripts/portfolio.py
```
Prints USDC cash balance and all open positions with current price, size, and value.
</details>

<details>
<summary><b>markets.py</b> — Browse and search markets</summary>

```bash
python scripts/markets.py                          # top markets by 24h volume
python scripts/markets.py --query "US election"   # keyword search
python scripts/markets.py --tag politics --limit 20
python scripts/markets.py --market-id SLUG_OR_ID  # single market + token IDs
```
</details>

<details>
<summary><b>orderbook.py</b> — Live bids, asks, spread</summary>

```bash
python scripts/orderbook.py --token-id TOKEN_ID
python scripts/orderbook.py --token-id TOKEN_ID --depth 10
```
</details>

<details>
<summary><b>trade.py</b> — Place orders (with confirmation) + preflight dry-run</summary>

```bash
# Preflight check — verify everything before committing money (run this first)
python scripts/trade.py --token-id TOKEN_ID --side BUY --price 0.55 --size 10 --dry-run

# Limit order (GTC — default, good till cancelled)
python scripts/trade.py --token-id TOKEN_ID --side BUY --price 0.55 --size 10

# Limit with expiry (GTD — min 60s expiry)
python scripts/trade.py --token-id TOKEN_ID --side SELL --price 0.70 --size 5 \
  --type GTD --expiry 3600
```

> **Note:** Polymarket enforces a minimum 1-minute order lifetime — FOK/fill-or-kill and immediate market orders are not supported. All orders rest on the book as GTC (default) or GTD.

`--dry-run` runs 5 checks without submitting anything:

| Check | What it catches |
|---|---|
| Credentials | Bad/expired API key |
| Balance | Not enough USDC for the order size |
| Market active | Closed market or wrong token ID |
| Geoblock | `403`/`451` from Polymarket if region is blocked |
| Order signing | Key format errors (pure local crypto, no POST) |

Always shows an order preview and asks for confirmation before submitting a real order.
</details>

<details>
<summary><b>notifier.py</b> — Bot trade notifications</summary>

```bash
poly notify                        # last 20 notifications
poly notify --limit 50
poly notify --since 2h             # last 2 hours
poly notify --bot auto_arbitrage   # filter by bot
poly notify --event trade_opened   # filter: trade_opened | trade_closed
poly notify --json                 # raw JSON
poly notify --clear                # wipe history
```

All auto bots (`auto_arbitrage`, `news_trader`, `ai_automation`, `market_maker`,
`correlation_arbitrage`) call `notify_trade_opened` / `notify_trade_closed` after
every real order. Each event fires a macOS Notification Center banner and appends
a structured record to `logs/trade_notifications.json`.

Notification hooks are `try/except`-wrapped — they never crash a live bot.

Aliases: `poly notifs` · `poly notifications` · `poly trades`
</details>

<details>
<summary><b>geoblock.py</b> — Check if your IP is geo-blocked</summary>

```bash
poly geoblock            # check via official Polymarket geoblock API
poly geoblock --json     # machine-readable output
```

Calls `GET https://polymarket.com/api/geoblock`. Returns your IP, country, region,
and whether trading is permitted. No credentials required.

Status codes:
- **`ok`** — trading permitted from your location
- **`close_only`** — you can close existing positions but not open new ones (PL, SG, TH, TW)
- **`blocked`** — region is restricted (AU, DE, FR, GB, US, and others)

Aliases: `poly geo` · `poly blocked` · `poly geo-check`
</details>

<details>
<summary><b>cancel.py</b> — Cancel orders</summary>

```bash
python scripts/cancel.py --order-id ORDER_ID      # single order
python scripts/cancel.py --all                    # all open orders
python scripts/cancel.py --market-id TOKEN_ID     # all orders in one market
```
</details>

<details>
<summary><b>open_orders.py</b> — List pending orders</summary>

```bash
python scripts/open_orders.py                     # all open orders
python scripts/open_orders.py --side BUY          # filter by side
python scripts/open_orders.py --json              # machine-readable
```
Shows age, fill percentage, and total exposure per order.
</details>

<details>
<summary><b>history.py</b> — Trade history</summary>

```bash
python scripts/history.py --limit 20
python scripts/history.py --market-id TOKEN_ID
```
</details>

<details>
<summary><b>price_history.py</b> — ASCII price chart</summary>

```bash
python scripts/price_history.py --token-id TOKEN_ID --interval 1h
python scripts/price_history.py --token-id TOKEN_ID --start 2024-01-01
python scripts/price_history.py --token-id TOKEN_ID --raw
```
Renders an ASCII sparkline with min/max/mean/volatility stats. Intervals: `1m 5m 15m 1h 6h 1d 1w max`.
</details>

<details>
<summary><b>market_stats.py</b> — Deep market analysis</summary>

```bash
python scripts/market_stats.py --market-id MARKET_ID_OR_SLUG
```
Combines Gamma API + Data API + CLOB: price changes (1h/24h/7d), orderbook depth, open interest, top holders, recent trades.
</details>

<details>
<summary><b>research_agent.py</b> — Structured research brief</summary>

```bash
python scripts/research_agent.py --market-id MARKET_ID_OR_SLUG
python scripts/research_agent.py --query "Will X happen?"
```
Fetches market data and outputs a structured research brief with Kelly sizing formula for the agent to complete with web search.
</details>

<details>
<summary><b>exposure.py</b> — Portfolio risk analysis</summary>

```bash
python scripts/exposure.py
python scripts/exposure.py --warn-threshold 0.30   # flag positions > 30%
```
Concentration per position, correlated groups by tag, max loss/gain scenarios, cash ratio warnings.
</details>

<details>
<summary><b>watchlist.py</b> — Price alerts</summary>

```bash
python scripts/watchlist.py add --token-id TOKEN_ID --above 0.70
python scripts/watchlist.py add --token-id TOKEN_ID --below 0.30
python scripts/watchlist.py check --loop --interval 60
python scripts/watchlist.py list
python scripts/watchlist.py remove --token-id TOKEN_ID
```
</details>

<details>
<summary><b>redeem.py</b> — Redeem resolved positions</summary>

```bash
python scripts/redeem.py --dry-run                # always run this first
python scripts/redeem.py
python scripts/redeem.py --market-id CONDITION_ID
```
Calls `redeemPositions()` on the Polymarket CTF contract on Polygon. Requires `web3`. Set `POLYGON_RPC_URL` in `.env` (defaults to `https://polygon-rpc.com`).
</details>

---

### Arbitrage

<details>
<summary><b>arbitrage.py</b> — Scan for mispriced markets</summary>

```bash
python scripts/arbitrage.py                            # 3% min gap, top 50 markets
python scripts/arbitrage.py --min-gap 0.02 --limit 100 --tag politics
python scripts/arbitrage.py --live                     # live CLOB prices
```
Scans markets where YES + NO prices don't sum to 1.0. Sorted by net profit after fees.
</details>

<details>
<summary><b>arbitrage_execute.py</b> — Execute an arbitrage trade</summary>

```bash
python scripts/arbitrage_execute.py --scan --budget 100
python scripts/arbitrage_execute.py --market-id ID --budget 50
python scripts/arbitrage_execute.py --scan --min-gap 0.04
```
Calculates position sizes, checks liquidity, and places all legs after confirmation.
</details>

<details>
<summary><b>auto_arbitrage.py</b> — Automated arbitrage bot</summary>

```bash
# Self-contained loop
python scripts/auto_arbitrage.py --interval 15m --min-gap 0.005 --budget-pct 0.10
python scripts/auto_arbitrage.py --interval 1h  --min-gap 0.01  --budget-pct 0.05 --dry-run

# Single-shot (for scheduler)
python scripts/auto_arbitrage.py --once --min-gap 0.005 --budget-pct 0.05

# Stats
python scripts/auto_arbitrage.py --status
```
Slippage-checked via `execution_simulator` before every order.
</details>

<details>
<summary><b>execution_simulator.py</b> — Orderbook slippage simulation</summary>

```bash
python scripts/execution_simulator.py --token-id TOKEN --size 50 --edge 0.07
python scripts/execution_simulator.py --token-id TOKEN --optimal-size --edge 0.06 --budget 200
```
Walks the live orderbook to estimate average fill price, slippage %, and net profit. Binary-searches for the optimal order size that maximises edge after slippage and fees. Used as an import gate by `auto_arbitrage.py` and `news_trader.py`.
</details>

<details>
<summary><b>correlation_arbitrage.py</b> — Cross-market correlated-pair arb</summary>

```bash
python scripts/correlation_arbitrage.py --scan                      # find all gaps
python scripts/correlation_arbitrage.py --scan --min-edge 0.03
python scripts/correlation_arbitrage.py --scan --execute --budget 100
python scripts/correlation_arbitrage.py --graph                     # full correlation graph
python scripts/correlation_arbitrage.py --once                      # scheduler-friendly
```
Builds a keyword graph across all active markets. Finds pairs like "Trump wins" + "Republican wins" where prices are logically inconsistent — and trades both legs simultaneously.
</details>

---

### News trading pipeline

The news system is a full 4-layer pipeline in `scripts/news/`:

```
GDELT (free, 65+ languages)  ─┐
NewsAPI (optional, free key)  ─┤─► normalize ─► cluster ─► map ─► score ─► gate ─► trade
RSS feeds (15 default)        ─┘
```

| Layer | File | What it does |
|---|---|---|
| L1 Ingest | `sources/gdelt.py` | GDELT DOC 2.0 — no key, broad breaking news |
| L1 Ingest | `sources/newsapi.py` | NewsAPI.org — optional, richer metadata |
| L1 Ingest | `sources/rss.py` | 15 curated feeds (White House, Fed, Reuters, AP, SCOTUS…) |
| L2 Normalize | `normalize.py` | SHA-1 fingerprints, 60-domain trust table, age filter |
| L2b Cluster | `cluster.py` | Jaccard token-set clustering → one rep per real event |
| L3 Map | `mapper.py` | Keywords → Gamma API → story↔market relevance |
| L4 Score | `score.py` | impact = (trust · novelty · relevance · specificity · urgency)^⅕ |
| Gate | `pipeline.py` | `edge > fees + slippage + safety_buffer` check |

<details>
<summary><b>news_trader.py</b> — CLI entrypoint</summary>

```bash
python scripts/news_trader.py --once                          # single pipeline cycle
python scripts/news_trader.py --loop --interval 5             # poll every 5 minutes
python scripts/news_trader.py --loop --interval 5 --dry-run   # simulate only

# Source management
python scripts/news_trader.py --sources
python scripts/news_trader.py --add-source "https://…" --source-label "Name" --source-trust 0.8

# History
python scripts/news_trader.py --history --limit 20
python scripts/news_trader.py --history --json
```

**Key flags:** `--min-edge 0.06` · `--min-impact 0.15` · `--min-relevance 0.15` · `--safety-buffer 0.02` · `--max-age 60` · `--newsapi-key KEY` · `--skip-slippage`

Set `NEWSAPI_KEY` in `.env` for richer article metadata. GDELT works with no key.
</details>

---

### Market making

<details>
<summary><b>market_maker.py</b> — Post bid/ask quotes, earn the spread</summary>

```bash
python scripts/market_maker.py --scan-targets                  # find best markets
python scripts/market_maker.py --market-id TOKEN --spread 0.02 --size 10
python scripts/market_maker.py --loop --interval 30            # refresh every 30s
python scripts/market_maker.py --once                          # single refresh
python scripts/market_maker.py --status                        # inventory view
python scripts/market_maker.py --close --market-id TOKEN       # cancel + exit
```
Targets near-50/50 high-volume markets. Inventory skew prevents directional over-exposure.

Execution sophistication: before cancelling and re-quoting, checks queue position (skips repost if price is still within one tick of best bid/ask) and partial-fill detection (tracks fills ≥50% and updates inventory immediately).
</details>

---

### AI & multi-strategy

<details>
<summary><b>ai_automation.py</b> — Heuristic signal engine</summary>

```bash
python scripts/ai_automation.py --once                          # research top 20
python scripts/ai_automation.py --research-top 50 --once
python scripts/ai_automation.py --signals                       # show saved signals
python scripts/ai_automation.py --once --execute --min-confidence 0.7
python scripts/ai_automation.py --loop --interval 30
```
Runs momentum, volume, and mean-reversion analysis across Polymarket's top markets. Saves signals to `ai_signals.json`. Designed as a drop-in slot for an LLM call.
</details>

<details>
<summary><b>master_bot.py</b> — Supervised all-in-one runner (recommended)</summary>

```bash
python scripts/master_bot.py --start --budget 1000
python scripts/master_bot.py --start --budget 1000 --dry-run
python scripts/master_bot.py --start --only arb,mm,news --budget 500
python scripts/master_bot.py --once
python scripts/master_bot.py --status
python scripts/master_bot.py --pnl
python scripts/master_bot.py --stop
python scripts/master_bot.py --list-strategies
```

Default budget split: `arb:25%` · `corr:10%` · `mm:15%` · `news:10%` · `ai:5%` · `time_decay:15%` · `logical_arb:10%` · `res_arb:5%` · `news_latency:5%` · `monitor:0%`

Features over omni_strategy: crash auto-restart (up to 5×), heartbeat notifications every 30 min, OpenClaw lifecycle alerts, `--only` subset mode, STRATEGY_REGISTRY pattern (single place to add new strategies).
</details>

<details>
<summary><b>omni_strategy.py</b> — Run every strategy at once (legacy)</summary>

```bash
python scripts/omni_strategy.py --start --budget 1000
python scripts/omni_strategy.py --start --budget 1000 --dry-run
python scripts/omni_strategy.py --start --split "arb:30,corr:25,mm:25,news:10,ai:10"
python scripts/omni_strategy.py --once
python scripts/omni_strategy.py --status
python scripts/omni_strategy.py --pnl
python scripts/omni_strategy.py --stop
```

Default budget split: `arb:30%` · `corr:25%` · `mm:25%` · `news:10%` · `ai:10%`

> Prefer `master_bot.py` for production — it adds supervised crash-restart, heartbeat alerts and STRATEGY_REGISTRY.
</details>

<details>
<summary><b>setup_all.py</b> — Automated first-time setup wizard</summary>

```bash
python scripts/setup_all.py          # interactive
python scripts/setup_all.py --yes    # non-interactive (accept all defaults)
python scripts/setup_all.py --dry-run --yes  # preview only, no changes
python scripts/setup_all.py --skip-creds     # skip API credential derivation
```

8 idempotent steps: dependencies · .env file · private key validation · API credentials · risk guard defaults · scheduler default jobs · database migration · geo-block check. Safe to re-run at any time.
</details>

---

### Automation

<details>
<summary><b>scheduler.py</b> — Background daemon for any script</summary>

```bash
# Register jobs
python scripts/scheduler.py add \
  --name auto_arbitrage \
  --script auto_arbitrage.py \
  --args "--min-gap 0.005 --budget-pct 0.05 --once" \
  --interval 15m

python scripts/scheduler.py add --name news --script news_trader.py \
  --args "--once" --interval 5m

# Control
python scripts/scheduler.py start --background
python scripts/scheduler.py status
python scripts/scheduler.py stop
python scripts/scheduler.py list
python scripts/scheduler.py disable --name auto_arbitrage
python scripts/scheduler.py enable  --name auto_arbitrage
python scripts/scheduler.py remove  --name auto_arbitrage
```
Logs to `logs/job_<name>_YYYY-MM-DD.log`. Zero extra dependencies.
</details>

<details>
<summary><b>auto_monitor.py</b> — Market alerts daemon</summary>

```bash
python scripts/auto_monitor.py --once                        # one scan
python scripts/auto_monitor.py --loop --interval 1h
python scripts/auto_monitor.py --alerts --since 24h
python scripts/auto_monitor.py --once --price-move 0.08      # 8pp threshold
```
Fires alerts for: price moves ≥5pp, arb gaps ≥3%, volume spikes, near-50/50 extremes.
Alert log: `logs/monitor_alerts.json`.
</details>

#### Available automated scripts

| Script | What it does | Scheduler flag |
|---|---|---|
| `auto_arbitrage.py` | Scan + execute arbitrage | `--once` |
| `auto_monitor.py` | Price moves, gaps, volume spikes | `--once` |
| `correlation_arbitrage.py` | Correlated-pair arb | `--once --scan` |
| `news_trader.py` | 4-layer news pipeline | `--once` |
| `market_maker.py` | Post bid/ask, earn spread | `--once` |
| `ai_automation.py` | Signal generation | `--once` |
| `master_bot.py` | All strategies (supervised) | `--once` |
| `omni_strategy.py` | All strategies (legacy) | `--once` |
| `exposure.py` | Portfolio risk check | *(runs and exits)* |
| `watchlist.py check` | Fire price alerts | *(runs and exits)* |

---

### Evaluation & safety

<details>
<summary><b>backtest.py</b> — Replay strategies on historical prices</summary>

```bash
# Test on last 25 resolved markets
python scripts/backtest.py --strategy momentum --limit 25
python scripts/backtest.py --strategy mean-revert --tag politics

# Single token, custom date range
python scripts/backtest.py --token-id TOKEN_ID --start 2024-06-01

# Show saved results
python scripts/backtest.py --results
python scripts/backtest.py --results --json
```

Fetches OHLC price history from the public Polymarket CLOB API, applies the
selected signal rule, simulates fills with spread + fee, and reports:
hit rate, total PnL, Sharpe ratio, max drawdown, avg PnL per trade.

Results saved to `backtest_results.json`.
</details>

<details>
<summary><b>eval.py</b> — Post-resolution signal evaluator</summary>

```bash
python scripts/eval.py                      # score all pending signals
python scripts/eval.py --since 7d           # last 7 days only
python scripts/eval.py --source news        # filter: news | ai | arb | all
python scripts/eval.py --report             # full accuracy report
python scripts/eval.py --report --json      # machine-readable
python scripts/eval.py --reset              # clear log
```

Reads trade logs from `news_trader_state.json`, `ai_signals.json`, and
`auto_arbitrage_state.json`, then queries Gamma API for resolved outcomes.
Compares each signal's predicted direction against what actually happened.

Outputs hit rate by source, per-signal table, running accuracy trend.
Results appended to `eval_log.json`.
</details>

<details>
<summary><b>risk_guard.py</b> — Daily loss limits + kill switch</summary>

```bash
# Check status
python scripts/risk_guard.py status

# Configure limits
python scripts/risk_guard.py set --max-daily-loss 0.05   # 5% daily loss cap
python scripts/risk_guard.py set --max-position-pct 0.20 # 20% max per trade

# Kill switch
python scripts/risk_guard.py kill     # halt all trading
python scripts/risk_guard.py reset    # resume + start new day

# Log a trade's PnL (called by strategy scripts)
python scripts/risk_guard.py record --pnl -12.50 --balance 500

# Check inline before placing a trade
python scripts/risk_guard.py check --size 50 --balance 400

# Daily history
python scripts/risk_guard.py history
```

Enforces three limits: max daily loss (auto-fires kill switch), max position
size, and max open orders. Other strategy scripts can import it directly:

```python
from risk_guard import check_limits, is_killed
ok, reason = check_limits(trade_size_usd=50, current_balance=400)
```

Config and daily PnL stored in `risk_state.json`.
</details>

<details>
<summary><b>db.py</b> — Unified SQLite data layer</summary>

```bash
python scripts/db.py status              # row counts for all tables
python scripts/db.py migrate             # absorb JSON state files → DB
python scripts/db.py accuracy            # per-source signal hit rate
python scripts/db.py signals --limit 20  # recent signals
python scripts/db.py trades  --limit 20  # recent trades
python scripts/db.py vacuum              # reclaim disk space
```

Importable in other scripts:

```python
from db import DB

with DB() as db:
    db.insert_signal(source="news", market_id="0xabc", direction="YES",
                     confidence=0.72, edge_estimate=0.09)
    accuracy = db.accuracy_by_source()   # {"news": {"hit_rate": 0.70, ...}}
```

Stores all state in `openpoly.db` (WAL mode). Run `poly db migrate` once after
upgrading from JSON state files.
</details>

<details>
<summary><b>prob_model.py</b> — Calibrated probability + Kelly sizing</summary>

```bash
python scripts/prob_model.py --market-id ID              # estimate fair value
python scripts/prob_model.py --market-id ID --balance 500  # + Kelly sizing
python scripts/prob_model.py --market-id ID --show-signals  # factor breakdown
python scripts/prob_model.py --market-id ID --json         # machine-readable
python scripts/prob_model.py --market-id ID --save         # save to DB
```

Algorithm: market price → Bayesian prior → weighted signal updates (news/AI/arb)
→ source credibility from DB accuracy table → time decay on old signals →
shrinkage toward market price → quarter-Kelly position size.

```python
from prob_model import estimate

result = estimate(market_id="0xabc", balance=500)
print(result["fair_prob"])       # 0.61
print(result["edge"])            # +0.09
print(result["suggested_size"])  # 22.50  USDC
```

Run `poly prob --market-id ID --balance N` before sizing any trade.
</details>

<details>
<summary><b>time_decay.py</b> — Resolution-timing edge (FADE / RUSH)</summary>

```bash
python scripts/time_decay.py --scan                         # scan markets nearing deadline
python scripts/time_decay.py --scan --execute --budget 25   # trade best opportunity
python scripts/time_decay.py --once                         # one scan+execute cycle
python scripts/time_decay.py --loop --interval 300          # watch every 5 minutes
python scripts/time_decay.py --max-days 3 --min-edge 0.05   # tighter filters
python scripts/time_decay.py --dry-run                      # preview without orders
python scripts/time_decay.py --status                       # show trade history
```

Two sub-strategies:
- **FADE**: buy NO when market is still priced as if the event *might* happen, but the deadline is too close — exponential decay model with `DECAY_PER_DAY=0.30`
- **RUSH**: buy YES when high-probability outcome is still *under*priced near resolution

Edge formula: `fair_no = 1 - yes_price × (1 - 0.30)^days`.  Entry if `fair_no - live_no - fee ≥ min_edge`.
</details>

<details>
<summary><b>logical_arb.py</b> — Logical constraint violation arbitrage</summary>

```bash
python scripts/logical_arb.py --scan                       # scan for violations
python scripts/logical_arb.py --scan --execute --budget 50 # trade best violation
python scripts/logical_arb.py --once                       # one cycle
python scripts/logical_arb.py --min-edge 0.04 --top 3      # tighter / fewer results
python scripts/logical_arb.py --dry-run --json             # preview as JSON
python scripts/logical_arb.py --status                     # trade history
```

Enforces strict mathematical bounds between related markets:
- **IMPLICATION**: if `P(narrow) > P(broad)` (e.g. P(Trump wins GOP primary) > P(Republican wins presidency)) → buy NO(narrow) + YES(broad)
- **MUTEX**: if `P(team A wins) + P(team B wins) > 1.0` in an exclusive tournament → buy NO on both legs

Seven built-in logic groups (trump→republican, btc_spot_etf→btc_etf, NBA/NFL champions, etc.)
</details>

<details>
<summary><b>resolution_arb.py</b> — Near-settlement guaranteed-profit arbitrage</summary>

```bash
python scripts/resolution_arb.py --scan                       # scan near-deadline markets
python scripts/resolution_arb.py --scan --max-days 1          # within 24 hours only
python scripts/resolution_arb.py --scan --execute --budget 75 # execute best opportunity
python scripts/resolution_arb.py --once                       # one cycle
python scripts/resolution_arb.py --include-anytime            # also check event-triggered markets
python scripts/resolution_arb.py --dry-run --json             # preview
python scripts/resolution_arb.py --status                     # trade history
```

Three opportunity types:
- **BOTH_SIDES**: `YES + NO > 1.0 + fees` → sell both sides → guaranteed profit at resolution
- **EXCESS_NO**: YES ≥ 0.93 but NO ≥ 0.04 → NO is mispriced high relative to near-certain outcome
- **EXCESS_YES**: symmetric case

Lowest risk of all strategies — profit is locked in before the market closes.
</details>

<details>
<summary><b>news_latency.py</b> — Sub-10-second RSS-only news trading</summary>

```bash
python scripts/news_latency.py --build-map          # build keyword→market map (run first)
python scripts/news_latency.py --loop               # continuous trading loop (10s poll)
python scripts/news_latency.py --loop --budget 20 --dry-run   # preview mode
python scripts/news_latency.py --once               # single poll cycle
python scripts/news_latency.py --status             # signal + trade history
```

Speed-optimised variant of `news_trader` — targets < 10 s from headline to order:
- RSS feeds only (no GDELT/NewsAPI — eliminates ~2s overhead)
- Pre-cached `news_latency_map.json` keyword→token_id map refreshed every 5 min
- No clustering or full impact scoring — simple keyword match + direction detection
- `MIN_EDGE = 0.05` buffer compensates for the removed slippage gate
- Poll interval hard-clamped to 10 s minimum
</details>

<details>
<summary><b>strategy_evaluator.py</b> — Performance tracker with auto-disable</summary>

```bash
python scripts/strategy_evaluator.py --report               # ranked performance table
python scripts/strategy_evaluator.py --report --json        # machine-readable
python scripts/strategy_evaluator.py --recommend            # scale-up/down suggestions
python scripts/strategy_evaluator.py --all                  # report + recommend
python scripts/strategy_evaluator.py --auto-disable         # disable ROI<0 strategies
python scripts/strategy_evaluator.py --auto-disable --min-trades 50  # require 50 trades first
python scripts/strategy_evaluator.py --reset STRATEGY       # clear a strategy's state
python scripts/strategy_evaluator.py --re-enable STRATEGY   # un-disable a strategy
```

Reads all strategy state files and computes per-strategy: ROI%, win rate, avg edge, total P&L, estimated Sharpe.
`--auto-disable` writes the disabled list into `master_state.json`; `master_bot` checks this before spawning each strategy.

Also accessible via `python scripts/master_bot.py --evaluate`.
</details>

---

## Project structure

```
OpenPoly/
├── .env.example                  ← copy to .env, add private key
├── requirements.txt
├── SKILL.md                      ← agent manifest (read by OpenClaw)
└── scripts/
    ├── _client.py                # shared CLOB client factory
    ├── _utils.py                 # shared paths, helpers, fee constant
    ├── _guards.py                # hard runtime limits — min order $, interval clamp, Gamma rate limiter
    │
    ├── setup_credentials.py      # one-time key derivation
    ├── portfolio.py
    ├── markets.py
    ├── orderbook.py
    ├── trade.py
    ├── geoblock.py           # IP geo-block check via official Polymarket API
    ├── cancel.py
    ├── open_orders.py
    ├── history.py
    ├── price_history.py
    ├── market_stats.py
    ├── research_agent.py
    ├── exposure.py
    ├── watchlist.py
    ├── redeem.py
    │
    ├── arbitrage.py
    ├── arbitrage_execute.py
    ├── auto_arbitrage.py         # automated bot (slippage-gated)
    ├── execution_simulator.py    # orderbook walk + optimal sizing
    ├── correlation_arbitrage.py  # cross-market correlated-pair arb
    │
    ├── news_trader.py            # thin CLI → delegates to news/
    └── news/                     # 4-layer pipeline package
    │   ├── sources/
    │   │   ├── gdelt.py          #   GDELT DOC 2.0 (no key)
    │   │   ├── newsapi.py        #   NewsAPI.org (optional)
    │   │   └── rss.py            #   RSS/Atom + 15 default feeds
    │   ├── normalize.py          #   dedup, fingerprint, trust weights
    │   ├── cluster.py            #   Jaccard story clustering
    │   ├── mapper.py             #   story → Polymarket markets
    │   ├── score.py              #   5-factor impact scoring
    │   └── pipeline.py           #   orchestrate all layers
    │
    ├── market_maker.py
    ├── ai_automation.py
    ├── omni_strategy.py
    ├── scheduler.py
    │
    ├── backtest.py            # replay signals on price history
    ├── eval.py                # post-resolution hit-rate scoring
    ├── risk_guard.py          # daily loss limit + kill switch
    ├── db.py                  # unified SQLite data layer
    ├── prob_model.py          # calibrated fair-probability + Kelly sizing
    ├── notifier.py            # trade open/close + lifecycle notifications → desktop + JSON log
    ├── master_bot.py          # supervised all-in-one runner — crash-restart, heartbeat, STRATEGY_REGISTRY
    ├── setup_all.py           # idempotent 8-step setup wizard
    ├── time_decay.py          # resolution-timing edge — FADE overpriced YES near deadline
    ├── logical_arb.py         # logical constraint violations — P(narrow) > P(broad) etc.
    ├── resolution_arb.py      # near-settlement YES+NO > 1 guaranteed-profit arbitrage
    ├── news_latency.py        # sub-10-second RSS-only news trading
    └── strategy_evaluator.py  # per-strategy ROI/win-rate tracker with auto-disable
```

---

## Credentials

`.env` (never committed):

```ini
POLYMARKET_PRIVATE_KEY=0xYOUR_KEY      # required — Polygon/Ethereum private key
POLYMARKET_FUNDER_ADDRESS=             # required for types 1 and 2
POLYMARKET_SIGNATURE_TYPE=0            # 0=EOA  1=POLY_PROXY  2=GNOSIS_SAFE
POLYMARKET_API_KEY=                    # auto-filled by setup_credentials.py
POLYMARKET_API_SECRET=                 # auto-filled
POLYMARKET_API_PASSPHRASE=             # auto-filled
NEWSAPI_KEY=                           # optional — newsapi.org free tier
```

**Which signature type?**

| How you access Polymarket | Type |
|---|---|
| MetaMask or hardware wallet | `0` (EOA) |
| Email / Google sign-in | `2` (GNOSIS_SAFE — most common) |
| Old Magic Link account | `1` (POLY_PROXY) |

For types `1` and `2`: export your private key from **polymarket.com → Settings → Export Key**.

---

## Security

- Private key is loaded from `.env` at runtime and never logged or transmitted
- API key/secret undergo an entropy check at startup — placeholder strings (`YOUR_KEY`, blank values, all-same-chars, keys shorter than 32 hex chars) are rejected before any network call
- Any exception that mentions a key or secret has it redacted from output — never appears in plain text logs
- Kill switch (`poly risk kill`) is wired into all autonomous bots — a single command halts `market_maker`, `auto_arbitrage`, `ai_automation`, and `trade`
- Hard input guards (`_guards.py`) enforce a minimum $1 order size in every bot at startup; values below minimum trigger a warning, suggest a fix, and abort the run — prevents accidentally trading dust amounts
- `news_trader --interval` is clamped to a minimum of 3 minutes regardless of user input — prevents Gamma API 429 rate-limit errors from rapid polling
- Gamma API calls in the news pipeline are rate-limited to 350 ms apart — prevents burst 429 errors when many stories require market lookups in a single cycle
- `.env` is in `.gitignore` — it will never be committed
- Every trade script shows a preview and requires explicit confirmation before submitting
- Order execution uses the official [py-clob-client](https://github.com/Polymarket/py-clob-client) library only
- All read operations (market scan, research, simulation) work without credentials

---

## Requirements

- **Python 3.11+**
- A Polymarket account with USDC on Polygon
- A wallet private key (MetaMask EOA or email/Magic proxy key)
- `web3` — only for `redeem.py` (included in `requirements.txt`)
- `NEWSAPI_KEY` — only for NewsAPI source in news pipeline (optional, free tier)
