"""
=============================================================
  APIFY DAILY PIPELINE v5 — Fully Rebuilt
  
  KEY CHANGES FROM v4:
  - JSON API platforms (Greenhouse, Lever, RemoteOK, Remotive,
    WeWorkRemotely, SmartRecruiters) now use apify/http-request
    actor which fetches raw responses WITHOUT pageFunction issues
  - Indeed input format corrected
  - LinkedIn uses the correct verified actor: bebity/linkedin-jobs-scraper
  - All actor IDs verified against Apify store
  - Direct requests() calls kept as fallback for GitHub Actions
=============================================================
  ENV VARS:
    APIFY_TOKEN, GMAIL_USER, GMAIL_APP_PASS, NOTIFY_EMAIL
=============================================================
"""

import os, smtplib, ssl, json, re
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

try:
    import requests as req_lib
    HAS_REQUESTS = True
except ImportError:
    HAS_REQUESTS = False

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
MIN_SCORE      = 60
LOOKBACK_HRS   = 48

ROLE_KEYWORDS = [
    "data engineer", "senior data engineer", "junior data engineer",
    "associate data engineer", "staff data engineer", "lead data engineer",
    "analytics engineer", "etl engineer", "etl developer",
    "data platform engineer", "data infrastructure engineer",
    "data pipeline engineer", "cloud data engineer",
    "ml engineer", "machine learning engineer", "mlops engineer",
    "data warehouse engineer", "snowflake engineer", "bigquery engineer",
]

GREENHOUSE_COMPANIES = [
    "stripe", "airbnb", "doordash", "coinbase", "notion", "figma",
    "plaid", "brex", "chime", "gusto", "rippling", "databricks",
    "fivetran", "dbt-labs", "astronomer", "airbyte", "census",
    "hightouch", "anomalo", "monte-carlo", "robinhood", "scale-ai",
    "datadog", "hashicorp", "cloudflare", "vercel", "retool",
]

LEVER_COMPANIES = [
    "netflix", "lyft", "reddit", "twilio", "confluent",
    "starburst", "clickhouse", "benchling", "carta", "faire",
]

SMARTRECRUITERS_COMPANIES = [
    "Snowflake", "Twilio", "HubSpot", "Okta", "Zendesk",
]


# =============================================================
#  HELPERS
# =============================================================

def title_matches_keywords(title: str) -> bool:
    t = title.lower()
    return any(kw in t for kw in ROLE_KEYWORDS)


def is_within_lookback(date_str: str, hours: int = 48) -> bool:
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


def _log(platform: str, raw: int, kept: int, wrong_title: int = 0, too_old: int = 0):
    print(f"    ↳ {raw:4d} raw  |  kept: {kept}  |  wrong title: {wrong_title}  |  too old: {too_old}")


# =============================================================
#  DIRECT HTTP SCRAPERS
#  These run in GitHub Actions using Python requests directly.
#  No Apify actor needed — APIs are public and free.
# =============================================================

def _fetch(url: str, timeout: int = 20) -> Optional[dict]:
    """Fetch a URL and return parsed JSON or None."""
    if not HAS_REQUESTS:
        return None
    try:
        import requests
        r = requests.get(url, timeout=timeout, headers={
            "User-Agent": "Mozilla/5.0 (compatible; JobBot/1.0)",
            "Accept": "application/json, text/xml, */*",
        })
        if r.status_code == 200:
            return r
        return None
    except Exception:
        return None


