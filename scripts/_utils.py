"""
_utils.py — Shared utilities imported by all OpenPoly strategy scripts.

Provides:
  SKILL_DIR       — absolute Path to the skill root
  LOG_DIR         — absolute Path to logs/
  FEE             — round-trip fee estimate (0.02 = 2%)
  load_json()     — load a JSON state/config file with a default fallback
  save_json()     — atomically write a JSON file
  get_mid()       — fetch live midpoint price for a token
  fetch_markets() — fetch active markets from the Gamma API
"""
import json, requests
from pathlib import Path

# ── Paths ──────────────────────────────────────────────────────────────────────
SKILL_DIR = Path(__file__).parent.parent
LOG_DIR   = SKILL_DIR / "logs"
LOG_DIR.mkdir(exist_ok=True)

# Round-trip fee estimate used across all strategy scripts
FEE = 0.02

# Gamma REST API base URL (also exported from _client.py for backwards compat)
GAMMA_API = "https://gamma-api.polymarket.com"


# ── JSON state helpers ─────────────────────────────────────────────────────────
def load_json(path: Path, default: dict | list) -> dict | list:
    """
    Load a JSON file, returning `default` if the file is missing or corrupt.
    The default is deep-copied so callers can mutate it safely.
    """
    import copy
    if path.exists():
        try:
            return json.loads(path.read_text())
        except Exception:
            pass
    return copy.deepcopy(default)


def save_json(path: Path, data: dict | list):
    """Write data to a JSON file (creates parent dirs if needed)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2))


# ── Market data helpers ────────────────────────────────────────────────────────
def get_mid(client, token_id: str) -> float | None:
    """
    Return the live midpoint price for a token_id, or None on error.
    Uses the CLOB client's get_midpoint() endpoint.
    """
    try:
        r = client.get_midpoint(token_id)
        v = r.get("mid")
        return float(v) if v is not None else None
    except Exception:
        return None


def fetch_markets(
    limit: int = 100,
    tag: str = "",
    active: bool = True,
    order: str = "volume24hr",
    ascending: bool = False,
    search: str = "",
) -> list:
    """
    Fetch markets from the Gamma API with common filters.

    Args:
        limit:     Maximum markets to return.
        tag:       Filter by tag slug (e.g. 'politics', 'crypto').
        active:    If True, only return currently active markets.
        order:     Sort field (default 'volume24hr').
        ascending: Sort direction.
        search:    Keyword search query.

    Returns:
        List of market dicts, or [] on error.
    """
    params: dict = {"limit": limit, "order": order, "ascending": str(ascending).lower()}
    if active:
        params["active"] = "true"
    if tag:
        params["tag"] = tag
    if search:
        params["search"] = search
    try:
        resp = requests.get(f"{GAMMA_API}/markets", params=params, timeout=20)
        if resp.ok:
            data = resp.json()
            return data if isinstance(data, list) else []
    except Exception:
        pass
    return []
