"""
=============================================================
  RESUME MATCHER — Sushma Dasari (Correct Resume)
  Based on: SUSHMA_DASARI_Resume.pdf
  Scores job descriptions against resume using weighted criteria
=============================================================
"""

import re
from dataclasses import dataclass, field
from typing import List, Tuple

# =============================================================
#  SUSHMA'S RESUME PROFILE — Exact skills from correct resume
# =============================================================

RESUME = {
    "name": "Sushma Dasari",
    "years_experience": 5,
    "current_level": "mid",

    "skills": [
        # ── Cloud Platforms ───────────────────────────────────
        "aws", "amazon web services", "s3", "redshift", "glue",
        "sagemaker", "aws sagemaker", "iam", "cloudformation",
        "google cloud platform", "gcp", "azure",

        # ── Data Warehousing & Big Data ───────────────────────
        "snowflake", "amazon redshift", "google bigquery", "bigquery",
        "apache spark", "spark", "apache kafka", "kafka",
        "data warehouse", "data warehousing",

        # ── ETL & Data Pipelines ──────────────────────────────
        "apache airflow", "airflow", "dbt", "fivetran",
        "aws glue", "informatica", "informatica powercenter",
        "etl", "elt", "data pipelines", "data pipeline",
        "etl pipelines", "elt pipelines",

        # ── Programming & Scripting ───────────────────────────
        "python", "sql", "scala", "shell scripting",

        # ── Databases ─────────────────────────────────────────
        "microsoft sql server", "sql server", "postgresql",
        "mysql", "oracle", "mongodb", "dynamodb",

        # ── Data Modeling & Governance ────────────────────────
        "dimensional modeling", "data vault 2.0", "data vault",
        "star schema", "data lineage", "great expectations",
        "data modeling", "data governance", "data quality",
        "data validation",

        # ── MLOps & AI ────────────────────────────────────────
        "mlops", "mlflow", "langchain", "llamaindex",
        "machine learning", "ml", "generative ai", "genai",
        "ml-based", "ai", "llm",

        # ── DevOps & Infrastructure ───────────────────────────
        "docker", "kubernetes", "terraform", "git", "jenkins",
        "ci/cd", "infrastructure as code",

        # ── Storage & Lake (from work experience) ─────────────
        "delta lake", "data lake", "data lakehouse",

        # ── Analytics & Visualization (from work exp) ─────────
        "tableau",

        # ── Domain-specific (from work experience) ────────────
        "healthcare", "claims", "fraud detection",
        "feature engineering", "data migration",
        "partitioning", "clustering", "data auditing",
    ],

    # ── Core tech stack (highest weight) ─────────────────────
    "tech_stack": [
        "python", "sql", "spark", "airflow", "kafka",
        "snowflake", "aws", "redshift", "bigquery", "databricks",
        "delta lake", "dbt", "glue", "sagemaker", "terraform",
        "docker", "kubernetes", "scala", "fivetran", "oracle",
        "postgresql", "mongodb", "mlflow", "langchain", "llamaindex",
        "great expectations", "tableau", "gcp", "azure",
    ],

    # ── Domains ───────────────────────────────────────────────
    "domains": [
        "healthcare", "enterprise", "analytics", "cloud",
        "machine learning", "fraud detection", "claims",
        "fintech", "data platform", "ai",
    ],

    "education": {
        "degree": "master",
        "field": "computer science",
    },

    "level_keywords": {
        "junior":     ["junior", "associate", "entry", "jr.", "entry-level",
                       "new grad", "early career", "0-2 years", "1-2 years"],
        "mid":        ["data engineer", "engineer ii", "engineer 2",
                       "mid-level", "intermediate", "3-5 years", "2-4 years"],
        "senior":     ["senior", "lead", "staff", "principal", "architect",
                       "sr.", "sr ", "7+", "8+", "10+"],
        "management": ["manager", "director", "vp ", "head of",
                       "vice president", "chief"],
    },
}

# =============================================================
#  SCORING WEIGHTS
# =============================================================

WEIGHTS = {
    "skills_overlap":     0.40,
    "tech_stack_overlap": 0.25,
    "experience_level":   0.15,
    "domain_relevance":   0.10,
    "education_req":      0.10,
}

# =============================================================
#  ROLE KEYWORDS — what titles to search & match
# =============================================================

ROLE_KEYWORDS = [
    # Core DE titles
    "data engineer", "senior data engineer", "junior data engineer",
    "associate data engineer", "staff data engineer", "lead data engineer",
    # Adjacent titles
    "analytics engineer", "etl engineer", "etl developer",
    "data platform engineer", "data infrastructure engineer",
    "data pipeline engineer", "cloud data engineer",
    # ML-adjacent (Sushma has SageMaker, MLflow, LangChain)
    "ml engineer", "machine learning engineer", "mlops engineer",
    "ai data engineer",
    # Warehouse/lake focused
    "data warehouse engineer", "snowflake engineer", "bigquery engineer",
]


