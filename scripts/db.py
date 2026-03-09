#!/usr/bin/env python3
"""
db.py — Unified SQLite data layer for OpenPoly.

Single database file: openpoly.db (in the skill root).

Tables:
  articles      — ingested news stories (from news pipeline)
  signals       — trade signals from any source (news/ai/arb)
  trades        — executed orders
  outcomes      — resolved market outcomes + per-signal correctness
  markets_cache — lightweight market metadata cache

Importable API:
  from db import DB
  db = DB()
  db.insert_article(...)
  db.insert_signal(...)
  db.record_trade(...)
  db.resolve_outcome(...)

CLI:
  python scripts/db.py status                  # counts per table
  python scripts/db.py migrate                 # absorb existing JSON state files
  python scripts/db.py articles [--limit 20]   # last N articles
  python scripts/db.py signals  [--source news] [--limit 20]
  python scripts/db.py trades   [--limit 20]
  python scripts/db.py outcomes [--market-id ID]
  python scripts/db.py vacuum                  # VACUUM + integrity check
"""

import argparse, json, sqlite3, sys, time
from datetime import datetime, timezone
from pathlib import Path

_SCRIPTS_DIR = Path(__file__).parent
_SKILL_DIR   = _SCRIPTS_DIR.parent
DB_PATH      = _SKILL_DIR / "openpoly.db"

# ── Schema ────────────────────────────────────────────────────────────────────
_SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS articles (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    fingerprint   TEXT    UNIQUE NOT NULL,
    url           TEXT,
    title         TEXT    NOT NULL,
    source        TEXT    NOT NULL DEFAULT '',
    trust         REAL    NOT NULL DEFAULT 0.5,
    published_at  INTEGER NOT NULL DEFAULT 0,   -- unix timestamp
    ingested_at   INTEGER NOT NULL DEFAULT 0,
    cluster_id    TEXT,
    keywords      TEXT    DEFAULT '[]',          -- JSON list
    raw_json      TEXT    DEFAULT '{}'           -- full story dict
);

CREATE TABLE IF NOT EXISTS signals (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    source        TEXT    NOT NULL,              -- news | ai | arb | manual
    market_id     TEXT    NOT NULL,
    token_id      TEXT    DEFAULT '',
    direction     TEXT    NOT NULL,              -- YES | NO | ARB
    confidence    REAL    NOT NULL DEFAULT 0.0,
    edge_estimate REAL    NOT NULL DEFAULT 0.0,
    fair_prob     REAL,                          -- output of prob_model (nullable)
    created_at    INTEGER NOT NULL DEFAULT 0,
    model_version TEXT    DEFAULT '1',
    meta          TEXT    DEFAULT '{}'           -- extra JSON
);

CREATE TABLE IF NOT EXISTS trades (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    signal_id     INTEGER REFERENCES signals(id),
    market_id     TEXT    NOT NULL,
    token_id      TEXT    NOT NULL,
    side          TEXT    NOT NULL,              -- BUY | SELL
    price         REAL    NOT NULL,
    size_usd      REAL    NOT NULL,
    order_id      TEXT,
    status        TEXT    NOT NULL DEFAULT 'open',   -- open | filled | cancelled
    filled_price  REAL,
    pnl           REAL,
    created_at    INTEGER NOT NULL DEFAULT 0,
    closed_at     INTEGER
);

CREATE TABLE IF NOT EXISTS outcomes (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    market_id     TEXT    NOT NULL,
    outcome       TEXT    NOT NULL,              -- YES | NO
    resolved_at   INTEGER NOT NULL DEFAULT 0,
    UNIQUE(market_id)
);

CREATE TABLE IF NOT EXISTS signal_outcomes (
    signal_id     INTEGER NOT NULL REFERENCES signals(id),
    outcome_id    INTEGER NOT NULL REFERENCES outcomes(id),
    correct       INTEGER NOT NULL,              -- 1=hit  0=miss
    PRIMARY KEY (signal_id, outcome_id)
);

