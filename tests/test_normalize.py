"""
Tests for scripts/news/normalize.py
"""
import sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
from news.normalize import (
    story_fingerprint,
    normalize_batch,
    SOURCE_TRUST,
    _DEFAULT_TRUST,
    domain_trust,
    dedup,
    filter_age,
)


def _story(title="Test headline", url="https://example.com/1",
           domain="example.com", pub_ts=None, source="Test") -> dict:
    return {
        "id": "",
        "title": title,
        "url": url,
        "domain": domain,
        "pub_ts": pub_ts or time.time(),
        "body": "Some body text",
        "source": source,
        "lang": "en",
        "_trust": 0.6,
    }


# ── story_fingerprint ──────────────────────────────────────────────────────────

def test_fingerprint_deterministic():
    ts = time.time()
    assert story_fingerprint("Trump wins", "a.com", ts) == \
           story_fingerprint("Trump wins", "a.com", ts)

def test_fingerprint_different_titles():
    ts = time.time()
    assert story_fingerprint("Trump wins", "a.com", ts) != \
           story_fingerprint("Biden wins", "a.com", ts)

def test_fingerprint_same_title_different_domain():
    ts = time.time()
    assert story_fingerprint("Big news", "a.com", ts) != \
           story_fingerprint("Big news", "b.com", ts)

def test_fingerprint_same_title_15min_bucket():
    # Anchor to the start of the current 15-min bucket so +5 min never crosses a boundary.
    base = (int(time.time()) // 900) * 900
    assert story_fingerprint("Big news", "a.com", base) == \
           story_fingerprint("Big news", "a.com", base + 300)   # 5 min later → same bucket

def test_fingerprint_different_15min_bucket():
    # Anchor to start of bucket; +900 s is exactly the next bucket boundary.
    base = (int(time.time()) // 900) * 900
    assert story_fingerprint("Big news", "a.com", base) != \
           story_fingerprint("Big news", "a.com", base + 900)   # 15 min later → new bucket

def test_fingerprint_case_insensitive():
    ts = time.time()
    assert story_fingerprint("FED RAISES RATES", "a.com", ts) == \
           story_fingerprint("fed raises rates", "a.com", ts)


# ── domain_trust ──────────────────────────────────────────────────────────────

def test_domain_trust_known():
    assert domain_trust(_story(domain="reuters.com")) == SOURCE_TRUST["reuters.com"]

def test_domain_trust_unknown_returns_default():
    # Remove the _trust key so fallback goes to _DEFAULT_TRUST
    s = {k: v for k, v in _story(domain="obscureblog999.xyz").items() if k != "_trust"}
    assert domain_trust(s) == _DEFAULT_TRUST

def test_domain_trust_subdomain():
    assert domain_trust(_story(domain="markets.reuters.com")) == SOURCE_TRUST["reuters.com"]


# ── dedup ──────────────────────────────────────────────────────────────────────

def test_dedup_removes_duplicate_fingerprints():
    ts = time.time()
    assert len(dedup([_story("Test", pub_ts=ts), _story("Test", pub_ts=ts)])) == 1

def test_dedup_keeps_highest_trust():
    """Pre-assign same id so dedup sees them as duplicates; higher-trust domain wins."""
    ts = time.time()
    s1 = _story("Test", url="https://reuters.com/1",  domain="reuters.com", pub_ts=ts)
    s2 = _story("Test", url="https://obscureblog.xyz/1", domain="obscureblog.xyz", pub_ts=ts)
    # Force same fingerprint id so dedup treats them as duplicates
    s1["id"] = s2["id"] = "collision_id"
    result = dedup([s1, s2])
    assert len(result) == 1
    assert result[0]["domain"] == "reuters.com"

def test_dedup_keeps_different_stories():
    assert len(dedup([_story("Fed raises rates"), _story("Market drops 5%")])) == 2


# ── filter_age ────────────────────────────────────────────────────────────────

def test_filter_age_removes_old():
    old    = _story("Old",    pub_ts=time.time() - 7200)
    recent = _story("Recent", url="https://example.com/2", pub_ts=time.time() - 1800)
    result = filter_age([old, recent], max_age_secs=3600)
    assert len(result) == 1
    assert result[0]["title"] == "Recent"

def test_filter_age_keeps_fresh():
    assert len(filter_age([_story(pub_ts=time.time() - 60)], max_age_secs=3600)) == 1


# ── normalize_batch ───────────────────────────────────────────────────────────

def test_normalize_batch_returns_tuple():
    result = normalize_batch([_story()])
    assert isinstance(result, tuple) and len(result) == 2

def test_normalize_batch_dedup_exact():
    s = _story()
    stories, _ = normalize_batch([s, s, s])
    assert len(stories) == 1

def test_normalize_batch_dedup_same_fingerprint():
    """Same title + same domain + same 15-min bucket → identical fingerprint → deduped."""
    base = time.time()
    s1 = _story("Trump wins re-election", "https://a.com/1", "a.com", pub_ts=base)
    s2 = _story("Trump wins re-election", "https://a.com/2", "a.com", pub_ts=base + 60)  # same domain
    stories, _ = normalize_batch([s1, s2])
    assert len(stories) == 1

def test_normalize_batch_keeps_different_stories():
    stories, _ = normalize_batch([_story("Fed raises rates", "https://a.com/1"),
                                   _story("Market drops 5%",  "https://a.com/2")])
    assert len(stories) == 2

def test_normalize_batch_attaches_trust_known_domain():
    stories, _ = normalize_batch([_story(domain="reuters.com")])
    assert stories[0]["trust"] == SOURCE_TRUST["reuters.com"]

def test_normalize_batch_attaches_unknown_trust():
    s = {k: v for k, v in _story(domain="obscureblog123.xyz").items() if k != "_trust"}
    stories, _ = normalize_batch([s])
    assert stories[0]["trust"] == _DEFAULT_TRUST

def test_normalize_batch_filters_old_stories():
    old    = _story("Old Story",    url="https://a.com/1", pub_ts=time.time() - 90000)
    recent = _story("Recent Story", url="https://a.com/2", pub_ts=time.time() - 3600)
    stories, _ = normalize_batch([old, recent], max_age_secs=86400)
    assert len(stories) == 1
    assert stories[0]["title"] == "Recent Story"

def test_normalize_batch_empty_input():
    stories, seen = normalize_batch([])
    assert stories == [] and isinstance(seen, set)

def test_normalize_batch_seen_ids_cross_run_dedup():
    s = _story()
    _, seen = normalize_batch([s])
    stories2, _ = normalize_batch([s], seen_ids=seen)
    assert len(stories2) == 0

def test_normalize_batch_attaches_fingerprint():
    stories, _ = normalize_batch([_story()])
    assert stories[0].get("id")

def test_source_trust_sanity():
    assert SOURCE_TRUST["reuters.com"] > 0.7
    assert SOURCE_TRUST["whitehouse.gov"] > 0.9
    assert 0.0 < _DEFAULT_TRUST < 0.7

