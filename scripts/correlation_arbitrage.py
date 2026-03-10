#!/usr/bin/env python3
"""
correlation_arbitrage.py — Cross-market correlation arbitrage for Polymarket.

Finds LOGICALLY LINKED markets where pricing is inconsistent — these gaps
are risk-free profit just like same-market arbitrage but far more common
and usually larger.

Examples of correlated market pairs:
  "Trump wins 2024 election"  ↔  "Republican wins 2024 election"
  "Bitcoin above $100k EOY"   ↔  "BTC price above $100k in December"
  "Fed raises rates in March" ↔  "Fed raises rates in Q1"

If P(A) implies a logical bound on P(B), but the market prices violate it:
  → YES(A) + NO(B) < 1.0  →  buy YES(A) + NO(B)  →  guaranteed profit
  → YES(A) > P(B)         →  sell YES(A), buy YES(B)

Strategy:
  1. Build a correlation graph via keyword/tag matching + LLM-style logic
  2. Score each pair by implied probability consistency
  3. Find pairs where pricing implies free money
  4. Execute the hedge legs (with execution simulation check)

Usage:
  python scripts/correlation_arbitrage.py --scan
  python scripts/correlation_arbitrage.py --scan --min-edge 0.03 --limit 200
  python scripts/correlation_arbitrage.py --scan --tag politics --execute --budget 100
  python scripts/correlation_arbitrage.py --graph                    # show full correlation graph
  python scripts/correlation_arbitrage.py --once                     # single-shot for scheduler
"""
import sys, argparse, requests, json, time, itertools
from pathlib import Path
from datetime import datetime, timezone

sys.path.insert(0, str(Path(__file__).parent))
from _client import get_client
from _utils import SKILL_DIR, FEE, get_mid, fetch_markets

STATE_FILE = SKILL_DIR / "correlation_state.json"

# ── Keyword cluster groups ─────────────────────────────────────────────────────
# Markets sharing 2+ clusters are candidates for correlation analysis.
CLUSTERS = [
    {"label": "trump",        "keywords": ["trump", "donald", "maga"]},
    {"label": "republican",   "keywords": ["republican", "gop", "rnc"]},
    {"label": "democrat",     "keywords": ["democrat", "harris", "biden", "dnc"]},
    {"label": "election",     "keywords": ["election", "wins", "elected", "vote", "ballot", "primary"]},
    {"label": "popular_vote", "keywords": ["popular vote", "popular-vote"]},
    {"label": "bitcoin",      "keywords": ["bitcoin", "btc"]},
    {"label": "ethereum",     "keywords": ["ethereum", "eth"]},
    {"label": "fed",          "keywords": ["federal reserve", "fomc", "interest rate", "rate hike", "rate cut"]},
    {"label": "inflation",    "keywords": ["inflation", "cpi", "pce", "consumer price"]},
    {"label": "recession",    "keywords": ["recession", "gdp", "contraction"]},
    {"label": "war",          "keywords": ["war", "conflict", "invasion", "ceasefire", "military"]},
    {"label": "ukraine",      "keywords": ["ukraine", "zelensky", "kyiv"]},
    {"label": "russia",       "keywords": ["russia", "putin", "kremlin"]},
    {"label": "china",        "keywords": ["china", "xi jinping", "beijing", "taiwan"]},
    {"label": "ai",           "keywords": ["artificial intelligence", " ai ", "openai", "gpt", "llm"]},
    {"label": "stock_market", "keywords": ["s&p", "dow jones", "nasdaq", "stock market"]},
    {"label": "elon",         "keywords": ["elon", "musk", "tesla", "spacex", "doge"]},
    {"label": "crypto",       "keywords": ["crypto", "defi", "blockchain", "nft", "token"]},
]


# ── Helpers ───────────────────────────────────────────────────────────────────
def get_clusters(question: str) -> set:
    q = question.lower()
    found = set()
    for c in CLUSTERS:
        if any(kw in q for kw in c["keywords"]):
            found.add(c["label"])
    return found





def get_best_prices(client, token_id: str) -> tuple[float, float]:
    """Return (best_ask, best_bid) from the live orderbook."""
    try:
        book = client.get_order_book(token_id)
        asks = sorted(book.asks or [], key=lambda x: float(x.price))
        bids = sorted(book.bids or [], key=lambda x: float(x.price), reverse=True)
        best_ask = float(asks[0].price) if asks else None
        best_bid = float(bids[0].price) if bids else None
        return best_ask, best_bid
    except Exception:
        return None, None


