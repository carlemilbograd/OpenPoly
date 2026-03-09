"""
cluster.py — Layer 2b: group near-duplicate stories into clusters

Problem: the same story ("Fed holds rates") arrives from 20 sources within
5 minutes. Trading on each copy multiplies exposure + fees for no new signal.

Approach:
  1. Tokenise normalised title → frozenset of meaningful tokens
  2. Jaccard similarity between token sets
  3. Union-Find clustering: merge stories above *threshold*
  4. For each cluster, elect the representative with best trust × recency score

This is O(n²) in token-set comparisons but fast enough for n ≤ 500 stories.
For larger batches we could use MinHash / LSH — not needed at this scale.
"""
from __future__ import annotations

import time

from .normalize import normalize_title

_MIN_TOKENS = 3  # skip stories with fewer meaningful tokens


def _tokens(title: str) -> frozenset[str]:
    """Return meaningful token set for a normalised title."""
    t = normalize_title(title)
    words = t.split()
    return frozenset(w for w in words if len(w) > 2)


def _jaccard(a: frozenset[str], b: frozenset[str]) -> float:
    if not a or not b:
        return 0.0
    inter = len(a & b)
    union = len(a | b)
    return inter / union if union else 0.0


# ---------------------------------------------------------------------------
# Union-Find
# ---------------------------------------------------------------------------
class _UF:
    def __init__(self, n: int):
        self.parent = list(range(n))

    def find(self, x: int) -> int:
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]
            x = self.parent[x]
        return x

    def union(self, x: int, y: int):
        self.parent[self.find(x)] = self.find(y)

    def groups(self) -> dict[int, list[int]]:
        from collections import defaultdict
        d: dict[int, list[int]] = defaultdict(list)
        for i in range(len(self.parent)):
            d[self.find(i)].append(i)
        return dict(d)


def cluster_stories(
    stories: list[dict],
    threshold: float = 0.40,
) -> list[dict]:
    """Group near-duplicate stories and return one representative per cluster.

    The representative is chosen by:
        score = trust × recency_weight
    where recency_weight decays to 0.5 over 2 hours.

    Args:
        stories:   Normalised story dicts (must have 'title', 'trust', 'pub_ts').
        threshold: Jaccard similarity threshold [0..1].
                   0.40 is aggressive; raise to 0.55 for looser grouping.

    Returns:
        List of representative stories (one per cluster), each with an added
        '_cluster_size' field indicating how many sources covered the story.
    """
    if not stories:
        return []

    n = len(stories)
    token_sets = [_tokens(s.get("title", "")) for s in stories]
    uf = _UF(n)

    for i in range(n):
        if len(token_sets[i]) < _MIN_TOKENS:
            continue
        for j in range(i + 1, n):
            if len(token_sets[j]) < _MIN_TOKENS:
                continue
            if _jaccard(token_sets[i], token_sets[j]) >= threshold:
                uf.union(i, j)

    now = time.time()
    reps: list[dict] = []
    for indices in uf.groups().values():
        best_idx = max(
            indices,
            key=lambda k: (
                stories[k].get("trust", 0.5)
                * max(0.5, 1.0 - (now - stories[k].get("pub_ts", now)) / 7200)
            ),
        )
        rep = dict(stories[best_idx])
        rep["_cluster_size"] = len(indices)
        # Boost trust slightly if multiple independent sources covered it
        if len(indices) > 1:
            extra = min(0.08, 0.02 * (len(indices) - 1))
            rep["trust"] = min(1.0, rep.get("trust", 0.5) + extra)
        reps.append(rep)

    return reps