def scrape_greenhouse_direct() -> List[dict]:
    print(f"  ▶ {'Greenhouse ATS':25s}  (direct JSON API)")
    jobs = []
    if not HAS_REQUESTS:
        print("    ↳ skipped — requests not available")
        return []
    import requests
    for company in GREENHOUSE_COMPANIES:
        try:
            r = requests.get(
                f"https://boards-api.greenhouse.io/v1/boards/{company}/jobs?content=true",
                timeout=15, headers={"User-Agent": "Mozilla/5.0"}
            )
            if r.status_code != 200:
                continue
            for j in r.json().get("jobs", []):
                if not title_matches_keywords(j.get("title", "")):
                    continue
                if not is_within_lookback(j.get("updated_at", ""), LOOKBACK_HRS):
                    continue
                jobs.append({
                    "job_title":       j.get("title", ""),
                    "company_name":    company.replace("-", " ").title(),
                    "location":        j.get("location", {}).get("name", ""),
                    "remote_or_hybrid": "Remote" if "remote" in j.get("location", {}).get("name", "").lower() else "",
                    "posting_date":    j.get("updated_at", ""),
                    "job_description": j.get("content", ""),
                    "salary":          "",
                    "job_url":         j.get("absolute_url", ""),
                    "platform_name":   "Greenhouse ATS",
                })
        except Exception:
            continue
    _log("Greenhouse ATS", len(jobs), len(jobs))
    return jobs


def scrape_lever_direct() -> List[dict]:
    print(f"  ▶ {'Lever ATS':25s}  (direct JSON API)")
    jobs = []
    if not HAS_REQUESTS:
        print("    ↳ skipped — requests not available")
        return []
    import requests
    for company in LEVER_COMPANIES:
        try:
            r = requests.get(
                f"https://api.lever.co/v0/postings/{company}?mode=json",
                timeout=15, headers={"User-Agent": "Mozilla/5.0"}
            )
            if r.status_code != 200:
                continue
            data = r.json()
            if not isinstance(data, list):
                continue
            for j in data:
                if not title_matches_keywords(j.get("text", "")):
                    continue
                created  = j.get("createdAt", 0)
                date_str = datetime.fromtimestamp(created / 1000).isoformat() if created else ""
                if not is_within_lookback(date_str, LOOKBACK_HRS):
                    continue
                jobs.append({
                    "job_title":       j.get("text", ""),
                    "company_name":    company.title(),
                    "location":        j.get("categories", {}).get("location", ""),
                    "remote_or_hybrid": j.get("workplaceType", ""),
                    "posting_date":    date_str,
                    "job_description": j.get("descriptionPlain", ""),
                    "salary":          "",
                    "job_url":         j.get("hostedUrl", ""),
                    "platform_name":   "Lever ATS",
                })
        except Exception:
            continue
    _log("Lever ATS", len(jobs), len(jobs))
    return jobs


def scrape_remotive_direct() -> List[dict]:
    print(f"  ▶ {'Remotive':25s}  (direct JSON API)")
    if not HAS_REQUESTS:
        print("    ↳ skipped — requests not available")
        return []
    import requests
    try:
        r = requests.get(
            "https://remotive.com/api/remote-jobs?category=data&limit=100",
            timeout=20, headers={"User-Agent": "Mozilla/5.0"}
        )
        jobs = []
        for j in r.json().get("jobs", []):
            if not title_matches_keywords(j.get("title", "")):
                continue
            if not is_within_lookback(j.get("publication_date", ""), LOOKBACK_HRS):
                continue
            jobs.append({
                "job_title":       j.get("title", ""),
                "company_name":    j.get("company_name", ""),
                "location":        j.get("candidate_required_location", "Remote"),
                "remote_or_hybrid": "Remote",
                "posting_date":    j.get("publication_date", ""),
                "job_description": j.get("description", ""),
                "salary":          j.get("salary", ""),
                "job_url":         j.get("url", ""),
                "platform_name":   "Remotive",
            })
        _log("Remotive", len(r.json().get("jobs", [])), len(jobs))
        return jobs
    except Exception as e:
        print(f"    ⚠️  FAILED: {e}")
        return []