CREATE TABLE IF NOT EXISTS markets_cache (
    market_id     TEXT    PRIMARY KEY,
    question      TEXT    NOT NULL DEFAULT '',
    tags          TEXT    DEFAULT '[]',
    yes_token_id  TEXT    DEFAULT '',
    no_token_id   TEXT    DEFAULT '',
    active        INTEGER DEFAULT 1,
    last_fetched  INTEGER NOT NULL DEFAULT 0,
    raw_json      TEXT    DEFAULT '{}'
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_articles_fp       ON articles(fingerprint);
CREATE INDEX IF NOT EXISTS idx_articles_pub      ON articles(published_at);
CREATE INDEX IF NOT EXISTS idx_signals_market    ON signals(market_id);
CREATE INDEX IF NOT EXISTS idx_signals_source    ON signals(source);
CREATE INDEX IF NOT EXISTS idx_signals_created   ON signals(created_at);
CREATE INDEX IF NOT EXISTS idx_trades_market     ON trades(market_id);
CREATE INDEX IF NOT EXISTS idx_trades_signal     ON trades(signal_id);
CREATE INDEX IF NOT EXISTS idx_outcomes_market   ON outcomes(market_id);
"""

# ── DB class ──────────────────────────────────────────────────────────────────

class DB:
    """
    Thread-safe SQLite wrapper. Use as a context manager or call close() when done.
    Connections use WAL mode for safe concurrent reads.
    """

    def __init__(self, path: Path | str = DB_PATH):
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self._path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(_SCHEMA)
        self._conn.commit()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

    def close(self):
        self._conn.close()

    def _now(self) -> int:
        return int(time.time())

    # ── Articles ──────────────────────────────────────────────────────────────

    def insert_article(self, story: dict) -> int | None:
        """
        Insert a news story from the pipeline. Silently ignores duplicates.
        Returns the rowid on insert, None if fingerprint already exists.
        story keys: fingerprint, url, title, source, trust, published_at,
                    cluster_id, keywords (list), raw (full dict)
        """
        fp = story.get("id") or story.get("fingerprint", "")
        if not fp:
            return None
        try:
            cur = self._conn.execute(
                """INSERT OR IGNORE INTO articles
                   (fingerprint, url, title, source, trust,
                    published_at, ingested_at, cluster_id, keywords, raw_json)
                   VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (
                    fp,
                    story.get("url", ""),
                    story.get("title", "")[:512],
                    story.get("source", ""),
                    float(story.get("trust", 0.5)),
                    int(story.get("published_at", self._now())),
                    self._now(),
                    story.get("cluster_id"),
                    json.dumps(story.get("keywords", [])),
                    json.dumps(story),
                ),
            )
            self._conn.commit()
            return cur.lastrowid if cur.rowcount else None
        except Exception:
            return None

    def article_exists(self, fingerprint: str) -> bool:
        row = self._conn.execute(
            "SELECT 1 FROM articles WHERE fingerprint=?", (fingerprint,)
        ).fetchone()
        return row is not None

    def recent_articles(self, limit: int = 20, source: str = "") -> list[sqlite3.Row]:
        if source:
            return self._conn.execute(
                "SELECT * FROM articles WHERE source=? ORDER BY published_at DESC LIMIT ?",
                (source, limit),
            ).fetchall()
        return self._conn.execute(
            "SELECT * FROM articles ORDER BY published_at DESC LIMIT ?", (limit,)
        ).fetchall()

    # ── Signals ───────────────────────────────────────────────────────────────

    def insert_signal(self, source: str, market_id: str, direction: str,
                      confidence: float = 0.0, edge_estimate: float = 0.0,
                      token_id: str = "", fair_prob: float | None = None,
                      model_version: str = "1", meta: dict | None = None) -> int:
        """Insert a trade signal. Returns the new signal id."""
        cur = self._conn.execute(
            """INSERT INTO signals
               (source, market_id, token_id, direction, confidence,
                edge_estimate, fair_prob, created_at, model_version, meta)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (
                source, market_id, token_id, direction,
                float(confidence), float(edge_estimate),
                float(fair_prob) if fair_prob is not None else None,
                self._now(), model_version,
                json.dumps(meta or {}),
            ),
        )
        self._conn.commit()
        return cur.lastrowid

    def recent_signals(self, limit: int = 20, source: str = "",
                       market_id: str = "") -> list[sqlite3.Row]:
        clauses, params = [], []
        if source:
            clauses.append("source=?")
            params.append(source)
        if market_id:
            clauses.append("market_id=?")
            params.append(market_id)
        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        params.append(limit)
        return self._conn.execute(
            f"SELECT * FROM signals {where} ORDER BY created_at DESC LIMIT ?",
            params,
        ).fetchall()

    # ── Trades ────────────────────────────────────────────────────────────────

    def record_trade(self, market_id: str, token_id: str, side: str,
                     price: float, size_usd: float, order_id: str = "",
                     signal_id: int | None = None) -> int:
        """Record a placed order. Returns the trade id."""
        cur = self._conn.execute(
            """INSERT INTO trades
               (signal_id, market_id, token_id, side, price,
                size_usd, order_id, status, created_at)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (
                signal_id, market_id, token_id, side,
                float(price), float(size_usd), order_id,
                "open", self._now(),
            ),
        )
        self._conn.commit()
        return cur.lastrowid

    def close_trade(self, trade_id: int, filled_price: float, pnl: float,
                    status: str = "filled"):
        self._conn.execute(
            """UPDATE trades SET status=?, filled_price=?, pnl=?, closed_at=?
               WHERE id=?""",
            (status, filled_price, pnl, self._now(), trade_id),
        )
        self._conn.commit()

    def recent_trades(self, limit: int = 20) -> list[sqlite3.Row]:
        return self._conn.execute(
            "SELECT * FROM trades ORDER BY created_at DESC LIMIT ?", (limit,)
        ).fetchall()

    # ── Outcomes ──────────────────────────────────────────────────────────────

    def resolve_outcome(self, market_id: str, outcome: str,
                        resolved_at: int = 0) -> int:
        """
        Record the resolved outcome for a market and score any pending signals.
        Returns outcome id.
        """
        ts = resolved_at or self._now()
        cur = self._conn.execute(
            """INSERT OR REPLACE INTO outcomes (market_id, outcome, resolved_at)
               VALUES (?,?,?)""",
            (market_id, outcome.upper(), ts),
        )
        self._conn.commit()
        outcome_id = cur.lastrowid

        # Score pending signals for this market
        sigs = self._conn.execute(
            "SELECT id, direction FROM signals WHERE market_id=?",
            (market_id,),
        ).fetchall()
        for sig in sigs:
            correct = 1 if (
                sig["direction"].upper() == outcome.upper() or
                sig["direction"].upper() == "ARB"   # arb always hedged
            ) else 0
            self._conn.execute(
                """INSERT OR IGNORE INTO signal_outcomes (signal_id, outcome_id, correct)
                   VALUES (?,?,?)""",
                (sig["id"], outcome_id, correct),
            )
        self._conn.commit()
        return outcome_id

    def get_outcome(self, market_id: str) -> str | None:
        row = self._conn.execute(
            "SELECT outcome FROM outcomes WHERE market_id=?", (market_id,)
        ).fetchone()
        return row["outcome"] if row else None

    # ── Markets cache ─────────────────────────────────────────────────────────

    def upsert_market(self, market_id: str, question: str = "",
                      tags: list | None = None, yes_token_id: str = "",
                      no_token_id: str = "", active: bool = True,
                      raw: dict | None = None):
        self._conn.execute(
            """INSERT INTO markets_cache
               (market_id, question, tags, yes_token_id, no_token_id,
                active, last_fetched, raw_json)
               VALUES (?,?,?,?,?,?,?,?)
               ON CONFLICT(market_id) DO UPDATE SET
                 question=excluded.question,
                 tags=excluded.tags,
                 yes_token_id=excluded.yes_token_id,
                 no_token_id=excluded.no_token_id,
                 active=excluded.active,
                 last_fetched=excluded.last_fetched,
                 raw_json=excluded.raw_json""",
            (
                market_id, question,
                json.dumps(tags or []),
                yes_token_id, no_token_id,
                int(active), self._now(),
                json.dumps(raw or {}),
            ),
        )
        self._conn.commit()

    def get_market(self, market_id: str) -> sqlite3.Row | None:
        return self._conn.execute(
            "SELECT * FROM markets_cache WHERE market_id=?", (market_id,)
        ).fetchone()

    # ── Accuracy stats ────────────────────────────────────────────────────────

    def accuracy_by_source(self) -> dict[str, dict]:
        """Return hit rate per signal source from scored signal_outcomes."""
        rows = self._conn.execute(
            """SELECT s.source, so.correct, COUNT(*) as n
               FROM signal_outcomes so
               JOIN signals s ON s.id = so.signal_id
               GROUP BY s.source, so.correct""",
        ).fetchall()
        stats: dict[str, dict] = {}
        for r in rows:
            d = stats.setdefault(r["source"], {"hit": 0, "miss": 0})
            key = "hit" if r["correct"] else "miss"
            d[key] += r["n"]
        for src, d in stats.items():
            total = d["hit"] + d["miss"]
            d["hit_rate"] = round(d["hit"] / total, 3) if total else None
        return stats

    # ── Table counts ──────────────────────────────────────────────────────────

    def counts(self) -> dict[str, int]:
        tables = ["articles", "signals", "trades", "outcomes",
                  "signal_outcomes", "markets_cache"]
        return {
            t: self._conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
            for t in tables
        }