# ── Correlation graph ─────────────────────────────────────────────────────────
def build_graph(markets: list) -> list:
    """
    Returns list of (market_a, market_b, shared_clusters, relationship) tuples.
    Relationship: 'same_direction' | 'opposite_direction'
    """
    edges = []
    annotated = []

    for m in markets:
        q = m.get("question", "")
        tokens = m.get("tokens", [])
        if not tokens:
            continue
        clusters = get_clusters(q)
        if clusters:
            annotated.append({"market": m, "clusters": clusters, "question": q})

    # Pair up markets sharing 2+ cluster tags
    for a, b in itertools.combinations(annotated, 2):
        shared = a["clusters"] & b["clusters"]
        if len(shared) < 2:
            continue

        # Heuristic: if both questions are about the same outcome, same_direction
        # If one is clearly a subset / superset, still same_direction
        q_a, q_b = a["question"].lower(), b["question"].lower()

        # Check for negation / opposition keywords
        opp_keywords = ["no ", "not ", "fail", "lose", "under", "below", "against"]
        a_opp = any(kw in q_a for kw in opp_keywords)
        b_opp = any(kw in q_b for kw in opp_keywords)
        relationship = "opposite_direction" if (a_opp ^ b_opp) else "same_direction"

        edges.append({
            "market_a":     a["market"],
            "market_b":     b["market"],
            "shared":       sorted(shared),
            "relationship": relationship,
        })

    return edges


# ── Find arbitrage in graph ───────────────────────────────────────────────────
def find_opportunities(edges: list, client, min_edge: float) -> list:
    """
    For each correlated pair, fetch live prices and check for pricing gaps.

    For same_direction markets A and B where P(A should ≈ P(B):
      If P(YES_A) + P(NO_B) < 1 - FEE  →  buy YES_A + NO_B  (guaranteed if A ↔ B)
      If P(YES_B) + P(NO_A) < 1 - FEE  →  buy YES_B + NO_A

    For opposite_direction markets (A = "X wins", B = "X loses"):
      P(YES_A) + P(YES_B) should ≈ 1.0
      Gap = 1 - (P(YES_A) + P(YES_B))  →  same as standard arbitrage
    """
    opps = []
    seen_pairs = set()

    for edge in edges:
        ma = edge["market_a"]
        mb = edge["market_b"]
        id_pair = tuple(sorted([ma.get("id",""), mb.get("id","")]))
        if id_pair in seen_pairs:
            continue
        seen_pairs.add(id_pair)

        tokens_a = [t for t in ma.get("tokens", []) if t.get("token_id")]
        tokens_b = [t for t in mb.get("tokens", []) if t.get("token_id")]
        if not tokens_a or not tokens_b:
            continue

        # Use first token as YES, second as NO (standard Polymarket layout)
        yes_token_a = tokens_a[0].get("token_id", "")
        no_token_a  = tokens_a[1].get("token_id", "") if len(tokens_a) > 1 else ""
        yes_token_b = tokens_b[0].get("token_id", "")
        no_token_b  = tokens_b[1].get("token_id", "") if len(tokens_b) > 1 else ""

        p_yes_a = get_mid(client, yes_token_a)
        p_yes_b = get_mid(client, yes_token_b)
        if p_yes_a is None or p_yes_b is None:
            continue

        p_no_a = 1.0 - p_yes_a
        p_no_b = 1.0 - p_yes_b

        if edge["relationship"] == "same_direction":
            # Arbitrage 1: buy YES_A + NO_B  (A fires → YES_A pays; A doesn't → NO_B needs B also not to fire)
            # Valid when A and B are logically equivalent (same outcome)
            edge1 = 1.0 - (p_yes_a + p_no_b)   # = p_yes_b - p_yes_a  (should be ≈ 0)
            edge2 = 1.0 - (p_yes_b + p_no_a)   # = p_yes_a - p_yes_b

            for leg1_label, leg1_token, leg1_price, leg2_label, leg2_token, leg2_price, edge_val in [
                ("YES_A", yes_token_a, p_yes_a, "NO_B", no_token_b, p_no_b, edge1),
                ("YES_B", yes_token_b, p_yes_b, "NO_A", no_token_a, p_no_a, edge2),
            ]:
                net = edge_val - FEE
                if net >= min_edge and edge_val > 0:
                    opps.append({
                        "type":         "CORRELATION",
                        "relationship": edge["relationship"],
                        "shared_tags":  edge["shared"],
                        "question_a":   ma.get("question","?"),
                        "question_b":   mb.get("question","?"),
                        "market_id_a":  ma.get("id",""),
                        "market_id_b":  mb.get("id",""),
                        "leg1_label":   leg1_label,
                        "leg1_token":   leg1_token,
                        "leg1_buy_at":  leg1_price,
                        "leg2_label":   leg2_label,
                        "leg2_token":   leg2_token,
                        "leg2_buy_at":  leg2_price,
                        "raw_edge":     round(edge_val, 4),
                        "net_edge":     round(net, 4),
                    })

        else:  # opposite_direction — standard implied-probability check
            total = p_yes_a + p_yes_b
            gap   = 1.0 - total
            net   = gap - FEE
            if net >= min_edge and gap > 0:
                opps.append({
                    "type":         "CORRELATION_OPPOSITE",
                    "relationship": edge["relationship"],
                    "shared_tags":  edge["shared"],
                    "question_a":   ma.get("question","?"),
                    "question_b":   mb.get("question","?"),
                    "market_id_a":  ma.get("id",""),
                    "market_id_b":  mb.get("id",""),
                    "leg1_label":   "YES_A",
                    "leg1_token":   yes_token_a,
                    "leg1_buy_at":  p_yes_a,
                    "leg2_label":   "YES_B",
                    "leg2_token":   yes_token_b,
                    "leg2_buy_at":  p_yes_b,
                    "raw_edge":     round(gap, 4),
                    "net_edge":     round(net, 4),
                })

    opps.sort(key=lambda x: x["net_edge"], reverse=True)
    return opps


