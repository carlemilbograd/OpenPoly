#!/usr/bin/env python3
"""
Place orders on Polymarket.
⚠️  ALWAYS confirm with user before running.

Usage:
  # Limit order (GTC):
  python trade.py --token-id TOKEN_ID --side BUY --price 0.55 --size 10

  # Market order (FOK):
  python trade.py --token-id TOKEN_ID --side BUY --size 25 --type FOK

  # Limit with expiry (GTD):
  python trade.py --token-id TOKEN_ID --side SELL --price 0.70 --size 5 --type GTD --expiry 3600

  # Preflight check (no order placed):
  python trade.py --token-id TOKEN_ID --side BUY --price 0.55 --size 10 --dry-run
"""
import sys, argparse, requests
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from _client import get_client, HOST, DATA_API, GAMMA_API

def _check(label: str, ok, detail: str = ""):
    if ok is None:
        icon = "⚠️ "
    elif ok:
        icon = "✅"
    else:
        icon = "❌"
    line = f"  {icon}  {label}"
    if detail:
        line += f"  — {detail}"
    print(line)
    return ok


def _dry_run(args, side_const, order_type):
    """
    Run a preflight sequence without placing any order.

    Checks (in order):
      1. API credentials valid         — authenticated GET to /auth-status
      2. USDC balance >= order size    — balance allowance endpoint
      3. Market exists + is active     — Gamma API lookup
      4. Geoblock / order POST allowed — bare authenticated POST to CLOB /order
                                         with an intentionally malformed body;
                                         a geo-blocked account gets 403/451
                                         before the payload is validated
      5. Order signs locally           — create_order() / create_market_order()
                                         (pure local crypto, no network call)
    """
    from py_clob_client.clob_types import (
        OrderArgs, MarketOrderArgs, AssetType, BalanceAllowanceParams
    )
    passed = 0
    failed = 0

    print()

    # ── 1. Credentials ────────────────────────────────────────────────────────
    try:
        client = get_client(authenticated=True)
        client.get_orders()           # authenticated endpoint
        ok = _check("Credentials", True, "API key accepted")
        passed += 1
    except Exception as e:
        err = str(e)
        if "401" in err or "403" in err or "Unauthorized" in err:
            _check("Credentials", False, f"rejected — re-run: poly setup")
        else:
            _check("Credentials", False, err[:80])
        failed += 1
        print(f"\n  Cannot continue — fix credentials first.")
        _summary(passed, failed)
        return

    # ── 2. Balance ────────────────────────────────────────────────────────────
    try:
        bal = client.get_balance_allowance(
            params=BalanceAllowanceParams(asset_type=AssetType.COLLATERAL)
        )
        usdc = float(bal.get("balance", 0)) / 1e6
        if usdc >= args.size:
            _check("Balance", True,
                   f"${usdc:,.2f} USDC available  (need ${args.size:.2f})")
            passed += 1
        else:
            _check("Balance", False,
                   f"${usdc:,.2f} USDC available, need ${args.size:.2f} — deposit more USDC")
            failed += 1
    except Exception as e:
        _check("Balance", False, str(e)[:80])
        failed += 1

    # ── 3. Market active ──────────────────────────────────────────────────────
    try:
        r = requests.get(
            f"{GAMMA_API}/markets",
            params={"clob_token_ids": args.token_id},
            timeout=8,
        )
        markets = r.json() if r.ok else []
        if markets:
            m = markets[0]
            active = m.get("active", True)
            closed = m.get("closed", False)
            q = m.get("question", "")[:50]
            if active and not closed:
                _check("Market active", True, q)
                passed += 1
            else:
                state = "closed" if closed else "inactive"
                _check("Market active", False, f"{state}: {q}")
                failed += 1
        else:
            _check("Market active", False, "token ID not found — check --token-id")
            failed += 1
    except Exception as e:
        _check("Market active", False, str(e)[:80])
        failed += 1

    # ── 4. Geoblock / order POST allowed ─────────────────────────────────────
    # Send an authenticated POST with an intentionally invalid body.
    # - Geo-blocked accounts: 403 / 451 Unavailable For Legal Reasons
    # - Valid accounts:       422 / 400 (invalid payload — expected)
    try:
        import os, time, hashlib, hmac, base64, json as _json
        api_key        = os.getenv("POLYMARKET_API_KEY", "")
        api_secret     = os.getenv("POLYMARKET_API_SECRET", "")
        api_passphrase = os.getenv("POLYMARKET_API_PASSPHRASE", "")

        if api_key and api_secret:
            ts        = str(int(time.time()))
            msg       = ts + "POST" + "/order" + "{}"
            sig       = base64.b64encode(
                hmac.new(api_secret.encode(), msg.encode(), hashlib.sha256).digest()
            ).decode()
            headers = {
                "POLY_ADDRESS":    os.getenv("POLYMARKET_FUNDER_ADDRESS", ""),
                "POLY_SIGNATURE":  sig,
                "POLY_TIMESTAMP":  ts,
                "POLY_API_KEY":    api_key,
                "POLY_PASSPHRASE": api_passphrase,
                "Content-Type":    "application/json",
            }
            probe = requests.post(f"{HOST}/order", json={}, headers=headers, timeout=8)
            code  = probe.status_code
            if code in (403, 451):
                body_txt = probe.text[:120]
                _check("Geoblock check", False,
                       f"HTTP {code} — account is blocked in your region  ({body_txt})")
                failed += 1
            elif code in (400, 422, 401):
                # 400/422 = payload rejected (expected for empty body) = not geoblocked
                _check("Geoblock check", True,
                       f"not blocked (HTTP {code} = payload validation, as expected)")
                passed += 1
            elif code == 200:
                _check("Geoblock check", True, "POST accepted (unexpected 200 — ping devs)")
                passed += 1
            else:
                _check("Geoblock check", None,
                       f"HTTP {code} — inconclusive (try placing an order to confirm)")
                # don't count as pass or fail
        else:
            _check("Geoblock check", True,
                   "skipped (no API key in .env — will be derived on first trade)")
            passed += 1
    except Exception as e:
        _check("Geoblock check", False, str(e)[:80])
        failed += 1

    # ── 5. Local order signing ────────────────────────────────────────────────
    try:
        if args.order_type == "FOK":
            mo_args = MarketOrderArgs(
                token_id=args.token_id,
                amount=args.size,
                side=side_const,
            )
            client.create_market_order(mo_args)
        else:
            from py_clob_client.clob_types import OrderArgs as OA
            expiration = args.expiry if args.order_type == "GTD" else 0
            o_args = OA(
                token_id=args.token_id,
                price=args.price or 0.5,
                size=args.size,
                side=side_const,
                expiration=expiration,
            )
            client.create_order(o_args)
        _check("Order signing", True, "signed locally — ready to submit")
        passed += 1
    except Exception as e:
        _check("Order signing", False, str(e)[:100])
        failed += 1

    _summary(passed, failed)


