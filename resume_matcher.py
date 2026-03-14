"""
=============================================================
  RESUME MATCHER — Semantic scoring engine
  Scores each job description against Sushma's resume
=============================================================
"""

import re
from dataclasses import dataclass, field
from typing import List, Tuple

# ─── RESUME PROFILE ──────────────────────────────────────────────────────────

RESUME = {
    "name": "Sushma Dasari",
    "years_experience": 5,
    "current_level": "mid",   # junior / mid / senior

    "skills": [
        # Core engineering
        "data engineering", "etl", "elt", "data pipelines", "data lakes",
        "data warehousing", "data modeling", "dimensional modeling",
        "data vault 2.0", "star schema", "data lineage", "data governance",
        "data quality", "data validation",
        # Cloud
        "aws", "s3", "redshift", "glue", "sagemaker", "iam", "cloudformation",
        "gcp", "google cloud", "bigquery", "azure",
        # Big data / streaming
        "apache spark", "spark", "apache kafka", "kafka", "delta lake",
        # Orchestration & ETL tools
        "apache airflow", "airflow", "dbt", "fivetran", "informatica",
        "aws glue",
        # Databases
        "snowflake", "postgresql", "mysql", "oracle", "mongodb",
        "dynamodb", "microsoft sql server", "sql server",
        # Programming
        "python", "sql", "scala", "shell scripting",
        # ML / AI
        "mlops", "mlflow", "langchain", "llamaindex", "machine learning",
        "feature engineering", "fraud detection", "generative ai",
        # DevOps
        "docker", "kubernetes", "terraform", "git", "jenkins",
        # Visualization
        "tableau",
        # Frameworks
        "great expectations",
    ],

    "tech_stack": [
        "python", "sql", "spark", "airflow", "kafka", "snowflake",
        "aws", "redshift", "bigquery", "databricks", "delta lake",
        "dbt", "glue", "sagemaker", "terraform", "docker", "kubernetes",
        "scala", "fivetran", "oracle", "postgresql", "mongodb",
    ],

    "domains": [
        "healthcare", "enterprise", "analytics", "cloud", "machine learning",
        "fraud detection", "claims processing", "data migration",
    ],

    "education": {
        "degree": "master",
        "field": "computer science",
        "levels_accepted": ["bachelor", "master", "phd"],
    },

    "level_keywords": {
        "junior":     ["junior", "associate", "entry", "jr.", "entry-level", "new grad"],
        "mid":        ["data engineer", "engineer ii", "engineer 2", "mid-level", "intermediate"],
        "senior":     ["senior", "lead", "staff", "principal", "architect", "sr.", "sr "],
        "management": ["manager", "director", "vp", "head of"],
    },
}

# ─── SCORING WEIGHTS ─────────────────────────────────────────────────────────

WEIGHTS = {
    "skills_overlap":       0.40,
    "tech_stack_overlap":   0.25,
    "experience_level":     0.15,
    "domain_relevance":     0.10,
    "education_req":        0.10,
}

# ─── DATA CLASSES ─────────────────────────────────────────────────────────────

@dataclass
class MatchResult:
    match_score: int
    matched_skills: List[str]
    missing_skills: List[str]
    recommendation: str          # "Apply" or "Skip"
    score_breakdown: dict = field(default_factory=dict)


# ─── HELPERS ─────────────────────────────────────────────────────────────────