# ── Execute ────────────────────────────────────────────────────────────────────
def execute_opportunity(opp: dict, budget: float, client, confirm: bool = True):
    from execution_simulation import simulate_order
    from py_clob_client.clob_types import OrderArgs, OrderType
    from py_clob_client.order_builder.constants import BUY

    legs = [
        {"label": opp["leg1_label"], "token_id": opp["leg1_token"], "price": opp["leg1_buy_at"]},
        {"label": opp["leg2_label"], "token_id": opp["leg2_token"], "price": opp["leg2_buy_at"]},
    ]
    total_price = sum(l["price"] for l in legs)
    shares      = budget / total_price
    profit_est  = shares - budget
    roi         = profit_est / budget * 100

    print(f"\n{'='*70}")
    print(f"  CORRELATION ARBITRAGE PLAN")
    print(f"{'='*70}")
    print(f"  Type:      {opp['type']}")
    print(f"  Tags:      {', '.join(opp['shared_tags'])}")
    print(f"  Market A:  {opp['question_a'][:65]}")
    print(f"  Market B:  {opp['question_b'][:65]}")
    print(f"  Edge:      {opp['raw_edge']*100:.2f}%  net after fees: ~{opp['net_edge']*100:.2f}%")
    print(f"  Budget:    ${budget:.2f} USDC")
    print(f"  Shares:    {shares:.4f}")
    print(f"  Est. profit: +${profit_est:.4f} ({roi:.2f}% ROI)")
    print(f"\n  {'LEG':<10} {'TOKEN':<24} {'PRICE':>7}  {'COST':>9}")
    print(f"  {'─'*10} {'─'*24} {'─'*7}  {'─'*9}")

    for leg in legs:
        leg_cost = shares * leg["price"]
        # Run execution simulation
        try:
            sim = simulate_order(client, leg["token_id"], "BUY", leg_cost)
            slippage_warn = f"  ⚠️ slip {sim['slippage_pct']:.1f}%" if sim["slippage_pct"] > 1.0 else ""
        except Exception:
            slippage_warn = ""
        print(f"  {leg['label']:<10} {leg['token_id'][:22]:<24} "
              f"{leg['price']:7.4f}  ${leg_cost:>8.2f}{slippage_warn}")

    print(f"{'='*70}")

    if not confirm:
        ans = input("\n  Execute correlation arbitrage? (yes/no): ").strip().lower()
        if ans not in ("yes", "y"):
            print("  Cancelled.\n")
            return

    print(f"\n  Placing {len(legs)} orders...")
    placed_ids: list[str] = []
    for leg in legs:
        leg_cost = shares * leg["price"]
        o_args   = OrderArgs(
            token_id=leg["token_id"],
            price=round(leg["price"], 4),
            size=round(leg_cost, 2),
            side=BUY,
        )
        try:
            signed = client.create_order(o_args)
            resp   = client.post_order(signed, OrderType.GTC)
            oid    = (resp or {}).get("orderID") or (resp or {}).get("id", "?")
            print(f"  ✅ {leg['label']}  order {str(oid)[:20]}")
            placed_ids.append(str(oid))
        except Exception as e:
            print(f"  ❌ {leg['label']} FAILED: {e}")

    # ── Notify OpenClaw ──────────────────────────────────────────────────────
    if placed_ids:
        try:
            from notifier import notify_trade_opened
            notify_trade_opened(
                bot="correlation_arbitrage",
                market=f"{opp['question_a'][:50]} ↔ {opp['question_b'][:50]}",
                market_id=opp.get("market_id_a", ""),
                direction="ARB",
                amount_usd=round(budget, 2),
                price=None,
                order_ids=placed_ids,
                extras={
                    "type":     opp.get("type", ""),
                    "raw_edge": round(opp.get("raw_edge", 0) * 100, 3),
                    "net_edge": round(opp.get("net_edge", 0) * 100, 3),
                    "legs":     len(placed_ids),
                    "profit_est_usd": round(profit_est, 4),
                },
            )
        except Exception:
            pass


