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
    ├── research_agent.py     # structured research brief + Kelly sizing
    ├── trade.py              # place limit or market orders
    ├── cancel.py             # cancel one, all, or per-market orders
    └── history.py            # trade history
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
| "Show the orderbook for [token-id]" | `orderbook.py --token-id ...` |
| "Research the market about X and suggest a trade" | `research_agent.py` |
| "Buy 20 USDC of YES on [market] at 0.45" | `trade.py` (asks for confirmation) |
| "Cancel all my open Polymarket orders" | `cancel.py --all` |
| "Show my last 20 trades" | `history.py --limit 20` |

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
