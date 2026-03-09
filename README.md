# openclaw-polymarket

A full-featured **Polymarket trading skill for [OpenClaw](https://docs.openclaw.ai/tools/creating-skills)** that lets your AI agent:

- View your portfolio and open positions
- Search and browse prediction markets
- Read live orderbooks
- Scan for arbitrage opportunities
- Run LLM-powered research to find value bets
- Execute trades (with mandatory confirmation)

---

## Repo structure

```
openclaw-polymarket/
├── .env.example           # credential template — copy to .env
├── .gitignore
├── requirements.txt
├── README.md
├── SKILL.md               # OpenClaw skill manifest & agent instructions
└── scripts/
    ├── _client.py         # shared Polymarket client factory
    ├── setup_credentials.py
    ├── portfolio.py
    ├── markets.py
    ├── orderbook.py
    ├── arbitrage.py
    ├── research_agent.py
    ├── trade.py
    ├── cancel.py
    └── history.py
```

---

## Installation

```bash
# 1. Clone and enter the repo
git clone https://github.com/YOUR_USERNAME/openclaw-polymarket.git
cd openclaw-polymarket

# 2. Install Python dependencies
pip install -r requirements.txt

# 3. Set up credentials
cp .env.example .env
# ↳ edit .env and add your POLYMARKET_PRIVATE_KEY

# 4. Derive API credentials (run once)
python scripts/setup_credentials.py

# 5. Copy skill to OpenClaw workspace
cp -r . ~/.openclaw/workspace/skills/polymarket

# 6. Restart OpenClaw or say "refresh skills"
```

---

## Usage (say these to your OpenClaw agent)

| What you say | What runs |
|---|---|
| "Show my Polymarket portfolio" | `portfolio.py` |
| "Search for crypto markets on Polymarket" | `markets.py --query crypto` |
| "Find arbitrage opportunities on Polymarket" | `arbitrage.py` |
| "Show the orderbook for [token-id]" | `orderbook.py --token-id ...` |
| "Research the market about X and suggest a trade" | `research_agent.py` |
| "Buy 20 USDC of YES on [market] at 0.45" | `trade.py` (with confirmation) |
| "Cancel all my open Polymarket orders" | `cancel.py --all` |
| "Show my last 20 Polymarket trades" | `history.py --limit 20` |

---

## Scripts reference

### `setup_credentials.py`
Derives API key / secret / passphrase from your private key and writes them to `.env`. Run once.

### `portfolio.py`
Shows USDC balance, open positions (size, current price, value), and total portfolio value.

### `markets.py`
Browse top markets by 24h volume or search by keyword/tag. Prints YES/NO prices and token IDs.

```bash
python scripts/markets.py                         # top markets
python scripts/markets.py --query "US election"   # search
python scripts/markets.py --tag politics --limit 20
python scripts/markets.py --market-id SLUG_OR_ID  # single market detail
```

### `orderbook.py`
Top bids/asks, mid price, and spread for any market token.

```bash
python scripts/orderbook.py --token-id TOKEN_ID --depth 5
```

### `arbitrage.py`
Scans markets for YES + NO price sum ≠ 1.0. Reports opportunities sorted by net profit after fees.

```bash
python scripts/arbitrage.py                        # default: 3% min gap, 50 markets
python scripts/arbitrage.py --min-gap 0.02 --limit 100 --tag politics
python scripts/arbitrage.py --live                 # fetch live CLOB prices
```

### `research_agent.py`
Emits a structured research brief (question, current prices, Kelly sizing instructions) for the agent to complete with web search.

```bash
python scripts/research_agent.py --market-id MARKET_ID_OR_SLUG
python scripts/research_agent.py --query "Will X happen?"
```

### `trade.py`
Place limit (GTC/GTD) or market (FOK) orders. Always prompts for confirmation.

```bash
# Limit order
python scripts/trade.py --token-id TOKEN_ID --side BUY --price 0.55 --size 10

# Market order
python scripts/trade.py --token-id TOKEN_ID --side BUY --size 25 --type FOK

# Limit with expiry
python scripts/trade.py --token-id TOKEN_ID --side SELL --price 0.70 --size 5 --type GTD --expiry 3600
```

### `cancel.py`
```bash
python scripts/cancel.py --order-id ORDER_ID     # single order
python scripts/cancel.py --all                   # all open orders
python scripts/cancel.py --market-id TOKEN_ID    # all orders for a market
```

### `history.py`
```bash
python scripts/history.py --limit 20
python scripts/history.py --market-id TOKEN_ID
```

---

## Security

- Private key is read from `.env` and never logged or printed in full
- All `.env` files are excluded by `.gitignore`
- All trades require explicit `yes` confirmation before execution
- Uses the official [`py-clob-client`](https://github.com/Polymarket/py-clob-client) library

---

## Requirements

- Python 3.11+
- A Polymarket account with USDC on Polygon
- A wallet private key (MetaMask EOA or Magic/email proxy wallet)
