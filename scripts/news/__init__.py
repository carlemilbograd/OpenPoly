"""
news/ — 4-layer news→signal pipeline for OpenPoly

Layer 1  sources/   — raw article fetch (GDELT, NewsAPI, RSS)
Layer 2  normalize  — dedup + source trust weights
Layer 3  cluster    — group near-duplicate stories
Layer 4  mapper     — map stories to Polymarket markets
         score      — 5-factor impact scoring
         pipeline   — orchestrate all layers → PipelineResult list
"""