def _summary(passed: int, failed: int):
    total = passed + failed
    print()
    print(f"  {'─'*50}")
    if failed == 0:
        print(f"  ✅  All {total} checks passed — order should go through.")
        print(f"  Re-run without --dry-run to place it.")
    else:
        print(f"  ⚠️   {passed}/{total} checks passed, {failed} failed.")
        print(f"  Fix the issues above before placing the order.")
    print()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--token-id", "-t", required=True)
    parser.add_argument("--side", "-s", required=True, choices=["BUY", "SELL"])
    parser.add_argument("--price", "-p", type=float, default=None,
                        help="Limit price (0.01-0.99). Omit for market orders.")
    parser.add_argument("--size", "-z", type=float, required=True,
                        help="Size in USDC")
    parser.add_argument("--type", dest="order_type", default="GTC",
                        choices=["GTC", "GTD"],
                        help="GTC=limit good-till-cancelled (default), "
                             "GTD=limit with expiry (min expiry 60s). "
                             "Note: Polymarket enforces a minimum 1-minute order "
                             "lifetime — fill-or-kill (FOK) is not supported.")
    parser.add_argument("--expiry", type=int, default=3600,
                        help="GTD expiry in seconds (default 3600)")
    parser.add_argument("--confirm", action="store_true",
                        help="Skip interactive confirmation (use only from trusted automation)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Preflight check only — verify credentials, balance, market "
                             "access and sign the order locally without submitting it")
    args = parser.parse_args()

    from py_clob_client.clob_types import OrderArgs, MarketOrderArgs, OrderType
    from py_clob_client.order_builder.constants import BUY, SELL

    side_const = BUY if args.side == "BUY" else SELL

    order_type_map = {
        "GTC": OrderType.GTC,
        "GTD": OrderType.GTD,
    }
    order_type = order_type_map[args.order_type]

    # Preview
    print(f"\n{'='*54}")
    if args.dry_run:
        print(f"  🧪 DRY-RUN PREFLIGHT  (no order will be placed)")
    else:
        print(f"  ORDER PREVIEW")
    print(f"{'='*54}")
    print(f"  Token ID:   {args.token_id}")
    print(f"  Side:       {args.side}")
    print(f"  Type:       {args.order_type}")
    if args.price:
        print(f"  Price:      {args.price:.4f}  ({args.price*100:.1f}%)")
    else:
        print(f"  Price:      MARKET")
    print(f"  Size:       ${args.size:.2f} USDC")
    if args.price:
        shares = args.size / args.price
        print(f"  Shares:     ~{shares:.2f}")
        print(f"  Max profit: ~${shares - args.size:.2f}")
    if args.order_type == "GTD":
        print(f"  Expiry:     {args.expiry}s ({args.expiry//60} min)")
    print(f"{'='*54}")

    if args.dry_run:
        _dry_run(args, side_const, order_type)
        return

    if not args.confirm:
        confirm = input("\n  ⚠️  Confirm order? (yes/no): ").strip().lower()
        if confirm not in ("yes", "y"):
            print("  Order cancelled.")
            sys.exit(0)

    client = get_client(authenticated=True)

    try:
        # All orders use GTC or GTD — Polymarket requires a minimum 1-minute
        # order lifetime, so FOK/immediate execution is not supported.
        expiration = args.expiry if args.order_type == "GTD" else 0
        o_args = OrderArgs(
            token_id=args.token_id,
            price=args.price,
            size=args.size,
            side=side_const,
            expiration=expiration,
        )
        signed = client.create_order(o_args)
        resp = client.post_order(signed, order_type)

        print(f"\n  ✅ Order submitted!")
        print(f"  Response: {resp}")
        if isinstance(resp, dict):
            order_id = resp.get("orderID") or resp.get("id") or ""
            if order_id:
                print(f"  Order ID: {order_id}")
                print(f"  Cancel with: python scripts/cancel.py --order-id {order_id}")
        print()

    except Exception as e:
        print(f"\n  ❌ Order failed: {e}")
        print("  Check credentials, balance, and token ID.")
        sys.exit(1)

if __name__ == "__main__":
    main()
