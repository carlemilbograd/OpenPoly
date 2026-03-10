"""
Tests for scripts/risk_guard.py (pure logic, no filesystem writes)
"""
import sys, json, tempfile, os
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))


def _make_risk_guard(state: dict, config: dict):
    """
    Import risk_guard with a temp state file pre-populated.
    Returns the module (fresh import per test).
    """
    import importlib
    import risk_guard as rg
    # Patch state file to tmp
    data = {"config": config, "state": state}
    tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False)
    json.dump(data, tmp)
    tmp.close()
    original = rg._STATE_FILE
    rg._STATE_FILE = Path(tmp.name)
    return rg, Path(tmp.name), original


def _clean(path: Path):
    try:
        os.unlink(path)
    except Exception:
        pass


import risk_guard as rg


# ── is_killed ─────────────────────────────────────────────────────────────────

def test_is_killed_false_by_default(tmp_path, monkeypatch):
    monkeypatch.setattr(rg, "_STATE_FILE", tmp_path / "rs.json")
    assert rg.is_killed() is False

def test_is_killed_true_when_set(tmp_path, monkeypatch):
    state_file = tmp_path / "rs.json"
    state_file.write_text(json.dumps({
        "config": rg._DEFAULT_CONFIG,
        "state": {**rg._DEFAULT_STATE, "kill_switch": True},
    }))
    monkeypatch.setattr(rg, "_STATE_FILE", state_file)
    assert rg.is_killed() is True


# ── check_limits ──────────────────────────────────────────────────────────────

def _write_state(path: Path, kill=False, daily_pnl=0.0,
                 day_start_balance=1000.0, open_orders=0,
                 max_daily_loss_pct=0.05, max_position_pct=0.20, max_open_orders=50):
    from datetime import date
    data = {
        "config": {
            "max_daily_loss_pct": max_daily_loss_pct,
            "max_position_pct":   max_position_pct,
            "max_open_orders":    max_open_orders,
            "enabled":            True,
        },
        "state": {
            "kill_switch":       kill,
            "day_start_date":    date.today().isoformat(),
            "day_start_balance": day_start_balance,
            "daily_pnl":         daily_pnl,
            "total_open_orders": open_orders,
            "history":           [],
        }
    }
    path.write_text(json.dumps(data))


def test_check_limits_ok(tmp_path, monkeypatch):
    p = tmp_path / "rs.json"
    _write_state(p, daily_pnl=0.0, day_start_balance=500)
    monkeypatch.setattr(rg, "_STATE_FILE", p)
    ok, reason = rg.check_limits(trade_size_usd=20, current_balance=500)
    assert ok, reason

def test_check_limits_kill_switch(tmp_path, monkeypatch):
    p = tmp_path / "rs.json"
    _write_state(p, kill=True)
    monkeypatch.setattr(rg, "_STATE_FILE", p)
    ok, reason = rg.check_limits(trade_size_usd=10, current_balance=500)
    assert not ok
    assert "kill" in reason.lower()

def test_check_limits_max_position(tmp_path, monkeypatch):
    p = tmp_path / "rs.json"
    # max_position_pct=0.10 → max $50 on balance=500
    _write_state(p, max_position_pct=0.10)
    monkeypatch.setattr(rg, "_STATE_FILE", p)
    ok, reason = rg.check_limits(trade_size_usd=100, current_balance=500)
    assert not ok
    assert "position" in reason.lower() or "size" in reason.lower()

def test_check_limits_daily_loss_exceeded(tmp_path, monkeypatch):
    p = tmp_path / "rs.json"
    # 5% of 1000 = $50, already lost $60
    _write_state(p, daily_pnl=-60.0, day_start_balance=1000.0)
    monkeypatch.setattr(rg, "_STATE_FILE", p)
    ok, reason = rg.check_limits(trade_size_usd=10, current_balance=940)
    assert not ok
    assert "loss" in reason.lower() or "daily" in reason.lower()

def test_check_limits_open_orders_cap(tmp_path, monkeypatch):
    p = tmp_path / "rs.json"
    _write_state(p, open_orders=50, max_open_orders=50)
    monkeypatch.setattr(rg, "_STATE_FILE", p)
    ok, reason = rg.check_limits(trade_size_usd=10, current_balance=500)
    assert not ok
    assert "order" in reason.lower()

def test_check_limits_zero_balance_skips_position_check(tmp_path, monkeypatch):
    """balance=0 tells risk_guard to skip the position-size check, so it allows."""
    p = tmp_path / "rs.json"
    _write_state(p)
    monkeypatch.setattr(rg, "_STATE_FILE", p)
    # Should be allowed — balance=0 skips position cap check by design
    ok, _ = rg.check_limits(trade_size_usd=10, current_balance=0)
    assert ok

def test_check_limits_disabled_skips_checks(tmp_path, monkeypatch):
    """When enabled=False, limits should not block trades."""
    p = tmp_path / "rs.json"
    data = {
        "config": {**rg._DEFAULT_CONFIG, "enabled": False},
        "state": {**rg._DEFAULT_STATE, "kill_switch": False,
                  "daily_pnl": -999, "day_start_balance": 100},
    }
    p.write_text(json.dumps(data))
    monkeypatch.setattr(rg, "_STATE_FILE", p)
    ok, _ = rg.check_limits(trade_size_usd=10, current_balance=100)
    assert ok


# ── _roll_day ─────────────────────────────────────────────────────────────────

def test_roll_day_resets_daily_pnl(tmp_path, monkeypatch):
    """After rolling to a new day, daily_pnl should reset to 0."""
    p = tmp_path / "rs.json"
    data = {
        "config": dict(rg._DEFAULT_CONFIG),
        "state": {
            **rg._DEFAULT_STATE,
            "day_start_date":    "2020-01-01",   # old date → triggers roll
            "daily_pnl":         -99.0,
            "day_start_balance": 500.0,
        }
    }
    p.write_text(json.dumps(data))
    monkeypatch.setattr(rg, "_STATE_FILE", p)
    loaded = rg._load()
    rg._roll_day(loaded)
    assert loaded["state"]["daily_pnl"] == 0.0
