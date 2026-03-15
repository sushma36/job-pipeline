"""
resume_matcher.py
=================
Scores job descriptions against Sushma Dasari's resume.
Returns match score 0-100 with breakdown.
"""

import re
from dataclasses import dataclass, field
from typing import List, Tuple

# ─── Resume profile ───────────────────────────────────────────
SKILLS = [
    # Cloud
    "aws", "s3", "redshift", "glue", "sagemaker", "iam", "cloudformation",
    "gcp", "google cloud", "azure",
    # Big data & streaming
    "apache spark", "spark", "apache kafka", "kafka", "delta lake",
    # ETL & orchestration
    "apache airflow", "airflow", "dbt", "fivetran", "aws glue",
    "informatica", "informatica powercenter", "etl", "elt",
    "data pipelines", "data pipeline",
    # Programming
    "python", "sql", "scala", "shell scripting",
    # Databases
    "postgresql", "mysql", "oracle", "mongodb", "dynamodb",
    "microsoft sql server", "sql server",
    # Warehousing
    "snowflake", "amazon redshift", "google bigquery", "bigquery",
    "data warehouse", "data warehousing",
    # Modeling & governance
    "dimensional modeling", "data vault 2.0", "data vault",
    "star schema", "data lineage", "great expectations",
    "data modeling", "data governance", "data quality", "data validation",
    # MLOps & AI
    "mlflow", "langchain", "llamaindex", "machine learning",
    "generative ai", "sagemaker",
    # DevOps
    "docker", "kubernetes", "terraform", "git", "jenkins",
    # Analytics
    "tableau",
    # Domain
    "healthcare", "claims", "fraud detection",
    "feature engineering", "data lake",
]

TECH_STACK = [
    "python", "sql", "spark", "airflow", "kafka", "snowflake",
    "aws", "redshift", "bigquery", "databricks", "delta lake",
    "dbt", "glue", "sagemaker", "terraform", "docker",
    "kubernetes", "scala", "fivetran", "oracle", "postgresql",
    "mongodb", "mlflow", "langchain", "great expectations",
    "tableau", "gcp", "azure",
]

DOMAINS = [
    "healthcare", "enterprise", "analytics", "cloud",
    "machine learning", "fraud", "claims", "fintech", "data platform",
]

WEIGHTS = {
    "skills":    0.40,
    "tech":      0.25,
    "level":     0.15,
    "domain":    0.10,
    "education": 0.10,
}


def _n(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s]", " ", text.lower())).strip()

def _has(phrase: str, text: str) -> bool:
    return _n(phrase) in _n(text)

def _count(items: list, text: str) -> Tuple[list, int]:
    matched = [i for i in items if _has(i, text)]
    return matched, len(matched)


def _score_skills(text: str) -> Tuple[float, list, list]:
    matched, n = _count(SKILLS, text)
    bonus = min(sum(1 for s in ["spark","airflow","dbt","snowflake","delta lake",
                                "sagemaker","great expectations","terraform"]
                    if _has(s, text)) * 0.025, 0.15)
    raw   = min(n / max(len(SKILLS) * 0.22, 1) + bonus, 1.0)
    key   = ["python","sql","spark","airflow","dbt","snowflake","kafka",
             "aws","bigquery","terraform","docker","kubernetes","delta lake","sagemaker"]
    ml    = [s for s in key if s not in [m.lower() for m in matched]][:8]
    return raw, matched, ml


def _score_tech(text: str) -> float:
    _, n = _count(TECH_STACK, text)
    return min(n / max(len(TECH_STACK) * 0.28, 1), 1.0)


def _score_level(title: str, jd: str) -> float:
    t = _n(f"{title} {jd[:500]}")
    mgmt    = ["manager","director","vp ","head of","vice president","chief"]
    senior  = ["senior","lead","staff","principal","architect","sr.","7+","8+","10+"]
    junior  = ["junior","associate","entry","jr.","entry-level","new grad","0-2","1-2"]
    if any(k in t for k in mgmt):   return 0.05
    if any(k in t for k in senior): return 0.65
    if any(k in t for k in junior): return 1.00
    return 0.90


def _score_domain(text: str) -> float:
    high = ["healthcare","fintech","enterprise","analytics","cloud","fraud"]
    _, nh = _count(high, text)
    _, nd = _count(DOMAINS, text)
    if nh >= 2: return 1.0
    if nh >= 1: return 0.80
    if nd >= 1: return 0.60
    return 0.35


def _score_edu(jd: str) -> float:
    j = _n(jd)
    if "phd" in j or "doctorate" in j:        return 0.40
    if "master" in j or "m.s" in j:           return 1.0
    if "bachelor" in j or "b.s" in j:         return 1.0
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

    rec = ("✅ Apply"    if score >= 70 else
           "⚠️ Consider" if score >= 50 else
           "⛔ Skip")

    return MatchResult(
        score          = score,
        matched_skills = ", ".join(sorted({m.lower() for m in matched[:20]})),
        missing_skills = ", ".join(missing),
        recommendation = rec,
        breakdown      = {
            "skills (40%)":    round(ss * 100),
            "tech (25%)":      round(st * 100),
            "level (15%)":     round(sl * 100),
            "domain (10%)":    round(sd * 100),
            "education (10%)": round(se * 100),
        },
    )


def filter_and_score(jobs: list,
                     min_score: int = 50,
                     fallback: int = 40,
                     target: int = 10) -> list:
    """
    Score all jobs. Auto-lower threshold to `fallback`
    if fewer than `target` jobs pass `min_score`.
    """
    for j in jobs:
        r = match_job(j)
        j["match_score"]    = r.score
        j["matched_skills"] = r.matched_skills
        j["missing_skills"] = r.missing_skills
        j["recommendation"] = r.recommendation
        j["breakdown"]      = r.breakdown

    passed = [j for j in jobs if j["match_score"] >= min_score]
    print(f"  Scored {len(jobs)} — {len(passed)} ≥{min_score}, "
          f"{len(jobs)-len(passed)} below")

    if len(passed) < target:
        passed = [j for j in jobs if j["match_score"] >= fallback]
        print(f"  ⚠️  Auto-lowered threshold → {len(passed)} ≥{fallback}")

    passed.sort(
        key=lambda j: (j.get("posting_date", ""), j["match_score"]),
        reverse=True,
    )
    return passed


def deduplicate(jobs: list) -> list:
    seen = {}
    for j in jobs:
        key = (re.sub(r"\W","", j.get("company_name","").lower()) + "|" +
               re.sub(r"\W","", j.get("job_title",   "").lower()))
        if key not in seen or j["match_score"] > seen[key]["match_score"]:
            seen[key] = j
    return list(seen.values())
