"""
=============================================================
  APIFY DAILY PIPELINE — Full ATS + Job Board Coverage
  Scrapes jobs → scores vs resume → emails Excel to you

  PLATFORMS COVERED (18 total):
  ── Aggregators ──────────────────────────────────────────
  1.  Indeed
  2.  LinkedIn
  3.  SimplyHired
  4.  Jooble
  ── ATS Boards (direct source — fastest postings) ────────
  5.  Greenhouse
  6.  Lever
  7.  Ashby
  8.  Workday
  9.  SmartRecruiters
  10. iCIMS
  ── Startup / Niche Boards ───────────────────────────────
  11. Wellfound (AngelList)
  12. YC Work at a Startup
  13. Otta
  ── Remote Boards ────────────────────────────────────────
  14. RemoteOK
  15. We Work Remotely
  16. Remotive
  ── Visa / Immigration Focused ───────────────────────────
  17. MyVisaJobs
  18. Handshake

  SCHEDULE: 7:00 AM ET  +  3:00 PM ET  (twice daily)

=============================================================
  SETUP
=============================================================
  pip install apify-client openpyxl pandas python-dateutil

  Set these environment variables:
    APIFY_TOKEN      = your Apify API token (apify.com → Settings → Integrations)
    GMAIL_USER       = sushmads698@gmail.com
    GMAIL_APP_PASS   = your 16-char Gmail app password
    NOTIFY_EMAIL     = sushmads698@gmail.com

=============================================================
  HOW TO GET GMAIL APP PASSWORD (one-time, 2 min)
=============================================================
  1. myaccount.google.com → Security
  2. Enable 2-Step Verification
  3. Search "App passwords" → Select app: Mail, Device: Other → "JobPipeline"
  4. Copy the 16-char password → set as GMAIL_APP_PASS env var
=============================================================
"""

import os
import smtplib
import ssl
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders
from datetime import datetime, timedelta
from typing import List, Optional

try:
    from apify_client import ApifyClient
    HAS_APIFY = True
except ImportError:
    HAS_APIFY = False

from resume_matcher import filter_and_score, deduplicate
from excel_exporter import export_to_excel

# =============================================================
#  CONFIGURATION
# =============================================================

APIFY_TOKEN    = os.environ.get("APIFY_TOKEN",    "YOUR_APIFY_TOKEN_HERE")
GMAIL_USER     = os.environ.get("GMAIL_USER",     "sushmads698@gmail.com")
GMAIL_APP_PASS = os.environ.get("GMAIL_APP_PASS", "YOUR_APP_PASSWORD_HERE")
NOTIFY_EMAIL   = os.environ.get("NOTIFY_EMAIL",   "sushmads698@gmail.com")
RUN_SLOT       = os.environ.get("RUN_SLOT",       "")

OUTPUT_PATH    = f"data_engineer_jobs_{datetime.now().strftime('%Y%m%d_%H%M')}.xlsx"
MIN_SCORE      = 70
LOOKBACK_HRS   = 12   # 12hrs per run since we run twice daily

ROLE_KEYWORDS = [
    "Data Engineer", "Junior Data Engineer", "Associate Data Engineer",
    "Analytics Engineer", "ETL Engineer", "Data Platform Engineer",
]

# Companies known to use each ATS — expand this list freely
GREENHOUSE_COMPANIES = [
    "stripe", "airbnb", "doordash", "robinhood", "coinbase", "notion",
    "figma", "plaid", "brex", "chime", "gusto", "rippling", "lattice",
    "databricks", "scale-ai", "weights-biases", "dbt-labs", "fivetran",
    "census", "hightouch", "rudderstack", "airbyte", "astronomer",
    "anomalo", "monte-carlo", "atlan", "secoda", "metaphor",
]

LEVER_COMPANIES = [
    "netflix", "lyft", "reddit", "twilio", "zendesk", "cloudflare",
    "hashicorp", "confluent", "starburst", "imply", "clickhouse",
    "preset", "lightdash", "cube-dev", "transform",
]

ASHBY_COMPANIES = [
    "linear", "loom", "vercel", "retool", "iter-ai", "hex", "deepnote",
    "y42", "grouparoo", "meltano", "elementary-data", "re-data",
    "soda-core", "great-expectations", "datafold",
]

WORKDAY_COMPANIES = [
    "amazon", "microsoft", "google", "meta", "apple", "salesforce",
    "oracle", "sap", "ibm", "accenture", "deloitte", "pwc",
    "jpmorgan", "goldman-sachs", "morgan-stanley", "citi",
    "unitedhealth", "cigna", "cvs-health", "humana", "anthem",
    "walmart", "target", "mckesson", "cardinal-health",
]


# =============================================================
#  ACTOR TASK CONFIGS
# =============================================================

