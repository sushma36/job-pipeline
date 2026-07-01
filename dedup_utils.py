"""
dedup_utils.py
==============
Shared deduplication logic for job listings scraped across multiple boards.

Problem this solves:
  The same posting shows up on several boards with slightly different text —
  "Senior Data Engineer" vs "Sr. Data Engineer II", "Acme Corp" vs "Acme
  Corporation", tracking params tacked onto an otherwise-identical URL.
  A strict exact-match key (old approach) treats all of these as different
  jobs. This module normalizes titles/companies/URLs and uses a fuzzy
  similarity check to catch near-duplicates.

Used by:
  - scrapers.py (dedup pass right after scraping, before scoring)
  - resume_matcher.py (dedup pass after scoring, keeps highest-scoring dupe)
"""

import re
from difflib import SequenceMatcher
from urllib.parse import urlparse, urlunparse

# ---------------------------------------------------------------------------
# Title normalization
# ---------------------------------------------------------------------------
_TITLE_ABBREVS = {
    r"\bsr\.?\b":        "senior",
    r"\bjr\.?\b":        "junior",
    r"\bii\b":           "2",
    r"\biii\b":          "3",
    r"\biv\b":           "4",
    r"\beng\.?\b":       "engineer",
    r"\bengr\.?\b":      "engineer",
    r"\bdev\b":          "developer",
}

# Noise phrases that don't change what the job actually is — strip before
# comparing so "Data Engineer - Remote (US)" matches "Data Engineer".
_TITLE_NOISE = [
    r"\(remote\)", r"\bremote\b", r"\bhybrid\b", r"\bonsite\b", r"\bon-site\b",
    r"\bus\b", r"\busa\b", r"\bunited states\b",
    r"\bfull[- ]time\b", r"\bpart[- ]time\b", r"\bcontract\b", r"\bw2\b",
    r"\bnew\b", r"\bopening\b", r"\bhiring\b",
    r"-\s*$",
]

_COMPANY_SUFFIXES = [
    r"\binc\.?\b", r"\bllc\.?\b", r"\bcorp\.?\b", r"\bcorporation\b",
    r"\bltd\.?\b", r"\bco\.?\b", r"\bplc\b", r"\bgroup\b", r"\bholdings\b",
]


def _n(text: str) -> str:
    """Lowercase, strip punctuation, collapse whitespace."""
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s]", " ", (text or "").lower())).strip()


def normalize_title(title: str) -> str:
    t = f" {_n(title)} "
    for pattern, repl in _TITLE_ABBREVS.items():
        t = re.sub(pattern, repl, t)
    for pattern in _TITLE_NOISE:
        t = re.sub(pattern, " ", t)
    return re.sub(r"\s+", " ", t).strip()


def normalize_company(company: str) -> str:
    c = f" {_n(company)} "
    for pattern in _COMPANY_SUFFIXES:
        c = re.sub(pattern, " ", c)
    return re.sub(r"\s+", " ", c).strip()


def normalize_url(url: str) -> str:
    """Strip query params/fragments/tracking so the same posting linked with
    different UTM/session params still collapses to one canonical URL."""
    if not url:
        return ""
    try:
        p = urlparse(url.strip())
        clean = p._replace(query="", fragment="")
        path = clean.path.rstrip("/")
        return urlunparse(clean._replace(path=path)).lower()
    except Exception:
        return url.strip().lower()


def title_similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, normalize_title(a), normalize_title(b)).ratio()


# ---------------------------------------------------------------------------
# Main dedup routine
# ---------------------------------------------------------------------------
def dedupe_jobs(jobs: list, score_key: str = None, title_threshold: float = 0.87) -> list:
    """
    Dedupe a list of job dicts.

    Pass 1: exact match on normalized URL (cheap, catches the common case).
    Pass 2: same normalized company + fuzzy title match above threshold
            (catches cross-board reposts with slightly different wording).

    If score_key is given (e.g. "match_score"), the higher-scoring job wins
    when a duplicate is found. Otherwise the first-seen job wins.
    """
    # Pass 1 — exact URL dedup
    seen_urls = {}
    stage1 = []
    for j in jobs:
        u = normalize_url(j.get("job_url", ""))
        if u:
            existing = seen_urls.get(u)
            if existing is not None:
                if score_key and j.get(score_key, 0) > existing.get(score_key, 0):
                    seen_urls[u] = j
                continue
            seen_urls[u] = j
        stage1.append(j)
    stage1 = list(seen_urls.values()) + [j for j in stage1 if not normalize_url(j.get("job_url", ""))]

    # Pass 2 — fuzzy company+title dedup
    buckets: dict = {}
    for j in stage1:
        buckets.setdefault(normalize_company(j.get("company_name", "")), []).append(j)

    result = []
    for company, group in buckets.items():
        kept: list = []
        for j in group:
            match_idx = None
            for i, k in enumerate(kept):
                if title_similarity(j.get("job_title", ""), k.get("job_title", "")) >= title_threshold:
                    match_idx = i
                    break
            if match_idx is None:
                kept.append(j)
            elif score_key and j.get(score_key, 0) > kept[match_idx].get(score_key, 0):
                kept[match_idx] = j
        result.extend(kept)

    return result
