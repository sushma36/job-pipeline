"""
=============================================================
  resume_matcher.py — Resume scoring engine
  Based on: SUSHMA_DASARI_Resume.pdf (correct version)
=============================================================
"""

import re
from dataclasses import dataclass, field
from typing import List, Tuple

# ─── RESUME PROFILE ──────────────────────────────────────────

RESUME = {
    "skills": [
        # Cloud
        "aws", "s3", "redshift", "glue", "sagemaker", "iam",
        "cloudformation", "gcp", "google cloud", "azure",
        # Big Data & Streaming
        "apache spark", "spark", "apache kafka", "kafka", "delta lake",
        # ETL & Pipelines
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
        # Modeling & Governance
        "dimensional modeling", "data vault 2.0", "data vault",
        "star schema", "data lineage", "great expectations",
        "data modeling", "data governance", "data quality",
        "data validation",
        # MLOps & AI
        "mlops", "mlflow", "langchain", "llamaindex",
        "machine learning", "ml", "generative ai", "genai",
        "ai", "llm", "sagemaker",
        # DevOps
        "docker", "kubernetes", "terraform", "git", "jenkins",
        # Analytics
        "tableau",
        # Domain
        "healthcare", "claims", "fraud detection",
        "feature engineering", "data lake", "data lakehouse",
    ],

    "tech_stack": [
        "python", "sql", "spark", "airflow", "kafka", "snowflake",
        "aws", "redshift", "bigquery", "databricks", "delta lake",
        "dbt", "glue", "sagemaker", "terraform", "docker",
        "kubernetes", "scala", "fivetran", "oracle", "postgresql",
        "mongodb", "mlflow", "langchain", "great expectations",
        "tableau", "gcp", "azure",
    ],

    "domains": [
        "healthcare", "enterprise", "analytics", "cloud",
        "machine learning", "fraud detection", "claims",
        "fintech", "data platform", "ai",
    ],

    "level_keywords": {
        "management": ["manager", "director", "vp ", "head of",
                       "vice president", "chief"],
        "senior":     ["senior", "lead", "staff", "principal",
                       "architect", "sr.", "sr ", "7+", "8+", "10+"],
        "junior":     ["junior", "associate", "entry", "jr.",
                       "entry-level", "new grad", "0-2", "1-2"],
    },
}

WEIGHTS = {
    "skills_overlap":     0.40,
    "tech_stack_overlap": 0.25,
    "experience_level":   0.15,
    "domain_relevance":   0.10,
    "education_req":      0.10,
}


# ─── HELPERS ─────────────────────────────────────────────────

def _norm(text: str) -> str:
    text = text.lower()
    text = re.sub(r"[^\w\s]", " ", text)
    return re.sub(r"\s+", " ", text).strip()

def _phrase_in(phrase: str, text: str) -> bool:
    return _norm(phrase) in _norm(text)

def _count_matches(items: List[str], text: str) -> Tuple[List[str], int]:
    matched = [i for i in items if _phrase_in(i, text)]
    return matched, len(matched)


# ─── SCORERS ─────────────────────────────────────────────────

def _score_skills(combined: str) -> Tuple[float, List[str], List[str]]:
    skills  = RESUME["skills"]
    matched, n = _count_matches(skills, combined)

    high_value = ["spark", "airflow", "kafka", "dbt", "snowflake",
                  "delta lake", "sagemaker", "langchain", "mlflow",
                  "great expectations", "terraform", "kubernetes", "bigquery"]
    bonus = min(sum(1 for s in high_value if _phrase_in(s, combined)) * 0.025, 0.15)

    ratio = n / max(len(skills) * 0.25, 1)   # 25% coverage = full score
    raw   = min(ratio + bonus, 1.0)

    key_skills = ["python", "sql", "spark", "airflow", "dbt", "snowflake",
                  "kafka", "aws", "bigquery", "terraform", "docker",
                  "kubernetes", "delta lake", "sagemaker", "mlflow"]
    matched_lower = [m.lower() for m in matched]
    missing = [s for s in key_skills if s not in matched_lower][:8]
    return raw, matched, missing


def _score_tech(combined: str) -> float:
    stack = RESUME["tech_stack"]
    _, n  = _count_matches(stack, combined)
    return min(n / max(len(stack) * 0.30, 1), 1.0)


