"""
normalize.py — Layer 2: deduplication and source trust weighting

Responsibilities:
  1. Assign a fingerprint to each story (title + domain + 15-min time bucket)
  2. Remove exact duplicates within a batch
  3. Attach a trust weight [0..1] based on source domain
  4. Filter out stories older than a configurable max age
  5. Normalise title text for downstream comparison

Source trust table covers ~60 domains; unknown domains default to 0.50.
"""
import hashlib
import re
import time
from datetime import timezone

# ---------------------------------------------------------------------------
# Source trust scores  (0.0 = ignore, 1.0 = maximum credibility)
# ---------------------------------------------------------------------------
SOURCE_TRUST: dict[str, float] = {
    # Official US government / regulatory
    "whitehouse.gov": 0.97,
    "federalreserve.gov": 0.97,
    "supremecourt.gov": 0.97,
    "sec.gov": 0.95,
    "justice.gov": 0.93,
    "cdc.gov": 0.90,
    "fda.gov": 0.90,
    "treasury.gov": 0.95,
    "doj.gov": 0.93,
    "state.gov": 0.90,
    "defense.gov": 0.88,
    "congress.gov": 0.90,
    # International official
    "ecb.europa.eu": 0.95,
    "bankofengland.co.uk": 0.94,
    "un.org": 0.88,
    "imf.org": 0.88,
    "worldbank.org": 0.85,
    # Major wire services
    "reuters.com": 0.87,
    "apnews.com": 0.87,
    "bloomberg.com": 0.86,
    "afp.com": 0.85,
    # Major business/finance press
    "ft.com": 0.84,
    "wsj.com": 0.83,
    "economist.com": 0.82,
    "nytimes.com": 0.80,
    "washingtonpost.com": 0.79,
    "theguardian.com": 0.78,
    "bbc.com": 0.80,
    "bbc.co.uk": 0.80,
    "cnbc.com": 0.76,
    "cnn.com": 0.72,
    "foxnews.com": 0.65,
    # Politics-specific
    "politico.com": 0.80,
    "thehill.com": 0.75,
    "axios.com": 0.78,
    "realclearpolitics.com": 0.65,
    "fivethirtyeight.com": 0.75,
    # Crypto-specific
    "coindesk.com": 0.72,
    "decrypt.co": 0.68,
    "theblock.co": 0.70,
    "cointelegraph.com": 0.65,
    "bitcoinmagazine.com": 0.62,
    # GDELT itself (aggregated)
    "gdelt.project": 0.60,
}

_DEFAULT_TRUST = 0.50

# ---------------------------------------------------------------------------
# Stop words for title normalisation
# ---------------------------------------------------------------------------
_STOPWORDS = frozenset(
    "a an the and or but in on at to for of with by from is are was were be "
    "been being have has had do does did will would could should may might "
    "shall can need must this that these those it its i we you he she they "
    "who what when where why how all any both each few more most other some "
    "such no nor not only own same so than too very just as".split()
)


def normalize_title(title: str) -> str:
    """Lowercase, strip punctuation, remove stopwords."""
    t = re.sub(r"[^\w\s]", " ", title.lower())
    tokens = [w for w in t.split() if w and w not in _STOPWORDS and not w.isdigit()]
    return " ".join(tokens)


def _time_bucket(ts: float, bucket_minutes: int = 15) -> int:
    """Round timestamp down to nearest N-minute bucket."""
    bucket_secs = bucket_minutes * 60
    return int(ts // bucket_secs)


def story_fingerprint(title: str, domain: str, pub_ts: float) -> str:
    """Stable 12-char hex fingerprint for deduplication."""
    key = f"{normalize_title(title)}|{domain}|{_time_bucket(pub_ts)}"
    return hashlib.sha1(key.encode()).hexdigest()[:12]


def domain_trust(story: dict) -> float:
    """Look up trust score for story's domain."""
    domain = story.get("domain", "").lower().lstrip("www.")
    # Exact match
    if domain in SOURCE_TRUST:
        return SOURCE_TRUST[domain]
    # Suffix match (e.g. sub.reuters.com)
    for key, val in SOURCE_TRUST.items():
        if domain.endswith(key):
            return val
    # Fall back to _trust embedded by RSS client
    return story.get("_trust", _DEFAULT_TRUST)


def dedup(stories: list[dict]) -> list[dict]:
    """Remove stories with identical fingerprints; keep highest-trust copy."""
    by_fp: dict[str, dict] = {}
    for s in stories:
        fp = s.get("id") or story_fingerprint(s["title"], s["domain"], s["pub_ts"])
        s["id"] = fp
        s["trust"] = domain_trust(s)
        existing = by_fp.get(fp)
        if existing is None or s["trust"] > existing["trust"]:
            by_fp[fp] = s
    return list(by_fp.values())


def filter_age(stories: list[dict], max_age_secs: float = 3600.0) -> list[dict]:
    """Keep only stories published within *max_age_secs* of now."""
    cutoff = time.time() - max_age_secs
    return [s for s in stories if s.get("pub_ts", 0) >= cutoff]


def normalize_batch(
    stories: list[dict],
    max_age_secs: float = 3600.0,
    seen_ids: set[str] | None = None,
) -> tuple[list[dict], set[str]]:
    """Full normalisation pipeline for a raw batch from any source.

    1. Assign fingerprint + trust to each story
    2. Deduplicate within batch
    3. Filter by age
    4. Remove already-seen fingerprints (cross-run dedup)

    Returns:
        (new_stories, updated_seen_ids)
    """
    if seen_ids is None:
        seen_ids = set()

    # Assign IDs and trust scores
    for s in stories:
        if not s.get("id"):
            s["id"] = story_fingerprint(s["title"], s.get("domain", ""), s.get("pub_ts", time.time()))
        s["trust"] = domain_trust(s)

    # Dedup within batch
    unique = dedup(stories)

    # Age filter
    fresh = filter_age(unique, max_age_secs)

    # Cross-run dedup
    new = [s for s in fresh if s["id"] not in seen_ids]
    new_seen = seen_ids | {s["id"] for s in new}

    return new, new_seen
