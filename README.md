# OpenPoly

An [OpenClaw](https://docs.openclaw.ai/tools/creating-skills) skill that gives your AI agent full access to a Polymarket account — read portfolio, browse markets, scan for arbitrage, run LLM-powered research, and execute trades, all via natural language.

---

## Structure

```
OpenPoly/
├── .env.example              # credential template — copy to .env and fill in
├── .gitignore
├── requirements.txt
├── SKILL.md                  # OpenClaw skill manifest (read by the agent)
├── README.md
└── scripts/
    ├── _client.py            # shared client factory (imported by all scripts)
    ├── setup_credentials.py  # derive API keys from private key — run once
    ├── portfolio.py          # USDC balance + open positions
    ├── markets.py            # search and browse markets
    ├── orderbook.py          # live bids/asks and spread
    ├── arbitrage.py          # scan for mispriced YES+NO pairs
    ├── arb_execute.py        # execute arbitrage trades with size calculation
    ├── auto_arb.py           # automated arb bot (loop or single-shot)
    ├── scheduler.py          # automation daemon — run any script on any interval
    ├── auto_monitor.py       # automated market monitor (price moves, arb gaps, alerts)
    ├── research_agent.py     # structured research brief + Kelly sizing
    ├── trade.py              # place limit or market orders
    ├── cancel.py             # cancel one, all, or per-market orders
    ├── open_orders.py        # list pending orders with age/fill/exposure
    ├── history.py            # trade history
    ├── price_history.py      # price chart over time with ASCII sparkline
    ├── market_stats.py       # deep stats combining Gamma + Data + CLOB APIs
    ├── exposure.py           # portfolio risk and concentration analysis
    ├── redeem.py             # on-chain redemption of resolved positions
    └── watchlist.py          # persistent price alerts with polling
```

---

## Installation

> One-time setup. After this the agent handles everything.

```bash
# 1. Clone into the OpenClaw skills directory
git clone https://github.com/carlemilbograd/OpenPoly.git ~/.openclaw/workspace/skills/polymarket

# 2. Install dependencies
cd ~/.openclaw/workspace/skills/polymarket
pip install -r requirements.txt

# 3. Add your private key  ← only manual step
cp .env.example .env
# Open .env and set POLYMARKET_PRIVATE_KEY=0xYOUR_KEY

# 4. Derive API credentials (writes to .env automatically)
python scripts/setup_credentials.py

# 5. Restart OpenClaw, or tell it: "refresh skills"
```

---

## Usage

Just talk to your OpenClaw agent naturally:

| Say this | Runs |
|---|---|
| "Show my Polymarket portfolio" | `portfolio.py` |
| "Search for crypto markets on Polymarket" | `markets.py --query crypto` |
| "Find arbitrage opportunities on Polymarket" | `arbitrage.py` |
| "Execute the best arbitrage opportunity with 100 USDC" | `arb_execute.py --scan --budget 100` |
| "Run auto arb every 15 minutes at 0.5% threshold" | `scheduler.py add` + `scheduler.py start --background` |
| "Start the arb bot risking 5% of balance" | `auto_arb.py --interval 15m --budget-pct 0.05` |
| "Monitor markets and alert me on price moves" | `auto_monitor.py --loop --interval 1h` |
| "Show recent market alerts" | `auto_monitor.py --alerts --since 24h` |
| "Show the orderbook for [token-id]" | `orderbook.py --token-id ...` |
| "Show price history for [token-id]" | `price_history.py --token-id ...` |
| "Show deep stats for this market" | `market_stats.py --market-id ...` |
| "Research the market about X and suggest a trade" | `research_agent.py` |
| "Buy 20 USDC of YES on [market] at 0.45" | `trade.py` (asks for confirmation) |
| "What orders do I have open?" | `open_orders.py` |
| "Cancel all my open Polymarket orders" | `cancel.py --all` |
| "Show my last 20 trades" | `history.py --limit 20` |
| "Redeem my winnings from resolved markets" | `redeem.py --dry-run` then confirm |
| "How exposed is my portfolio?" | `exposure.py` |
| "Alert me when [market] goes above 0.70" | `watchlist.py add --token-id ... --above 0.70` |
| "What automation tasks are scheduled?" | `scheduler.py status` |
| "Stop the automation daemon" | `scheduler.py stop` |

The agent reads `SKILL.md` to know exactly when and how to call each script.

---

## Scripts

All scripts are run from the skill root as `python scripts/<name>.py [args]`.

### `setup_credentials.py`
Derives API key/secret/passphrase from your private key and saves them to `.env`. Run once after setting `POLYMARKET_PRIVATE_KEY`.

### `portfolio.py`
Prints USDC cash balance and all open positions with current price, size, and value.

### `markets.py`
```bash
python scripts/markets.py                          # top markets by 24h volume
python scripts/markets.py --query "US election"   # keyword search
python scripts/markets.py --tag politics --limit 20
python scripts/markets.py --market-id SLUG_OR_ID  # single market detail + token IDs
```

### `orderbook.py`
```bash
python scripts/orderbook.py --token-id TOKEN_ID   # top 5 bids/asks, mid, spread
python scripts/orderbook.py --token-id TOKEN_ID --depth 10
```

### `arbitrage.py`
Scans markets where YES + NO prices don't sum to 1.0. Sorts results by net profit after fees.
```bash
python scripts/arbitrage.py                        # 3% min gap, top 50 markets
python scripts/arbitrage.py --min-gap 0.02 --limit 100 --tag politics
python scripts/arbitrage.py --live                 # use live CLOB prices (slower)
```

### `research_agent.py`
Fetches a market, prints current prices, and outputs a structured brief with web-search instructions and Kelly sizing formula for the agent to complete.
```bash
python scripts/research_agent.py --market-id MARKET_ID_OR_SLUG
python scripts/research_agent.py --query "Will X happen?"
```

### `trade.py`
Always shows an order preview and asks for confirmation before submitting.
```bash
# Limit order (GTC)
python scripts/trade.py --token-id TOKEN_ID --side BUY --price 0.55 --size 10

# Market order (FOK)
python scripts/trade.py --token-id TOKEN_ID --side BUY --size 25 --type FOK

# Limit with expiry (GTD)
python scripts/trade.py --token-id TOKEN_ID --side SELL --price 0.70 --size 5 --type GTD --expiry 3600
```

### `cancel.py`
```bash
python scripts/cancel.py --order-id ORDER_ID      # single order
python scripts/cancel.py --all                    # all open orders (prompts confirmation)
python scripts/cancel.py --market-id TOKEN_ID     # all orders for one market
```

### `history.py`
```bash
python scripts/history.py --limit 20
python scripts/history.py --market-id TOKEN_ID
```

### `open_orders.py`
Lists all open/unfilled orders with age, fill percentage, and total exposure.
```bash
python scripts/open_orders.py                         # all open orders
python scripts/open_orders.py --market-id TOKEN_ID    # filter by market
python scripts/open_orders.py --side BUY              # filter by side
python scripts/open_orders.py --json                  # machine-readable JSON
```

### `price_history.py`
Fetches price over time and renders an ASCII sparkline chart with statistics.
```bash
python scripts/price_history.py --token-id TOKEN_ID
python scripts/price_history.py --token-id TOKEN_ID --interval 1h   # 1m 5m 15m 1h 6h 1d 1w max
python scripts/price_history.py --token-id TOKEN_ID --start 2024-01-01 --end 2024-02-01
python scripts/price_history.py --token-id TOKEN_ID --raw            # all data points
```

### `market_stats.py`
Deep stats combining Gamma API, Data API, and CLOB. Outputs price changes (1h/24h/7d), orderbook depth, open interest, top holders, and recent trades.
```bash
python scripts/market_stats.py --market-id MARKET_ID_OR_SLUG
```

### `arb_execute.py`
Scans for or targets a specific arbitrage opportunity, calculates position sizes, checks liquidity, and places all legs after confirmation.
```bash
python scripts/arb_execute.py --scan --budget 100         # auto-find best opportunity
python scripts/arb_execute.py --market-id ID --budget 50  # specific market
python scripts/arb_execute.py --scan --min-gap 0.04       # custom gap threshold
```

### `auto_arb.py`
Automated arbitrage bot. Scans markets at a configurable interval, and executes when a gap exceeds the threshold — risking a percentage of available balance.
```bash
# Run once (for use by scheduler.py)
python scripts/auto_arb.py --once --min-gap 0.005 --budget-pct 0.05

# Self-contained loop
python scripts/auto_arb.py --interval 15m --min-gap 0.005 --budget-pct 0.10
python scripts/auto_arb.py --interval 1h  --min-gap 0.01  --budget-pct 0.05 --dry-run
python scripts/auto_arb.py --interval 30s --min-gap 0.003 --max-budget 200

# Check bot history/stats
python scripts/auto_arb.py --status
```

### `scheduler.py`
General-purpose automation daemon. Registers any script to run on any interval, then runs them in the background.
```bash
# Register jobs
python scripts/scheduler.py add --name auto_arb --script auto_arb.py \
  --args "--min-gap 0.005 --budget-pct 0.05 --once" --interval 15m
python scripts/scheduler.py add --name monitor --script auto_monitor.py \
  --args "--once" --interval 1h
python scripts/scheduler.py add --name exposure --script exposure.py \
  --args "" --interval 6h
python scripts/scheduler.py add --name watchlist --script watchlist.py \
  --args "check" --interval 5m

# Control
python scripts/scheduler.py start --background   # start daemon (detached)
python scripts/scheduler.py status               # daemon status + job list
python scripts/scheduler.py stop                 # stop daemon
python scripts/scheduler.py list                 # all jobs + next-run times
python scripts/scheduler.py disable --name auto_arb
python scripts/scheduler.py enable  --name auto_arb
python scripts/scheduler.py remove  --name auto_arb
```
Job logs: `logs/job_<name>_YYYY-MM-DD.log`. Requires no extra dependencies.

### `auto_monitor.py`
Automated market monitor. Fires alerts for: price moves ≥5pp, arb gaps ≥3%, volume spikes, near-50/50 markets, and extreme prices.
```bash
python scripts/auto_monitor.py --once                       # one scan, print new alerts
python scripts/auto_monitor.py --loop --interval 1h         # continuous monitoring
python scripts/auto_monitor.py --alerts                     # last 20 alerts
python scripts/auto_monitor.py --alerts --since 24h         # past 24 hours
python scripts/auto_monitor.py --once --price-move 0.08     # 8pp move threshold
```
Alert log: `logs/monitor_alerts.json`.

### `exposure.py`
Portfolio risk analysis: concentration per position, correlated positions grouped by tag, max loss/gain scenarios, cash ratio warning.
```bash
python scripts/exposure.py
python scripts/exposure.py --warn-threshold 0.30          # flag positions > 30% of portfolio
```

### `redeem.py`
On-chain redemption of resolved winning positions. Calls `redeemPositions()` on the Polymarket CTF contract on Polygon.
```bash
python scripts/redeem.py --dry-run                        # preview without transacting (always run first)
python scripts/redeem.py                                  # redeem all eligible positions
python scripts/redeem.py --market-id CONDITION_ID         # single market
```
Requires `web3` package (`pip install web3`). Optional env var `POLYGON_RPC_URL` (defaults to `https://polygon-rpc.com`).

### `watchlist.py`
Persistent price monitoring with above/below threshold alerts. Stores state in `watchlist.json`.
```bash
python scripts/watchlist.py add --token-id TOKEN_ID --above 0.70   # alert above 70¢
python scripts/watchlist.py add --token-id TOKEN_ID --below 0.30   # alert below 30¢
python scripts/watchlist.py list                                     # show watchlist
python scripts/watchlist.py check                                    # check all alerts once
python scripts/watchlist.py check --loop --interval 60              # poll every 60 seconds
python scripts/watchlist.py remove --token-id TOKEN_ID
```

---

## Automation

Run hands-off bots that execute in the background while you're away.

### Quick setup — auto arb every 15 minutes

```bash
# 1. Register the arb bot job
python scripts/scheduler.py add \
  --name auto_arb \
  --script auto_arb.py \
  --args "--min-gap 0.005 --budget-pct 0.05 --once" \
  --interval 15m

# 2. (Optional) also monitor for opportunities
python scripts/scheduler.py add \
  --name monitor \
  --script auto_monitor.py \
  --args "--once" \
  --interval 1h

# 3. Start the scheduler daemon
python scripts/scheduler.py start --background

# 4. Check it's running
python scripts/scheduler.py status
```

### Managing automation

```bash
python scripts/scheduler.py list                  # see all jobs + next-run times
python scripts/scheduler.py stop                  # stop everything
python scripts/scheduler.py disable --name auto_arb  # pause without removing
python scripts/auto_arb.py --status              # arb bot stats (runs, profits)
python scripts/auto_monitor.py --alerts --since 24h  # recent market alerts
```

### Available automated scripts

| Script | Description | Single-shot flag |
|---|---|---|
| `auto_arb.py` | Scan + execute arb at threshold | `--once` |
| `auto_monitor.py` | Scan for price moves, arb gaps, spikes | `--once` |
| `exposure.py` | Portfolio risk check | *(runs and exits)* |
| `watchlist.py check` | Fire watchlist price alerts | *(runs and exits)* |
| `portfolio.py` | Balance + positions snapshot | *(runs and exits)* |

---

## Credentials

The `.env` file (never committed) holds:

```
POLYMARKET_PRIVATE_KEY=0xYOUR_PRIVATE_KEY     # required — always a Polygon/Ethereum private key
POLYMARKET_FUNDER_ADDRESS=                    # required for types 1 and 2 (address shown on polymarket.com)
POLYMARKET_SIGNATURE_TYPE=0                   # 0=MetaMask/EOA  1=POLY_PROXY  2=GNOSIS_SAFE
POLYMARKET_API_KEY=                           # auto-filled by setup_credentials.py
POLYMARKET_API_SECRET=                        # auto-filled
POLYMARKET_API_PASSPHRASE=                    # auto-filled
```

**Which signature type am I?**

| How you use Polymarket | Type | Funder address needed? |
|---|---|---|
| MetaMask or hardware wallet | `0` | No — same as your wallet |
| Signed up with email / Google | `2` (GNOSIS_SAFE, most common) | Yes — shown on polymarket.com |
| Old Magic Link account | `1` (POLY_PROXY) | Yes — shown on polymarket.com |

For types `1` and `2`: export your private key from **polymarket.com → Settings → Export Key**.

---

## Security

- Private key is read from `.env` at runtime and never logged
- `.env` is in `.gitignore` — it will never be committed
- Every trade requires explicit `yes` before execution
- Uses the official [py-clob-client](https://github.com/Polymarket/py-clob-client) library

---

## Requirements

- Python 3.11+
- A Polymarket account funded with USDC on Polygon
- A wallet private key (MetaMask EOA or Magic/email proxy wallet)
- `web3` package required only for `redeem.py` (included in `requirements.txt`)
