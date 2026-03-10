<div align="center">

```
 ██████╗ ██████╗ ███████╗███╗   ██╗██████╗  ██████╗ ██╗  ██╗   ██╗
██╔═══██╗██╔══██╗██╔════╝████╗  ██║██╔══██╗██╔═══██╗██║  ╚██╗ ██╔╝
██║   ██║██████╔╝█████╗  ██╔██╗ ██║██████╔╝██║   ██║██║   ╚████╔╝
██║   ██║██╔═══╝ ██╔══╝  ██║╚██╗██║██╔═══╝ ██║   ██║██║    ╚██╔╝
╚██████╔╝██║     ███████╗██║ ╚████║██║     ╚██████╔╝███████╗██║
 ╚═════╝ ╚═╝     ╚══════╝╚═╝  ╚═══╝╚═╝      ╚═════╝ ╚══════╝╚═╝
```

**An [OpenClaw](https://docs.openclaw.ai/tools/creating-skills) skill that gives your AI agent full control over a Polymarket account.**

*Trade · Research · Arbitrage · Run autonomous strategies — all via natural language.*

<br>

[![Python](https://img.shields.io/badge/Python-3.11+-3776AB?style=for-the-badge&logo=python&logoColor=white)](https://python.org)
[![Polymarket](https://img.shields.io/badge/Polymarket-CLOB%20API-6C5CE7?style=for-the-badge)](https://docs.polymarket.com)
[![OpenClaw](https://img.shields.io/badge/OpenClaw-Skill-00B894?style=for-the-badge)](https://docs.openclaw.ai)
[![Tests](https://img.shields.io/badge/Tests-100%20passing-2ECC71?style=for-the-badge&logo=pytest&logoColor=white)](tests/)
[![License](https://img.shields.io/badge/License-MIT-95A5A6?style=for-the-badge)](LICENSE)

</div>

---

## What is this?

OpenPoly bridges your OpenClaw AI agent and a live Polymarket account. The agent reads `SKILL.md` to understand every capability, then invokes the right script for whatever you ask — from a quick portfolio check to running a supervised suite of nine concurrent trading strategies.

```
You ──► "Find arbitrage and run the news pipeline dry"
              │
              ▼
         OpenClaw Agent  (reads SKILL.md)
              │
       ┌──────┴────────┐
       ▼               ▼
correlation_       news_trader.py
arbitrage.py       --once --dry-run
--scan
       │               │
       └──────┬─────────┘
              ▼
         Results streamed back to you
```

No dashboard. No intermediary. Just your agent and a complete trading toolkit.

---

## Quickstart

```bash
# 1 — Clone into OpenClaw skills directory
git clone https://github.com/carlemilbograd/OpenPoly.git \
  ~/.openclaw/workspace/skills/polymarket

# 2 — Install dependencies
cd ~/.openclaw/workspace/skills/polymarket
pip install -r requirements.txt

# 3 — Run the interactive setup wizard
#   Walks you through: private key · signature type · API credential derivation
#   · Telegram notifications · NewsAPI key · proxy · risk limits · database
python scripts/setup_all.py

# 4 — Reload OpenClaw skills, then just talk to your agent ✓
```

> [!TIP]
> The wizard asks for your private key, signature type (0 = MetaMask, 2 = email/Google), optional Telegram and NewsAPI keys, and derives your API credentials automatically. Run `setup_all.py --yes` for a non-interactive / scripted setup.

> [!NOTE]
> **Manual alternative** — skip the wizard and edit `.env` directly: `cp .env.example .env && nano .env`, then run `python scripts/setup_credentials.py`. See the [Credentials](#credentials) section for the full list of variables.

---

## Talk to your agent

```
"Show my Polymarket portfolio"
"Find the best arbitrage opportunity right now"
"Execute the arbitrage with a $100 budget"
"Start the news pipeline in dry-run mode"
"Make markets on near-50/50 high-volume markets"
"Run all strategies with $500"
"Alert me when this market crosses 0.70"
"Simulate how much slippage a $200 buy would cause"
"How are my strategies performing?"
"Stop everything immediately"
```

<details>
<summary><b>Full natural language → script reference</b></summary>

| What you say | Script called |
|---|---|
| Show portfolio / balance | `portfolio.py` |
| Search for markets | `markets.py --query …` |
| Find arbitrage | `arbitrage.py` |
| Execute arbitrage | `arbitrage_execute.py --scan --budget 100` |
| Start auto arb bot | `auto_arbitrage.py --interval 15m` |
| Monitor markets, alert on moves | `auto_monitor.py --loop` |
| Show orderbook | `orderbook.py --token-id …` |
| Price chart | `price_history.py --token-id …` |
| Deep market stats | `market_stats.py --market-id …` |
| Research + suggest trade | `research_agent.py` |
| Buy/Sell | `trade.py` (confirmation gate) |
| Am I geo-blocked? | `geoblock.py` |
| Open orders | `open_orders.py` |
| Cancel orders | `cancel.py --all` |
| Trade history | `history.py` |
| Portfolio risk / exposure | `exposure.py` |
| Set price alert | `watchlist.py add --above 0.70` |
| Simulate slippage | `execution_simulator.py` |
| Correlated-pair arb | `correlation_arbitrage.py --scan` |
| Trade on news | `news_trader.py --once` |
| Market making | `market_maker.py --scan-targets` |
| AI signals | `ai_automation.py --once --signals` |
| Run all strategies | `master_bot.py --start --budget 500` |
| Scan timing mispricings | `time_decay.py --scan` |
| Logical constraint arb | `logical_arb.py --scan --execute` |
| Near-settlement arb | `resolution_arb.py --once` |
| Fast RSS news trading | `news_latency.py --loop` |
| Strategy performance | `strategy_evaluator.py --report` |
| Auto-disable losers | `strategy_evaluator.py --auto-disable` |
| First-time setup | `setup_all.py --yes` |
| Redeem winnings | `redeem.py` |
| Kill all bots NOW | `stopall.py` |
| Schedule a job | `scheduler.py add` |

</details>

---

## Capability overview

| Area | What's included |
|---|---|
| 📊 **Portfolio** | Balance, open positions, P&L, concentration risk, max loss/gain |
| 🔍 **Research** | Market search, orderbook, price history, deep stats, prob model, Kelly sizing |
| ⚡ **Trading** | Limit (GTC/GTD) orders — 5-point preflight dry-run, confirmation gate |
| 📐 **Arbitrage** | Scanner, executor, automated bot, correlation arb, slippage simulator |
| 📰 **News trading** | 4-layer pipeline: GDELT + NewsAPI + RSS → dedup → cluster → score → gate |
| ⚡ **News latency** | Sub-10 s RSS-only path — pre-cached keyword map, no clustering overhead |
| 🤖 **Market making** | Bid/ask spread earning, inventory skew, tick-aware queue preservation |
| 🧠 **AI signals** | Momentum + volume + mean-reversion heuristic signal engine |
| 🕐 **Time decay arb** | FADE/RUSH on resolution-timing mispricings, exponential decay model |
| 🔗 **Logical arb** | Implication + mutex constraint enforcement across related markets |
| 🏁 **Resolution arb** | Near-settlement YES+NO > 1 guaranteed-profit — lowest risk strategy |
| 🎛️ **Master bot** | Supervised runner — crash-restart, heartbeat, `--only` subset, kill-switch aware |
| 📅 **Scheduler** | Cron-style daemon — any script, any interval, zero extra deps |
| 📈 **Backtesting** | Replay momentum / mean-reversion on resolved market price history |
| 🏆 **Evaluator** | Per-strategy ROI / win-rate / Sharpe tracker, auto-disables losers |
| 🛡️ **Risk guard** | Max daily loss cap, position size limits, manual kill switch |
| 🗄️ **DB layer** | Unified SQLite — articles, signals, trades, outcomes, source accuracy |
| 🔔 **Notifications** | macOS banners + Telegram push + persistent JSON log on every trade event |
| 🚨 **Emergency stop** | `poly stopall` — 3-layer bot hunt (state files → PID → pgrep), SIGKILL fallback |
| 🧪 **Tests** | 100 pytest tests, GitHub Actions CI |

---

## Autonomous strategies

The nine trading strategies are managed by `master_bot.py` as supervised subprocesses with automatic crash-restart, heartbeat notifications, and a per-strategy budget split.

```
master_bot.py  ──────────────────────────────────────────────────────────────
│
├── auto_arbitrage      (arb)    25% ─── continuous loop, 5 min interval
├── time_decay          (td)     15% ─── continuous loop, 5 min interval
├── market_maker        (mm)     15% ─── continuous loop, 30 s interval
├── correlation_arb     (corr)   10% ─── scan-only, respawned every 30 min ★
├── news_trader         (news)   10% ─── continuous loop, 5 min interval
├── logical_arb         (la)     10% ─── scan-only, respawned every 1 h ★
├── ai_automation       (ai)      5% ─── continuous loop, 30 min interval
├── resolution_arb      (res)     5% ─── scan-only, respawned every 1 h ★
├── news_latency        (nl)      5% ─── continuous loop, 10 s interval
└── auto_monitor        (mon)     0% ─── alerts only, no trading
```

★ *Scan-only scripts exit normally after one pass. The master treats a clean exit as "done" — not a crash — and re-spawns on a fixed schedule rather than incrementing the restart counter.*

```bash
# Start everything
python scripts/master_bot.py --start --budget 1000

# Start a subset
python scripts/master_bot.py --start --only arb,mm,news --budget 500

# Live status
python scripts/master_bot.py --status

# P&L summary
python scripts/master_bot.py --pnl

# Stop gracefully
python scripts/master_bot.py --stop

# Nuclear stop (all bots, incl. scheduler & zombies)
python scripts/stopall.py
```

---

## News trading pipeline

```
GDELT (free, 65+ languages)  ─┐
NewsAPI (optional, free key)  ─┼─► normalize ─► cluster ─► map ─► score ─► gate ─► trade
RSS feeds (15 curated)        ─┘
```

| Layer | File | Role |
|---|---|---|
| L1 Ingest | `sources/gdelt.py` | GDELT DOC 2.0 — no key, broad breaking news |
| L1 Ingest | `sources/newsapi.py` | NewsAPI.org — optional, richer metadata |
| L1 Ingest | `sources/rss.py` | 15 curated feeds (White House, Fed, Reuters, AP, SCOTUS…) |
| L2 Normalize | `normalize.py` | SHA-1 fingerprints, 60-domain trust table, age filter |
| L2b Cluster | `cluster.py` | Jaccard token-set → one representative per real event |
| L3 Map | `mapper.py` | Keywords → Gamma API → story↔market relevance |
| L4 Score | `score.py` | `impact = (trust · novelty · relevance · specificity · urgency)^⅕` |
| Gate | `pipeline.py` | `edge > fees + slippage + safety_buffer` — aborts if not met |

---

## Scripts

<details>
<summary><b>📊 portfolio.py</b></summary>

```bash
python scripts/portfolio.py
```
USDC cash balance and all open positions with current price, size, and value.
</details>

<details>
<summary><b>🔍 markets.py</b></summary>

```bash
python scripts/markets.py                          # top by 24h volume
python scripts/markets.py --query "US election"
python scripts/markets.py --tag politics --limit 20
python scripts/markets.py --market-id SLUG_OR_ID   # single market + token IDs
```
</details>

<details>
<summary><b>📖 orderbook.py</b></summary>

```bash
python scripts/orderbook.py --token-id TOKEN_ID
python scripts/orderbook.py --token-id TOKEN_ID --depth 10
```
</details>

<details>
<summary><b>⚡ trade.py — Place orders (confirmation gate + dry-run)</b></summary>

```bash
# Always dry-run first
python scripts/trade.py --token-id TOKEN_ID --side BUY --price 0.55 --size 10 --dry-run

# Limit order (GTC — good till cancelled, default)
python scripts/trade.py --token-id TOKEN_ID --side BUY --price 0.55 --size 10

# Limit with expiry (GTD — min 60 s)
python scripts/trade.py --token-id TOKEN_ID --side SELL --price 0.70 --size 5 \
  --type GTD --expiry 3600
```

`--dry-run` runs 5 preflight checks without submitting:

| Check | What it catches |
|---|---|
| Credentials | Bad / expired API key |
| Balance | Insufficient USDC |
| Market active | Closed market or wrong token ID |
| Geoblock | `403`/`451` from Polymarket |
| Order signing | Key format errors (local crypto only — no POST) |

All orders show a preview and require explicit confirmation before submitting.
</details>

<details>
<summary><b>🔔 notifier.py — Trade notifications (desktop + Telegram + JSON)</b></summary>

```bash
poly notify                        # last 20 notifications
poly notify --limit 50
poly notify --since 2h
poly notify --bot auto_arbitrage
poly notify --event trade_opened
poly notify --json
poly notify --clear
poly notify --test-telegram        # verify credentials + send test message
```

Every trade event fires a macOS Notification Center banner and appends a record to `logs/trade_notifications.json`. Set `TELEGRAM_BOT_TOKEN` + `TELEGRAM_CHAT_ID` in `.env` to also receive every alert in Telegram.

> **Telegram setup:** message `@BotFather` → `/newbot` → copy token. Send your bot any message, then visit `https://api.telegram.org/bot<TOKEN>/getUpdates` to find your `chat_id`. Run `poly notify --test-telegram` — it now shows the exact API error if anything is wrong.

> [!NOTE]
> The notifier always connects directly to Telegram — `POLYMARKET_PROXY` is intentionally ignored. The proxy is only for Polymarket CLOB order placement.

Hooks are `try/except`-wrapped — they **never crash a live bot**.
</details>

<details>
<summary><b>🌍 geoblock.py — IP geo-block check</b></summary>

```bash
poly geoblock
poly geoblock --json
```

| Status | Meaning |
|---|---|
| `ok` | Trading fully permitted |
| `close_only` | Can close existing positions only (PL, SG, TH, TW) |
| `blocked` | Region restricted (AU, DE, FR, GB, US, others) |

No credentials required.
</details>

<details>
<summary><b>cancel.py · open_orders.py · history.py</b></summary>

```bash
python scripts/cancel.py --order-id ORDER_ID
python scripts/cancel.py --all
python scripts/cancel.py --market-id TOKEN_ID

python scripts/open_orders.py
python scripts/open_orders.py --side BUY
python scripts/open_orders.py --json     # shows age, fill %, exposure

python scripts/history.py --limit 20
python scripts/history.py --market-id TOKEN_ID
```
</details>

<details>
<summary><b>📈 price_history.py — ASCII price chart</b></summary>

```bash
python scripts/price_history.py --token-id TOKEN_ID --interval 1h
python scripts/price_history.py --token-id TOKEN_ID --start 2024-01-01
python scripts/price_history.py --token-id TOKEN_ID --raw
```
ASCII sparkline with min/max/mean/volatility. Intervals: `1m 5m 15m 1h 6h 1d 1w max`.
</details>

<details>
<summary><b>📊 market_stats.py · research_agent.py · exposure.py · watchlist.py</b></summary>

```bash
python scripts/market_stats.py --market-id MARKET_ID_OR_SLUG
# → price changes (1h/24h/7d), orderbook depth, open interest, top holders, recent trades

python scripts/research_agent.py --market-id MARKET_ID_OR_SLUG
python scripts/research_agent.py --query "Will X happen?"
# → structured research brief with Kelly sizing formula

python scripts/exposure.py
python scripts/exposure.py --warn-threshold 0.30
# → concentration per position, correlated groups by tag, max loss/gain, cash ratio

python scripts/watchlist.py add --token-id TOKEN_ID --above 0.70
python scripts/watchlist.py add --token-id TOKEN_ID --below 0.30
python scripts/watchlist.py check --loop --interval 60
python scripts/watchlist.py list
python scripts/watchlist.py remove --token-id TOKEN_ID
```
</details>

<details>
<summary><b>💸 redeem.py — Redeem resolved winning positions</b></summary>

```bash
python scripts/redeem.py --dry-run   # always run this first
python scripts/redeem.py
python scripts/redeem.py --market-id CONDITION_ID
```
Calls `redeemPositions()` on the Polymarket CTF contract on Polygon. Requires `web3`. Set `POLYGON_RPC_URL` in `.env` (defaults to `https://polygon-rpc.com`).
</details>

---

<details>
<summary><b>📐 arbitrage.py · arbitrage_execute.py</b></summary>

```bash
python scripts/arbitrage.py                              # default: 3% min gap, top 50
python scripts/arbitrage.py --min-gap 0.02 --tag politics --limit 100
python scripts/arbitrage.py --live

python scripts/arbitrage_execute.py --scan --budget 100
python scripts/arbitrage_execute.py --market-id ID --budget 50
python scripts/arbitrage_execute.py --scan --min-gap 0.04
```
`arbitrage.py` finds markets where YES + NO don't sum to 1.0. `arbitrage_execute.py` calculates position sizes, checks liquidity, and places all legs after confirmation.
</details>

<details>
<summary><b>🤖 auto_arbitrage.py — Automated arbitrage bot</b></summary>

```bash
python scripts/auto_arbitrage.py --interval 15m --min-gap 0.005 --budget-pct 0.10
python scripts/auto_arbitrage.py --interval 1h  --min-gap 0.01  --budget-pct 0.05 --dry-run
python scripts/auto_arbitrage.py --once --min-gap 0.005 --budget-pct 0.05
python scripts/auto_arbitrage.py --status
```
Every order is slippage-checked via `execution_simulator` before placement.
</details>

<details>
<summary><b>⚖️ execution_simulator.py — Orderbook slippage simulation</b></summary>

```bash
python scripts/execution_simulator.py --token-id TOKEN --size 50 --edge 0.07
python scripts/execution_simulator.py --token-id TOKEN --optimal-size --edge 0.06 --budget 200
```
Walks the live orderbook to estimate average fill price, slippage %, and net profit. Binary-searches for the optimal order size that maximises edge after slippage and fees. Used as an import gate by `auto_arbitrage.py` and `news_trader.py`.
</details>

<details>
<summary><b>🔗 correlation_arbitrage.py — Cross-market correlated-pair arb</b></summary>

```bash
python scripts/correlation_arbitrage.py --scan
python scripts/correlation_arbitrage.py --scan --min-edge 0.03
python scripts/correlation_arbitrage.py --scan --execute --budget 100
python scripts/correlation_arbitrage.py --graph
python scripts/correlation_arbitrage.py --once
```
Builds a keyword graph across all active markets. Finds pairs like "Trump wins" + "Republican wins" where prices are logically inconsistent — and trades both legs simultaneously. Respawned by master_bot every 30 min.
</details>

---

<details>
<summary><b>📰 news_trader.py — 4-layer news pipeline</b></summary>

```bash
python scripts/news_trader.py --once
python scripts/news_trader.py --loop --interval 5
python scripts/news_trader.py --loop --interval 5 --dry-run
python scripts/news_trader.py --sources
python scripts/news_trader.py --history --limit 20
```

Key flags: `--min-edge 0.06` · `--min-impact 0.15` · `--min-relevance 0.15` · `--safety-buffer 0.02` · `--max-age 60` · `--newsapi-key KEY`

Set `NEWSAPI_KEY` in `.env` for richer article metadata. GDELT works with no key. Interval clamped to ≥ 3 minutes.
</details>

<details>
<summary><b>⚡ news_latency.py — Sub-10-second RSS-only news trading</b></summary>

```bash
python scripts/news_latency.py --build-map          # build keyword map (run first)
python scripts/news_latency.py --loop               # continuous 10 s poll
python scripts/news_latency.py --loop --dry-run
python scripts/news_latency.py --once
python scripts/news_latency.py --status
```

Speed-optimised vs `news_trader`: RSS-only (no GDELT/NewsAPI overhead), pre-cached `news_latency_map.json` keyword→token_id map rebuilt every 5 min, no clustering pass, hard-minimum 10 s poll interval.
</details>

---

<details>
<summary><b>🤖 market_maker.py — Post bid/ask quotes, earn the spread</b></summary>

```bash
python scripts/market_maker.py --scan-targets
python scripts/market_maker.py --market-id TOKEN --spread 0.02 --size 10
python scripts/market_maker.py --loop --interval 30
python scripts/market_maker.py --once
python scripts/market_maker.py --status
python scripts/market_maker.py --close --market-id TOKEN
```
Targets near-50/50 high-volume markets. Checks queue position before re-quoting (skips repost if within one tick of best bid/ask). Tracks partial fills ≥50% and updates inventory immediately to avoid over-quoting.
</details>

<details>
<summary><b>🧠 ai_automation.py — Heuristic signal engine</b></summary>

```bash
python scripts/ai_automation.py --once
python scripts/ai_automation.py --research-top 50 --once
python scripts/ai_automation.py --signals
python scripts/ai_automation.py --once --execute --min-confidence 0.7
python scripts/ai_automation.py --loop --interval 30
```
Runs momentum, volume, and mean-reversion analysis across top markets. Signals saved to `ai_signals.json`. Designed as a drop-in slot for an LLM inference call.
</details>

<details>
<summary><b>🕐 time_decay.py — Resolution-timing edge (FADE / RUSH)</b></summary>

```bash
python scripts/time_decay.py --scan
python scripts/time_decay.py --scan --execute --budget 25
python scripts/time_decay.py --once
python scripts/time_decay.py --loop --interval 300
python scripts/time_decay.py --dry-run --status
```

- **FADE** — buy NO when the deadline is too close for YES to resolve: `fair_no = 1 - yes × (1 − 0.30)^days`
- **RUSH** — buy YES when a high-probability outcome is still underpriced near resolution

Entry filter: `fair_no − live_no − fee ≥ min_edge`. Window: ≤7 days.
</details>

<details>
<summary><b>🔗 logical_arb.py — Logical constraint violation arb</b></summary>

```bash
python scripts/logical_arb.py --scan
python scripts/logical_arb.py --scan --execute --budget 50
python scripts/logical_arb.py --once
python scripts/logical_arb.py --dry-run --json
```

- **IMPLICATION** — `P(Trump wins primary) > P(Republican wins presidency)` → buy NO(narrow) + YES(broad)
- **MUTEX** — `P(team A) + P(team B) > 1.0` in an exclusive tournament → buy NO on both legs

7 built-in logic groups. Respawned by master_bot every 1 h.
</details>

<details>
<summary><b>🏁 resolution_arb.py — Near-settlement guaranteed profit</b></summary>

```bash
python scripts/resolution_arb.py --scan
python scripts/resolution_arb.py --scan --max-days 1
python scripts/resolution_arb.py --scan --execute --budget 75
python scripts/resolution_arb.py --include-anytime
python scripts/resolution_arb.py --dry-run --json
```

Three opportunity types:
- **BOTH_SIDES** — `YES + NO > 1.0 + fees` → sell both → guaranteed profit at resolution
- **EXCESS_NO** — YES ≥ 0.93, NO ≥ 0.04 → NO is mispriced high
- **EXCESS_YES** — symmetric case

Lowest risk of all strategies. Profit locked in before the market closes. Respawned every 1 h.
</details>

---

<details>
<summary><b>📅 scheduler.py — Background cron daemon</b></summary>

```bash
python scripts/scheduler.py add \
  --name auto_arbitrage \
  --script auto_arbitrage.py \
  --args "--min-gap 0.005 --budget-pct 0.05 --once" \
  --interval 15m

python scripts/scheduler.py start --background
python scripts/scheduler.py status
python scripts/scheduler.py stop
python scripts/scheduler.py list
python scripts/scheduler.py disable --name auto_arbitrage
python scripts/scheduler.py remove  --name auto_arbitrage
```
Logs to `logs/job_<name>_YYYY-MM-DD.log`. Zero extra dependencies.
</details>

<details>
<summary><b>🔭 auto_monitor.py — Market alerts daemon</b></summary>

```bash
python scripts/auto_monitor.py --once
python scripts/auto_monitor.py --loop --interval 1h
python scripts/auto_monitor.py --alerts --since 24h
python scripts/auto_monitor.py --once --price-move 0.08
```
Fires alerts for: price moves ≥5pp, arb gaps ≥3%, volume spikes, near-50/50 extremes. Alert log: `logs/monitor_alerts.json`.
</details>

---

<details>
<summary><b>📉 backtest.py — Replay signals on historical prices</b></summary>

```bash
python scripts/backtest.py --strategy momentum --limit 25
python scripts/backtest.py --strategy mean-revert --tag politics
python scripts/backtest.py --token-id TOKEN_ID --start 2024-06-01
python scripts/backtest.py --results
```
Fetches OHLC from the CLOB API, applies the signal rule, simulates fills with spread + fee, and reports: hit rate, total PnL, Sharpe ratio, max drawdown, avg PnL per trade. Results saved to `backtest_results.json`.
</details>

<details>
<summary><b>🏆 strategy_evaluator.py — Per-strategy ROI / Sharpe tracker</b></summary>

```bash
python scripts/strategy_evaluator.py --report
python scripts/strategy_evaluator.py --recommend
python scripts/strategy_evaluator.py --auto-disable --min-trades 50
python scripts/strategy_evaluator.py --re-enable STRATEGY
python scripts/strategy_evaluator.py --reset STRATEGY
```
Computes ROI%, win rate, avg edge, total P&L, estimated Sharpe per strategy. `--auto-disable` writes the disable list into `master_state.json` — master_bot checks this before spawning each strategy. Also accessible via `master_bot.py --evaluate`.
</details>

<details>
<summary><b>✅ eval.py — Post-resolution signal hit-rate scoring</b></summary>

```bash
python scripts/eval.py
python scripts/eval.py --since 7d
python scripts/eval.py --source news
python scripts/eval.py --report
python scripts/eval.py --report --json
python scripts/eval.py --reset
```
Reads trade logs, queries Gamma for resolved outcomes, compares each signal's predicted direction vs what actually happened. Outputs hit rate by source + per-signal accuracy table.
</details>

<details>
<summary><b>🛡️ risk_guard.py — Daily loss limit + kill switch</b></summary>

```bash
python scripts/risk_guard.py status
python scripts/risk_guard.py set --max-daily-loss 0.05    # 5% daily cap
python scripts/risk_guard.py set --max-position-pct 0.20  # 20% max per trade
python scripts/risk_guard.py kill     # halt all trading immediately
python scripts/risk_guard.py reset    # resume + start new day
python scripts/risk_guard.py check --size 50 --balance 400
python scripts/risk_guard.py history
```

```python
from risk_guard import check_limits, is_killed
ok, reason = check_limits(trade_size_usd=50, current_balance=400)
```

Config and daily P&L stored in `risk_state.json`.
</details>

<details>
<summary><b>🗄️ db.py — Unified SQLite data layer</b></summary>

```bash
python scripts/db.py status
python scripts/db.py migrate   # absorb legacy JSON state → DB (run once after upgrade)
python scripts/db.py accuracy
python scripts/db.py signals --limit 20
python scripts/db.py trades  --limit 20
python scripts/db.py vacuum
```

```python
from db import DB
with DB() as db:
    db.insert_signal(source="news", market_id="0xabc", direction="YES",
                     confidence=0.72, edge_estimate=0.09)
    accuracy = db.accuracy_by_source()  # {"news": {"hit_rate": 0.70, ...}}
```
All state in `openpoly.db` (WAL mode).
</details>

<details>
<summary><b>🔢 prob_model.py — Calibrated fair probability + Kelly sizing</b></summary>

```bash
python scripts/prob_model.py --market-id ID
python scripts/prob_model.py --market-id ID --balance 500
python scripts/prob_model.py --market-id ID --show-signals
python scripts/prob_model.py --market-id ID --json
python scripts/prob_model.py --market-id ID --save
```

Algorithm: market price → Bayesian prior → weighted signal updates (news/AI/arb) → source credibility from DB accuracy table → time decay on old signals → shrinkage toward market price → quarter-Kelly position size.

```python
from prob_model import estimate
result = estimate(market_id="0xabc", balance=500)
# {"fair_prob": 0.61, "edge": +0.09, "suggested_size": 22.50}
```
</details>

<details>
<summary><b>🚨 stopall.py — Nuclear stop</b></summary>

```bash
poly stopall              # stop everything + activate kill switch
poly stopall --dry-run    # show what would be killed, do nothing
poly stopall --force      # skip 3 s grace, SIGKILL immediately
poly stopall --no-guard   # kill processes but don't activate kill switch
```

Three-layer bot hunt:

| Layer | Method | Catches |
|---|---|---|
| 1 | Reads `master_state.json` + `omni_state.json` | Bots started via master / omni |
| 2 | Reads `scheduler.pid` | Scheduler daemon |
| 3 | `pgrep -f` over all 13 bot script names | Orphans, zombies, manually started processes |

Sequence: `SIGTERM` → 3 s grace → `SIGKILL` survivors. Clears stored PIDs, then activates the risk_guard kill switch.

Resume trading: `poly risk reset`
</details>

<details>
<summary><b>🧙 setup_all.py — Automated first-time setup wizard</b></summary>

```bash
python scripts/setup_all.py          # interactive
python scripts/setup_all.py --yes    # non-interactive, accept all defaults
python scripts/setup_all.py --dry-run --yes
python scripts/setup_all.py --skip-creds
```
8 idempotent steps: dependencies · .env · private key validation · API credentials · risk guard defaults · scheduler default jobs · DB migration · geo-block check. Safe to re-run at any time.
</details>

---

## Project structure

```
OpenPoly/
├── .env                          ← secrets (never committed)
├── .env.example
├── requirements.txt
├── SKILL.md                      ← agent manifest (read by OpenClaw)
└── scripts/
    ├── _client.py                # shared CLOB client factory
    ├── _utils.py                 # shared paths, helpers, fee constant
    ├── _guards.py                # hard runtime limits: $1 min order, interval clamp, rate limiter
    │
    ├── setup_credentials.py      # one-time API key derivation
    ├── setup_all.py              # 8-step automated setup wizard
    ├── notifier.py               # trade events → macOS banner + Telegram + JSON log
    ├── risk_guard.py             # daily loss cap + kill switch
    ├── db.py                     # unified SQLite: articles, signals, trades, outcomes
    ├── prob_model.py             # Bayesian fair-prob + quarter-Kelly sizing
    ├── strategy_evaluator.py     # per-strategy ROI/Sharpe + auto-disable
    ├── master_bot.py             # supervised runner: crash-restart, heartbeat, STRATEGY_REGISTRY
    ├── stopall.py                # 3-layer nuclear stop
    │
    ├── portfolio.py
    ├── markets.py
    ├── orderbook.py
    ├── trade.py                  # limit orders — dry-run preflight + confirmation gate
    ├── geoblock.py
    ├── cancel.py
    ├── open_orders.py
    ├── history.py
    ├── price_history.py          # ASCII sparkline chart
    ├── market_stats.py           # deep analysis: depth, OI, holders, recent trades
    ├── research_agent.py
    ├── exposure.py               # concentration risk, max loss/gain, cash ratio
    ├── watchlist.py              # price alert daemon
    ├── redeem.py                 # CTF contract redemption via web3
    │
    ├── arbitrage.py
    ├── arbitrage_execute.py
    ├── auto_arbitrage.py         # automated bot (slippage-gated)
    ├── execution_simulator.py    # orderbook walk + optimal sizing
    ├── correlation_arbitrage.py  # cross-market correlated-pair arb
    ├── time_decay.py             # FADE/RUSH resolution-timing edge
    ├── logical_arb.py            # implication + mutex constraint enforcement
    ├── resolution_arb.py         # near-settlement YES+NO>1 guaranteed arb
    │
    ├── news_trader.py            # CLI → delegates to news/ pipeline
    ├── news_latency.py           # sub-10 s RSS-only speed variant
    └── news/
        ├── sources/
        │   ├── gdelt.py          #   GDELT DOC 2.0 (no key)
        │   ├── newsapi.py        #   NewsAPI.org (optional)
        │   └── rss.py            #   RSS/Atom + 15 default feeds
        ├── normalize.py          #   dedup, fingerprint, trust weights
        ├── cluster.py            #   Jaccard story clustering
        ├── mapper.py             #   story → Polymarket markets
        ├── score.py              #   5-factor impact scoring
        └── pipeline.py           #   orchestrate all layers
    │
    ├── market_maker.py           # bid/ask spread earning, inventory skew
    ├── ai_automation.py          # momentum + mean-reversion signals
    ├── omni_strategy.py          # legacy all-in-one runner (use master_bot instead)
    ├── scheduler.py              # cron-style background daemon
    ├── auto_monitor.py           # price move / arb gap / volume alerts
    ├── backtest.py               # replay signals on resolved market history
    └── eval.py                   # post-resolution signal hit-rate scoring
```

---

## Credentials

`.env` (never committed):

```ini
POLYMARKET_PRIVATE_KEY=0xYOUR_KEY      # required — Polygon/Ethereum private key
POLYMARKET_FUNDER_ADDRESS=             # required for signature types 1 and 2
POLYMARKET_SIGNATURE_TYPE=0            # 0=EOA  1=POLY_PROXY  2=GNOSIS_SAFE

POLYMARKET_API_KEY=                    # auto-filled by setup_credentials.py
POLYMARKET_API_SECRET=                 # auto-filled
POLYMARKET_API_PASSPHRASE=             # auto-filled

NEWSAPI_KEY=                           # optional — newsapi.org free tier
POLYGON_RPC_URL=                       # optional — defaults to https://polygon-rpc.com

POLYMARKET_PROXY=                      # optional — proxy for CLOB orders (geo-blocked regions)
TELEGRAM_BOT_TOKEN=                    # optional — push all trade alerts to Telegram
TELEGRAM_CHAT_ID=                      # required with BOT_TOKEN — your chat / group ID
```

**Which signature type do I need?**

| How you connected to Polymarket | Type |
|---|---|
| MetaMask or hardware wallet | `0` (EOA) |
| Email / Google sign-in | `2` (GNOSIS_SAFE) — most common |
| Old Magic Link account | `1` (POLY_PROXY) |

For types `1` and `2`: export your private key from **polymarket.com → Settings → Export Key**.

**Geo-blocked?** Set `POLYMARKET_PROXY` to route CLOB order traffic through a proxy:
```ini
POLYMARKET_PROXY=socks5h://127.0.0.1:1080
```
Start a reverse SSH tunnel with: `ssh -D 1080 -N user@your-server`. Supports `http://`, `https://`, `socks5://`, `socks5h://`. Telegram notifications are always direct — they bypass the proxy regardless.

---

## Security

- Private key loaded from `.env` at runtime — never logged or transmitted
- API keys undergo entropy check at startup — placeholders, blank values, all-same-chars, and keys shorter than 32 hex chars are rejected before any network call
- Exception messages with key/secret values are redacted — never appear in plain text logs
- Kill switch (`poly risk kill`) is wired into every autonomous bot — one command halts all trading
- Hard input guards (`_guards.py`) enforce minimum $1 order size at startup in every bot
- `news_trader --interval` clamped to ≥ 3 minutes regardless of user input
- Gamma API rate-limited in the news pipeline to 350 ms between calls
- `.env` is in `.gitignore` — will never be committed
- Every trade script shows a full preview and requires explicit `y` confirmation before submitting
- All read operations (market scan, research, simulation) work with zero credentials

---

## Requirements

- **Python 3.11+**
- A Polymarket account with USDC on Polygon
- A wallet private key (MetaMask EOA or email/Magic proxy key)
- `web3` — only for `redeem.py` (included in `requirements.txt`)
- `NEWSAPI_KEY` — only for the NewsAPI source in the news pipeline (optional, free tier)