def _normalize(text: str) -> str:
    """Lowercase, remove punctuation, collapse whitespace."""
    text = text.lower()
    text = re.sub(r"[^\w\s]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _tokens(text: str) -> set:
    return set(_normalize(text).split())


def _phrase_in_text(phrase: str, text: str) -> bool:
    """Check if a multi-word phrase appears in text."""
    return _normalize(phrase) in _normalize(text)


def _count_matches(items: List[str], text: str) -> Tuple[List[str], int]:
    """Return (matched_items, count) for items found in text."""
    matched = [item for item in items if _phrase_in_text(item, text)]
    return matched, len(matched)


# ─── COMPONENT SCORERS ───────────────────────────────────────────────────────

def score_skills(jd: str) -> Tuple[float, List[str], List[str]]:
    """
    Skills overlap: 40% weight
    Measures what % of resume skills appear in the job description,
    and what % of JD-mentioned skills are on the resume.
    """
    resume_skills = RESUME["skills"]
    matched, n_matched = _count_matches(resume_skills, jd)

    # Bonus: high-value skills mentioned in JD that are ON resume
    high_value = ["spark", "airflow", "kafka", "dbt", "snowflake",
                  "databricks", "delta lake", "sagemaker"]
    bonus_hits = sum(1 for s in high_value if _phrase_in_text(s, jd))

    # Base ratio
    if not resume_skills:
        return 0.0, [], []

    ratio = n_matched / len(resume_skills)
    bonus = min(bonus_hits * 0.03, 0.15)  # up to 15% bonus
    raw = min(ratio + bonus, 1.0)

    missing = [s for s in resume_skills[:20] if s not in matched]  # top 20 for brevity
    return raw, matched, missing


def score_tech_stack(jd: str) -> float:
    """
    Tech stack overlap: 25% weight
    Focused check on the core 20-tech stack.
    """
    stack = RESUME["tech_stack"]
    _, n = _count_matches(stack, jd)
    return min(n / max(len(stack) * 0.4, 1), 1.0)  # 40% coverage = full score


def score_experience_level(job_title: str, jd: str) -> float:
    """
    Experience level alignment: 15% weight
    Penalizes senior/management roles heavily; neutral for mid/junior.
    """
    text = _normalize(f"{job_title} {jd[:500]}")   # title + top of JD

    # Reject management
    for kw in RESUME["level_keywords"]["management"]:
        if kw in text:
            return 0.1

    # Senior: slight penalty (Sushma has 5yrs, can stretch but not ideal)
    for kw in RESUME["level_keywords"]["senior"]:
        if kw in text:
            return 0.65

    # Junior / associate: perfect fit
    for kw in RESUME["level_keywords"]["junior"]:
        if kw in text:
            return 1.0

    # Mid-level default: good fit
    return 0.9


def score_domain(jd: str) -> float:
    """
    Domain relevance: 10% weight
    Healthcare, enterprise, analytics, cloud are strongest matches.
    """
    domains = RESUME["domains"]
    high_value_domains = ["healthcare", "enterprise", "analytics", "cloud", "fintech"]
    _, n_domain = _count_matches(domains, jd)
    _, n_high = _count_matches(high_value_domains, jd)

    if n_high >= 2:
        return 1.0
    elif n_domain >= 2 or n_high >= 1:
        return 0.75
    elif n_domain == 1:
        return 0.5
    return 0.3   # data engineering is domain-agnostic; partial credit


def score_education(jd: str) -> float:
    """
    Education requirements: 10% weight
    Sushma has MS CS — any role requiring ≤ MS gets full score.
    """
    jd_lower = _normalize(jd)
    if "phd" in jd_lower or "ph.d" in jd_lower or "doctorate" in jd_lower:
        return 0.3   # over-qualified requirement
    if "master" in jd_lower or "m.s" in jd_lower or "m.sc" in jd_lower:
        return 1.0   # exact match
    if "bachelor" in jd_lower or "b.s" in jd_lower or "undergraduate" in jd_lower:
        return 1.0   # Sushma exceeds requirement
    return 0.8   # no education requirement stated — probably fine


# ─── MAIN MATCHER ────────────────────────────────────────────────────────────

def match_job(job: dict) -> MatchResult:
    """
    Score a job dict against Sushma's resume.

    job dict keys: job_title, job_description, [company_name, location, ...]
    Returns MatchResult with score 0-100.
    """
    title = job.get("job_title", "")
    jd    = job.get("job_description", "")
    combined = f"{title} {jd}"

    # ── Component scores (0.0 – 1.0 each)
    s_skills, matched, missing  = score_skills(combined)
    s_tech                      = score_tech_stack(combined)
    s_level                     = score_experience_level(title, jd)
    s_domain                    = score_domain(combined)
    s_edu                       = score_education(jd)

    # ── Weighted total
    raw_score = (
        s_skills  * WEIGHTS["skills_overlap"]      +
        s_tech    * WEIGHTS["tech_stack_overlap"]   +
        s_level   * WEIGHTS["experience_level"]     +
        s_domain  * WEIGHTS["domain_relevance"]     +
        s_edu     * WEIGHTS["education_req"]
    )

    final_score = round(raw_score * 100)

    # ── Format for Excel display
    matched_display = ", ".join(sorted(set(matched[:15])))    # top 15
    missing_display = ", ".join(sorted(set(missing[:10])))    # top 10 gaps

    recommendation = "✅ Apply" if final_score >= 70 else "⛔ Skip"

    return MatchResult(
        match_score      = final_score,
        matched_skills   = matched_display,
        missing_skills   = missing_display,
        recommendation   = recommendation,
        score_breakdown  = {
            "skills_overlap (40%)":     round(s_skills * 100),
            "tech_stack (25%)":         round(s_tech * 100),
            "experience_level (15%)":   round(s_level * 100),
            "domain_relevance (10%)":   round(s_domain * 100),
            "education_req (10%)":      round(s_edu * 100),
        }
    )


# ─── PIPELINE UTILITIES ──────────────────────────────────────────────────────

def filter_and_score(jobs: list, min_score: int = 70) -> list:
    """
    Run match_job on all jobs, attach scores, filter by min_score.
    Returns enriched job dicts sorted by posting_date DESC, match_score DESC.
    """
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
    """
    Remove duplicate postings using company_name + job_title as key.
    Keeps the record with the highest match_score.
    """
    seen = {}
    for job in jobs:
        company = _normalize(job.get("company_name", ""))
        title   = _normalize(job.get("job_title", ""))
        key     = f"{company}|{title}"

        if key not in seen or job["match_score"] > seen[key]["match_score"]:
            seen[key] = job

    return list(seen.values())


# ─── DEMO / TEST ─────────────────────────────────────────────────────────────

SAMPLE_JOBS = [
    {
        "job_title": "Data Engineer",
        "company_name": "Stripe",
        "location": "San Francisco, CA (Remote OK)",
        "remote_or_hybrid": "Hybrid",
        "posting_date": "2025-01-15",
        "salary": "$140,000 - $180,000",
        "job_url": "https://stripe.com/jobs/listing/data-engineer/12345",
        "platform_name": "LinkedIn",
        "job_description": """
            We are looking for a Data Engineer with 3-5 years of experience to join our
            Data Platform team. You will build and maintain scalable data pipelines using
            Apache Spark, Apache Airflow, and dbt. Experience with Python, SQL, and AWS
            (S3, Redshift, Glue) is required. Familiarity with Kafka for real-time streaming
            and Snowflake for data warehousing is a plus. You will work with data scientists
            to build ML feature pipelines and with analytics engineers to power our dashboards.
            We use Docker and Kubernetes for deployment, Terraform for infra, and Git/Jenkins
            for CI/CD. Healthcare or fintech domain experience appreciated. Bachelor's or
            Master's in Computer Science preferred.
        """,
    },
    {
        "job_title": "Senior Data Engineer",
        "company_name": "Google",
        "location": "New York, NY",
        "remote_or_hybrid": "Onsite",
        "posting_date": "2025-01-15",
        "salary": "$200,000 - $250,000",
        "job_url": "https://careers.google.com/jobs/results/12345",
        "platform_name": "Indeed",
        "job_description": """
            Senior Data Engineer needed with 7+ years of experience. Must lead a team
            of 5 engineers. Deep expertise in BigQuery, Apache Spark, Kafka, and GCP.
            Python and Scala required. Experience with Dataflow, Pub/Sub, and Cloud
            Composer. Strong background in data modeling, data governance, and
            enterprise-scale data lakes. Must have experience leading architecture
            decisions. PhD preferred. Managing stakeholder relationships at VP level.
        """,
    },
    {
        "job_title": "Analytics Engineer",
        "company_name": "Figma",
        "location": "Remote",
        "remote_or_hybrid": "Remote",
        "posting_date": "2025-01-14",
        "salary": "$120,000 - $160,000",
        "job_url": "https://figma.com/careers/analytics-engineer",
        "platform_name": "Wellfound",
        "job_description": """
            Analytics Engineer to own our dbt transformation layer and Snowflake data
            warehouse. Write SQL and Python to build reliable data models. Partner with
            data analysts and business stakeholders to deliver dashboards in Tableau.
            Experience with Fivetran for data ingestion, Great Expectations for data
            quality, and Airflow for orchestration. AWS experience a plus.
            2-4 years experience. Bachelor's degree in CS, Engineering, or related field.
        """,
    },
    {
        "job_title": "Junior Data Engineer",
        "company_name": "Acme Corp",
        "location": "Austin, TX",
        "remote_or_hybrid": "Hybrid",
        "posting_date": "2025-01-15",
        "salary": "$80,000",
        "job_url": "https://acmecorp.jobs/junior-data-engineer",
        "platform_name": "SimplyHired",
        "job_description": """
            Entry level data engineer. Build ETL pipelines using Python and SQL.
            Work with PostgreSQL and MySQL databases. Learn AWS tools on the job.
            0-2 years experience. Bachelor's required. No Spark or Kafka needed.
            Focus on batch processing with basic Airflow DAGs.
        """,
    },
    {
        "job_title": "Data Engineer",        # duplicate of Stripe above on different platform
        "company_name": "Stripe",
        "location": "San Francisco, CA",
        "remote_or_hybrid": "Remote",
        "posting_date": "2025-01-15",
        "salary": "$140,000 - $180,000",
        "job_url": "https://stripe.com/jobs/listing/data-engineer/99999",
        "platform_name": "RemoteOK",
        "job_description": """
            Data Engineer to build scalable data pipelines using Spark, Airflow, dbt.
            Python, SQL, AWS (S3, Redshift, Glue). Kafka streaming. Snowflake.
            Docker, Kubernetes, Terraform. ML feature pipelines with SageMaker.
        """,
    },
]


if __name__ == "__main__":
    print("=" * 60)
    print("  RESUME MATCHER — TEST RUN")
    print("=" * 60)

    for job in SAMPLE_JOBS:
        result = match_job(job)
        print(f"\n📌 {job['job_title']} @ {job['company_name']} [{job['platform_name']}]")
        print(f"   Match Score : {result.match_score}/100  → {result.recommendation}")
        print(f"   Matched     : {result.matched_skills[:80]}...")
        print(f"   Missing     : {result.missing_skills}")
        print(f"   Breakdown   : {result.score_breakdown}")

    print("\n" + "=" * 60)
    print("  AFTER FILTER (≥70) + DEDUP")
    print("=" * 60)
    filtered = filter_and_score(SAMPLE_JOBS, min_score=70)
    deduped  = deduplicate(filtered)
    for j in deduped:
        print(f"  ✅ {j['job_title']:35s} | {j['company_name']:20s} | Score: {j['match_score']}")