# =============================================================
#  HELPERS
# =============================================================

def _normalize(text: str) -> str:
    text = text.lower()
    text = re.sub(r"[^\w\s\./]", " ", text)
    return re.sub(r"\s+", " ", text).strip()

def _phrase_in_text(phrase: str, text: str) -> bool:
    return _normalize(phrase) in _normalize(text)

def _count_matches(items: List[str], text: str) -> Tuple[List[str], int]:
    matched = [item for item in items if _phrase_in_text(item, text)]
    return matched, len(matched)


# =============================================================
#  COMPONENT SCORERS
# =============================================================

def score_skills(jd: str) -> Tuple[float, List[str], List[str]]:
    """Skills overlap — 40% weight."""
    resume_skills = RESUME["skills"]
    matched, n = _count_matches(resume_skills, jd)

    # Bonus for high-value skills present in JD
    high_value = [
        "spark", "airflow", "kafka", "dbt", "snowflake", "databricks",
        "delta lake", "sagemaker", "langchain", "llamaindex", "mlflow",
        "great expectations", "terraform", "kubernetes", "bigquery",
    ]
    bonus = sum(1 for s in high_value if _phrase_in_text(s, jd))
    bonus_score = min(bonus * 0.025, 0.15)

    # 30% coverage of resume skills = full score (skills list is broad)
    ratio = n / max(len(resume_skills) * 0.30, 1)
    raw   = min(ratio + bonus_score, 1.0)

    # Key skills to flag as missing
    key_skills = [
        "python", "sql", "spark", "airflow", "dbt", "snowflake",
        "kafka", "aws", "bigquery", "terraform", "docker",
        "kubernetes", "delta lake", "sagemaker", "mlflow",
        "langchain", "great expectations", "fivetran",
    ]
    matched_lower = [m.lower() for m in matched]
    missing = [s for s in key_skills if s not in matched_lower][:10]

    return raw, matched, missing


def score_tech_stack(jd: str) -> float:
    """Tech stack overlap — 25% weight."""
    stack = RESUME["tech_stack"]
    _, n  = _count_matches(stack, jd)
    return min(n / max(len(stack) * 0.35, 1), 1.0)


def score_experience_level(job_title: str, jd: str) -> float:
    """Experience level fit — 15% weight. Sushma has 5 years."""
    text = _normalize(f"{job_title} {jd[:800]}")

    for kw in RESUME["level_keywords"]["management"]:
        if kw in text:
            return 0.05

    for kw in RESUME["level_keywords"]["senior"]:
        if kw in text:
            return 0.65   # 5 yrs — can apply to senior but not ideal

    for kw in RESUME["level_keywords"]["junior"]:
        if kw in text:
            return 1.0    # perfect fit

    return 0.90   # mid-level default — best fit


def score_domain(jd: str) -> float:
    """Domain relevance — 10% weight."""
    domains    = RESUME["domains"]
    high_value = ["healthcare", "fintech", "enterprise", "analytics", "cloud", "ai", "ml"]
    _, n_d = _count_matches(domains, jd)
    _, n_h = _count_matches(high_value, jd)

    if n_h >= 2:  return 1.0
    if n_h >= 1:  return 0.80
    if n_d >= 1:  return 0.60
    return 0.35   # DE is domain-agnostic — always some credit


def score_education(jd: str) -> float:
    """Education requirements — 10% weight. Sushma has MS CS."""
    jd_lower = _normalize(jd)
    if "phd" in jd_lower or "doctorate" in jd_lower:
        return 0.40
    if "master" in jd_lower or "m.s" in jd_lower or "graduate degree" in jd_lower:
        return 1.0
    if "bachelor" in jd_lower or "b.s" in jd_lower or "undergraduate" in jd_lower:
        return 1.0
    return 0.85   # no requirement stated


# =============================================================
#  MATCH RESULT
# =============================================================

@dataclass
class MatchResult:
    match_score:     int
    matched_skills:  str
    missing_skills:  str
    recommendation:  str
    score_breakdown: dict = field(default_factory=dict)