def _score_level(title: str, jd: str) -> float:
    text = _norm(f"{title} {jd[:600]}")
    for kw in RESUME["level_keywords"]["management"]:
        if kw in text: return 0.05
    for kw in RESUME["level_keywords"]["senior"]:
        if kw in text: return 0.65
    for kw in RESUME["level_keywords"]["junior"]:
        if kw in text: return 1.0
    return 0.90


def _score_domain(combined: str) -> float:
    high = ["healthcare", "fintech", "enterprise", "analytics", "cloud", "ai", "ml"]
    _, nh = _count_matches(high, combined)
    _, nd = _count_matches(RESUME["domains"], combined)
    if nh >= 2: return 1.0
    if nh >= 1: return 0.80
    if nd >= 1: return 0.60
    return 0.35


def _score_edu(jd: str) -> float:
    jd_l = _norm(jd)
    if "phd" in jd_l or "doctorate" in jd_l:  return 0.40
    if "master" in jd_l or "m.s" in jd_l:     return 1.0
    if "bachelor" in jd_l or "b.s" in jd_l:   return 1.0
    return 0.85


# ─── MAIN MATCH FUNCTION ─────────────────────────────────────

@dataclass
class MatchResult:
    match_score:     int
    matched_skills:  str
    missing_skills:  str
    recommendation:  str
    breakdown:       dict = field(default_factory=dict)


def match_job(job: dict) -> MatchResult:
    title    = job.get("job_title", "")
    jd       = job.get("job_description", "")
    combined = f"{title} {jd}"

    s_skills, matched, missing = _score_skills(combined)
    s_tech                      = _score_tech(combined)
    s_level                     = _score_level(title, jd)
    s_domain                    = _score_domain(combined)
    s_edu                       = _score_edu(jd)

    raw   = (s_skills  * WEIGHTS["skills_overlap"] +
             s_tech    * WEIGHTS["tech_stack_overlap"] +
             s_level   * WEIGHTS["experience_level"] +
             s_domain  * WEIGHTS["domain_relevance"] +
             s_edu     * WEIGHTS["education_req"])
    score = round(raw * 100)

    return MatchResult(
        match_score    = score,
        matched_skills = ", ".join(sorted(set(m.lower() for m in matched[:20]))),
        missing_skills = ", ".join(missing),
        recommendation = "✅ Apply" if score >= 70 else "⚠️ Consider" if score >= 55 else "⛔ Skip",
        breakdown      = {
            "skills (40%)":   round(s_skills * 100),
            "tech (25%)":     round(s_tech * 100),
            "level (15%)":    round(s_level * 100),
            "domain (10%)":   round(s_domain * 100),
            "education (10%)": round(s_edu * 100),
        }
    )


def filter_and_score(jobs: list,
                     min_score: int = 50,
                     fallback_score: int = 40,
                     target_count: int = 10) -> list:
    """
    Score all jobs. If fewer than target_count pass min_score,
    automatically lower threshold to fallback_score.
    """
    scored = []
    total  = len(jobs)
    below  = 0

    for job in jobs:
        result = match_job(job)
        job["match_score"]    = result.match_score
        job["matched_skills"] = result.matched_skills
        job["missing_skills"] = result.missing_skills
        job["recommendation"] = result.recommendation
        job["breakdown"]      = result.breakdown
        if result.match_score >= min_score:
            scored.append(job)
        else:
            below += 1

    print(f"  Scored {total} jobs: {len(scored)} ≥{min_score}, {below} below")

    # Auto-lower threshold if too few results
    if len(scored) < target_count:
        print(f"  ⚠️  Only {len(scored)} jobs — lowering threshold to ≥{fallback_score}")
        scored = [j for j in jobs if j["match_score"] >= fallback_score]
        print(f"  Now {len(scored)} jobs at ≥{fallback_score}")

    # Sort: newest first, then by score
    scored.sort(
        key=lambda j: (j.get("posting_date", ""), j["match_score"]),
        reverse=True
    )
    return scored


def deduplicate(jobs: list) -> list:
    def _norm_key(s): return re.sub(r"\s+", "", s.lower().strip())
    seen = {}
    for job in jobs:
        key = (_norm_key(job.get("company_name", "")) + "|" +
               _norm_key(job.get("job_title", "")))
        if key not in seen or job["match_score"] > seen[key]["match_score"]:
            seen[key] = job
    return list(seen.values())
