"""
Tests for scripts/prob_model.py (pure-logic / no network calls)
"""
import sys, math, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

# Stub out _utils and db before importing so no .env / SQLite needed
import types

_utils_stub = types.ModuleType("_utils")
_utils_stub.SKILL_DIR = Path("/tmp")
_utils_stub.GAMMA_API = "https://gamma-api.polymarket.com"
_utils_stub.get_mid   = lambda client, token_id: 0.5
sys.modules["_utils"] = _utils_stub

db_stub = types.ModuleType("db")
db_stub.DB_PATH = Path("/tmp/nonexistent_openpoly.db")
class _FakeDB:
    def __enter__(self): return self
    def __exit__(self, *a): pass
    def recent_signals(self, **kw): return []
    def accuracy_by_source(self): return {}
    def insert_signal(self, **kw): pass
db_stub.DB = _FakeDB
sys.modules["db"] = db_stub

from prob_model import (
    _bayesian_update,
    _time_weight,
    _calibration_weights,
    estimate,
    confidence_bar,
    _DEFAULT_HIT_RATES,
    _SHRINKAGE_N,
)


# ── _bayesian_update ──────────────────────────────────────────────────────────

def test_bayesian_update_neutral_signal_no_change():
    """sig_prob=0.5, any weight → posterior == prior."""
    prior = 0.6
    result = _bayesian_update(prior, 0.5, 1.0)
    assert abs(result - prior) < 0.001

def test_bayesian_update_confirming_signal_increases():
    """Signal agrees with prior → posterior > prior."""
    result = _bayesian_update(0.6, 0.8, 1.0)
    assert result > 0.6

def test_bayesian_update_contradicting_signal_decreases():
    """Signal contradicts prior → posterior < prior."""
    result = _bayesian_update(0.6, 0.2, 1.0)
    assert result < 0.6

def test_bayesian_update_weight_zero_no_change():
    """weight=0 → effective signal is 0.5 (neutral) → posterior == prior."""
    prior = 0.7
    result = _bayesian_update(prior, 0.9, 0.0)   # weight=0 collapses signal to 0.5
    assert abs(result - prior) < 0.001

def test_bayesian_update_stays_in_bounds():
    for prior in (0.01, 0.1, 0.5, 0.9, 0.99):
        for sig in (0.01, 0.99):
            result = _bayesian_update(prior, sig, 1.0)
            assert 0.0 < result < 1.0

def test_bayesian_update_strong_confirming_signal():
    result = _bayesian_update(0.5, 0.95, 1.0)
    assert result > 0.8

def test_bayesian_update_strong_contradicting_signal():
    result = _bayesian_update(0.5, 0.05, 1.0)
    assert result < 0.2


# ── _time_weight ──────────────────────────────────────────────────────────────

def test_time_weight_fresh_signal():
    """Signal from now → weight ≈ 1.0."""
    w = _time_weight(time.time(), time.time())
    assert abs(w - 1.0) < 0.01

def test_time_weight_half_life():
    """Signal from exactly half_life ago → weight ≈ 0.5."""
    now = time.time()
    half_life = 24.0
    created = now - half_life * 3600
    w = _time_weight(created, now, half_life_hours=half_life)
    assert abs(w - 0.5) < 0.01

def test_time_weight_old_signal_near_zero():
    """Signal from 7 days ago → weight nearly 0."""
    now = time.time()
    w = _time_weight(now - 7 * 24 * 3600, now, half_life_hours=24)
    assert w < 0.01

def test_time_weight_never_negative():
    for age_hours in (0, 1, 24, 72, 168):
        w = _time_weight(time.time() - age_hours * 3600, time.time())
        assert w >= 0.0


# ── _calibration_weights ──────────────────────────────────────────────────────

def test_calibration_weights_fallback_present():
    """Without DB data, all default sources must be present."""
    weights = _calibration_weights()
    for src in _DEFAULT_HIT_RATES:
        assert src in weights

def test_calibration_weights_positive():
    weights = _calibration_weights()
    for w in weights.values():
        assert w > 0

def test_calibration_weights_better_source_higher():
    """Source with hit_rate 0.72 (arb) should have higher weight than 0.54 (news)."""
    weights = _calibration_weights()
    assert weights["arb"] > weights["news"]