def _build_greenhouse_urls():
    """Greenhouse has a public JSON API per company: no auth needed."""
    return [
        {"url": f"https://boards-api.greenhouse.io/v1/boards/{co}/jobs?content=true"}
        for co in GREENHOUSE_COMPANIES
    ]

def _build_lever_urls():
    """Lever has a public postings API per company."""
    return [
        {"url": f"https://api.lever.co/v0/postings/{co}?mode=json&department=Engineering&team=Data"}
        for co in LEVER_COMPANIES
    ]

def _build_ashby_urls():
    """Ashby job board URLs."""
    return [
        {"url": f"https://jobs.ashbyhq.com/{co}"}
        for co in ASHBY_COMPANIES
    ]


ACTOR_TASKS = [

    # ── 1. INDEED ──────────────────────────────────────────────
    {
        "name": "indeed",
        "actor_id": "misceres/indeed-scraper",
        "platform_name": "Indeed",
        "input": {
            "queries": [
                {"keyword": kw, "location": "United States", "maxItems": 50}
                for kw in ROLE_KEYWORDS
            ],
            "maxItems": 300,
            "timePosted": "last24hours",
        },
        "field_map": {
            "title": "job_title", "company": "company_name",
            "location": "location", "salary": "salary",
            "postedAt": "posting_date", "description": "job_description",
            "url": "job_url",
        },
    },

    # ── 2. LINKEDIN ────────────────────────────────────────────
    {
        "name": "linkedin",
        "actor_id": "curious_coder/linkedin-jobs-scraper",
        "platform_name": "LinkedIn",
        "input": {
            "searchQueries": [
                {"keyword": kw, "location": "United States"}
                for kw in ROLE_KEYWORDS
            ],
            "maxResults": 200,
            "postedAt": "past-24h",
            "experienceLevels": ["ENTRY_LEVEL", "ASSOCIATE", "MID_SENIOR_LEVEL"],
            "jobTypes": ["FULL_TIME", "CONTRACT"],
        },
        "field_map": {
            "title": "job_title", "company": "company_name",
            "location": "location", "workplaceType": "remote_or_hybrid",
            "salary": "salary", "postedAt": "posting_date",
            "description": "job_description", "applyUrl": "job_url",
        },
    },

    # ── 3. SIMPLYHIRED ─────────────────────────────────────────
    {
        "name": "simplyhired",
        "actor_id": "apify/web-scraper",
        "platform_name": "SimplyHired",
        "input": {
            "startUrls": [
                {"url": f"https://www.simplyhired.com/search?q={kw.replace(' ', '+')}&l=United+States&t=1"}
                for kw in ["data+engineer", "analytics+engineer", "etl+engineer", "data+platform+engineer"]
            ],
            "pageFunction": """
                async function pageFunction(context) {
                    const { $ } = context;
                    return $('.SerpJob').map((i, el) => ({
                        job_title: $(el).find('.jobposting-title').text().trim(),
                        company_name: $(el).find('[data-testid="companyName"]').text().trim(),
                        location: $(el).find('[data-testid="searchSerpJobLocation"]').text().trim(),
                        posting_date: $(el).find('time').attr('datetime') || '',
                        salary: $(el).find('[data-testid="searchSerpJobSalaryEst"]').text().trim() || '',
                        job_url: 'https://www.simplyhired.com' + $(el).find('a.card-link').attr('href'),
                        platform_name: 'SimplyHired'
                    })).get();
                }
            """,
            "maxRequestsPerCrawl": 20,
        },
        "field_map": {},
    },

    # ── 4. JOOBLE ──────────────────────────────────────────────
    {
        "name": "jooble",
        "actor_id": "apify/web-scraper",
        "platform_name": "Jooble",
        "input": {
            "startUrls": [
                {"url": "https://jooble.org/jobs-data-engineer/United-States?date=1"},
                {"url": "https://jooble.org/jobs-analytics-engineer/United-States?date=1"},
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
                        job_url: $(el).find('a.position').attr('href') || '',
                        platform_name: 'Jooble'
                    })).get();
                }
            """,
            "maxRequestsPerCrawl": 10,
        },
        "field_map": {},
    },

    # ── 5. GREENHOUSE (direct ATS API — fastest postings) ──────
    # No auth required. Public JSON API for every company on Greenhouse.
    {
        "name": "greenhouse",
        "actor_id": "apify/cheerio-scraper",
        "platform_name": "Greenhouse ATS",
        "input": {
            "startUrls": _build_greenhouse_urls(),
            "pageFunction": """
                async function pageFunction(context) {
                    const { $, request, json } = context;
                    // Greenhouse returns JSON directly
                    try {
                        const data = json || JSON.parse($('body').text());
                        const company = request.url.split('/boards/')[1].split('/')[0];
                        return (data.jobs || []).map(job => ({
                            job_title: job.title || '',
                            company_name: job.departments?.[0]?.name
                                ? company + ' (' + job.departments[0].name + ')'
                                : company,
                            location: job.location?.name || 'Unknown',
                            remote_or_hybrid: (job.location?.name || '').toLowerCase().includes('remote') ? 'Remote' : '',
                            posting_date: job.updated_at || job.created_at || '',
                            job_description: job.content || '',
                            salary: '',
                            job_url: job.absolute_url || '',
                            platform_name: 'Greenhouse ATS'
                        }));
                    } catch(e) {
                        return [];
                    }
                }
            """,
            "maxRequestsPerCrawl": 200,
        },
        "field_map": {},
    },

    # ── 6. LEVER (direct ATS API — fastest postings) ───────────
    # Lever's public API returns postings JSON per company.
    {
        "name": "lever",
        "actor_id": "apify/cheerio-scraper",
        "platform_name": "Lever ATS",
        "input": {
            "startUrls": _build_lever_urls(),
            "pageFunction": """
                async function pageFunction(context) {
                    const { $, request } = context;
                    try {
                        const data = JSON.parse($('body').text());
                        const company = request.url.split('/postings/')[1].split('?')[0];
                        return (Array.isArray(data) ? data : []).map(job => ({
                            job_title: job.text || '',
                            company_name: company,
                            location: job.categories?.location || job.workplaceType || '',
                            remote_or_hybrid: job.workplaceType || '',
                            posting_date: job.createdAt
                                ? new Date(job.createdAt).toISOString()
                                : '',
                            job_description: job.descriptionPlain || job.description || '',
                            salary: job.salaryRange?.min
                                ? '$' + job.salaryRange.min + ' - $' + job.salaryRange.max
                                : '',
                            job_url: job.hostedUrl || job.applyUrl || '',
                            platform_name: 'Lever ATS'
                        }));
                    } catch(e) {
                        return [];
                    }
                }
            """,
            "maxRequestsPerCrawl": 100,
        },
        "field_map": {},
    },

    # ── 7. ASHBY (ATS used by linear, vercel, hex, etc.) ───────
    {
        "name": "ashby",
        "actor_id": "apify/puppeteer-scraper",
        "platform_name": "Ashby ATS",
        "input": {
            "startUrls": _build_ashby_urls(),
            "pageFunction": """
                async function pageFunction(context) {
                    await context.page.waitForSelector('[class*="JobList"]', {timeout: 10000})
                        .catch(() => {});
                    return context.page.evaluate((platformName) => {
                        const jobs = [];
                        document.querySelectorAll('a[href*="/jobs/"]').forEach(el => {
                            const title = el.querySelector('h3,h2,[class*="title"]')?.innerText?.trim();
                            const dept  = el.querySelector('[class*="department"],[class*="team"]')?.innerText?.trim();
                            const loc   = el.querySelector('[class*="location"]')?.innerText?.trim();
                            if (title) {
                                jobs.push({
                                    job_title: title,
                                    company_name: document.title.replace(' Jobs','').replace(' Careers','').trim(),
                                    location: loc || 'Remote',
                                    remote_or_hybrid: (loc||'').toLowerCase().includes('remote') ? 'Remote' : 'Hybrid',
                                    posting_date: '',
                                    job_description: dept || '',
                                    salary: '',
                                    job_url: el.href,
                                    platform_name: platformName,
                                });
                            }
                        });
                        return jobs;
                    }, 'Ashby ATS');
                }
            """,
            "maxRequestsPerCrawl": 60,
            "useChrome": True,
        },
        "field_map": {},
    },

    # ── 8. WORKDAY (large enterprise companies) ────────────────
    # Workday has a standard REST API pattern across all tenants.
    {
        "name": "workday",
        "actor_id": "apify/puppeteer-scraper",
        "platform_name": "Workday ATS",
        "input": {
            "startUrls": [
                {"url": f"https://{co}.wd5.myworkdayjobs.com/en-US/External_Career_Site/jobs"}
                for co in ["amazon", "microsoft", "google", "cigna", "unitedhealthgroup",
                           "jpmorgan", "goldmansachs", "walmart", "target", "ibm"]
            ],
            "pageFunction": """
                async function pageFunction(context) {
                    const { page, request } = context;
                    await page.waitForSelector('[data-automation-id="jobResults"]', {timeout: 15000})
                        .catch(() => {});
                    return page.evaluate((companyUrl) => {
                        const company = new URL(companyUrl).hostname.split('.')[0];
                        const jobs = [];
                        document.querySelectorAll('[data-automation-id="jobTitle"]').forEach(el => {
                            const row  = el.closest('li,article,[class*="job"]');
                            const loc  = row?.querySelector('[data-automation-id="locations"]')?.innerText || '';
                            const date = row?.querySelector('[data-automation-id="postedOn"]')?.innerText || '';
                            jobs.push({
                                job_title: el.innerText.trim(),
                                company_name: company,
                                location: loc.trim(),
                                remote_or_hybrid: loc.toLowerCase().includes('remote') ? 'Remote' : 'Onsite',
                                posting_date: date.replace('Posted','').trim(),
                                job_description: '',
                                salary: '',
                                job_url: el.querySelector('a')?.href || companyUrl,
                                platform_name: 'Workday ATS',
                            });
                        });
                        return jobs;
                    }, request.url);
                }
            """,
            "maxRequestsPerCrawl": 50,
            "useChrome": True,
        },
        "field_map": {},
    },

    # ── 9. SMARTRECRUITERS ─────────────────────────────────────
    # SmartRecruiters has a public REST API: no auth needed.
    {
        "name": "smartrecruiters",
        "actor_id": "apify/cheerio-scraper",
        "platform_name": "SmartRecruiters ATS",
        "input": {
            "startUrls": [
                {"url": "https://api.smartrecruiters.com/v1/companies/Snowflake/postings?status=PUBLIC&limit=100&q=data+engineer"},
                {"url": "https://api.smartrecruiters.com/v1/companies/Twilio/postings?status=PUBLIC&limit=100&q=data+engineer"},
                {"url": "https://api.smartrecruiters.com/v1/companies/HubSpot/postings?status=PUBLIC&limit=100&q=data+engineer"},
                {"url": "https://api.smartrecruiters.com/v1/companies/Okta/postings?status=PUBLIC&limit=100&q=data+engineer"},
                {"url": "https://api.smartrecruiters.com/v1/companies/Medallia/postings?status=PUBLIC&limit=100&q=data+engineer"},
            ],
            "pageFunction": """
                async function pageFunction(context) {
                    const { $, request } = context;
                    try {
                        const data  = JSON.parse($('body').text());
                        const company = request.url.split('/companies/')[1].split('/')[0];
                        return (data.content || []).map(job => ({
                            job_title: job.name || '',
                            company_name: company,
                            location: [job.location?.city, job.location?.country].filter(Boolean).join(', '),
                            remote_or_hybrid: job.typeOfEmployment?.id === 'remote' ? 'Remote' : '',
                            posting_date: job.releasedDate || '',
                            job_description: job.customField?.find(f=>f.fieldLabel==='Job Description')?.valueLabel || '',
                            salary: '',
                            job_url: `https://jobs.smartrecruiters.com/${company}/${job.id}`,
                            platform_name: 'SmartRecruiters ATS'
                        }));
                    } catch(e) { return []; }
                }
            """,
            "maxRequestsPerCrawl": 20,
        },
        "field_map": {},
    },

    # ── 10. iCIMS ──────────────────────────────────────────────
    # iCIMS powers many Fortune 500 career sites.
    {
        "name": "icims",
        "actor_id": "apify/web-scraper",
        "platform_name": "iCIMS ATS",
        "input": {
            "startUrls": [
                {"url": "https://careers.verizon.com/jobs/search?keyword=data+engineer"},
                {"url": "https://jobs.jnj.com/jobs?keywords=data+engineer&posted_within=1d"},
                {"url": "https://jobs.bofa.com/en-us/search#q=data%20engineer&t=1"},
                {"url": "https://careers.boehringer-ingelheim.com/search/?q=data+engineer&posted=1"},
            ],
            "pageFunction": """
                async function pageFunction(context) {
                    const { $ } = context;
                    const jobs = [];
                    $('article.job-listing, .iCIMS_JobsTable tr, [class*="job-card"]').each((i, el) => {
                        const title = $(el).find('[class*="title"] a, h2 a, h3 a').first().text().trim();
                        if (!title) return;
                        jobs.push({
                            job_title: title,
                            company_name: $('meta[property="og:site_name"]').attr('content') || window?.location?.hostname || '',
                            location: $(el).find('[class*="location"]').text().trim(),
                            posting_date: $(el).find('[class*="date"], time').text().trim(),
                            salary: '',
                            job_url: $(el).find('a').first().attr('href') || '',
                            platform_name: 'iCIMS ATS',
                        });
                    });
                    return jobs;
                }
            """,
            "maxRequestsPerCrawl": 20,
        },
        "field_map": {},
    },

    # ── 11. WELLFOUND ──────────────────────────────────────────
    {
        "name": "wellfound",
        "actor_id": "epctex/wellfound-scraper",
        "platform_name": "Wellfound",
        "input": {
            "searchTerms": ["Data Engineer", "Analytics Engineer", "ETL Engineer"],
            "locations": ["United States", "Remote"],
            "maxItems": 100,
            "postedWithin": 1,
        },
        "field_map": {
            "title": "job_title", "company": "company_name",
            "location": "location", "remote": "remote_or_hybrid",
            "compensation": "salary", "postedAt": "posting_date",
            "description": "job_description", "url": "job_url",
        },
    },

    # ── 12. YC WORK AT A STARTUP ───────────────────────────────
    {
        "name": "yc_startup",
        "actor_id": "epctex/y-combinator-jobs-scraper",
        "platform_name": "YC Work at a Startup",
        "input": {
            "startUrls": ["https://www.workatastartup.com/jobs?role=eng&query=data+engineer"],
            "maxItems": 100,
        },
        "field_map": {
            "title": "job_title", "company": "company_name",
            "location": "location", "remote": "remote_or_hybrid",
            "salary": "salary", "createdAt": "posting_date",
            "description": "job_description", "url": "job_url",
        },
    },

    # ── 13. OTTA ───────────────────────────────────────────────
    {
        "name": "otta",
        "actor_id": "apify/puppeteer-scraper",
        "platform_name": "Otta",
        "input": {
            "startUrls": [{"url": "https://app.otta.com/jobs/search?query=data+engineer"}],
            "pageFunction": """
                async function pageFunction(context) {
                    await context.page.waitForSelector('[data-testid="job-card"]', {timeout: 15000})
                        .catch(() => {});
                    return context.page.evaluate(() =>
                        Array.from(document.querySelectorAll('[data-testid="job-card"]')).map(el => ({
                            job_title: el.querySelector('h2')?.innerText || '',
                            company_name: el.querySelector('[data-testid="company-name"]')?.innerText || '',
                            location: el.querySelector('[data-testid="job-location"]')?.innerText || '',
                            remote_or_hybrid: el.querySelector('[data-testid="remote-type"]')?.innerText || '',
                            posting_date: el.querySelector('time')?.getAttribute('datetime') || '',
                            salary: el.querySelector('[data-testid="salary"]')?.innerText || '',
                            job_url: el.querySelector('a')?.href || '',
                            platform_name: 'Otta'
                        }))
                    );
                }
            """,
            "maxRequestsPerCrawl": 5,
            "useChrome": True,
        },
        "field_map": {},
    },

    # ── 14. REMOTEOK ───────────────────────────────────────────
    {
        "name": "remoteok",
        "actor_id": "epctex/remoteok-scraper",
        "platform_name": "RemoteOK",
        "input": {
            "tags": ["data-engineer", "python", "sql", "aws", "spark"],
            "maxItems": 100,
        },
        "field_map": {
            "position": "job_title", "company": "company_name",
            "location": "location", "date": "posting_date",
            "description": "job_description", "url": "job_url",
        },
    },

    # ── 15. WE WORK REMOTELY ───────────────────────────────────
    {
        "name": "weworkremotely",
        "actor_id": "epctex/we-work-remotely-scraper",
        "platform_name": "WeWorkRemotely",
        "input": {
            "startUrls": [
                "https://weworkremotely.com/categories/remote-data-science-jobs",
                "https://weworkremotely.com/categories/remote-programming-jobs",
            ],
            "searchTerms": ["data engineer", "analytics engineer"],
            "maxItems": 50,
        },
        "field_map": {
            "title": "job_title", "company": "company_name",
            "location": "location", "type": "remote_or_hybrid",
            "salary": "salary", "date": "posting_date",
            "description": "job_description", "url": "job_url",
        },
    },

    # ── 16. REMOTIVE ───────────────────────────────────────────
    {
        "name": "remotive",
        "actor_id": "apify/cheerio-scraper",
        "platform_name": "Remotive",
        "input": {
            "startUrls": [
                {"url": "https://remotive.com/api/remote-jobs?category=data&limit=100"},
            ],
            "pageFunction": """
                async function pageFunction(context) {
                    const { $ } = context;
                    try {
                        const data = JSON.parse($('body').text());
                        return (data.jobs || [])
                            .filter(j => /data engineer|analytics engineer|etl/i.test(j.title))
                            .map(j => ({
                                job_title: j.title,
                                company_name: j.company_name,
                                location: j.candidate_required_location || 'Remote',
                                remote_or_hybrid: 'Remote',
                                posting_date: j.publication_date,
                                job_description: j.description || '',
                                salary: j.salary || '',
                                job_url: j.url,
                                platform_name: 'Remotive'
                            }));
                    } catch(e) { return []; }
                }
            """,
            "maxRequestsPerCrawl": 5,
        },
        "field_map": {},
    },

    # ── 17. MYVISAJOBS ─────────────────────────────────────────
    {
        "name": "myvisajobs",
        "actor_id": "apify/web-scraper",
        "platform_name": "MyVisaJobs",
        "input": {
            "startUrls": [{"url": "https://www.myvisajobs.com/Search-Data-Engineer-Jobs.htm?Keyword=Data+Engineer&TimePosted=1"}],
            "pageFunction": """
                async function pageFunction(context) {
                    const { $ } = context;
                    return $('table.tbl tr').slice(1).map((i, row) => ({
                        job_title: $(row).find('td:eq(0) a').text().trim(),
                        company_name: $(row).find('td:eq(1) a').text().trim(),
                        location: $(row).find('td:eq(2)').text().trim(),
                        posting_date: $(row).find('td:eq(3)').text().trim(),
                        salary: '',
                        job_url: 'https://www.myvisajobs.com' + $(row).find('td:eq(0) a').attr('href'),
                        platform_name: 'MyVisaJobs'
                    })).get().filter(j => j.job_title);
                }
            """,
            "maxRequestsPerCrawl": 10,
        },
        "field_map": {},
    },

    # ── 18. HANDSHAKE ──────────────────────────────────────────
    {
        "name": "handshake",
        "actor_id": "apify/puppeteer-scraper",
        "platform_name": "Handshake",
        "input": {
            "startUrls": [{"url": "https://app.joinhandshake.com/stu/postings?query=data+engineer&posted_date_range_key=yesterday"}],
            "pageFunction": """
                async function pageFunction(context) {
                    await context.page.waitForSelector('.posting-card', {timeout: 10000})
                        .catch(() => {});
                    return context.page.evaluate(() =>
                        Array.from(document.querySelectorAll('.posting-card')).map(el => ({
                            job_title: el.querySelector('.posting-name')?.innerText || '',
                            company_name: el.querySelector('.employer-name')?.innerText || '',
                            location: el.querySelector('.posting-location')?.innerText || '',
                            remote_or_hybrid: '',
                            posting_date: el.querySelector('.posted-date')?.innerText || '',
                            job_description: '',
                            salary: '',
                            job_url: el.querySelector('a')?.href || '',
                            platform_name: 'Handshake'
                        }))
                    );
                }
            """,
            "maxRequestsPerCrawl": 5,
            "useChrome": True,
        },
        "field_map": {},
    },
]


# =============================================================
#  NORMALIZATION
# =============================================================

def normalize_job(raw: dict, field_map: dict, platform_name: str) -> Optional[dict]:
    job = {"platform_name": platform_name, "remote_or_hybrid": "", "salary": ""}
    if field_map:
        for src, dst in field_map.items():
            job[dst] = raw.get(src, "")
    else:
        job.update(raw)
    for f in ["job_title", "company_name", "location", "posting_date",
              "job_description", "job_url"]:
        job.setdefault(f, "")
    job["platform_name"] = platform_name
    return job if job["job_title"] else None


def is_within_lookback(date_str: str, hours: int = 12) -> bool:
    if not date_str:
        return True
    try:
        from dateutil import parser as dp
        from datetime import timezone
        dt  = dp.parse(str(date_str))
        now = datetime.now(timezone.utc) if dt.tzinfo else datetime.now()
        return (now - dt) <= timedelta(hours=hours)
    except Exception:
        return True


def title_matches_keywords(title: str) -> bool:
    t = title.lower()
    return any(kw.lower() in t for kw in ROLE_KEYWORDS)


# =============================================================
#  SCRAPING
# =============================================================

def run_actor(client, task_cfg: dict) -> List[dict]:
    print(f"  ▶ {task_cfg['platform_name']:25s}  ({task_cfg['actor_id']})")
    try:
        run   = client.actor(task_cfg["actor_id"]).call(
            run_input=task_cfg["input"], timeout_secs=300
        )
        items = list(client.dataset(run["defaultDatasetId"]).iterate_items())
        print(f"    ↳ {len(items):4d} raw  ", end="")

        jobs = []
        for item in items:
            job = normalize_job(item, task_cfg["field_map"], task_cfg["platform_name"])
            if job and title_matches_keywords(job["job_title"]):
                if is_within_lookback(job["posting_date"], LOOKBACK_HRS):
                    jobs.append(job)

        print(f"→ {len(jobs):3d} kept")
        return jobs
    except Exception as e:
        print(f"    ⚠️  Failed: {e}")
        return []


# =============================================================
#  EMAIL
# =============================================================

def _html_body(jobs: list, run_date: str, run_slot: str) -> str:
    apply_count = sum(1 for j in jobs if "Apply" in j.get("recommendation", ""))
    avg         = round(sum(j.get("match_score", 0) for j in jobs) / max(len(jobs), 1))

    # Platform breakdown
    from collections import Counter
    platform_counts = Counter(j.get("platform_name", "") for j in jobs)
    platform_pills  = " &nbsp; ".join(
        f'<span style="background:#1E3A5F;color:#fff;padding:2px 8px;'
        f'border-radius:10px;font-size:11px;">{p}: {c}</span>'
        for p, c in sorted(platform_counts.items(), key=lambda x: -x[1])
    )

    rows = ""
    for j in jobs:
        score  = j.get("match_score", 0)
        sc     = "#375623" if score >= 85 else "#7F6000" if score >= 75 else "#595959"
        rec    = j.get("recommendation", "")
        rc     = "#375623" if "Apply" in rec else "#8B0000"
        url    = j.get("job_url", "#")
        skills = j.get("matched_skills", "")[:80]
        rows  += f"""
        <tr style="border-bottom:1px solid #e0e0e0;">
          <td style="padding:8px 10px;font-weight:600;">{j.get('job_title','')}</td>
          <td style="padding:8px 10px;">{j.get('company_name','')}</td>
          <td style="padding:8px 10px;color:#555;font-size:11px;">{j.get('platform_name','')}</td>
          <td style="padding:8px 10px;color:#555;">{j.get('location','')}</td>
          <td style="padding:8px 10px;color:#555;">{j.get('remote_or_hybrid','')}</td>
          <td style="padding:8px 10px;text-align:center;font-weight:700;color:{sc};">{score}</td>
          <td style="padding:8px 10px;font-size:11px;color:#444;">{skills}…</td>
          <td style="padding:8px 10px;text-align:center;font-weight:700;color:{rc};">{rec}</td>
          <td style="padding:8px 10px;text-align:center;">
            <a href="{url}" style="background:#1E3A5F;color:#fff;padding:4px 10px;
               border-radius:4px;text-decoration:none;font-size:12px;">Apply</a>
          </td>
        </tr>"""

    slot_badge = f'<span style="background:#2E75B6;color:#fff;padding:3px 10px;border-radius:12px;font-size:12px;">{run_slot}</span>' if run_slot else ""

    return f"""<html><body style="font-family:Arial,sans-serif;color:#222;max-width:1100px;margin:auto;">
      <div style="background:#13315C;color:#fff;padding:20px 28px;border-radius:8px 8px 0 0;">
        <h2 style="margin:0;">🚀 Data Engineer Job Matches &nbsp; {slot_badge}</h2>
        <p style="margin:6px 0 0;opacity:.8;">{run_date} &nbsp;•&nbsp; Matched to Sushma Dasari's resume &nbsp;•&nbsp; 18 platforms scraped</p>
      </div>
      <div style="background:#EBF3FB;padding:12px 28px;border-bottom:2px solid #c8dff5;">
        📋 <strong>{len(jobs)}</strong> jobs matched &nbsp;|&nbsp;
        ✅ <strong>{apply_count}</strong> to apply &nbsp;|&nbsp;
        📊 Avg score: <strong>{avg}/100</strong> &nbsp;|&nbsp;
        🎯 Min threshold: <strong>≥{MIN_SCORE}</strong>
      </div>
      <div style="background:#f7fafd;padding:10px 28px;border-bottom:1px solid #dde8f5;font-size:12px;">
        Sources: &nbsp; {platform_pills}
      </div>
      <table style="width:100%;border-collapse:collapse;font-size:13px;">
        <thead>
          <tr style="background:#1E3A5F;color:#fff;">
            <th style="padding:10px;text-align:left;">Job Title</th>
            <th style="padding:10px;text-align:left;">Company</th>
            <th style="padding:10px;text-align:left;">Source</th>
            <th style="padding:10px;text-align:left;">Location</th>
            <th style="padding:10px;text-align:left;">Mode</th>
            <th style="padding:10px;text-align:center;">Score</th>
            <th style="padding:10px;text-align:left;">Top Matched Skills</th>
            <th style="padding:10px;text-align:center;">Rec</th>
            <th style="padding:10px;text-align:center;">Link</th>
          </tr>
        </thead>
        <tbody>{rows}</tbody>
      </table>
      <div style="background:#f5f5f5;padding:14px 28px;border-radius:0 0 8px 8px;
                  font-size:12px;color:#777;margin-top:2px;">
        Full matched/missing skill details in the attached Excel. &nbsp;
        ATS sources (Greenhouse, Lever, Ashby, Workday) show jobs before aggregators pick them up.
      </div>
    </body></html>"""


def send_email(excel_path: str, jobs: list) -> bool:
    if GMAIL_APP_PASS == "YOUR_APP_PASSWORD_HERE":
        print("  ⚠️  Email skipped — GMAIL_APP_PASS not set.")
        return False

    run_date    = datetime.now().strftime("%B %d, %Y")
    apply_count = sum(1 for j in jobs if "Apply" in j.get("recommendation", ""))
    slot_tag    = f" | {RUN_SLOT}" if RUN_SLOT else ""

    print(f"  📧 Sending to {NOTIFY_EMAIL}...")

    msg            = MIMEMultipart("alternative")
    msg["Subject"] = f"🔍 {len(jobs)} DE Jobs — {apply_count} to Apply | {run_date}{slot_tag}"
    msg["From"]    = f"Job Pipeline <{GMAIL_USER}>"
    msg["To"]      = NOTIFY_EMAIL

    plain = (
        f"Data Engineer Jobs — {run_date}{slot_tag}\n"
        f"{len(jobs)} matched | {apply_count} to apply\n\n"
        + "\n".join(
            f"[{j['match_score']}] {j['job_title']} @ {j['company_name']} "
            f"({j['platform_name']}) — {j['job_url']}"
            for j in jobs
        )
        + "\n\nFull details in the attached Excel file."
    )
    msg.attach(MIMEText(plain, "plain"))
    msg.attach(MIMEText(_html_body(jobs, run_date, RUN_SLOT), "html"))

    with open(excel_path, "rb") as f:
        part = MIMEBase("application", "octet-stream")
        part.set_payload(f.read())
    encoders.encode_base64(part)
    part.add_header("Content-Disposition",
                    f'attachment; filename="{os.path.basename(excel_path)}"')
    msg.attach(part)

    ctx = ssl.create_default_context()
    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465, context=ctx) as server:
            server.login(GMAIL_USER, GMAIL_APP_PASS.replace(" ", ""))
            server.sendmail(GMAIL_USER, NOTIFY_EMAIL, msg.as_string())
        print(f"  ✅ Email delivered to {NOTIFY_EMAIL}")
        return True
    except smtplib.SMTPAuthenticationError:
        print("  ❌ Auth failed — check GMAIL_APP_PASS and that 2FA is on.")
        return False
    except Exception as e:
        print(f"  ❌ Email error: {e}")
        return False


# =============================================================
#  MAIN PIPELINE
# =============================================================

def run_pipeline():
    print("=" * 65)
    print(f"  DATA ENGINEER JOB PIPELINE  —  {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    if RUN_SLOT:
        print(f"  {RUN_SLOT}")
    print(f"  Platforms: 18  |  Lookback: {LOOKBACK_HRS}hrs  |  Min score: {MIN_SCORE}")
    print("=" * 65)

    if not HAS_APIFY:
        print("❌ Run: pip install apify-client"); return
    if APIFY_TOKEN == "YOUR_APIFY_TOKEN_HERE":
        print("❌ Set APIFY_TOKEN environment variable."); return

    # Step 1 — Scrape all 18 platforms
    print(f"\n📡 Step 1: Scraping 18 platforms...")
    client   = ApifyClient(APIFY_TOKEN)
    all_jobs = []
    for task_cfg in ACTOR_TASKS:
        all_jobs.extend(run_actor(client, task_cfg))
    print(f"\n  Total raw jobs: {len(all_jobs)}")

    # Step 2 — Score
    print(f"\n📊 Step 2: Resume matching (threshold ≥{MIN_SCORE})...")
    filtered = filter_and_score(all_jobs, min_score=MIN_SCORE)
    print(f"  {len(filtered)} jobs passed")

    # Step 3 — Deduplicate
    print(f"\n🔄 Step 3: Deduplication...")
    deduped = deduplicate(filtered)
    print(f"  {len(deduped)} unique jobs")

    if not deduped:
        print("\n⚠️  No matching jobs this run — no email sent.")
        return

    # Step 4 — Export
    print(f"\n📁 Step 4: Exporting to Excel...")
    export_to_excel(deduped, OUTPUT_PATH)

    # Step 5 — Email
    print(f"\n📧 Step 5: Sending email...")
    send_email(OUTPUT_PATH, deduped)

    # Summary
    avg   = sum(j["match_score"] for j in deduped) // len(deduped)
    apply = sum(1 for j in deduped if "Apply" in j.get("recommendation", ""))
    from collections import Counter
    by_platform = Counter(j.get("platform_name","") for j in deduped)
    print(f"""
{'='*65}
  PIPELINE COMPLETE
  Jobs found   : {len(deduped)}
  Apply now    : {apply}
  Avg score    : {avg}/100
  By platform  : {dict(by_platform)}
  Excel        : {OUTPUT_PATH}
  Email sent   : {NOTIFY_EMAIL}
{'='*65}""")


if __name__ == "__main__":
    run_pipeline()