# ── Migration: absorb existing JSON state files ───────────────────────────────

def _migrate(db: DB):
    """
    One-time migration: read existing JSON state files and write them into
    the database. Safe to run multiple times (uses INSERT OR IGNORE / upsert).
    """
    migrated = {}

    # news_trader_state.json → signals + articles
    p = _SKILL_DIR / "news_trader_state.json"
    if p.exists():
        state = json.loads(p.read_text())
        n = 0
        for entry in state.get("trade_log", []):
            mid = entry.get("market_id") or entry.get("conditionId", "")
            direction = entry.get("side", entry.get("direction", "")).upper()
            if mid and direction:
                db.insert_signal(
                    source="news", market_id=mid, direction=direction,
                    confidence=float(entry.get("impact", entry.get("edge", 0))),
                    edge_estimate=float(entry.get("edge", 0)),
                    meta=entry,
                )
                n += 1
        if n:
            migrated["news_signals"] = n

        # seen article fingerprints
        n = 0
        for fp in state.get("seen_ids", []):
            try:
                db._conn.execute(
                    "INSERT OR IGNORE INTO articles (fingerprint,title,source,ingested_at)"
                    " VALUES (?,?,?,?)",
                    (fp, f"[migrated:{fp[:16]}]", "news_trader_state", int(time.time())),
                )
                n += 1
            except Exception:
                pass
        db._conn.commit()
        if n:
            migrated["article_fp"] = n

    # ai_signals.json → signals
    p = _SKILL_DIR / "ai_signals.json"
    if p.exists():
        state = json.loads(p.read_text())
        raw = state.get("history", state.get("signals", []))
        n = 0
        for entry in (raw if isinstance(raw, list) else []):
            mid = entry.get("market_id") or entry.get("conditionId", "")
            d   = (entry.get("direction", entry.get("side", "")) or "").upper()
            if d == "BUY": d = "YES"
            elif d == "SELL": d = "NO"
            if mid and d:
                db.insert_signal(
                    source="ai", market_id=mid, direction=d,
                    confidence=float(entry.get("confidence", entry.get("edge", 0))),
                    edge_estimate=float(entry.get("edge", 0)),
                    meta=entry,
                )
                n += 1
        if n:
            migrated["ai_signals"] = n

    # eval_log.json → outcomes + signal scoring
    p = _SKILL_DIR / "eval_log.json"
    if p.exists():
        log = json.loads(p.read_text())
        n = 0
        for entry in (log if isinstance(log, list) else []):
            mid     = entry.get("market_id", "")
            outcome = entry.get("actual_outcome", "")
            if mid and outcome:
                db.resolve_outcome(mid, outcome)
                n += 1
        if n:
            migrated["outcomes"] = n

    # watchlist.json → markets_cache
    p = _SKILL_DIR / "watchlist.json"
    if p.exists():
        wl = json.loads(p.read_text())
        n = 0
        for entry in (wl if isinstance(wl, list) else wl.values()):
            tid = entry.get("token_id", "")
            if tid:
                db.upsert_market(
                    market_id=entry.get("market_id", tid),
                    question=entry.get("question", entry.get("market", "")),
                    yes_token_id=tid,
                )
                n += 1
        if n:
            migrated["watchlist"] = n

    return migrated


