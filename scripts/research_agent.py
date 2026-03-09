#!/usr/bin/env python3
"""
LLM Research Agent for Polymarket.
Fetches market details, then outputs a structured research prompt for the agent
to use with web search to estimate probability and suggest a trade.

Usage:
  python research_agent.py --market-id MARKET_ID_OR_SLUG
  python research_agent.py --token-id TOKEN_ID
  python research_agent.py --query "Who will win the 2025 UK election?"
"""
import sys, requests, argparse, json
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from _client import GAMMA_API, get_client

def fetch_market(market_id: str) -> dict | None:
    # Try by ID first
    resp = requests.get(f"{GAMMA_API}/markets/{market_id}")
    if resp.ok:
        return resp.json()
    # Try by slug
    resp = requests.get(f"{GAMMA_API}/markets", params={"slug": market_id, "limit": 1})
    if resp.ok:
        data = resp.json()
        return data[0] if data else None
    return None

def get_market_price(token_id: str) -> float | None:
    try:
        client = get_client(authenticated=False)
        resp = client.get_midpoint(token_id)
        return float(resp.get("mid", 0))
    except Exception:
        return None

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--market-id", "-m", default="")
    parser.add_argument("--token-id", "-t", default="")
    parser.add_argument("--query", "-q", default="")
    args = parser.parse_args()

    market = None

    if args.market_id:
        market = fetch_market(args.market_id)
    elif args.query:
        resp = requests.get(f"{GAMMA_API}/events", params={"q": args.query, "limit": 5})
        events = resp.json() if resp.ok else []
        all_markets = []
        for ev in events:
            all_markets.extend(ev.get("markets", []))
        if all_markets:
            market = all_markets[0]
            print(f"Found market: {market.get('question','?')}")

    if not market and not args.token_id:
        print("No market found. Use --market-id, --token-id, or --query.")
        sys.exit(1)

    # Build research context
    if market:
        question = market.get("question", "?")
        description = market.get("description", "")
        close_date = market.get("endDate", "?")
        tokens = market.get("tokens", [])

        prices = {}
        for t in tokens:
            tid = t.get("token_id", "")
            outcome = t.get("outcome", "?")
            live_price = get_market_price(tid) if tid else None
            stored_price = t.get("price")
            price = live_price or stored_price
            if price:
                prices[outcome] = float(price)
    else:
        question = f"Token {args.token_id}"
        description = ""
        close_date = "?"
        prices = {}
        live = get_market_price(args.token_id)
        if live:
            prices["YES"] = live
            prices["NO"] = 1 - live

    # Print research brief for the agent to act on
    print(f"\n{'='*65}")
    print(f"  📊 POLYMARKET RESEARCH BRIEF")
    print(f"{'='*65}")
    print(f"  Question:   {question}")
    if description:
        print(f"  Details:    {description[:200]}")
    print(f"  Closes:     {close_date}")
    print(f"\n  Current Market Prices:")
    for outcome, price in prices.items():
        implied_prob = price * 100
        print(f"    {outcome}: {price:.3f}  (implies {implied_prob:.1f}% probability)")

    print(f"\n{'='*65}")
    print(f"  🔎 RESEARCH INSTRUCTIONS FOR AGENT")
    print(f"{'='*65}")
    print(f"""
  1. Search the web for recent news and data about:
       "{question}"

  2. Look for:
     - Official statistics, polls, or expert forecasts
     - Recent developments that change the likelihood
     - Base rates for similar historical events
     - Conflicting signals or uncertainty factors

  3. Form your probability estimate for each outcome.

  4. Compare to market prices above:
     - If your estimate > market price by >5%: consider BUYING that outcome
     - If your estimate < market price by >5%: consider SELLING (or skip)
     - Edge = |your_estimate - market_price|

  5. Kelly position sizing:
     - If edge = E and odds = 1/price:
       f = E / (1/price - 1)   [fraction of bankroll to risk]
     - Apply a fractional Kelly (e.g. 25%) for safety

  6. Output your recommendation:
     [ BUY / SELL / HOLD ] [outcome] at [price]
     Reasoning: [2-3 sentences]
     Confidence: [Low / Medium / High]
     Suggested size: $[amount] (based on stated bankroll or default $50)
""")

    if market:
        print(f"  Market ID: {market.get('id','')}")
        print(f"  Tokens:")
        for t in market.get("tokens", []):
            print(f"    [{t.get('outcome','?')}] token_id: {t.get('token_id','')}")
    print()

if __name__ == "__main__":
    main()