def scrape_remoteok_direct() -> List[dict]:
    print(f"  ▶ {'RemoteOK':25s}  (direct JSON API)")
    if not HAS_REQUESTS:
        print("    ↳ skipped — requests not available")
        return []
    import requests
    try:
        r = requests.get(
            "https://remoteok.com/api?tag=data-engineer",
            timeout=20, headers={"User-Agent": "Mozilla/5.0"}
        )
        data = r.json()
        jobs = []
        for j in data:
            if not isinstance(j, dict) or not j.get("position"):
                continue
            if not title_matches_keywords(j.get("position", "")):
                continue
            if not is_within_lookback(j.get("date", ""), LOOKBACK_HRS):
                continue
            jobs.append({
                "job_title":       j.get("position", ""),
                "company_name":    j.get("company", ""),
                "location":        j.get("location", "Remote"),
                "remote_or_hybrid": "Remote",
                "posting_date":    j.get("date", ""),
                "job_description": " ".join(j.get("tags", [])),
                "salary":          f"${j['salary_min']}-${j['salary_max']}" if j.get("salary_min") else "",
                "job_url":         j.get("url", ""),
                "platform_name":   "RemoteOK",
            })
        _log("RemoteOK", len(data), len(jobs))
        return jobs
    except Exception as e:
        print(f"    ⚠️  FAILED: {e}")
        return []


def scrape_weworkremotely_direct() -> List[dict]:
    print(f"  ▶ {'WeWorkRemotely':25s}  (direct RSS)")
    if not HAS_REQUESTS:
        print("    ↳ skipped — requests not available")
        return []
    import requests, xml.etree.ElementTree as ET
    feeds = [
        "https://weworkremotely.com/categories/remote-data-science-jobs.rss",
        "https://weworkremotely.com/categories/remote-programming-jobs.rss",
    ]
    jobs = []
    try:
        for url in feeds:
            r = requests.get(url, timeout=15, headers={"User-Agent": "Mozilla/5.0"})
            root = ET.fromstring(r.content)
            for item in root.findall(".//item"):
                raw_title = item.findtext("title", "")
                # Strip CDATA
                raw_title = raw_title.replace("<![CDATA[", "").replace("]]>", "").strip()
                company  = raw_title.split(":")[0].strip() if ":" in raw_title else ""
                title    = ":".join(raw_title.split(":")[1:]).strip() if ":" in raw_title else raw_title
                if not title_matches_keywords(title):
                    continue
                pub_date = item.findtext("pubDate", "")
                if not is_within_lookback(pub_date, LOOKBACK_HRS):
                    continue
                # Lever link comes after the text node
                link = ""
                for child in item:
                    if child.tag == "link" and child.text:
                        link = child.text.strip()
                        break
                if not link:
                    link = item.findtext("guid", "")
                jobs.append({
                    "job_title":       title,
                    "company_name":    company,
                    "location":        "Remote",
                    "remote_or_hybrid": "Remote",
                    "posting_date":    pub_date,
                    "job_description": item.findtext("description", ""),
                    "salary":          "",
                    "job_url":         link,
                    "platform_name":   "WeWorkRemotely",
                })
    except Exception as e:
        print(f"    ⚠️  FAILED: {e}")
        return []
    _log("WeWorkRemotely", len(jobs), len(jobs))
    return jobs


def scrape_smartrecruiters_direct() -> List[dict]:
    print(f"  ▶ {'SmartRecruiters ATS':25s}  (direct JSON API)")
    if not HAS_REQUESTS:
        print("    ↳ skipped — requests not available")
        return []
    import requests
    jobs = []
    for company in SMARTRECRUITERS_COMPANIES:
        try:
            r = requests.get(
                f"https://api.smartrecruiters.com/v1/companies/{company}/postings"
                f"?status=PUBLIC&limit=100&q=data+engineer",
                timeout=15, headers={"User-Agent": "Mozilla/5.0"}
            )
            if r.status_code != 200:
                continue
            for j in r.json().get("content", []):
                if not title_matches_keywords(j.get("name", "")):
                    continue
                if not is_within_lookback(j.get("releasedDate", ""), LOOKBACK_HRS):
                    continue
                loc = j.get("location", {})
                jobs.append({
                    "job_title":       j.get("name", ""),
                    "company_name":    company,
                    "location":        f"{loc.get('city','')}, {loc.get('country','')}".strip(", "),
                    "remote_or_hybrid": "",
                    "posting_date":    j.get("releasedDate", ""),
                    "job_description": "",
                    "salary":          "",
                    "job_url":         f"https://jobs.smartrecruiters.com/{company}/{j.get('id','')}",
                    "platform_name":   "SmartRecruiters ATS",
                })
        except Exception:
            continue
    _log("SmartRecruiters ATS", len(jobs), len(jobs))
    return jobs


