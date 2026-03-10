"""
Tests for scripts/db.py — SQLite data layer
Uses a fresh in-memory / temp DB per test; no shared state.
"""
import sys, importlib, time, tempfile, os
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
# Note: sys.modules["db"] is managed by conftest.py to ensure we always
# get the real db module here, not the stub used by test_prob_model.py.


def _make_db(tmp_path):
    """Return a DB instance pointing at a fresh temp file."""
    import db as db_module
    db_path = tmp_path / "test_openpoly.db"
    original = db_module.DB_PATH
    db_module.DB_PATH = db_path
    instance = db_module.DB(db_path)
    return instance, db_path, db_module, original


# ── Article ops ───────────────────────────────────────────────────────────────

def test_insert_and_exists(tmp_path):
    import db as db_module
    db_module.DB_PATH = tmp_path / "t.db"
    with db_module.DB(tmp_path / "t.db") as d:
        fp = "abc123"
        assert not d.article_exists(fp)
        d.insert_article({"id": fp, "url": "https://a.com/1", "title": "Test",
                          "source": "reuters", "trust": 0.85})
        assert d.article_exists(fp)

def test_insert_duplicate_ignored(tmp_path):
    import db as db_module
    db_module.DB_PATH = tmp_path / "t.db"
    with db_module.DB(tmp_path / "t.db") as d:
        for _ in range(3):
            d.insert_article({"id": "dup", "url": "https://a.com/1",
                              "title": "Dup", "source": "x", "trust": 0.5})
        rows = d.recent_articles(limit=100)
        assert len([r for r in rows if r["fingerprint"] == "dup"]) == 1

def test_recent_articles_limit(tmp_path):
    import db as db_module
    db_module.DB_PATH = tmp_path / "t.db"
    with db_module.DB(tmp_path / "t.db") as d:
        for i in range(10):
            d.insert_article({"id": f"fp{i}", "url": f"https://a.com/{i}",
                              "title": f"Article {i}", "source": "x", "trust": 0.5})
        rows = d.recent_articles(limit=5)
        assert len(rows) == 5


# ── Signal ops ────────────────────────────────────────────────────────────────

def test_insert_and_recent_signals(tmp_path):
    import db as db_module
    db_module.DB_PATH = tmp_path / "t.db"
    with db_module.DB(tmp_path / "t.db") as d:
        d.insert_signal(source="news", market_id="0xabc", direction="YES",
                        confidence=0.72, edge_estimate=0.08)
        rows = d.recent_signals(limit=10)
        assert len(rows) == 1
        assert rows[0]["source"] == "news"
        assert rows[0]["direction"] == "YES"

def test_signal_market_id_filter(tmp_path):
    import db as db_module
    db_module.DB_PATH = tmp_path / "t.db"
    with db_module.DB(tmp_path / "t.db") as d:
        d.insert_signal(source="news", market_id="0xabc", direction="YES",
                        confidence=0.7, edge_estimate=0.05)
        d.insert_signal(source="ai",   market_id="0xdef", direction="NO",
                        confidence=0.6, edge_estimate=0.04)
        rows = d.recent_signals(limit=10, market_id="0xabc")
        assert len(rows) == 1
        assert rows[0]["market_id"] == "0xabc"


# ── Trade ops ─────────────────────────────────────────────────────────────────

def test_record_and_close_trade(tmp_path):
    import db as db_module
    db_module.DB_PATH = tmp_path / "t.db"
    with db_module.DB(tmp_path / "t.db") as d:
        trade_id = d.record_trade(market_id="0xabc", token_id="tok1",
                                  side="BUY", price=0.55, size_usd=20.0,
                                  order_id="ord001")
        assert trade_id > 0
        d.close_trade(trade_id, filled_price=0.55, pnl=1.20, status="filled")
        trades = d.recent_trades(limit=5)
        assert trades[0]["pnl"] == 1.20
        assert trades[0]["status"] == "filled"

def test_recent_trades_limit(tmp_path):
    import db as db_module
    db_module.DB_PATH = tmp_path / "t.db"
    with db_module.DB(tmp_path / "t.db") as d:
        for i in range(8):
            d.record_trade(market_id=f"0x{i}", token_id=f"tok{i}",
                           side="BUY", price=0.5, size_usd=10.0, order_id=f"ord{i}")
        rows = d.recent_trades(limit=3)
        assert len(rows) == 3


# ── Outcome + accuracy ────────────────────────────────────────────────────────

def test_resolve_outcome(tmp_path):
    import db as db_module
    db_module.DB_PATH = tmp_path / "t.db"
    with db_module.DB(tmp_path / "t.db") as d:
        d.resolve_outcome(market_id="0xabc", outcome="YES", resolved_at=int(time.time()))
        outcome = d.get_outcome("0xabc")
        assert outcome == "YES"

def test_resolve_outcome_idempotent(tmp_path):
    import db as db_module
    db_module.DB_PATH = tmp_path / "t.db"
    with db_module.DB(tmp_path / "t.db") as d:
        for _ in range(3):
            d.resolve_outcome(market_id="0xabc", outcome="NO", resolved_at=int(time.time()))
        assert d.get_outcome("0xabc") == "NO"

def test_accuracy_by_source_empty(tmp_path):
    import db as db_module
    db_module.DB_PATH = tmp_path / "t.db"
    with db_module.DB(tmp_path / "t.db") as d:
        stats = d.accuracy_by_source()
        assert isinstance(stats, dict)


# ── Market cache ──────────────────────────────────────────────────────────────

def test_upsert_and_get_market(tmp_path):
    import db as db_module
    db_module.DB_PATH = tmp_path / "t.db"
    with db_module.DB(tmp_path / "t.db") as d:
        d.upsert_market(market_id="0xabc", question="Will X happen?",
                        yes_token_id="tok_yes", no_token_id="tok_no", active=True)
        m = d.get_market("0xabc")
        assert m is not None
        assert m["question"] == "Will X happen?"
        assert m["active"] == 1

def test_upsert_market_updates(tmp_path):
    import db as db_module
    db_module.DB_PATH = tmp_path / "t.db"
    with db_module.DB(tmp_path / "t.db") as d:
        d.upsert_market(market_id="0xabc", question="Old question",
                        yes_token_id="t1", no_token_id="t2", active=True)
        d.upsert_market(market_id="0xabc", question="New question",
                        yes_token_id="t1", no_token_id="t2", active=False)
        m = d.get_market("0xabc")
        assert m["question"] == "New question"
        assert m["active"] == 0


# ── counts / status ───────────────────────────────────────────────────────────

def test_counts_structure(tmp_path):
    import db as db_module
    db_module.DB_PATH = tmp_path / "t.db"
    with db_module.DB(tmp_path / "t.db") as d:
        counts = d.counts()
        assert isinstance(counts, dict)
        for table in ("articles", "signals", "trades", "outcomes", "markets_cache"):
            assert table in counts
            assert counts[table] >= 0