# ── estimate (no network) ──────────────────────────────────────────────────────

def test_estimate_no_signals_returns_prior():
    """With no signals, fair_prob should equal market_price (no update)."""
    result = estimate(market_id="test", market_price=0.65)
    assert abs(result["fair_prob"] - 0.65) < 0.01

def test_estimate_output_fields():
    result = estimate(market_id="test", market_price=0.50)
    for key in ("fair_prob", "market_price", "edge", "direction",
                "kelly_full", "kelly_quarter", "confidence", "n_signals", "factors"):
        assert key in result

def test_estimate_edge_consistent():
    result = estimate(market_id="test", market_price=0.55)
    assert abs(result["edge"] - (result["fair_prob"] - result["market_price"])) < 1e-6

def test_estimate_direction_yes_when_positive_edge():
    result = estimate(market_id="test", market_price=0.40,
                      extra_signals=[
                          {"source": "news", "direction": "YES",
                           "confidence": 0.8, "created_at": time.time()}
                      ])
    if result["edge"] > 0:
        assert result["direction"] == "YES"

def test_estimate_direction_no_when_negative_edge():
    result = estimate(market_id="test", market_price=0.70,
                      extra_signals=[
                          {"source": "news", "direction": "NO",
                           "confidence": 0.8, "created_at": time.time()}
                      ])
    if result["edge"] < 0:
        assert result["direction"] == "NO"

def test_estimate_kelly_non_negative():
    for price, conf in [(0.4, 0.7), (0.5, 0.5), (0.6, 0.8), (0.3, 0.9)]:
        result = estimate(market_id="test", market_price=price,
                          extra_signals=[{"source": "news", "direction": "YES",
                                         "confidence": conf, "created_at": time.time()}])
        assert result["kelly_full"] >= 0
        assert result["kelly_quarter"] >= 0

def test_estimate_kelly_quarter_less_than_full():
    result = estimate(market_id="test", market_price=0.40,
                      extra_signals=[{"source": "news", "direction": "YES",
                                      "confidence": 0.8, "created_at": time.time()}])
    assert result["kelly_quarter"] <= result["kelly_full"] + 1e-9

def test_estimate_fair_prob_in_bounds():
    for price in (0.1, 0.3, 0.5, 0.7, 0.9):
        result = estimate(market_id="test", market_price=price)
        assert 0.0 < result["fair_prob"] < 1.0

def test_estimate_suggested_size_with_balance():
    result = estimate(market_id="test", market_price=0.40, balance=1000,
                      extra_signals=[{"source": "news", "direction": "YES",
                                      "confidence": 0.9, "created_at": time.time()}])
    if result["kelly_quarter"] > 0:
        assert result["suggested_size"] > 0
        assert result["suggested_size"] <= 1000 * 0.25  # capped at 25% of balance

def test_estimate_old_signals_have_less_effect():
    """Signals from 5 days ago should produce less edge than fresh signals."""
    now = time.time()
    result_fresh = estimate(market_id="test", market_price=0.5,
                            extra_signals=[{"source": "news", "direction": "YES",
                                           "confidence": 0.9, "created_at": now}])
    result_old   = estimate(market_id="test", market_price=0.5,
                            extra_signals=[{"source": "news", "direction": "YES",
                                           "confidence": 0.9, "created_at": now - 5*24*3600}])
    assert abs(result_fresh["edge"]) >= abs(result_old["edge"])

def test_estimate_no_signals_zero_confidence():
    result = estimate(market_id="test", market_price=0.5)
    assert result["n_signals"] == 0
    assert result["confidence"] < 0.5


# ── confidence_bar ────────────────────────────────────────────────────────────

def test_confidence_bar_full():
    bar = confidence_bar(1.0)
    assert "100%" in bar
    assert "░" not in bar

def test_confidence_bar_half():
    bar = confidence_bar(0.5)
    assert "50%" in bar
    assert "█" in bar
    assert "░" in bar

def test_confidence_bar_zero():
    bar = confidence_bar(0.0)
    assert "0%" in bar
    assert "█" not in bar
