#!/usr/bin/env python3
"""
_guards.py — Hard runtime limits that protect against user misconfiguration.

These constants CANNOT be overridden by CLI flags.  They are enforced at
startup before any order is placed or any loop begins.

  MIN_ORDER_USD        Polymarket's minimum order size.  Any --budget / --size
                       flag below this is rejected, the user is warned and a
                       corrected value is suggested.

  SUGGESTED_MIN_USD    Practical floor ($5) — covers fees even on small markets.

  MIN_NEWS_INTERVAL    Minimum minutes between news_trader scan cycles.
                       A shorter --interval is silently clamped to this value
                       to prevent Gamma / GDELT 429 throttling.

  GAMMA_RATE_LIMIT_SEC Minimum seconds between consecutive Gamma API calls
                       inside the news mapper.  Prevents burst 429 errors when
                       a batch of stories all trigger market-lookup requests.
"""
from __future__ import annotations

import sys
import threading
import time

# ── Hard limits ───────────────────────────────────────────────────────────────
MIN_ORDER_USD        = 1.0    # Polymarket minimum order size (USDC)
SUGGESTED_MIN_USD    = 5.0    # Practical floor — fees + slippage on small markets
MIN_NEWS_INTERVAL    = 3.0    # Minimum minutes between news_trader cycles
GAMMA_RATE_LIMIT_SEC = 0.35   # Minimum seconds between Gamma API calls in mapper


# ── Budget guard ──────────────────────────────────────────────────────────────

def check_min_order(
    amount_usd: float,
    *,
    flag:         str  = "--budget",
    bot:          str  = "",
    exit_on_fail: bool = False,
) -> bool:
    """Return True if *amount_usd* is >= MIN_ORDER_USD; False with a warning otherwise.

    When *exit_on_fail* is True the process is terminated so automated runners
    (master_bot, scheduler) don't silently spawn strategies below the minimum.

    Usage:
        from _guards import check_min_order
        if not check_min_order(args.budget, flag="--budget", bot="news_trader",
                               exit_on_fail=True):
            return   # unreachable when exit_on_fail=True, here for linters
    """
    if amount_usd >= MIN_ORDER_USD:
        return True

    prefix    = f"[{bot}]  " if bot else ""
    suggested = max(SUGGESTED_MIN_USD, MIN_ORDER_USD)

    print(
        f"\n  ⚠️  {prefix}{flag} ${amount_usd:.2f} is below the Polymarket minimum "
        f"order size (${MIN_ORDER_USD:.2f}).\n"
        f"      → Suggested fix:  {flag} {suggested:.2f}  "
        f"  (practical minimum: ${SUGGESTED_MIN_USD:.2f})\n",
        file=sys.stderr,
    )

    # Push an OpenClaw notification so the user sees this even in background runs
    try:
        from notifier import notify_event
        notify_event(
            source=bot or "guard",
            title="⚠️ Min order size not met",
            body=(
                f"{flag} ${amount_usd:.2f} is below the minimum "
                f"${MIN_ORDER_USD:.2f}. "
                f"Suggested fix: {flag} {suggested:.2f}"
            ),
            level="warning",
        )
    except Exception:
        pass

    if exit_on_fail:
        sys.exit(1)

    return False


# ── Interval guard ────────────────────────────────────────────────────────────

def enforce_min_interval(interval_min: float, bot: str = "") -> float:
    """Clamp *interval_min* to MIN_NEWS_INTERVAL and warn if it was adjusted.

    Returns the (possibly clamped) interval value so the caller can
    simply do:  args.interval = enforce_min_interval(args.interval, "news_trader")
    """
    if interval_min >= MIN_NEWS_INTERVAL:
        return interval_min

    prefix = f"[{bot}]  " if bot else ""
    print(
        f"\n  ⚠️  {prefix}--interval {interval_min:.1f}m is below the hard minimum "
        f"{MIN_NEWS_INTERVAL:.0f}m (prevents Gamma / GDELT 429 throttling).\n"
        f"      → Using {MIN_NEWS_INTERVAL:.0f}m instead.\n",
        file=sys.stderr,
    )
    return MIN_NEWS_INTERVAL


# ── Gamma API rate limiter ────────────────────────────────────────────────────
_gamma_lock: threading.Lock = threading.Lock()
_gamma_last: float          = 0.0


def gamma_rate_wait() -> None:
    """Block until GAMMA_RATE_LIMIT_SEC has elapsed since the last Gamma call.

    Thread-safe.  Call this immediately before every Gamma API request inside
    the news mapper / pipeline to prevent burst 429 responses.

    Usage:
        from _guards import gamma_rate_wait
        gamma_rate_wait()
        resp = requests.get(gamma_url, ...)
    """
    global _gamma_last
    with _gamma_lock:
        now  = time.monotonic()
        wait = GAMMA_RATE_LIMIT_SEC - (now - _gamma_last)
        if wait > 0:
            time.sleep(wait)
        _gamma_last = time.monotonic()
