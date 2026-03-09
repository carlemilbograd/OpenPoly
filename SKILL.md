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

1. **Account & Portfolio** — view balance, open positions, trade history
2. **Market Discovery** — search and list active prediction markets
3. **Orderbook & Pricing** — read live bids/asks, spreads, price history
4. **Arbitrage Detection** — scan multi-outcome markets for pricing gaps
5. **LLM Research Agent** — web-search a market topic, form a probability estimate, compare to market price, and suggest a trade
6. **Order Execution** — place limit or market orders, cancel orders

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

Always `pip install py-clob-client requests python-dotenv --quiet --break-system-packages` before running if the package is not available.

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

---

## Error Handling

- If scripts fail with `ModuleNotFoundError`: run `pip install py-clob-client requests python-dotenv --break-system-packages`
- If `401 Unauthorized`: credentials are wrong or expired — re-derive with `python scripts/setup_credentials.py`
- If `insufficient balance`: user needs to deposit USDC to their Polygon wallet
- Always show the raw error to the user if a trade fails

---

## Safety Rules

1. **Never place a trade without explicit user confirmation**
2. **Never invest more than the user specifies**
3. **Warn the user** that prediction markets carry risk and past performance is not indicative of future results
4. **Never store private keys in logs or output** — mask as `0x****...****`
