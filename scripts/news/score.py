"""
score.py — 5-factor impact scoring

Computes a structured impact signal for a (story, market) pair.

The five factors:
  source_trust    — credibility of the publishing domain          [0..1]
  novelty         — how recent + uncovered-before the story is    [0..1]
  relevance       — keyword overlap story ↔ market question       [0..1]
  specificity     — how directly the story bears on THIS market   [0..1]
  urgency         — linguistic urgency signals in title           [0..1]

Aggregate: impact = source_trust × novelty × relevance × specificity × urgency
           (geometric mean to penalise any single weak dimension)

A high impact score alone doesn't mean "trade". It means the signal is strong.
Trade gating (edge > fees + slippage) happens later in pipeline.py.
"""
from __future__ import annotations

import math
import re
import time


# ---------------------------------------------------------------------------
# 1. Source trust  (already computed in normalize layer; just read it)
# ---------------------------------------------------------------------------
def source_trust_score(story: dict) -> float:
    return float(story.get("trust", 0.5))


# ---------------------------------------------------------------------------
# 2. Novelty  (decays with age; boost for multi-source coverage)
# ---------------------------------------------------------------------------
def novelty_score(story: dict, now: float | None = None) -> float:
    """Higher for fresher stories.  Drops to 0.5 after 1 hour, 0.2 after 4h."""
    if now is None:
        now = time.time()
    age_secs = max(0.0, now - story.get("pub_ts", now))
    cluster_size = story.get("_cluster_size", 1)

    # Base decay: exponential with half-life 45 min
    base = math.exp(-age_secs / 2700)

    # Multi-source boost: capped at 0.15 extra
    boost = min(0.15, 0.05 * (cluster_size - 1))

    return min(1.0, base + boost)


# ---------------------------------------------------------------------------
# 3. Relevance  (from mapper; passed in)
# ---------------------------------------------------------------------------
def relevance_score(relevance: float) -> float:
    """Clip to [0..1]."""
    return max(0.0, min(1.0, relevance))


# ---------------------------------------------------------------------------
# 4. Specificity  (how directly the story names THIS market's subject)
# ---------------------------------------------------------------------------
_HIGH_SPEC_PATTERNS = [
    # Ruling / decision on named entity
    r"\b(rules?|ruled|ruling|decides?|decided|orders?|ordered)\b",
    # Direct action affecting a market
    r"\b(wins?|won|loses?|lost|elected|appointed|confirmed|indicted|convicted|acquitted)\b",
    # Hard numbers
    r"\b\d+[\.,]\d+\s*%",
    # Named individuals in political markets
    r"\b(trump|biden|harris|desantis|obama|powell|yellen|lagarde)\b",
    # Central bank specifics
    r"\b(25bp|50bp|rate (cut|hike|hold)|basis points?)\b",
]
_LOW_SPEC_PATTERNS = [
    r"\b(could|might|may|possibly|reportedly|sources? say|rumou?r)\b",
    r"\b(opinion|analysis|market watch|explainer)\b",
]

_HIGH_RE = re.compile("|".join(_HIGH_SPEC_PATTERNS), re.I)
_LOW_RE  = re.compile("|".join(_LOW_SPEC_PATTERNS), re.I)


def specificity_score(story: dict, market: dict) -> float:
    """0..1 score for how specifically the story addresses THIS market."""
    text = f"{story.get('title', '')} {story.get('body', '')}".lower()
    question = (market.get("question") or "").lower()

    # Extract market subject entities (nouns > 3 chars)
    subject_words = frozenset(
        w for w in re.sub(r"[^\w\s]", " ", question).split()
        if len(w) > 3
    )
    text_words = frozenset(re.sub(r"[^\w\s]", " ", text).split())
    overlap = len(subject_words & text_words) / max(1, len(subject_words))

    # Boost for action/decision language
    if _HIGH_RE.search(text):
        overlap = min(1.0, overlap + 0.25)
    # Penalty for hedged/rumour language
    if _LOW_RE.search(story.get("title", "")):
        overlap *= 0.6

    return min(1.0, overlap)


# ---------------------------------------------------------------------------
# 5. Urgency  (language + title casing signals)
# ---------------------------------------------------------------------------
_URGENCY_HIGH = frozenset(
    "breaking just now immediately urgent alert flash confirmed official "
    "announces announced statement decision verdict ruling passes signed "
    "emergency exclusive".split()
)
_URGENCY_MED = frozenset(
    "report says warns expects plans considering weighing proposes "
    "prepares urges calls moves".split()
)


def urgency_score(story: dict) -> float:
    """0..1 urgency estimate from title vocabulary."""
    title = story.get("title", "").lower()
    words = set(re.sub(r"[^\w\s]", " ", title).split())

    high_hits = len(words & _URGENCY_HIGH)
    med_hits  = len(words & _URGENCY_MED)

    base = 0.35  # default: moderate urgency
    score = base + 0.20 * min(3, high_hits) + 0.08 * min(3, med_hits)

    # ALL-CAPS words in title → slight boost (headline alarm signal)
    caps_words = [w for w in story.get("title", "").split() if len(w) > 3 and w.isupper()]
    if caps_words:
        score = min(1.0, score + 0.05 * len(caps_words))

    return min(1.0, score)


# ---------------------------------------------------------------------------
# Aggregate
# ---------------------------------------------------------------------------
def impact_score(story: dict, market: dict, relevance: float) -> dict:
    """Compute all 5 factors and return a structured score dict.

    Returns:
        {
          "trust":       float,
          "novelty":     float,
          "relevance":   float,
          "specificity": float,
          "urgency":     float,
          "impact":      float,   # geometric mean of all 5
        }
    """
    trust   = source_trust_score(story)
    novelty = novelty_score(story)
    rel     = relevance_score(relevance)
    spec    = specificity_score(story, market)
    urg     = urgency_score(story)

    # Geometric mean → any single zero kills the signal
    factors = [trust, novelty, rel, spec, urg]
    geo     = math.prod(f for f in factors) ** (1 / len(factors))

    return {
        "trust":       round(trust,   3),
        "novelty":     round(novelty, 3),
        "relevance":   round(rel,     3),
        "specificity": round(spec,    3),
        "urgency":     round(urg,     3),
        "impact":      round(geo,     4),
    }
