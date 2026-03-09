"""News source clients — each returns a list of normalised story dicts.

Story schema (all sources produce this)
----------------------------------------
{
    "id":        str,          # sha1 fingerprint (set by normalize layer)
    "title":     str,
    "url":       str,
    "domain":    str,          # e.g. "reuters.com"
    "pub_ts":    float,        # UTC unix timestamp
    "body":      str,          # snippet / summary (may be empty)
    "source":    str,          # human label of the feed
    "lang":      str,          # ISO 639-1, default "en"
}
"""
