#!/usr/bin/env python3
"""
Show price history for a market token.

Usage:
  python price_history.py --token-id TOKEN_ID
  python price_history.py --token-id TOKEN_ID --interval 1d
  python price_history.py --token-id TOKEN_ID --interval 1w --fidelity 168
  python price_history.py --token-id TOKEN_ID --start 2025-01-01

Intervals: 1m  5m  15m  1h  6h  1d  1w  max
Fidelity:  number of data points returned (1–1440, default 100)
"""
import sys, argparse, requests
from pathlib import Path
from datetime import datetime, timezone, timedelta

sys.path.insert(0, str(Path(__file__).parent))
from _client import HOST, GAMMA_API

INTERVAL_SECONDS = {
    "1m": 60, "5m": 300, "15m": 900,
    "1h": 3600, "6h": 21600, "1d": 86400,
    "1w": 604800, "max": 0,
}


def sparkline(values: list[float], width: int = 40) -> str:
    """ASCII sparkline from a list of floats."""
    if not values:
        return ""
    blocks = " ▁▂▃▄▅▆▇█"
    lo, hi = min(values), max(values)
    span = hi - lo or 1
    # Sample down to width
    step = max(1, len(values) // width)
    sampled = values[::step][:width]
    return "".join(blocks[int((v - lo) / span * 8)] for v in sampled)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--token-id", "-t", required=True)
    parser.add_argument("--interval", "-i", default="1d",
                        choices=list(INTERVAL_SECONDS.keys()),
                        help="Time interval (default: 1d)")
    parser.add_argument("--fidelity", "-f", type=int, default=100,
                        help="Number of data points (1-1440, default 100)")
    parser.add_argument("--start", default="",
                        help="Start date YYYY-MM-DD (overrides interval)")
    parser.add_argument("--end", default="",
                        help="End date YYYY-MM-DD (default: now)")
    parser.add_argument("--raw", action="store_true",
                        help="Print all raw data points")
    args = parser.parse_args()

    # Build query params
    params: dict = {
        "token_id": args.token_id,
        "fidelity": args.fidelity,
    }

    now_ts = int(datetime.now(timezone.utc).timestamp())

    if args.start:
        try:
            start_dt = datetime.strptime(args.start, "%Y-%m-%d").replace(
                tzinfo=timezone.utc
            )
            params["startTs"] = int(start_dt.timestamp())
        except ValueError:
            print(f"Invalid start date: {args.start}. Use YYYY-MM-DD.")
            sys.exit(1)
    elif args.interval != "max":
        secs = INTERVAL_SECONDS[args.interval]
        params["startTs"] = now_ts - secs * args.fidelity

    if args.end:
        try:
            end_dt = datetime.strptime(args.end, "%Y-%m-%d").replace(
                tzinfo=timezone.utc
            )
            params["endTs"] = int(end_dt.timestamp())
        except ValueError:
            print(f"Invalid end date: {args.end}. Use YYYY-MM-DD.")
            sys.exit(1)

    params["interval"] = args.interval

    # Fetch market name
    market_name = args.token_id[:16] + "..."
    try:
        resp = requests.get(
            f"{GAMMA_API}/markets",
            params={"clob_token_ids": args.token_id},
            timeout=5,
        )
        if resp.ok:
            markets = resp.json()
            if markets:
                t = markets[0]
                question = t.get("question", "")
                tokens = t.get("tokens", [])
                for tok in tokens:
                    if tok.get("token_id") == args.token_id:
                        market_name = f"{question[:45]} [{tok.get('outcome','?')}]"
                        break
                else:
                    market_name = question[:50]
    except Exception:
        pass

    # Fetch price history from CLOB
    url = f"{HOST}/prices-history"
    try:
        resp = requests.get(url, params=params, timeout=15)
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        print(f"\n  Error fetching price history: {e}\n")
        sys.exit(1)

    history = data.get("history", [])
    if not history:
        print(f"\n  No price history found for this token/interval.\n")
        return

    prices = [float(p.get("p", 0)) for p in history]
    timestamps = [int(p.get("t", 0)) for p in history]

    # Stats
    p_first = prices[0]
    p_last = prices[-1]
    p_min = min(prices)
    p_max = max(prices)
    p_change = p_last - p_first
    p_change_pct = (p_change / p_first * 100) if p_first else 0
    volatility = (p_max - p_min)

    dt_start = datetime.fromtimestamp(timestamps[0], tz=timezone.utc).strftime(
        "%Y-%m-%d %H:%M UTC"
    )
    dt_end = datetime.fromtimestamp(timestamps[-1], tz=timezone.utc).strftime(
        "%Y-%m-%d %H:%M UTC"
    )

    trend_arrow = "▲" if p_change > 0.001 else ("▼" if p_change < -0.001 else "→")
    change_sign = "+" if p_change >= 0 else ""

    print(f"\n{'='*65}")
    print(f"  PRICE HISTORY  —  {market_name}")
    print(f"{'='*65}")
    print(f"  From:      {dt_start}")
    print(f"  To:        {dt_end}")
    print(f"  Interval:  {args.interval}  |  {len(prices)} data points")
    print(f"\n  Current:   {p_last:.4f}  ({p_last*100:.1f}%)")
    print(f"  Change:    {trend_arrow} {change_sign}{p_change:.4f}  "
          f"({change_sign}{p_change_pct:.1f}%)")
    print(f"  Range:     {p_min:.4f} – {p_max:.4f}  "
          f"(volatility: {volatility:.4f})")
    print(f"\n  Sparkline ({dt_start} → now):")
    print(f"  {p_max:.3f} ┤")
    print(f"         │ {sparkline(prices)}")
    print(f"  {p_min:.3f} ┘")
    print(f"         {'▲':>{3}} {'▲':>{len(sparkline(prices))}}")

    if args.raw:
        print(f"\n  {'TIMESTAMP':<22} {'DATE':<20} {'PRICE':>8}")
        print(f"  {'-'*22} {'-'*20} {'-'*8}")
        for entry in history:
            ts = int(entry.get("t", 0))
            p = float(entry.get("p", 0))
            dt = datetime.fromtimestamp(ts, tz=timezone.utc).strftime(
                "%Y-%m-%d %H:%M:%S"
            )
            print(f"  {ts:<22} {dt:<20} {p:8.5f}")

    print(f"\n{'='*65}\n")


if __name__ == "__main__":
    main()