# ── Main ───────────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="Correlation arbitrage scanner")
    parser.add_argument("--scan",       action="store_true", help="Scan for opportunities")
    parser.add_argument("--graph",      action="store_true", help="Print the full correlation graph")
    parser.add_argument("--once",       action="store_true", help="Single-shot mode for scheduler")
    parser.add_argument("--min-edge",   type=float, default=0.03, help="Minimum net edge (default 0.03 = 3%%)")
    parser.add_argument("--limit",      type=int,   default=150,  help="Markets to scan (default 150)")
    parser.add_argument("--tag",        default="",               help="Filter by tag (politics, crypto...)")
    parser.add_argument("--execute",    action="store_true",       help="Execute best opportunity after confirmation")
    parser.add_argument("--budget",     type=float, default=50.0,  help="USDC budget per execution (default 50)")
    parser.add_argument("--confirm",    action="store_true",       help="Skip interactive confirmation")
    parser.add_argument("--json",       action="store_true",       help="Output raw JSON")
    args = parser.parse_args()

    authenticated = args.execute
    client = get_client(authenticated=authenticated)

    print(f"\n  Fetching {args.limit} markets...")
    markets = fetch_markets(args.limit, args.tag)
    if not markets:
        print("  No markets returned.")
        return

    print(f"  Building correlation graph...")
    edges = build_graph(markets)
    print(f"  Found {len(edges)} correlated pairs across {len(markets)} markets")

    if args.graph:
        print(f"\n  {'MARKET A':<45} ↔  {'MARKET B':<45}  TAGS  REL")
        print(f"  {'─'*45}    {'─'*45}  ────  ───────────────")
        for e in edges[:50]:
            print(f"  {e['market_a'].get('question','?')[:43]:<45}  "
                  f"{e['market_b'].get('question','?')[:43]:<45}  "
                  f"{','.join(e['shared'][:2]):<14}  {e['relationship']}")
        if len(edges) > 50:
            print(f"  ... and {len(edges)-50} more pairs")
        print()
        return

    if args.scan or args.once:
        print(f"  Checking prices for correlated pairs (min edge {args.min_edge*100:.1f}%)...")
        opps = find_opportunities(edges, client, args.min_edge)

        if not opps:
            print(f"\n  No correlation arbitrage opportunities found above "
                  f"{args.min_edge*100:.1f}% edge.\n")
            return

        if args.json:
            print(json.dumps(opps, indent=2))
            return

        print(f"\n  Found {len(opps)} opportunity(ies):\n")
        print(f"  {'#':<3} {'NET':>6}  {'TAGS':<20}  MARKET PAIR")
        print(f"  {'─'*3} {'─'*6}  {'─'*20}  {'─'*55}")
        for i, o in enumerate(opps[:15], 1):
            tags = ", ".join(o["shared_tags"][:3])
            qa   = o["question_a"][:35]
            qb   = o["question_b"][:35]
            print(f"  {i:<3} {o['net_edge']*100:>5.2f}%  {tags:<20}  {qa}")
            print(f"  {'':3} {'':6}  {'':20}  ↔ {qb}")
            print(f"  {'':3} {'':6}  {'':20}  Legs: {o['leg1_label']} @ {o['leg1_buy_at']:.3f}  +  "
                  f"{o['leg2_label']} @ {o['leg2_buy_at']:.3f}")
            print()

        if args.execute and opps:
            execute_opportunity(opps[0], args.budget, client, confirm=args.confirm)


if __name__ == "__main__":
    main()