# ── Formatting helpers ────────────────────────────────────────────────────────

def _ts(ts: int) -> str:
    if not ts:
        return "–"
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d %H:%M")


def _print_articles(rows):
    print(f"\n  {'DATE':>16}  {'SOURCE':<18} {'TITLE':<50}")
    print("  " + "─" * 86)
    for r in rows:
        print(f"  {_ts(r['published_at']):>16}  {r['source']:<18} {r['title'][:50]}")


def _print_signals(rows):
    print(f"\n  {'DATE':>16}  {'SRC':<6} {'DIR':<5} {'CONF':>5} {'EDGE':>5}  {'MARKET':<40}")
    print("  " + "─" * 80)
    for r in rows:
        fp = float(r["fair_prob"]) if r["fair_prob"] is not None else float("nan")
        print(f"  {_ts(r['created_at']):>16}  {r['source']:<6} {r['direction']:<5} "
              f"{r['confidence']:>5.2f} {r['edge_estimate']:>5.2f}  {r['market_id'][:40]}")


def _print_trades(rows):
    print(f"\n  {'DATE':>16}  {'SIDE':<5} {'PRICE':>6} {'SIZE':>7} {'STATUS':<10} {'ORDER':<20}")
    print("  " + "─" * 72)
    for r in rows:
        print(f"  {_ts(r['created_at']):>16}  {r['side']:<5} {r['price']:>6.3f} "
              f"${r['size_usd']:>6.2f} {r['status']:<10} {(r['order_id'] or '')[:18]}")


