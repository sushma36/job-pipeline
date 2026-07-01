"""
resume_matcher.py
=================
Scores job descriptions against Sushma Dasari's resume.
"""

import re
from dataclasses import dataclass, field
from typing import List, Tuple

from dedup_utils import dedupe_jobs

SKILLS = [
    "aws","s3","glue","sagemaker","iam","cloudformation",
    "gcp","google cloud",
    "apache spark","spark","apache kafka","kafka","delta lake",
    "apache airflow","airflow","dbt","aws glue","parquet",
    "etl","elt",
    "data pipelines","data pipeline",
    "python","sql","shell scripting","shell",
    "postgresql","mysql","oracle","sql server","microsoft sql server",
    "google bigquery","bigquery","databricks",
    "data warehouse","data warehousing",
    "data lineage","data modeling","data governance",
    "data quality","data validation","anomaly detection",
    "sagemaker","machine learning","scikit-learn","pandas","numpy",
    "feature engineering",
    "git","tableau","healthcare","claims","fraud detection",
    "hipaa","data lake","infrastructure as code",
]

TECH_STACK = [
    "python","sql","spark","airflow","aws","bigquery","databricks",
    "delta lake","dbt","glue","sagemaker","oracle","postgresql",
    "mysql","sql server","tableau","gcp","kafka","parquet",
    "cloudformation","git",
]

DOMAINS = [
    "healthcare","enterprise","analytics","cloud","machine learning",
    "fraud","claims","fintech","data platform",
]

WEIGHTS = {"skills": 0.40, "tech": 0.25, "level": 0.15,
           "domain": 0.10, "education": 0.10}


def _n(t: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s]", " ", (t or "").lower())).strip()

def _has(phrase: str, text: str) -> bool:
    return _n(phrase) in _n(text)

def _count(items, text) -> Tuple[list, int]:
    matched = [i for i in items if _has(i, text)]
    return matched, len(matched)


def _score_skills(text):
    matched, n = _count(SKILLS, text)
    bonus = min(
        sum(1 for s in ["spark","airflow","dbt","delta lake",
                        "sagemaker","databricks","bigquery"]
            if _has(s, text)) * 0.025, 0.15
    )
    raw   = min(n / max(len(SKILLS) * 0.22, 1) + bonus, 1.0)
    key   = ["python","sql","spark","airflow","dbt","kafka",
             "aws","bigquery","databricks","glue",
             "delta lake","sagemaker"]
    ml    = [s for s in key if not _has(s, text)][:8]
    return raw, matched, ml


def _score_tech(text):
    _, n = _count(TECH_STACK, text)
    return min(n / max(len(TECH_STACK) * 0.28, 1), 1.0)


def _score_level(title, jd):
    t = _n(f"{title} {(jd or '')[:500]}")
    if any(k in t for k in ["manager","director","vp ","head of","chief"]):
        return 0.05
    if any(k in t for k in ["senior","lead","staff","principal","architect","7+","8+"]):
        return 0.65
    if any(k in t for k in ["junior","associate","entry","new grad","0-2","1-2"]):
        return 1.00
    return 0.90


def _score_domain(text):
    high = ["healthcare","fintech","enterprise","analytics","cloud","fraud"]
    _, nh = _count(high, text)
    _, nd = _count(DOMAINS, text)
    if nh >= 2: return 1.0
    if nh >= 1: return 0.80
    if nd >= 1: return 0.60
    return 0.35


def _score_edu(jd):
    j = _n(jd or "")
    if "phd" in j or "doctorate" in j: return 0.40
    if "master" in j or "m.s" in j:    return 1.0
    if "bachelor" in j or "b.s" in j:  return 1.0
    return 0.85


@dataclass
class MatchResult:
    score:          int
    matched_skills: str
    missing_skills: str
    recommendation: str
    breakdown:      dict = field(default_factory=dict)


def match_job(job: dict) -> MatchResult:
    title    = job.get("job_title",       "") or ""
    jd       = job.get("job_description", "") or ""
    combined = f"{title} {jd}"

    ss, matched, missing = _score_skills(combined)
    st = _score_tech(combined)
    sl = _score_level(title, jd)
    sd = _score_domain(combined)
    se = _score_edu(jd)

    score = round((ss * WEIGHTS["skills"]  +
                   st * WEIGHTS["tech"]    +
                   sl * WEIGHTS["level"]   +
                   sd * WEIGHTS["domain"]  +
                   se * WEIGHTS["education"]) * 100)

    rec = ("✅ Apply"     if score >= 70 else
           "⚠️  Consider" if score >= 50 else
           "⛔ Skip")

    return MatchResult(
        score          = score,
        matched_skills = ", ".join(sorted({m.lower() for m in matched[:20]})),
        missing_skills = ", ".join(missing),
        recommendation = rec,
        breakdown      = {
            "skills(40%)":    round(ss * 100),
            "tech(25%)":      round(st * 100),
            "level(15%)":     round(sl * 100),
            "domain(10%)":    round(sd * 100),
            "education(10%)": round(se * 100),
        },
    )


def filter_and_score(jobs: list,
                     min_score:     int = 50,
                     fallback:      int = 40,
                     target:        int = 10,
                     window_label:  str = "24h") -> list:
    for j in jobs:
        r = match_job(j)
        j["match_score"]    = r.score
        j["matched_skills"] = r.matched_skills
        j["missing_skills"] = r.missing_skills
        j["recommendation"] = r.recommendation
        j["breakdown"]      = r.breakdown
        j["window_label"]   = window_label

    passed = [j for j in jobs if j["match_score"] >= min_score]
    print(f"  Scored {len(jobs):3d} — {len(passed):3d} ≥{min_score}, "
          f"{len(jobs)-len(passed):3d} below")

    if len(passed) < target:
        passed = [j for j in jobs if j["match_score"] >= fallback]
        print(f"  ⚠️  Auto-lowered threshold → {len(passed)} ≥{fallback}")

    passed.sort(
        key=lambda j: (j.get("posting_date", ""), j["match_score"]),
        reverse=True,
    )
    return passed


def deduplicate(jobs: list) -> list:
    """Fuzzy dedup (see dedup_utils.py) — keeps the highest-scoring copy of
    each near-duplicate posting instead of requiring an exact title match."""
    return dedupe_jobs(jobs, score_key="match_score")
