"""
=============================================================
  APIFY SCRAPING CONFIGURATION — DATA ENGINEER JOB DISCOVERY
=============================================================
Each section defines:
  - Which Apify actor to use
  - Input JSON config to pass to the actor
  - Fields to extract
  - Notes on platform-specific handling
"""

ROLE_KEYWORDS = [
    "Data Engineer",
    "Junior Data Engineer",
    "Associate Data Engineer",
    "Analytics Engineer",
    "ETL Engineer",
    "Data Platform Engineer",
]

TECH_KEYWORDS = [
    "Python", "SQL", "Spark", "Airflow", "Kafka",
    "Snowflake", "AWS", "Redshift", "BigQuery", "Databricks",
    "dbt", "GCP", "Azure", "Delta Lake", "Terraform",
    "Docker", "Kubernetes", "SageMaker", "Glue", "Fivetran",
]

# =============================================================
# PLATFORM CONFIGS (pass as input JSON to each Apify actor)
# =============================================================

PLATFORM_CONFIGS = {

    # ── 1. INDEED ─────────────────────────────────────────────
    "indeed": {
        "actor": "misceres/indeed-scraper",   # or "hynekhruza/indeed-scraper"
        "description": "Largest general job board. Best for volume.",
        "input": {
            "queries": [
                {"keyword": kw, "location": "United States", "maxItems": 50}
                for kw in ROLE_KEYWORDS
            ],
            "maxItems": 300,
            "countryCode": "US",
            "timePosted": "last24hours",       # built-in filter
            "extractFields": [
                "title", "company", "location", "salary",
                "postedAt", "description", "url"
            ],
        },
        "field_map": {
            "job_title": "title",
            "company_name": "company",
            "location": "location",
            "salary": "salary",
            "posting_date": "postedAt",
            "job_description": "description",
            "job_url": "url",
        },
        "platform_name": "Indeed",
        "notes": "Use maxItems ~50 per keyword to stay within free tier. Enable proxy rotation.",
    },

    # ── 2. LINKEDIN ────────────────────────────────────────────
    "linkedin": {
        "actor": "curious_coder/linkedin-jobs-scraper",
        "description": "Premium jobs with seniority filters. Best quality signal.",
        "input": {
            "searchQueries": [
                {"keyword": kw, "location": "United States"}
                for kw in ROLE_KEYWORDS
            ],
            "maxResults": 200,
            "postedAt": "past-24h",
            "experienceLevels": ["ENTRY_LEVEL", "ASSOCIATE", "MID_SENIOR_LEVEL"],
            "jobTypes": ["FULL_TIME", "CONTRACT"],
            "extractFields": [
                "title", "company", "location", "workplaceType",
                "postedAt", "description", "salary", "applyUrl"
            ],
        },
        "field_map": {
            "job_title": "title",
            "company_name": "company",
            "location": "location",
            "remote_or_hybrid": "workplaceType",
            "salary": "salary",
            "posting_date": "postedAt",
            "job_description": "description",
            "job_url": "applyUrl",
        },
        "platform_name": "LinkedIn",
        "notes": "Requires session cookie (li_at) for deep scraping. Respect rate limits.",
    },

    # ── 3. WELLFOUND (AngelList Talent) ───────────────────────
    "wellfound": {
        "actor": "epctex/wellfound-scraper",
        "description": "Startup & VC-backed companies. Great for growth-stage roles.",
        "input": {
            "searchTerms": ["Data Engineer", "Analytics Engineer", "ETL Engineer"],
            "locations": ["United States", "Remote"],
            "maxItems": 100,
            "postedWithin": 1,              # days
            "extractFields": [
                "title", "company", "location", "remote",
                "compensation", "postedAt", "description", "url"
            ],
        },
        "field_map": {
            "job_title": "title",
            "company_name": "company",
            "location": "location",
            "remote_or_hybrid": "remote",
            "salary": "compensation",
            "posting_date": "postedAt",
            "job_description": "description",
            "job_url": "url",
        },
        "platform_name": "Wellfound",
        "notes": "No auth needed. Filter by 'postedWithin: 1' for 24hr freshness.",
    },

    # ── 4. REMOTEOK ────────────────────────────────────────────
    "remoteok": {
        "actor": "epctex/remoteok-scraper",
        "description": "Remote-first job board with tech focus. Good for WFH roles.",
        "input": {
            "tags": ["data-engineer", "python", "sql", "aws", "spark"],
            "maxItems": 100,
            "startUrls": [
                "https://remoteok.com/remote-data-engineer-jobs",
                "https://remoteok.com/remote-analytics-engineer-jobs",
            ],
        },
        "field_map": {
            "job_title": "position",
            "company_name": "company",
            "location": "location",
            "remote_or_hybrid": "remote",
            "salary": "salary",
            "posting_date": "date",
            "job_description": "description",
            "job_url": "url",
        },
        "platform_name": "RemoteOK",
        "notes": "RemoteOK has a public JSON API: https://remoteok.com/api — can also fetch directly.",
    },

    # ── 5. WE WORK REMOTELY ────────────────────────────────────
    "weworkremotely": {
        "actor": "epctex/we-work-remotely-scraper",
        "description": "Curated remote jobs. Low volume, high quality.",
        "input": {
            "startUrls": [
                "https://weworkremotely.com/categories/remote-data-science-jobs",
                "https://weworkremotely.com/categories/remote-programming-jobs",
            ],
            "searchTerms": ["data engineer", "analytics engineer"],
            "maxItems": 50,
        },
        "field_map": {
            "job_title": "title",
            "company_name": "company",
            "location": "location",
            "remote_or_hybrid": "type",
            "salary": "salary",
            "posting_date": "date",
            "job_description": "description",
            "job_url": "url",
        },
        "platform_name": "WeWorkRemotely",
        "notes": "Small board — filter post-scrape by date since no built-in time filter.",
    },

    # ── 6. REMOTIVE ────────────────────────────────────────────
    "remotive": {
        "actor": "web_scraper",              # use generic Apify Web Scraper
        "description": "Remote tech jobs with public API.",
        "input": {
            "startUrls": [
                {"url": "https://remotive.com/api/remote-jobs?category=data&limit=100"}
            ],
            "pageFunction": """
                async function pageFunction(context) {
                    const data = await context.request.json();
                    return data.jobs.filter(j =>
                        /data engineer|analytics engineer|etl/i.test(j.title)
                    ).map(j => ({
                        job_title: j.title,
                        company_name: j.company_name,
                        location: j.candidate_required_location,
                        remote_or_hybrid: 'Remote',
                        posting_date: j.publication_date,
                        job_description: j.description,
                        salary: j.salary || '',
                        job_url: j.url,
                        platform_name: 'Remotive'
                    }));
                }
            """,
        },
        "platform_name": "Remotive",
        "notes": "Has free public API. No auth needed. Filter by publication_date < 24hrs in post-processing.",
    },

    # ── 7. SIMPLYHIRED ─────────────────────────────────────────
    "simplyhired": {
        "actor": "apify/web-scraper",
        "description": "Aggregator pulling from many ATS sources.",
        "input": {
            "startUrls": [
                {"url": f"https://www.simplyhired.com/search?q={kw.replace(' ', '+')}&l=United+States&t=1"}
                for kw in ["data+engineer", "analytics+engineer", "etl+engineer"]
            ],
            "pageFunction": """
                async function pageFunction(context) {
                    const { $ } = context;
                    return $('.SerpJob').map((i, el) => ({
                        job_title: $(el).find('.jobposting-title').text().trim(),
                        company_name: $(el).find('[data-testid="companyName"]').text().trim(),
                        location: $(el).find('[data-testid="searchSerpJobLocation"]').text().trim(),
                        posting_date: $(el).find('time').attr('datetime'),
                        job_url: 'https://www.simplyhired.com' + $(el).find('a.card-link').attr('href'),
                        platform_name: 'SimplyHired'
                    })).get();
                }
            """,
            "maxRequestsPerCrawl": 20,
        },
        "platform_name": "SimplyHired",
        "notes": "Use ?t=1 param for 'last 24 hours'. Proxy rotation recommended.",
    },

    # ── 8. JOOBLE ──────────────────────────────────────────────
    "jooble": {
        "actor": "apify/web-scraper",
        "description": "International aggregator with US coverage.",
        "input": {
            "startUrls": [
                {"url": "https://jooble.org/jobs-data-engineer/United-States?date=1"}
            ],
            "pageFunction": """
                async function pageFunction(context) {
                    const { $ } = context;
                    return $('article.result').map((i, el) => ({
                        job_title: $(el).find('.position').text().trim(),
                        company_name: $(el).find('.company-name').text().trim(),
                        location: $(el).find('.location').text().trim(),
                        posting_date: $(el).find('.date').text().trim(),
                        salary: $(el).find('.salary').text().trim() || '',
                        job_url: $(el).find('a.position').attr('href'),
                        platform_name: 'Jooble'
                    })).get();
                }
            """,
            "maxRequestsPerCrawl": 10,
        },
        "platform_name": "Jooble",
        "notes": "?date=1 filters to last 24hrs. Jooble also has an official API (api.jooble.org).",
    },

    # ── 9. YC WORK AT A STARTUP ────────────────────────────────
    "yc_startup": {
        "actor": "epctex/y-combinator-jobs-scraper",
        "description": "YC-backed companies. High quality, fast-growing startups.",
        "input": {
            "startUrls": ["https://www.workatastartup.com/jobs?role=eng&query=data+engineer"],
            "maxItems": 100,
        },
        "field_map": {
            "job_title": "title",
            "company_name": "company",
            "location": "location",
            "remote_or_hybrid": "remote",
            "salary": "salary",
            "posting_date": "createdAt",
            "job_description": "description",
            "job_url": "url",
        },
        "platform_name": "YC Work at a Startup",
        "notes": "Includes batch info (S24, W25) — filter by recent batches for newer companies.",
    },

    # ── 10. HANDSHAKE ──────────────────────────────────────────
    "handshake": {
        "actor": "apify/web-scraper",
        "description": "Entry-level and new grad roles. Good for Associate/Junior titles.",
        "input": {
            "startUrls": [
                {"url": "https://app.joinhandshake.com/stu/postings?query=data+engineer&posted_date_range_key=yesterday"}
            ],
            "pageFunction": """
                async function pageFunction(context) {
                    // Handshake is React SPA — requires full page render
                    await context.page.waitForSelector('.posting-card', {timeout: 10000});
                    const jobs = await context.page.evaluate(() =>
                        Array.from(document.querySelectorAll('.posting-card')).map(el => ({
                            job_title: el.querySelector('.posting-name')?.innerText,
                            company_name: el.querySelector('.employer-name')?.innerText,
                            location: el.querySelector('.posting-location')?.innerText,
                            posting_date: el.querySelector('.posted-date')?.innerText,
                            job_url: el.querySelector('a')?.href,
                            platform_name: 'Handshake'
                        }))
                    );
                    return jobs;
                }
            """,
            "maxRequestsPerCrawl": 5,
            "useChrome": true,
        },
        "platform_name": "Handshake",
        "notes": "Requires headless Chrome. Use Apify's Puppeteer actor for SPA rendering.",
    },

    # ── 11. MYVISAJOBS ─────────────────────────────────────────
    "myvisajobs": {
        "actor": "apify/web-scraper",
        "description": "H1B/visa-sponsoring employers. Critical for sponsorship-needed candidates.",
        "input": {
            "startUrls": [
                {"url": "https://www.myvisajobs.com/Search-Data-Engineer-Jobs.htm?JobID=0&Keyword=Data+Engineer&TimePosted=1"}
            ],
            "pageFunction": """
                async function pageFunction(context) {
                    const { $ } = context;
                    return $('table.tbl tr').slice(1).map((i, row) => ({
                        job_title: $(row).find('td:eq(0) a').text().trim(),
                        company_name: $(row).find('td:eq(1) a').text().trim(),
                        location: $(row).find('td:eq(2)').text().trim(),
                        posting_date: $(row).find('td:eq(3)').text().trim(),
                        job_url: 'https://www.myvisajobs.com' + $(row).find('td:eq(0) a').attr('href'),
                        platform_name: 'MyVisaJobs'
                    })).get();
                }
            """,
            "maxRequestsPerCrawl": 10,
        },
        "platform_name": "MyVisaJobs",
        "notes": "?TimePosted=1 = last 24hrs. Tracks H1B sponsorship history by employer.",
    },

    # ── 12. OTTA ───────────────────────────────────────────────
    "otta": {
        "actor": "apify/web-scraper",
        "description": "Curated tech roles at growth companies. Quality > quantity.",
        "input": {
            "startUrls": [
                {"url": "https://app.otta.com/jobs/search?query=data+engineer"}
            ],
            "pageFunction": """
                async function pageFunction(context) {
                    await context.page.waitForSelector('[data-testid="job-card"]', {timeout: 15000});
                    return context.page.evaluate(() =>
                        Array.from(document.querySelectorAll('[data-testid="job-card"]')).map(el => ({
                            job_title: el.querySelector('h2')?.innerText,
                            company_name: el.querySelector('[data-testid="company-name"]')?.innerText,
                            location: el.querySelector('[data-testid="job-location"]')?.innerText,
                            remote_or_hybrid: el.querySelector('[data-testid="remote-type"]')?.innerText,
                            posting_date: el.querySelector('time')?.getAttribute('datetime'),
                            salary: el.querySelector('[data-testid="salary"]')?.innerText,
                            job_url: el.querySelector('a')?.href,
                            platform_name: 'Otta'
                        }))
                    );
                }
            """,
            "maxRequestsPerCrawl": 5,
            "useChrome": true,
        },
        "platform_name": "Otta",
        "notes": "React SPA — needs headless Chrome. Login may be required for full description.",
    },
}

# =============================================================
# APIFY ORCHESTRATION — Main pipeline entry point
# =============================================================
APIFY_PIPELINE_PSEUDOCODE = """
STEP 1: Run all scrapers in parallel via Apify API
   POST https://api.apify.com/v2/actor-tasks/{taskId}/runs?token={YOUR_TOKEN}
   Collect results from each actor dataset

STEP 2: Normalize all results to unified schema:
   { job_title, company_name, location, remote_or_hybrid,
     posting_date, job_description, salary, job_url, platform_name }

STEP 3: Filter to last 24 hours only
   Parse posting_date → drop jobs older than 24hrs

STEP 4: Filter by role keywords
   Keep jobs where job_title matches ROLE_KEYWORDS (case-insensitive)

STEP 5: Resume matching (see resume_matcher.py)
   Score each job 0-100 against Sushma's resume
   Keep only jobs with score >= 70

STEP 6: Deduplicate
   Dedup key: normalize(company_name) + normalize(job_title)
   Keep record with highest match_score when duplicates exist

STEP 7: Sort
   Primary: posting_date DESC (newest first)
   Secondary: match_score DESC

STEP 8: Export to Excel (see excel_exporter.py)
   Output: data_engineer_jobs.xlsx
"""