# ── CLI ───────────────────────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser(description="OpenPoly SQLite data layer")
    sp = ap.add_subparsers(dest="cmd")

    sp.add_parser("status",  help="Row counts per table")
    sp.add_parser("migrate", help="Absorb existing JSON state files")
    sp.add_parser("vacuum",  help="VACUUM + integrity check")
    sp.add_parser("schema",  help="Print the full schema")

    sp_art = sp.add_parser("articles", help="Show recent ingested articles")
    sp_art.add_argument("--limit",  type=int, default=20)
    sp_art.add_argument("--source", default="")

    sp_sig = sp.add_parser("signals",  help="Show recent signals")
    sp_sig.add_argument("--limit",     type=int, default=20)
    sp_sig.add_argument("--source",    default="",
                        help="news | ai | arb")
    sp_sig.add_argument("--market-id", default="")

    sp_tr = sp.add_parser("trades",    help="Show recent trades")
    sp_tr.add_argument("--limit",      type=int, default=20)

    sp_out = sp.add_parser("outcomes", help="Show resolved outcomes")
    sp_out.add_argument("--market-id", default="")
    sp_out.add_argument("--limit",     type=int, default=20)

    sp_acc = sp.add_parser("accuracy", help="Hit rate by signal source")
    sp_acc.add_argument("--json",      action="store_true")

    args = ap.parse_args()

    with DB() as db:

        if args.cmd in (None, "status"):
            counts = db.counts()
            print()
            print("═" * 44)
            print("  OpenPoly DB — " + str(DB_PATH))
            print("═" * 44)
            for t, n in counts.items():
                print(f"  {t:<22} {n:>8,} rows")
            size = DB_PATH.stat().st_size / 1024 if DB_PATH.exists() else 0
            print(f"\n  File size: {size:.1f} KB")
            print("═" * 44)

        elif args.cmd == "migrate":
            print("Migrating existing JSON state files…")
            result = _migrate(db)
            if result:
                for k, v in result.items():
                    print(f"  ✓ {k}: {v:,} rows")
                print("Migration complete.")
            else:
                print("Nothing to migrate (no JSON state files found).")

        elif args.cmd == "vacuum":
            print("Running VACUUM…", end=" ", flush=True)
            db._conn.execute("VACUUM")
            result = db._conn.execute(
                "PRAGMA integrity_check"
            ).fetchone()[0]
            print(f"done.  Integrity: {result}")

        elif args.cmd == "schema":
            print(_SCHEMA)

        elif args.cmd == "articles":
            rows = db.recent_articles(args.limit, args.source)
            print(f"\n  {len(rows)} most recent articles"
                  + (f" (source={args.source})" if args.source else ""))
            _print_articles(rows)

        elif args.cmd == "signals":
            rows = db.recent_signals(
                args.limit, args.source,
                getattr(args, "market_id", "").replace("-", "_"),
            )
            market_id = getattr(args, "market_id", "") or ""
            print(f"\n  {len(rows)} most recent signals"
                  + (f" (source={args.source})" if args.source else "")
                  + (f" (market={market_id})" if market_id else ""))
            _print_signals(rows)

        elif args.cmd == "trades":
            rows = db.recent_trades(args.limit)
            print(f"\n  {len(rows)} most recent trades")
            _print_trades(rows)

        elif args.cmd == "outcomes":
            market_id = getattr(args, "market_id", "") or ""
            limit     = getattr(args, "limit", 20)
            if market_id:
                row = db._conn.execute(
                    "SELECT * FROM outcomes WHERE market_id=?",
                    (market_id,),
                ).fetchone()
                rows = [row] if row else []
            else:
                rows = db._conn.execute(
                    "SELECT * FROM outcomes ORDER BY resolved_at DESC LIMIT ?",
                    (limit,),
                ).fetchall()
            print(f"\n  {'RESOLVED':>16}  {'OUTCOME':<6}  MARKET ID")
            print("  " + "─" * 62)
            for r in rows:
                print(f"  {_ts(r['resolved_at']):>16}  {r['outcome']:<6}  {r['market_id']}")

        elif args.cmd == "accuracy":
            stats = db.accuracy_by_source()
            if getattr(args, "json", False):
                print(json.dumps(stats, indent=2))
            else:
                print(f"\n  {'SOURCE':<10} {'HIT%':>6} {'HITS':>6} {'MISSES':>7}")
                print("  " + "─" * 34)
                for src, d in sorted(stats.items()):
                    hr = f"{d['hit_rate']:.1%}" if d.get("hit_rate") is not None else "  n/a"
                    print(f"  {src:<10} {hr:>6} {d['hit']:>6} {d['miss']:>7}")
                if not stats:
                    print("  No scored signals yet. Run  poly eval  first.")


if __name__ == "__main__":
    main()
