#!/usr/bin/env python3
"""
geoblock.py — Check whether your current IP is geo-blocked on Polymarket.

Uses the official Polymarket geoblock endpoint:
  GET https://polymarket.com/api/geoblock

Returns:
  { "blocked": bool, "ip": "...", "country": "XX", "region": "..." }

No credentials required — the check is purely IP-based.

Usage:
  poly geoblock
  python scripts/geoblock.py
  python scripts/geoblock.py --json
"""
import sys, argparse, json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

GEOBLOCK_URL = "https://polymarket.com/api/geoblock"

_BLOCKED_COUNTRIES = {
    "AU", "BE", "BY", "BI", "CF", "CD", "CU", "DE", "ET", "FR", "GB",
    "IR", "IQ", "IT", "KP", "LB", "LY", "MM", "NI", "NL", "RU", "SO",
    "SS", "SD", "SY", "UM", "US", "VE", "YE", "ZW",
}
_CLOSE_ONLY_COUNTRIES = {"PL", "SG", "TH", "TW"}


def check_geoblock() -> dict:
    """
    Call GET https://polymarket.com/api/geoblock and return a normalised result.

    Returns:
        {
            status:   "ok" | "blocked" | "close_only" | "error"
            blocked:  bool
            ip:       str
            country:  str
            region:   str
            detail:   str          # human-readable explanation
        }
    """
    try:
        import requests
    except ImportError:
        return {"status": "error", "blocked": None,
                "detail": "requests not installed — run: pip install requests"}

    try:
        resp = requests.get(GEOBLOCK_URL, timeout=10)
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        return {"status": "error", "blocked": None, "ip": "", "country": "", "region": "",
                "detail": f"Request failed: {e}"}

    blocked  = bool(data.get("blocked", False))
    ip       = data.get("ip", "")
    country  = data.get("country", "")
    region   = data.get("region", "")

    if blocked:
        close_only = country in _CLOSE_ONLY_COUNTRIES
        status = "close_only" if close_only else "blocked"
        detail = (
            f"{'Close-only' if close_only else 'Blocked'}: "
            f"{country}{f'/{region}' if region else ''} "
            f"({ip}) — you can {'close existing positions only' if close_only else 'not trade'} "
            f"from this location."
        )
    else:
        status = "ok"
        detail = (
            f"Not blocked: {country}{f'/{region}' if region else ''} ({ip}) "
            f"— trading is permitted from this location."
        )

    return {
        "status":  status,
        "blocked": blocked,
        "ip":      ip,
        "country": country,
        "region":  region,
        "detail":  detail,
    }


def main():
    parser = argparse.ArgumentParser(
        description="Check if your current IP is geo-blocked on Polymarket"
    )
    parser.add_argument("--json", action="store_true", help="Output result as JSON")
    args = parser.parse_args()

    if not args.json:
        print(f"\n  ── Polymarket Geo-Block Check ──────────────────────────")
        print(f"  Endpoint: {GEOBLOCK_URL}\n")

    result = check_geoblock()

    if args.json:
        print(json.dumps(result, indent=2))
    else:
        icon = {"ok": "✅", "blocked": "❌", "close_only": "⚠️ ", "error": "⚠️ "}.get(result["status"], "⚠️ ")
        print(f"  {icon}  {result['detail']}\n")

        if result["status"] == "blocked":
            print("  Suggestions:")
            print("    • Try from a different network or VPN")
            print("    • Check https://polymarket.com/restricted-territories")
            print()
        elif result["status"] == "close_only":
            print("  Note: You can still close existing positions via  poly cancel")
            print()

    sys.exit(0 if result["status"] in ("ok", "close_only") else 1)


if __name__ == "__main__":
    main()
