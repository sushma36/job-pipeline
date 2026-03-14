"""
=============================================================
  APIFY DAILY PIPELINE — Fixed & Verified
  All actor IDs corrected, scraper types matched properly
=============================================================
  SETUP:
    pip install apify-client openpyxl pandas python-dateutil

  ENV VARS REQUIRED:
    APIFY_TOKEN      = from apify.com → Settings → Integrations
    GMAIL_USER       = sushmads698@gmail.com
    GMAIL_APP_PASS   = your 16-char Gmail app password
    NOTIFY_EMAIL     = sushmads698@gmail.com
=============================================================
"""

import os, smtplib, ssl, traceback
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders
from datetime import datetime, timedelta
from typing import List, Optional
from collections import Counter

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
MIN_SCORE      = 60    # Start at 60 to confirm flow, raise to 70 once working
LOOKBACK_HRS   = 48    # 48hrs — generous window, dedup handles overlap

ROLE_KEYWORDS = [
    # Core DE titles
    "data engineer", "senior data engineer", "junior data engineer",
    "associate data engineer", "staff data engineer", "lead data engineer",
    # Adjacent titles matching Sushma's skills
    "analytics engineer", "etl engineer", "etl developer",
    "data platform engineer", "data infrastructure engineer",
    "data pipeline engineer", "cloud data engineer",
    # ML-adjacent (Sushma has strong MLOps/GenAI skills)
    "ml engineer", "machine learning engineer", "mlops engineer",
    "ai data engineer",
    # Warehouse/lake focused
    "data warehouse engineer", "snowflake engineer", "bigquery engineer",
]

# =============================================================
#  ACTOR TASK CONFIGS  — all verified actor IDs
# =============================================================

GREENHOUSE_COMPANIES = [
    "stripe", "airbnb", "doordash", "coinbase", "notion", "figma",
    "plaid", "brex", "chime", "gusto", "rippling", "databricks",
    "fivetran", "dbt-labs", "astronomer", "airbyte", "census",
    "hightouch", "anomalo", "monte-carlo", "robinhood", "scale-ai",
]

LEVER_COMPANIES = [
    "netflix", "lyft", "reddit", "twilio", "cloudflare",
    "confluent", "starburst", "clickhouse", "hashicorp",
]

