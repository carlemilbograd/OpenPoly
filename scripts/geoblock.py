#!/usr/bin/env python3
"""
geoblock.py — Check whether your current location / account is geo-blocked
on Polymarket's CLOB API.

Method: sends an authenticated POST to /order with an intentionally empty body.
  HTTP 403 / 451  → blocked in your region
  HTTP 400 / 422  → not blocked (payload rejected as expected)
  HTTP 401        → not blocked (unauthenticated — check API key)

Usage:
  poly geoblock
  python scripts/geoblock.py          [--json]
  python scripts/geoblock.py --no-auth   # skip HMAC signing (anonymous probe)
"""
import sys, os, argparse, time, hashlib, hmac, base64, json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).parent.parent / ".env")
except ImportError:
    pass

HOST = "https://clob.polymarket.com"

# ── result helpers ────────────────────────────────────────────────────────────
_ICONS = {True: "✅", False: "❌", None: "⚠️ "}

def _result(ok: bool | None, label: str, detail: str, as_json: bool) -> dict:
    row = {"status": "ok" if ok else ("blocked" if ok is False else "inconclusive"),
           "label": label, "detail": detail}
    if not as_json:
        icon = _ICONS[ok]
        print(f"\n  {icon}  {label}")
        print(f"     {detail}")
    return row


def check_geoblock(use_auth: bool = True) -> dict:
    """
    Probe the CLOB and return a result dict.

    Returns:
        {status: "ok"|"blocked"|"inconclusive", label, detail,
         http_code, authenticated}
    """
    try:
        import requests
    except ImportError:
        return {"status": "error", "detail": "requests not installed"}

    headers = {"Content-Type": "application/json"}
    authenticated = False

    if use_auth:
        api_key        = os.getenv("POLYMARKET_API_KEY", "")
        api_secret     = os.getenv("POLYMARKET_API_SECRET", "")
        api_passphrase = os.getenv("POLYMARKET_API_PASSPHRASE", "")
        funder         = os.getenv("POLYMARKET_FUNDER_ADDRESS", "")

        if api_key and api_secret:
            ts  = str(int(time.time()))
            msg = ts + "POST" + "/order" + "{}"
            sig = base64.b64encode(
                hmac.new(api_secret.encode(), msg.encode(), hashlib.sha256).digest()
            ).decode()
            headers.update({
                "POLY_ADDRESS":    funder,
                "POLY_SIGNATURE":  sig,
                "POLY_TIMESTAMP":  ts,
                "POLY_API_KEY":    api_key,
                "POLY_PASSPHRASE": api_passphrase,
            })
            authenticated = True

    try:
        resp = requests.post(f"{HOST}/order", json={}, headers=headers, timeout=10)
        code = resp.status_code
    except requests.exceptions.ConnectionError:
        return {"status": "error", "label": "Network error",
                "detail": "Could not reach clob.polymarket.com — check internet connection",
                "http_code": None, "authenticated": authenticated}
    except Exception as e:
        return {"status": "error", "label": "Request failed",
                "detail": str(e)[:120], "http_code": None, "authenticated": authenticated}

    if code in (403, 451):
        return {
            "status": "blocked",
            "label":  "Geo-blocked",
            "detail": f"HTTP {code} — your IP / account is not permitted to trade on Polymarket "
                      f"from this location. ({resp.text[:120].strip()})",
            "http_code": code,
            "authenticated": authenticated,
        }
    elif code in (400, 422):
        return {
            "status": "ok",
            "label":  "Not geo-blocked",
            "detail": f"HTTP {code} — CLOB rejected empty payload as expected; "
                      f"your region is permitted.",
            "http_code": code,
            "authenticated": authenticated,
        }
    elif code == 401:
        return {
            "status": "ok",
            "label":  "Not geo-blocked (unauthenticated)",
            "detail": f"HTTP 401 — server returned 'unauthorized', not blocked. "
                      f"Credentials may be missing or incorrect, but the region is permitted.",
            "http_code": 401,
            "authenticated": authenticated,
        }
    elif code == 200:
        return {
            "status": "ok",
            "label":  "Not geo-blocked",
            "detail": f"HTTP 200 — POST accepted (unexpectedly). Region is permitted.",
            "http_code": 200,
            "authenticated": authenticated,
        }
    else:
        return {
            "status": "inconclusive",
            "label":  "Inconclusive",
            "detail": f"HTTP {code} — unexpected response. "
                      f"Try  poly trade --dry-run  for a fuller check.",
            "http_code": code,
            "authenticated": authenticated,
        }


def main():
    parser = argparse.ArgumentParser(
        description="Check if your current IP/account is geo-blocked on Polymarket"
    )
    parser.add_argument("--no-auth",  action="store_true",
                        help="Send an anonymous (unsigned) probe instead of using API credentials")
    parser.add_argument("--json",     action="store_true",
                        help="Output result as JSON")
    args = parser.parse_args()

    if not args.json:
        print("\n  ── Polymarket Geo-Block Check ──────────────────────────")
        print(f"  Probing:  {HOST}/order")

    result = check_geoblock(use_auth=not args.no_auth)

    if not args.json:
        auth_note = "(authenticated)" if result.get("authenticated") else "(anonymous probe)"
        icon = _ICONS.get(
            True  if result["status"] == "ok" else
            False if result["status"] == "blocked" else None
        )
        code_str = f"  HTTP {result['http_code']}" if result.get("http_code") else ""
        print(f"\n  {icon}  {result['label']}  {auth_note}{code_str}")
        print(f"     {result['detail']}")
        print()
        if result["status"] == "blocked":
            print("  Suggestions:")
            print("    • Try from a different network / VPN")
            print("    • Verify your account is not banned on polymarket.com")
            print("    • Check https://polymarket.com/restricted-territories")
            print()
        sys.exit(0 if result["status"] in ("ok", "inconclusive") else 1)
    else:
        print(json.dumps(result, indent=2))
        sys.exit(0 if result["status"] in ("ok", "inconclusive") else 1)


if __name__ == "__main__":
    main()