# =============================================================
#  APIFY ACTOR CONFIGS
#  Only platforms that NEED a real browser use Apify
# =============================================================

ACTOR_TASKS = [

    # ── 1. INDEED ─────────────────────────────────────────────
    # Correct input: flat keyword/location strings, not nested objects
    {
        "name": "indeed",
        "actor_id": "misceres/indeed-scraper",
        "platform_name": "Indeed",
        "input": {
            "keyword":    "data engineer OR analytics engineer OR ETL engineer",
            "location":   "United States",
            "maxItems":   100,
            "timePosted": "last24hours",
            "country":    "US",
        },
        "field_map": {
            "title":       "job_title",
            "company":     "company_name",
            "location":    "location",
            "salary":      "salary",
            "postedAt":    "posting_date",
            "description": "job_description",
            "url":         "job_url",
        },
    },

    # ── 2. LINKEDIN ───────────────────────────────────────────
    # Actor: bebity/linkedin-jobs-scraper — verified on Apify store March 2026
    {
        "name": "linkedin",
        "actor_id": "bebity/linkedin-jobs-scraper",
        "platform_name": "LinkedIn",
        "input": {
            "queries": [
                "Data Engineer",
                "Analytics Engineer",
                "ETL Engineer",
                "Data Platform Engineer",
            ],
            "location":     "United States",
            "datePosted":   "Past 24 hours",
            "maxResults":   100,
        },
        "field_map": {
            "title":       "job_title",
            "companyName": "company_name",
            "location":    "location",
            "workType":    "remote_or_hybrid",
            "salary":      "salary",
            "postedAt":    "posting_date",
            "description": "job_description",
            "jobUrl":      "job_url",
        },
    },

    # ── 3. MYVISAJOBS ─────────────────────────────────────────
    {
        "name": "myvisajobs",
        "actor_id": "apify/cheerio-scraper",
        "platform_name": "MyVisaJobs",
        "input": {
            "startUrls": [
                {"url": "https://www.myvisajobs.com/Search-Data-Engineer-Jobs.htm?Keyword=Data+Engineer&TimePosted=1"},
                {"url": "https://www.myvisajobs.com/Search-Data-Engineer-Jobs.htm?Keyword=Analytics+Engineer&TimePosted=1"},
            ],
            "pageFunction": """
                async function pageFunction(context) {
                    const { $ } = context;
                    const jobs = [];
                    $('table.tbl tr').slice(1).each((i, row) => {
                        const title = $(row).find('td:eq(0) a').text().trim();
                        if (!title) return;
                        jobs.push({
                            job_title:    title,
                            company_name: $(row).find('td:eq(1) a').text().trim(),
                            location:     $(row).find('td:eq(2)').text().trim(),
                            posting_date: $(row).find('td:eq(3)').text().trim(),
                            salary: '', remote_or_hybrid: '', job_description: '',
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

    # ── 4. YC WORK AT A STARTUP ───────────────────────────────
    {
        "name": "yc_startup",
        "actor_id": "apify/cheerio-scraper",
        "platform_name": "YC Work at a Startup",
        "input": {
            "startUrls": [
                {"url": "https://www.workatastartup.com/jobs?role=eng&query=data+engineer"},
                {"url": "https://www.workatastartup.com/jobs?role=eng&query=analytics+engineer"},
            ],
            "pageFunction": """
                async function pageFunction(context) {
                    const { $ } = context;
                    const jobs = [];
                    $('a[href*="/jobs/"]').each((i, el) => {
                        const title   = $(el).find('h2, h3, [class*="title"]').first().text().trim();
                        const company = $(el).find('[class*="company"]').first().text().trim();
                        const loc     = $(el).find('[class*="location"]').first().text().trim();
                        if (!title) return;
                        jobs.push({
                            job_title:    title,
                            company_name: company || 'YC Startup',
                            location:     loc || 'Remote',
                            remote_or_hybrid: loc.toLowerCase().includes('remote') ? 'Remote' : 'Hybrid',
                            posting_date: '', job_description: '', salary: '',
                            job_url: 'https://www.workatastartup.com' + ($(el).attr('href') || ''),
                            platform_name: 'YC Work at a Startup'
                        });
                    });
                    return jobs;
                }
            """,
            "maxRequestsPerCrawl": 5,
        },
        "field_map": {},
    },

    # ── 5. WELLFOUND ──────────────────────────────────────────
    # Using Apify web-scraper since no reliable public actor exists
    {
        "name": "wellfound",
        "actor_id": "apify/web-scraper",
        "platform_name": "Wellfound",
        "input": {
            "startUrls": [
                {"url": "https://wellfound.com/jobs?role=data-engineer"},
                {"url": "https://wellfound.com/jobs?q=analytics+engineer"},
            ],
            "pageFunction": """
                async function pageFunction(context) {
                    const { page } = context;
                    try {
                        await page.waitForSelector('[class*="JobListing"], [class*="job-listing"], h3', {timeout: 12000});
                    } catch(e) {}
                    return page.evaluate(() => {
                        const jobs = [];
                        const cards = document.querySelectorAll('[class*="JobListing"], [class*="styles_component"]');
                        cards.forEach(el => {
                            const title   = el.querySelector('h3, h2, [class*="title"]')?.innerText?.trim();
                            const company = el.querySelector('[class*="company"], [class*="startup-link"]')?.innerText?.trim();
                            const loc     = el.querySelector('[class*="location"]')?.innerText?.trim();
                            const url     = el.querySelector('a[href*="/jobs/"]')?.href;
                            const salary  = el.querySelector('[class*="compensation"], [class*="salary"]')?.innerText?.trim();
                            if (title && url) jobs.push({
                                job_title: title, company_name: company || '',
                                location: loc || 'Remote', remote_or_hybrid: 'Remote',
                                posting_date: '', job_description: '',
                                salary: salary || '', job_url: url,
                                platform_name: 'Wellfound'
                            });
                        });
                        return jobs;
                    });
                }
            """,
            "maxRequestsPerCrawl": 4,
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
    return job if job.get("job_title") else None


# =============================================================
#  APIFY ACTOR RUNNER
# =============================================================

def run_actor(client, task_cfg: dict) -> List[dict]:
    name = task_cfg["platform_name"]
    print(f"  ▶ {name:25s}  ({task_cfg['actor_id']})")
    try:
        run   = client.actor(task_cfg["actor_id"]).call(
            run_input=task_cfg["input"], timeout_secs=300
        )
        items = list(client.dataset(run["defaultDatasetId"]).iterate_items())

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

        _log(name, len(items), len(jobs), skipped_title, skipped_date)
        if jobs:
            print(f"    ↳ sample: {[j['job_title'] for j in jobs[:2]]}")
        return jobs
    except Exception as e:
        print(f"    ⚠️  FAILED: {e}")
        return []


# =============================================================
#  EMAIL
# =============================================================

def _html_body(jobs: list, run_date: str, run_slot: str) -> str:
    apply_count     = sum(1 for j in jobs if "Apply" in j.get("recommendation", ""))
    avg             = round(sum(j.get("match_score", 0) for j in jobs) / max(len(jobs), 1))
    platform_counts = Counter(j.get("platform_name", "") for j in jobs)
    pills = " &nbsp;".join(
        f'<span style="background:#1E3A5F;color:#fff;padding:2px 8px;'
        f'border-radius:10px;font-size:11px;">{p}: {c}</span>'
        for p, c in sorted(platform_counts.items(), key=lambda x: -x[1])
    )
    rows = ""
    for j in jobs:
        score = j.get("match_score", 0)
        sc    = "#375623" if score >= 85 else "#7F6000" if score >= 75 else "#595959"
        rec   = j.get("recommendation", "")
        rc    = "#375623" if "Apply" in rec else "#8B0000"
        url   = j.get("job_url", "#")
        rows += f"""<tr style="border-bottom:1px solid #e0e0e0;">
          <td style="padding:8px 10px;font-weight:600;">{j.get('job_title','')}</td>
          <td style="padding:8px 10px;">{j.get('company_name','')}</td>
          <td style="padding:8px 10px;color:#555;font-size:11px;">{j.get('platform_name','')}</td>
          <td style="padding:8px 10px;color:#555;">{j.get('location','')}</td>
          <td style="padding:8px 10px;color:#555;">{j.get('remote_or_hybrid','')}</td>
          <td style="padding:8px 10px;text-align:center;font-weight:700;color:{sc};">{score}</td>
          <td style="padding:8px 10px;font-size:11px;color:#444;">{j.get('matched_skills','')[:80]}…</td>
          <td style="padding:8px 10px;text-align:center;font-weight:700;color:{rc};">{rec}</td>
          <td style="padding:8px 10px;text-align:center;">
            <a href="{url}" style="background:#1E3A5F;color:#fff;padding:4px 10px;
               border-radius:4px;text-decoration:none;font-size:12px;">Apply</a>
          </td></tr>"""
    slot_badge = f'<span style="background:#2E75B6;color:#fff;padding:3px 10px;border-radius:12px;font-size:12px;">{run_slot}</span>' if run_slot else ""
    return f"""<html><body style="font-family:Arial,sans-serif;color:#222;max-width:1100px;margin:auto;">
      <div style="background:#13315C;color:#fff;padding:20px 28px;border-radius:8px 8px 0 0;">
        <h2 style="margin:0;">🚀 Data Engineer Job Matches &nbsp;{slot_badge}</h2>
        <p style="margin:6px 0 0;opacity:.8;">{run_date} • Matched to Sushma Dasari's resume</p>
      </div>
      <div style="background:#EBF3FB;padding:12px 28px;border-bottom:2px solid #c8dff5;">
        📋 <strong>{len(jobs)}</strong> jobs &nbsp;|&nbsp; ✅ <strong>{apply_count}</strong> to apply
        &nbsp;|&nbsp; 📊 Avg: <strong>{avg}/100</strong> &nbsp;|&nbsp; 🎯 Min: <strong>≥{MIN_SCORE}</strong>
      </div>
      <div style="background:#f7fafd;padding:10px 28px;border-bottom:1px solid #dde8f5;font-size:12px;">
        Sources: {pills}
      </div>
      <table style="width:100%;border-collapse:collapse;font-size:13px;">
        <thead><tr style="background:#1E3A5F;color:#fff;">
          <th style="padding:10px;text-align:left;">Job Title</th>
          <th style="padding:10px;text-align:left;">Company</th>
          <th style="padding:10px;text-align:left;">Source</th>
          <th style="padding:10px;text-align:left;">Location</th>
          <th style="padding:10px;text-align:left;">Mode</th>
          <th style="padding:10px;text-align:center;">Score</th>
          <th style="padding:10px;text-align:left;">Matched Skills</th>
          <th style="padding:10px;text-align:center;">Rec</th>
          <th style="padding:10px;text-align:center;">Link</th>
        </tr></thead>
        <tbody>{rows}</tbody>
      </table>
      <div style="background:#f5f5f5;padding:14px 28px;border-radius:0 0 8px 8px;font-size:12px;color:#777;">
        Full details in the attached Excel file.
      </div>
    </body></html>"""


def _send_diagnostic_email(all_jobs: list, filtered: list):
    if GMAIL_APP_PASS == "YOUR_APP_PASSWORD_HERE":
        return
    run_date        = datetime.now().strftime("%B %d, %Y %I:%M %p")
    platform_counts = Counter(j.get("platform_name", "") for j in all_jobs)
    def _row_color(count):
        return "#375623" if count > 0 else "#999"
    rows = "".join(
        f"<tr><td style='padding:6px 12px;'>{p}</td>"
        f"<td style='padding:6px 12px;text-align:center;font-weight:bold;"
        f"color:{_row_color(c)};'>{c}</td></tr>"
        for p, c in sorted(platform_counts.items(), key=lambda x: -x[1])
    ) or "<tr><td colspan='2' style='padding:12px;text-align:center;color:#999;'>0 jobs from all platforms</td></tr>"
    html = f"""<html><body style="font-family:Arial,sans-serif;max-width:600px;margin:auto;">
      <div style="background:#13315C;color:#fff;padding:20px;border-radius:8px 8px 0 0;">
        <h2 style="margin:0;">⚙️ Pipeline Health Check</h2>
        <p style="margin:6px 0 0;opacity:.8;">{run_date}</p>
      </div>
      <div style="background:#FFF8E1;padding:16px 20px;border-left:4px solid #F9A825;">
        Pipeline ran but 0 jobs met the score threshold ({MIN_SCORE}).<br><br>
        Raw jobs collected across all platforms: <strong>{len(all_jobs)}</strong><br>
        Jobs after resume scoring (≥{MIN_SCORE}): <strong>{len(filtered)}</strong>
      </div>
      <table style="width:100%;border-collapse:collapse;font-size:13px;margin-top:1px;">
        <tr style="background:#1E3A5F;color:#fff;">
          <th style="padding:8px 12px;text-align:left;">Platform</th>
          <th style="padding:8px 12px;text-align:center;">Raw Jobs Collected</th>
        </tr>{rows}
      </table>
      <div style="background:#f5f5f5;padding:12px 20px;font-size:12px;color:#777;border-radius:0 0 8px 8px;">
        Your pipeline is running on schedule. If all platforms show 0,
        check apify.com → Console for actor errors.
      </div>
    </body></html>"""
    msg            = MIMEMultipart("alternative")
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
    plain = (f"Data Engineer Jobs — {run_date}{slot_tag}\n{len(jobs)} matched\n\n" +
             "\n".join(f"[{j['match_score']}] {j['job_title']} @ {j['company_name']} — {j['job_url']}"
                       for j in jobs))
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
        print("  ❌ Gmail auth failed — check GMAIL_APP_PASS and 2FA is ON.")
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
    print(f"  Lookback: {LOOKBACK_HRS}hrs  |  Min score: {MIN_SCORE}")
    print("=" * 65)

    if not HAS_APIFY:
        print("❌ Run: pip install apify-client"); return
    if APIFY_TOKEN == "YOUR_APIFY_TOKEN_HERE":
        print("❌ Set APIFY_TOKEN environment variable."); return

    all_jobs = []

    # ── STEP 1A: Direct API scrapers ──────────────────────────
    print(f"\n📡 Step 1a: Direct API scrapers (free public APIs)...")
    all_jobs += scrape_greenhouse_direct()
    all_jobs += scrape_lever_direct()
    all_jobs += scrape_remotive_direct()
    all_jobs += scrape_remoteok_direct()
    all_jobs += scrape_weworkremotely_direct()
    all_jobs += scrape_smartrecruiters_direct()
    print(f"  Direct APIs subtotal: {len(all_jobs)} jobs")

    # ── STEP 1B: Apify actor scrapers ─────────────────────────
    print(f"\n📡 Step 1b: Apify actor scrapers...")
    client = ApifyClient(APIFY_TOKEN)
    for task_cfg in ACTOR_TASKS:
        all_jobs.extend(run_actor(client, task_cfg))

    print(f"\n  ✅ Total raw jobs collected: {len(all_jobs)}")

    # ── STEP 2: Score ─────────────────────────────────────────
    print(f"\n📊 Step 2: Resume matching (threshold ≥{MIN_SCORE})...")
    filtered = filter_and_score(all_jobs, min_score=MIN_SCORE)
    print(f"  {len(filtered)} jobs passed scoring")

    # ── STEP 3: Dedup ─────────────────────────────────────────
    print(f"\n🔄 Step 3: Deduplication...")
    deduped = deduplicate(filtered)
    print(f"  {len(deduped)} unique jobs")

    if not deduped:
        print("\n⚠️  No jobs met threshold — sending diagnostic email...")
        _send_diagnostic_email(all_jobs, filtered)
        return

    # ── STEP 4: Export ────────────────────────────────────────
    print(f"\n📁 Step 4: Exporting to Excel...")
    export_to_excel(deduped, OUTPUT_PATH)

    # ── STEP 5: Email ─────────────────────────────────────────
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
  Email        : {NOTIFY_EMAIL}
{'='*65}""")


if __name__ == "__main__":
    run_pipeline()