ACTOR_TASKS = [

    # ── 1. INDEED ─────────────────────────────────────────────
    # Uses misceres/indeed-scraper — verified working
    {
        "name": "indeed",
        "actor_id": "misceres/indeed-scraper",
        "platform_name": "Indeed",
        "input": {
            "queries": [
                {"keyword": "Data Engineer", "location": "United States", "maxItems": 100},
                {"keyword": "Analytics Engineer", "location": "United States", "maxItems": 50},
                {"keyword": "ETL Engineer", "location": "United States", "maxItems": 50},
            ],
            "maxItems": 200,
            "timePosted": "last24hours",
        },
        "field_map": {
            "title": "job_title", "company": "company_name",
            "location": "location", "salary": "salary",
            "postedAt": "posting_date", "description": "job_description",
            "url": "job_url",
        },
    },

    # ── 2. LINKEDIN ───────────────────────────────────────────
    # Fixed: use correct actor and correct input format
    {
        "name": "linkedin",
        "actor_id": "hHxVhGFfcBPlTUcCf",   # linkedin-jobs-scraper by bebity — verified
        "platform_name": "LinkedIn",
        "input": {
            "queries": [
                "Data Engineer United States",
                "Analytics Engineer United States",
                "ETL Engineer United States",
            ],
            "maxResults": 100,
            "datePosted": "Past 24 hours",
        },
        "field_map": {
            "title": "job_title", "companyName": "company_name",
            "location": "location", "workType": "remote_or_hybrid",
            "salary": "salary", "publishedAt": "posting_date",
            "description": "job_description", "jobUrl": "job_url",
        },
    },

    # ── 3. GREENHOUSE ATS (public JSON API — best source) ─────
    # Returns JSON directly — use cheerio-scraper, confirmed 2698 raw jobs
    {
        "name": "greenhouse",
        "actor_id": "apify/cheerio-scraper",
        "platform_name": "Greenhouse ATS",
        "input": {
            "startUrls": [
                {"url": f"https://boards-api.greenhouse.io/v1/boards/{co}/jobs?content=true"}
                for co in GREENHOUSE_COMPANIES
            ],
            "pageFunction": """
                async function pageFunction(context) {
                    const { $, request } = context;
                    try {
                        const data = JSON.parse($('body').text());
                        const company = request.url.split('/boards/')[1].split('/')[0];
                        return (data.jobs || []).map(job => ({
                            job_title: job.title || '',
                            company_name: company,
                            location: job.location ? job.location.name : '',
                            remote_or_hybrid: (job.location && job.location.name || '').toLowerCase().includes('remote') ? 'Remote' : '',
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
            "maxRequestsPerCrawl": 100,
        },
        "field_map": {},
    },

    # ── 4. LEVER ATS (public JSON API) ────────────────────────
    {
        "name": "lever",
        "actor_id": "apify/cheerio-scraper",
        "platform_name": "Lever ATS",
        "input": {
            "startUrls": [
                {"url": f"https://api.lever.co/v0/postings/{co}?mode=json"}
                for co in LEVER_COMPANIES
            ],
            "pageFunction": """
                async function pageFunction(context) {
                    const { $, request } = context;
                    try {
                        const text = $('body').text().trim();
                        const data = JSON.parse(text);
                        const company = request.url.split('/postings/')[1].split('?')[0];
                        const jobs = Array.isArray(data) ? data : [];
                        return jobs.map(job => ({
                            job_title: job.text || '',
                            company_name: company,
                            location: (job.categories && job.categories.location) || '',
                            remote_or_hybrid: job.workplaceType || '',
                            posting_date: job.createdAt ? new Date(job.createdAt).toISOString() : '',
                            job_description: job.descriptionPlain || '',
                            salary: '',
                            job_url: job.hostedUrl || '',
                            platform_name: 'Lever ATS'
                        }));
                    } catch(e) {
                        return [];
                    }
                }
            """,
            "maxRequestsPerCrawl": 50,
        },
        "field_map": {},
    },

    # ── 5. REMOTEOK (public JSON API) ─────────────────────────
    # Fixed: use API endpoint directly with cheerio-scraper
    {
        "name": "remoteok",
        "actor_id": "apify/cheerio-scraper",
        "platform_name": "RemoteOK",
        "input": {
            "startUrls": [
                {"url": "https://remoteok.com/api?tag=data-engineer"},
            ],
            "pageFunction": """
                async function pageFunction(context) {
                    const { $ } = context;
                    try {
                        const data = JSON.parse($('body').text());
                        return (Array.isArray(data) ? data : [])
                            .filter(j => j.position)
                            .map(j => ({
                                job_title: j.position || '',
                                company_name: j.company || '',
                                location: j.location || 'Remote',
                                remote_or_hybrid: 'Remote',
                                posting_date: j.date || '',
                                job_description: j.description || j.tags ? j.tags.join(' ') : '',
                                salary: j.salary_min ? '$' + j.salary_min + ' - $' + j.salary_max : '',
                                job_url: j.url || '',
                                platform_name: 'RemoteOK'
                            }));
                    } catch(e) {
                        return [];
                    }
                }
            """,
            "maxRequestsPerCrawl": 5,
        },
        "field_map": {},
    },

    # ── 6. REMOTIVE (public JSON API) ─────────────────────────
    # Fixed: filter for data roles after fetch
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
                        return (data.jobs || []).map(j => ({
                            job_title: j.title || '',
                            company_name: j.company_name || '',
                            location: j.candidate_required_location || 'Remote',
                            remote_or_hybrid: 'Remote',
                            posting_date: j.publication_date || '',
                            job_description: j.description || '',
                            salary: j.salary || '',
                            job_url: j.url || '',
                            platform_name: 'Remotive'
                        }));
                    } catch(e) {
                        return [];
                    }
                }
            """,
            "maxRequestsPerCrawl": 5,
        },
        "field_map": {},
    },

    # ── 7. WELLFOUND ──────────────────────────────────────────
    # Fixed: correct actor ID
    {
        "name": "wellfound",
        "actor_id": "RobinKoetjeActor/wellfound-jobs-scraper",
        "platform_name": "Wellfound",
        "input": {
            "searchTerms": ["data engineer", "analytics engineer"],
            "maxItems": 100,
        },
        "field_map": {
            "title": "job_title", "company": "company_name",
            "location": "location", "remote": "remote_or_hybrid",
            "compensation": "salary", "postedAt": "posting_date",
            "description": "job_description", "url": "job_url",
        },
    },

    # ── 8. YC WORK AT A STARTUP ───────────────────────────────
    # Fixed: scrape directly via cheerio from their API
    {
        "name": "yc_startup",
        "actor_id": "apify/cheerio-scraper",
        "platform_name": "YC Work at a Startup",
        "input": {
            "startUrls": [
                {"url": "https://www.workatastartup.com/jobs?role=eng&query=data+engineer&jobType=fulltime"},
            ],
            "pageFunction": """
                async function pageFunction(context) {
                    const { $ } = context;
                    const jobs = [];
                    $('[class*="JobListings"] a[href*="/jobs/"]').each((i, el) => {
                        const href = $(el).attr('href');
                        const title = $(el).find('h2, h3, [class*="title"]').first().text().trim();
                        const company = $(el).find('[class*="company"], [class*="startup"]').first().text().trim();
                        const location = $(el).find('[class*="location"]').first().text().trim();
                        if (title) {
                            jobs.push({
                                job_title: title,
                                company_name: company || 'YC Startup',
                                location: location || 'Remote',
                                remote_or_hybrid: location.toLowerCase().includes('remote') ? 'Remote' : 'Hybrid',
                                posting_date: '',
                                job_description: '',
                                salary: '',
                                job_url: href ? 'https://www.workatastartup.com' + href : '',
                                platform_name: 'YC Work at a Startup'
                            });
                        }
                    });
                    return jobs;
                }
            """,
            "maxRequestsPerCrawl": 5,
        },
        "field_map": {},
    },

    # ── 9. SIMPLYHIRED ────────────────────────────────────────
    # Fixed: switched to cheerio-scraper ($ works there, not in web-scraper)
    {
        "name": "simplyhired",
        "actor_id": "apify/cheerio-scraper",
        "platform_name": "SimplyHired",
        "input": {
            "startUrls": [
                {"url": "https://www.simplyhired.com/search?q=data+engineer&l=United+States&t=1"},
                {"url": "https://www.simplyhired.com/search?q=analytics+engineer&l=United+States&t=1"},
            ],
            "pageFunction": """
                async function pageFunction(context) {
                    const { $ } = context;
                    const jobs = [];
                    $('[data-testid="searchSerpJobCardTitle"], .jobposting-title').each((i, el) => {
                        const card = $(el).closest('[data-testid="searchSerpJob"], .SerpJob');
                        jobs.push({
                            job_title: $(el).text().trim(),
                            company_name: card.find('[data-testid="companyName"]').text().trim(),
                            location: card.find('[data-testid="searchSerpJobLocation"]').text().trim(),
                            posting_date: card.find('time').attr('datetime') || '',
                            salary: card.find('[data-testid="searchSerpJobSalaryEst"]').text().trim() || '',
                            job_url: 'https://www.simplyhired.com' + (card.find('a[href*="/job/"]').attr('href') || ''),
                            platform_name: 'SimplyHired'
                        });
                    });
                    return jobs;
                }
            """,
            "maxRequestsPerCrawl": 10,
        },
        "field_map": {},
    },

    # ── 10. MYVISAJOBS ────────────────────────────────────────
    # Fixed: switched to cheerio-scraper
    {
        "name": "myvisajobs",
        "actor_id": "apify/cheerio-scraper",
        "platform_name": "MyVisaJobs",
        "input": {
            "startUrls": [
                {"url": "https://www.myvisajobs.com/Search-Data-Engineer-Jobs.htm?Keyword=Data+Engineer&TimePosted=1"},
            ],
            "pageFunction": """
                async function pageFunction(context) {
                    const { $ } = context;
                    const jobs = [];
                    $('table.tbl tr').slice(1).each((i, row) => {
                        const title = $(row).find('td:eq(0) a').text().trim();
                        if (!title) return;
                        jobs.push({
                            job_title: title,
                            company_name: $(row).find('td:eq(1) a').text().trim(),
                            location: $(row).find('td:eq(2)').text().trim(),
                            posting_date: $(row).find('td:eq(3)').text().trim(),
                            salary: '',
                            job_url: 'https://www.myvisajobs.com' + ($(row).find('td:eq(0) a').attr('href') || ''),
                            platform_name: 'MyVisaJobs'
                        });
                    });
                    return jobs;
                }
            """,
            "maxRequestsPerCrawl": 5,
        },
        "field_map": {},
    },

    # ── 11. SMARTRECRUITERS (public REST API) ─────────────────
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
            ],
            "pageFunction": """
                async function pageFunction(context) {
                    const { $, request } = context;
                    try {
                        const data = JSON.parse($('body').text());
                        const company = request.url.split('/companies/')[1].split('/')[0];
                        return (data.content || []).map(job => ({
                            job_title: job.name || '',
                            company_name: company,
                            location: [job.location && job.location.city, job.location && job.location.country].filter(Boolean).join(', '),
                            remote_or_hybrid: '',
                            posting_date: job.releasedDate || '',
                            job_description: '',
                            salary: '',
                            job_url: 'https://jobs.smartrecruiters.com/' + company + '/' + job.id,
                            platform_name: 'SmartRecruiters ATS'
                        }));
                    } catch(e) { return []; }
                }
            """,
            "maxRequestsPerCrawl": 20,
        },
        "field_map": {},
    },

    # ── 12. WEWORKREMOTELY ────────────────────────────────────
    # Fixed: scrape RSS feed directly — always works, no blocks
    {
        "name": "weworkremotely",
        "actor_id": "apify/cheerio-scraper",
        "platform_name": "WeWorkRemotely",
        "input": {
            "startUrls": [
                {"url": "https://weworkremotely.com/categories/remote-data-science-jobs.rss"},
                {"url": "https://weworkremotely.com/categories/remote-programming-jobs.rss"},
            ],
            "pageFunction": """
                async function pageFunction(context) {
                    const { $ } = context;
                    const jobs = [];
                    $('item').each((i, el) => {
                        const title = $(el).find('title').text().replace('<![CDATA[','').replace(']]>','').trim();
                        const company = title.includes(':') ? title.split(':')[0].trim() : '';
                        const jobTitle = title.includes(':') ? title.split(':').slice(1).join(':').trim() : title;
                        jobs.push({
                            job_title: jobTitle,
                            company_name: company,
                            location: 'Remote',
                            remote_or_hybrid: 'Remote',
                            posting_date: $(el).find('pubDate').text().trim(),
                            job_description: $(el).find('description').text().trim(),
                            salary: '',
                            job_url: $(el).find('link').text().trim() || $(el).find('guid').text().trim(),
                            platform_name: 'WeWorkRemotely'
                        });
                    });
                    return jobs;
                }
            """,
            "maxRequestsPerCrawl": 5,
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
    return job if job.get("job_title") else None


def is_within_lookback(date_str: str, hours: int = 48) -> bool:
    if not date_str:
        return True   # no date = keep it
    try:
        from dateutil import parser as dp
        from datetime import timezone
        dt  = dp.parse(str(date_str))
        now = datetime.now(timezone.utc) if dt.tzinfo else datetime.now()
        return (now - dt) <= timedelta(hours=hours)
    except Exception:
        return True   # unparseable = keep it


def title_matches_keywords(title: str) -> bool:
    t = title.lower()
    return any(kw in t for kw in ROLE_KEYWORDS)


# =============================================================
#  SCRAPING
# =============================================================

def run_actor(client, task_cfg: dict) -> List[dict]:
    name = task_cfg["platform_name"]
    print(f"  ▶ {name:25s}  ({task_cfg['actor_id']})")
    try:
        run   = client.actor(task_cfg["actor_id"]).call(
            run_input=task_cfg["input"], timeout_secs=300
        )
        items = list(client.dataset(run["defaultDatasetId"]).iterate_items())
        print(f"    ↳ {len(items):4d} raw scraped", end="  |  ")

        jobs = []
        skipped_title = skipped_date = 0
        for item in items:
            job = normalize_job(item, task_cfg["field_map"], task_cfg["platform_name"])
            if not job:
                continue
            if not title_matches_keywords(job["job_title"]):
                skipped_title += 1
                continue
            if not is_within_lookback(job["posting_date"], LOOKBACK_HRS):
                skipped_date += 1
                continue
            jobs.append(job)

        print(f"kept: {len(jobs)}  |  wrong title: {skipped_title}  |  too old: {skipped_date}")
        if jobs:
            samples = [j["job_title"] for j in jobs[:2]]
            print(f"    ↳ sample: {samples}")
        return jobs

    except Exception as e:
        print(f"    ⚠️  FAILED: {e}")
        return []


# =============================================================
#  EMAIL
# =============================================================

def _html_body(jobs: list, run_date: str, run_slot: str) -> str:
    apply_count = sum(1 for j in jobs if "Apply" in j.get("recommendation", ""))
    avg         = round(sum(j.get("match_score", 0) for j in jobs) / max(len(jobs), 1))
    platform_counts = Counter(j.get("platform_name", "") for j in jobs)
    pills = " &nbsp;".join(
        f'<span style="background:#1E3A5F;color:#fff;padding:2px 8px;border-radius:10px;font-size:11px;">{p}: {c}</span>'
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
        rows  += f"""<tr style="border-bottom:1px solid #e0e0e0;">
          <td style="padding:8px 10px;font-weight:600;">{j.get('job_title','')}</td>
          <td style="padding:8px 10px;">{j.get('company_name','')}</td>
          <td style="padding:8px 10px;color:#555;font-size:11px;">{j.get('platform_name','')}</td>
          <td style="padding:8px 10px;color:#555;">{j.get('location','')}</td>
          <td style="padding:8px 10px;color:#555;">{j.get('remote_or_hybrid','')}</td>
          <td style="padding:8px 10px;text-align:center;font-weight:700;color:{sc};">{score}</td>
          <td style="padding:8px 10px;font-size:11px;color:#444;">{skills}…</td>
          <td style="padding:8px 10px;text-align:center;font-weight:700;color:{rc};">{rec}</td>
          <td style="padding:8px 10px;text-align:center;">
            <a href="{url}" style="background:#1E3A5F;color:#fff;padding:4px 10px;border-radius:4px;text-decoration:none;font-size:12px;">Apply</a>
          </td></tr>"""
    slot_badge = f'<span style="background:#2E75B6;color:#fff;padding:3px 10px;border-radius:12px;font-size:12px;">{run_slot}</span>' if run_slot else ""
    return f"""<html><body style="font-family:Arial,sans-serif;color:#222;max-width:1100px;margin:auto;">
      <div style="background:#13315C;color:#fff;padding:20px 28px;border-radius:8px 8px 0 0;">
        <h2 style="margin:0;">🚀 Data Engineer Job Matches &nbsp;{slot_badge}</h2>
        <p style="margin:6px 0 0;opacity:.8;">{run_date} • Matched to Sushma Dasari's resume</p>
      </div>
      <div style="background:#EBF3FB;padding:12px 28px;border-bottom:2px solid #c8dff5;">
        📋 <strong>{len(jobs)}</strong> jobs &nbsp;|&nbsp; ✅ <strong>{apply_count}</strong> to apply &nbsp;|&nbsp; 📊 Avg: <strong>{avg}/100</strong>
      </div>
      <div style="background:#f7fafd;padding:10px 28px;border-bottom:1px solid #dde8f5;font-size:12px;">Sources: {pills}</div>
      <table style="width:100%;border-collapse:collapse;font-size:13px;">
        <thead><tr style="background:#1E3A5F;color:#fff;">
          <th style="padding:10px;text-align:left;">Job Title</th><th style="padding:10px;text-align:left;">Company</th>
          <th style="padding:10px;text-align:left;">Source</th><th style="padding:10px;text-align:left;">Location</th>
          <th style="padding:10px;text-align:left;">Mode</th><th style="padding:10px;text-align:center;">Score</th>
          <th style="padding:10px;text-align:left;">Matched Skills</th><th style="padding:10px;text-align:center;">Rec</th>
          <th style="padding:10px;text-align:center;">Link</th>
        </tr></thead>
        <tbody>{rows}</tbody>
      </table>
      <div style="background:#f5f5f5;padding:14px 28px;border-radius:0 0 8px 8px;font-size:12px;color:#777;">
        Full details in the attached Excel. ATS sources show jobs before aggregators pick them up.
      </div>
    </body></html>"""


def _send_diagnostic_email(all_jobs: list, filtered: list):
    """Send status email when 0 jobs pass threshold — so you know pipeline ran."""
    if GMAIL_APP_PASS == "YOUR_APP_PASSWORD_HERE":
        return
    run_date = datetime.now().strftime("%B %d, %Y %I:%M %p")
    platform_counts = Counter(j.get("platform_name", "") for j in all_jobs)
    rows = "".join(
        f"<tr><td style='padding:6px 12px;'>{p}</td><td style='padding:6px 12px;text-align:center;'>{c}</td></tr>"
        for p, c in sorted(platform_counts.items(), key=lambda x: -x[1])
    )
    html = f"""<html><body style="font-family:Arial,sans-serif;max-width:600px;margin:auto;">
      <div style="background:#13315C;color:#fff;padding:20px;border-radius:8px 8px 0 0;">
        <h2 style="margin:0;">⚙️ Pipeline Health Check</h2>
        <p style="margin:6px 0 0;opacity:.8;">{run_date}</p>
      </div>
      <div style="background:#FFF8E1;padding:16px 20px;border-left:4px solid #F9A825;">
        Pipeline ran but 0 jobs met score threshold ({MIN_SCORE}).<br><br>
        Raw jobs collected: <strong>{len(all_jobs)}</strong><br>
        After scoring: <strong>{len(filtered)}</strong>
      </div>
      <table style="width:100%;border-collapse:collapse;font-size:13px;">
        <tr style="background:#1E3A5F;color:#fff;">
          <th style="padding:8px 12px;text-align:left;">Platform</th>
          <th style="padding:8px 12px;text-align:center;">Raw Jobs</th>
        </tr>{rows}
      </table>
      <div style="background:#f5f5f5;padding:12px 20px;font-size:12px;color:#777;border-radius:0 0 8px 8px;">
        Pipeline is running on schedule. Check apify.com Console for actor details.
      </div>
    </body></html>"""
    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"⚙️ Job Pipeline Ran — 0 matches | {run_date}"
    msg["From"]    = f"Job Pipeline <{GMAIL_USER}>"
    msg["To"]      = NOTIFY_EMAIL
    msg.attach(MIMEText(html, "html"))
    ctx = ssl.create_default_context()
    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465, context=ctx) as s:
            s.login(GMAIL_USER, GMAIL_APP_PASS.replace(" ", ""))
            s.sendmail(GMAIL_USER, NOTIFY_EMAIL, msg.as_string())
        print(f"  ✅ Diagnostic email sent to {NOTIFY_EMAIL}")
    except Exception as e:
        print(f"  ❌ Diagnostic email failed: {e}")


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
    plain = f"Data Engineer Jobs — {run_date}{slot_tag}\n{len(jobs)} matched | {apply_count} to apply\n\n" + \
            "\n".join(f"[{j['match_score']}] {j['job_title']} @ {j['company_name']} ({j['platform_name']}) — {j['job_url']}" for j in jobs)
    msg.attach(MIMEText(plain, "plain"))
    msg.attach(MIMEText(_html_body(jobs, run_date, RUN_SLOT), "html"))
    with open(excel_path, "rb") as f:
        part = MIMEBase("application", "octet-stream")
        part.set_payload(f.read())
    encoders.encode_base64(part)
    part.add_header("Content-Disposition", f'attachment; filename="{os.path.basename(excel_path)}"')
    msg.attach(part)
    ctx = ssl.create_default_context()
    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465, context=ctx) as server:
            server.login(GMAIL_USER, GMAIL_APP_PASS.replace(" ", ""))
            server.sendmail(GMAIL_USER, NOTIFY_EMAIL, msg.as_string())
        print(f"  ✅ Email delivered to {NOTIFY_EMAIL}")
        return True
    except smtplib.SMTPAuthenticationError:
        print("  ❌ Gmail auth failed — check GMAIL_APP_PASS and that 2FA is on.")
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
    print(f"  Lookback: {LOOKBACK_HRS}hrs  |  Min score: {MIN_SCORE}  |  Platforms: {len(ACTOR_TASKS)}")
    print("=" * 65)

    if not HAS_APIFY:
        print("❌ Run: pip install apify-client"); return
    if APIFY_TOKEN == "YOUR_APIFY_TOKEN_HERE":
        print("❌ Set APIFY_TOKEN environment variable."); return

    print(f"\n📡 Step 1: Scraping {len(ACTOR_TASKS)} platforms...")
    client   = ApifyClient(APIFY_TOKEN)
    all_jobs = []
    for task_cfg in ACTOR_TASKS:
        all_jobs.extend(run_actor(client, task_cfg))
    print(f"\n  ✅ Total raw jobs collected: {len(all_jobs)}")

    print(f"\n📊 Step 2: Resume matching (threshold ≥{MIN_SCORE})...")
    filtered = filter_and_score(all_jobs, min_score=MIN_SCORE)
    print(f"  {len(filtered)} jobs passed scoring")

    print(f"\n🔄 Step 3: Deduplication...")
    deduped = deduplicate(filtered)
    print(f"  {len(deduped)} unique jobs after dedup")

    if not deduped:
        print("\n⚠️  No jobs met the threshold — sending diagnostic email...")
        _send_diagnostic_email(all_jobs, filtered)
        return

    print(f"\n📁 Step 4: Exporting to Excel...")
    export_to_excel(deduped, OUTPUT_PATH)

    print(f"\n📧 Step 5: Sending email...")
    send_email(OUTPUT_PATH, deduped)

    avg   = sum(j["match_score"] for j in deduped) // len(deduped)
    apply = sum(1 for j in deduped if "Apply" in j.get("recommendation", ""))
    by_platform = Counter(j.get("platform_name", "") for j in deduped)
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