def match_job(job: dict) -> MatchResult:
    title    = job.get("job_title", "")
    jd       = job.get("job_description", "")
    combined = f"{title} {jd}"

    s_skills, matched, missing = score_skills(combined)
    s_tech                      = score_tech_stack(combined)
    s_level                     = score_experience_level(title, jd)
    s_domain                    = score_domain(combined)
    s_edu                       = score_education(jd)

    raw = (
        s_skills  * WEIGHTS["skills_overlap"]      +
        s_tech    * WEIGHTS["tech_stack_overlap"]   +
        s_level   * WEIGHTS["experience_level"]     +
        s_domain  * WEIGHTS["domain_relevance"]     +
        s_edu     * WEIGHTS["education_req"]
    )

    final = round(raw * 100)

    matched_display = ", ".join(sorted(set(m.lower() for m in matched[:20])))
    missing_display = ", ".join(missing[:10])
    rec             = "✅ Apply" if final >= 70 else "⛔ Skip"

    return MatchResult(
        match_score     = final,
        matched_skills  = matched_display,
        missing_skills  = missing_display,
        recommendation  = rec,
        score_breakdown = {
            "skills_overlap (40%)":   round(s_skills * 100),
            "tech_stack (25%)":       round(s_tech * 100),
            "experience_level (15%)": round(s_level * 100),
            "domain_relevance (10%)": round(s_domain * 100),
            "education_req (10%)":    round(s_edu * 100),
        }
    )


# =============================================================
#  PIPELINE UTILITIES
# =============================================================

def filter_and_score(jobs: list, min_score: int = 70) -> list:
    scored = []
    for job in jobs:
        result = match_job(job)
        if result.match_score >= min_score:
            job["match_score"]    = result.match_score
            job["matched_skills"] = result.matched_skills
            job["missing_skills"] = result.missing_skills
            job["recommendation"] = result.recommendation
            scored.append(job)
    scored.sort(
        key=lambda j: (j.get("posting_date", ""), j["match_score"]),
        reverse=True
    )
    return scored


def deduplicate(jobs: list) -> list:
    def _norm(s): return re.sub(r"\s+", "", s.lower().strip())
    seen = {}
    for job in jobs:
        key = _norm(job.get("company_name", "")) + "|" + _norm(job.get("job_title", ""))
        if key not in seen or job["match_score"] > seen[key]["match_score"]:
            seen[key] = job
    return list(seen.values())


# =============================================================
#  QUICK TEST
# =============================================================

if __name__ == "__main__":
    test_jobs = [
        {
            "job_title": "Data Engineer",
            "company_name": "Stripe",
            "job_description": """Build scalable data pipelines using Apache Spark, Airflow,
            dbt, Snowflake, Python, SQL. AWS (S3, Redshift, Glue, SageMaker). Kafka streaming.
            Delta Lake. MLflow. Docker, Kubernetes, Terraform, Git. Great Expectations for data
            quality. LangChain for LLM pipelines. Healthcare domain. MS Computer Science. 3-5 yrs.""",
            "platform_name": "LinkedIn", "location": "Remote",
            "posting_date": "2026-03-14", "job_url": "https://stripe.com/jobs/1",
            "salary": "$150k-$190k",
        },
        {
            "job_title": "Analytics Engineer",
            "company_name": "Figma",
            "job_description": """dbt, Snowflake, Python, SQL, Fivetran, Airflow.
            Great Expectations, data lineage, Tableau. AWS. 2-4 years. BS/MS.""",
            "platform_name": "Lever ATS", "location": "Remote",
            "posting_date": "2026-03-14", "job_url": "https://figma.com/jobs/1",
            "salary": "$120k-$150k",
        },
        {
            "job_title": "ETL Engineer",
            "company_name": "JPMorgan",
            "job_description": """ETL pipelines Python SQL Informatica PowerCenter Snowflake
            Redshift Kafka AWS Glue Data Vault 2.0 Star Schema Dimensional Modeling Git Jenkins
            Docker financial services 3-6 years BS required.""",
            "platform_name": "Workday ATS", "location": "New York",
            "posting_date": "2026-03-14", "job_url": "https://jpmorgan.com/jobs/1",
            "salary": "$130k-$160k",
        },
        {
            "job_title": "Senior Data Engineer",
            "company_name": "Amazon",
            "job_description": """Senior DE leading team of 8. 7+ years required. Spark Kafka
            Redshift DynamoDB Glue Python Scala. Architecture decisions. PhD preferred.
            VP level stakeholder management.""",
            "platform_name": "Indeed", "location": "Seattle",
            "posting_date": "2026-03-14", "job_url": "https://amazon.com/jobs/1",
            "salary": "$200k+",
        },
    ]

    print("=" * 65)
    print("  RESUME MATCHER TEST — Sushma Dasari (Correct Resume)")
    print("=" * 65)
    for job in test_jobs:
        r = match_job(job)
        print(f"\n📌 {job['job_title']:35s} @ {job['company_name']}")
        print(f"   Score      : {r.match_score}/100  →  {r.recommendation}")
        print(f"   Matched    : {r.matched_skills[:100]}")
        print(f"   Missing    : {r.missing_skills}")
        print(f"   Breakdown  : {r.score_breakdown}")
