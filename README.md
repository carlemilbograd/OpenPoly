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
| **Trading** | Limit / market / GTD orders with confirmation gate |
| **Arbitrage** | Scanner, executor, automated bot, slippage simulation |
| **Corr. Arb** | Cross-market keyword graph — finds logically linked mispriced pairs |
| **News trading** | 4-layer pipeline: GDELT + NewsAPI + RSS → dedup → cluster → score → gate |
| **Market making** | Bid/ask spread earning with inventory skew control |
| **AI signals** | Heuristic momentum + mean-reversion signal engine |
| **Omni** | One command to launch all strategies with budget split |
| **Automation** | Scheduler daemon — any script on any interval, background-safe |
| **Alerts** | Watchlist price alerts + market monitor (volume, arb gaps, extremes) |
| **On-chain** | Redeem resolved winning positions via Polygon CTF contract |

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
| Run all strategies with $500 | `omni_strategy.py --start --budget 500` |
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
<summary><b>trade.py</b> — Place orders (with confirmation)</summary>

```bash
# Limit order (GTC)
python scripts/trade.py --token-id TOKEN_ID --side BUY --price 0.55 --size 10

# Market order (FOK)
python scripts/trade.py --token-id TOKEN_ID --side BUY --size 25 --type FOK

# Limit with expiry (GTD)
python scripts/trade.py --token-id TOKEN_ID --side SELL --price 0.70 --size 5 \
  --type GTD --expiry 3600
```
Always shows an order preview and asks for confirmation before submitting.
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
<summary><b>omni_strategy.py</b> — Run every strategy at once</summary>

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
| `omni_strategy.py` | All strategies | `--once` |
| `exposure.py` | Portfolio risk check | *(runs and exits)* |
| `watchlist.py check` | Fire price alerts | *(runs and exits)* |

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
    │
    ├── setup_credentials.py      # one-time key derivation
    ├── portfolio.py
    ├── markets.py
    ├── orderbook.py
    ├── trade.py
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
    └── scheduler.py
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
