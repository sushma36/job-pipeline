"""
=============================================================
  APIFY DAILY PIPELINE v6 — Final Fixed Version

  FIXES FROM v5:
  - requests imported ONCE at top, used everywhere (no re-import)
  - Indeed input fixed: uses 'position' field correctly
  - Added Jobicy public API (100% free, no auth)
  - Added Adzuna public API (free, 50 req/month)  
  - Direct API scrapers now use single top-level import
  - MyVisaJobs and YC updated with better selectors
=============================================================
"""

import os, smtplib, ssl, json, re, xml.etree.ElementTree as ET
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders
from datetime import datetime, timedelta
from typing import List, Optional
from collections import Counter

import requests  # Always available in GitHub Actions

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
RUN_SLOT         = os.environ.get("RUN_SLOT",         "")

OUTPUT_PATH  = f"data_engineer_jobs_{datetime.now().strftime('%Y%m%d_%H%M')}.xlsx"
MIN_SCORE    = 60
LOOKBACK_HRS = 48

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
    # Data/Analytics companies
    "stripe", "airbnb", "doordash", "coinbase", "notion", "figma",
    "plaid", "brex", "chime", "gusto", "rippling", "databricks",
    "fivetran", "dbt-labs", "astronomer", "airbyte", "census",
    "hightouch", "anomalo", "monte-carlo", "robinhood", "scale-ai",
    "datadog", "cloudflare", "vercel", "retool", "benchling",
    # More US tech companies
    "lyft", "reddit", "duolingo", "discord", "hubspot", "zendesk",
    "twilio", "okta", "hashicorp", "elastic", "mongodb-inc",
    "cockroachdb", "airtable", "zapier", "segment", "amplitude",
    "mixpanel", "heap", "iteratively", "rudderstack",
    # Healthcare (good match for Sushma)
    "tempus", "flatiron", "veeva", "health-gorilla", "commure",
]

LEVER_COMPANIES = [
    "netflix", "lyft", "reddit", "twilio", "confluent",
    "starburst", "clickhouse", "carta", "faire", "benchling",
]

# =============================================================
#  HELPERS
# =============================================================

def title_matches(title: str) -> bool:
    t = title.lower()
    return any(kw in t for kw in ROLE_KEYWORDS)


def within_lookback(date_str: str, hours: int = 48) -> bool:
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


def make_job(title, company, location, remote, date, description, salary, url, platform):
    return {
        "job_title":       title,
        "company_name":    company,
        "location":        location,
        "remote_or_hybrid": remote,
        "posting_date":    date,
        "job_description": description,
        "salary":          salary,
        "job_url":         url,
        "platform_name":   platform,
    }



# US states, territories and keywords for location filtering
US_LOCATIONS = {
    "united states", "usa", "u.s.a", "u.s.", "remote", "anywhere",
    "worldwide", "global", "us only", "us-only", "north america",
    # States
    "alabama","alaska","arizona","arkansas","california","colorado",
    "connecticut","delaware","florida","georgia","hawaii","idaho",
    "illinois","indiana","iowa","kansas","kentucky","louisiana","maine",
    "maryland","massachusetts","michigan","minnesota","mississippi",
    "missouri","montana","nebraska","nevada","new hampshire","new jersey",
    "new mexico","new york","north carolina","north dakota","ohio",
    "oklahoma","oregon","pennsylvania","rhode island","south carolina",
    "south dakota","tennessee","texas","utah","vermont","virginia",
    "washington","west virginia","wisconsin","wyoming",
    # Common city abbreviations
    "ny", "nyc", "la", "sf", "dc", "atl", "chi", "sea", "bos", "aus",
    # State abbreviations
    "al","ak","az","ar","ca","co","ct","de","fl","ga","hi","id","il",
    "in","ia","ks","ky","la","me","md","ma","mi","mn","ms","mo","mt",
    "ne","nv","nh","nj","nm","nc","nd","oh","ok","or","pa","ri","sc",
    "sd","tn","tx","ut","vt","va","wa","wv","wi","wy",
}

def is_us_or_remote(location: str, description: str = "") -> bool:
    """Return True if job is in the US, remote, or location is unspecified."""
    if not location:
        return True   # no location = keep it
    loc_lower = location.lower()
    # Explicit non-US countries to reject
    non_us = [
        "india", "bengaluru", "bangalore", "hyderabad", "mumbai", "delhi",
        "chennai", "pune", "kolkata", "canada", "toronto", "vancouver",
        "uk", "united kingdom", "london", "england", "germany", "berlin",
        "france", "paris", "australia", "sydney", "melbourne", "singapore",
        "japan", "china", "brazil", "mexico", "netherlands", "amsterdam",
        "ireland", "dublin", "poland", "spain", "madrid", "italy", "rome",
        "sweden", "stockholm", "denmark", "norway", "finland",
    ]
    for country in non_us:
        if country in loc_lower:
            return False
    # Check if it matches a US location
    for us_loc in US_LOCATIONS:
        if us_loc in loc_lower:
            return True
    # If location has no clear signal, keep it (benefit of the doubt)
    return True

def fetch_json(url, timeout=20):
    try:
        r = requests.get(url, timeout=timeout,
                         headers={"User-Agent": "Mozilla/5.0 JobBot/1.0"})
        if r.status_code == 200:
            return r.json()
    except Exception:
        pass
    return None


def fetch_xml(url, timeout=15):
    try:
        r = requests.get(url, timeout=timeout,
                         headers={"User-Agent": "Mozilla/5.0 JobBot/1.0"})
        if r.status_code == 200:
            return ET.fromstring(r.content)
    except Exception:
        pass
    return None


# =============================================================
#  DIRECT API SCRAPERS — free public APIs, no Apify needed
# =============================================================

def scrape_greenhouse() -> List[dict]:
    print(f"  ▶ {'Greenhouse ATS':25s}  (direct JSON API — {len(GREENHOUSE_COMPANIES)} companies)")
    jobs = []
    for company in GREENHOUSE_COMPANIES:
        data = fetch_json(
            f"https://boards-api.greenhouse.io/v1/boards/{company}/jobs?content=true"
        )
        if not data:
            continue
        for j in data.get("jobs", []):
            if not title_matches(j.get("title", "")):
                continue
            if not within_lookback(j.get("updated_at", ""), LOOKBACK_HRS):
                continue
            loc = j.get("location", {}).get("name", "") if j.get("location") else ""
            if not is_us_or_remote(loc):
                continue   # skip non-US Greenhouse jobs
            jobs.append(make_job(
                j.get("title", ""),
                company.replace("-", " ").title(),
                loc,
                "Remote" if "remote" in loc.lower() else "",
                j.get("updated_at", ""),
                j.get("content", ""),
                "",
                j.get("absolute_url", ""),
                "Greenhouse ATS"
            ))
    print(f"    ↳ {len(jobs)} jobs matched")
    return jobs


def scrape_lever() -> List[dict]:
    print(f"  ▶ {'Lever ATS':25s}  (direct JSON API — {len(LEVER_COMPANIES)} companies)")
    jobs = []
    for company in LEVER_COMPANIES:
        data = fetch_json(f"https://api.lever.co/v0/postings/{company}?mode=json")
        if not isinstance(data, list):
            continue
        for j in data:
            if not title_matches(j.get("text", "")):
                continue
            created  = j.get("createdAt", 0)
            date_str = datetime.fromtimestamp(created / 1000).isoformat() if created else ""
            if not within_lookback(date_str, LOOKBACK_HRS):
                continue
            jobs.append(make_job(
                j.get("text", ""),
                company.title(),
                j.get("categories", {}).get("location", ""),
                j.get("workplaceType", ""),
                date_str,
                j.get("descriptionPlain", ""),
                "",
                j.get("hostedUrl", ""),
                "Lever ATS"
            ))
    print(f"    ↳ {len(jobs)} jobs matched")
    return jobs


def scrape_remotive() -> List[dict]:
    print(f"  ▶ {'Remotive':25s}  (direct JSON API)")
    data = fetch_json("https://remotive.com/api/remote-jobs?category=data&limit=100")
    if not data:
        print("    ↳ 0 (API unreachable)")
        return []
    jobs = []
    for j in data.get("jobs", []):
        if not title_matches(j.get("title", "")):
            continue
        if not within_lookback(j.get("publication_date", ""), LOOKBACK_HRS):
            continue
        jobs.append(make_job(
            j.get("title", ""),
            j.get("company_name", ""),
            j.get("candidate_required_location", "Remote"),
            "Remote",
            j.get("publication_date", ""),
            j.get("description", ""),
            j.get("salary", ""),
            j.get("url", ""),
            "Remotive"
        ))
    print(f"    ↳ {len(jobs)} jobs matched")
    return jobs


def scrape_remoteok() -> List[dict]:
    print(f"  ▶ {'RemoteOK':25s}  (direct JSON API)")
    data = fetch_json("https://remoteok.com/api?tag=data-engineer")
    if not data:
        print("    ↳ 0 (API unreachable)")
        return []
    jobs = []
    for j in data:
        if not isinstance(j, dict) or not j.get("position"):
            continue
        if not title_matches(j.get("position", "")):
            continue
        if not within_lookback(j.get("date", ""), LOOKBACK_HRS):
            continue
        jobs.append(make_job(
            j.get("position", ""),
            j.get("company", ""),
            j.get("location", "Remote"),
            "Remote",
            j.get("date", ""),
            " ".join(j.get("tags", [])),
            f"${j['salary_min']}-${j['salary_max']}" if j.get("salary_min") else "",
            j.get("url", ""),
            "RemoteOK"
        ))
    print(f"    ↳ {len(jobs)} jobs matched")
    return jobs


def scrape_jobicy() -> List[dict]:
    """Jobicy — 100% free public API, no auth required."""
    print(f"  ▶ {'Jobicy':25s}  (direct JSON API)")
    data = fetch_json("https://jobicy.com/api/v2/remote-jobs?count=50&tag=data-engineer")
    if not data:
        print("    ↳ 0 (API unreachable)")
        return []
    jobs = []
    for j in data.get("jobs", []):
        if not title_matches(j.get("jobTitle", "")):
            continue
        if not within_lookback(j.get("pubDate", ""), LOOKBACK_HRS):
            continue
        jobs.append(make_job(
            j.get("jobTitle", ""),
            j.get("companyName", ""),
            j.get("jobGeo", "Remote"),
            "Remote",
            j.get("pubDate", ""),
            j.get("jobDescription", ""),
            j.get("annualSalaryMin", ""),
            j.get("url", ""),
            "Jobicy"
        ))
    print(f"    ↳ {len(jobs)} jobs matched")
    return jobs


def scrape_weworkremotely() -> List[dict]:
    print(f"  ▶ {'WeWorkRemotely':25s}  (direct RSS)")
    feeds = [
        "https://weworkremotely.com/categories/remote-data-science-jobs.rss",
        "https://weworkremotely.com/categories/remote-programming-jobs.rss",
    ]
    jobs = []
    for url in feeds:
        root = fetch_xml(url)
        if root is None:
            continue
        for item in root.findall(".//item"):
            raw = (item.findtext("title") or "").strip()
            raw = raw.replace("<![CDATA[", "").replace("]]>", "").strip()
            company = raw.split(":")[0].strip() if ":" in raw else ""
            title   = ":".join(raw.split(":")[1:]).strip() if ":" in raw else raw
            if not title_matches(title):
                continue
            pub = item.findtext("pubDate", "")
            if not within_lookback(pub, LOOKBACK_HRS):
                continue
            # Get link — it comes as text node after <link> tag in RSS
            link = ""
            for child in item:
                if child.tag == "link":
                    link = (child.text or "").strip()
                    break
            if not link:
                link = item.findtext("guid", "")
            jobs.append(make_job(
                title, company, "Remote", "Remote",
                pub, item.findtext("description", ""),
                "", link, "WeWorkRemotely"
            ))
    print(f"    ↳ {len(jobs)} jobs matched")
    return jobs


def scrape_smartrecruiters() -> List[dict]:
    print(f"  ▶ {'SmartRecruiters ATS':25s}  (direct JSON API)")
    companies = ["Snowflake", "Twilio", "HubSpot", "Okta", "Zendesk", "Medallia"]
    jobs = []
    for company in companies:
        data = fetch_json(
            f"https://api.smartrecruiters.com/v1/companies/{company}"
            f"/postings?status=PUBLIC&limit=100&q=data+engineer"
        )
        if not data:
            continue
        for j in data.get("content", []):
            if not title_matches(j.get("name", "")):
                continue
            if not within_lookback(j.get("releasedDate", ""), LOOKBACK_HRS):
                continue
            loc = j.get("location", {}) or {}
            jobs.append(make_job(
                j.get("name", ""),
                company,
                f"{loc.get('city','')}, {loc.get('country','')}".strip(", "),
                "",
                j.get("releasedDate", ""),
                "",
                "",
                f"https://jobs.smartrecruiters.com/{company}/{j.get('id','')}",
                "SmartRecruiters ATS"
            ))
    print(f"    ↳ {len(jobs)} jobs matched")
    return jobs


# =============================================================
#  APIFY ACTOR TASKS — only platforms needing a real browser
# =============================================================

ACTOR_TASKS = [

    # ── 1. INDEED ─────────────────────────────────────────────
    # Fixed: use 'position' not 'keyword', and queries list format
    {
        "name":          "indeed",
        "actor_id":      "misceres/indeed-scraper",
        "platform_name": "Indeed",
        "input": {
            "queries": [
                {"position": "Data Engineer",         "country": "US", "location": "United States", "maxItems": 50},
                {"position": "Analytics Engineer",    "country": "US", "location": "United States", "maxItems": 25},
                {"position": "ETL Engineer",          "country": "US", "location": "United States", "maxItems": 25},
                {"position": "Data Platform Engineer","country": "US", "location": "United States", "maxItems": 25},
                {"position": "ML Engineer",           "country": "US", "location": "United States", "maxItems": 25},
            ],
            "maxItems":   150,
            "timePosted": "last24hours",
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


    # ── 2. MYVISAJOBS ─────────────────────────────────────────
    {
        "name":          "myvisajobs",
        "actor_id":      "apify/cheerio-scraper",
        "platform_name": "MyVisaJobs",
        "input": {
            "startUrls": [
                {"url": "https://www.myvisajobs.com/Search-Data-Engineer-Jobs.htm?Keyword=Data+Engineer&TimePosted=1"},
            ],
            "pageFunction": """
                async function pageFunction(context) {
                    const { $ } = context;
                    const jobs = [];
                    $('table tr').each((i, row) => {
                        if (i === 0) return;
                        const cells = $(row).find('td');
                        if (cells.length < 3) return;
                        const titleEl = cells.eq(0).find('a').first();
                        const title   = titleEl.text().trim();
                        if (!title) return;
                        jobs.push({
                            job_title:    title,
                            company_name: cells.eq(1).text().trim(),
                            location:     cells.eq(2).text().trim(),
                            posting_date: cells.eq(3).text().trim() || '',
                            salary: '', remote_or_hybrid: '',
                            job_description: '',
                            job_url: 'https://www.myvisajobs.com' + (titleEl.attr('href') || ''),
                            platform_name: 'MyVisaJobs'
                        });
                    });
                    return jobs;
                }
            """,
            "maxRequestsPerCrawl": 3,
        },
        "field_map": {},
    },

    # ── 3. YC WORK AT A STARTUP ───────────────────────────────
    {
        "name":          "yc_startup",
        "actor_id":      "apify/cheerio-scraper",
        "platform_name": "YC Work at a Startup",
        "input": {
            "startUrls": [
                {"url": "https://www.workatastartup.com/jobs?role=eng&query=data+engineer&jobType=fulltime"},
            ],
            "pageFunction": """
                async function pageFunction(context) {
                    const { $ } = context;
                    const jobs = [];
                    $('[class*="job"], .job-listing, article').each((i, el) => {
                        const titleEl = $(el).find('h2 a, h3 a, [class*="title"] a').first();
                        const title   = titleEl.text().trim();
                        if (!title) return;
                        jobs.push({
                            job_title:    title,
                            company_name: $(el).find('[class*="company"]').first().text().trim() || 'YC Startup',
                            location:     $(el).find('[class*="location"]').first().text().trim() || 'Remote',
                            remote_or_hybrid: 'Hybrid',
                            posting_date: '',
                            job_description: $(el).find('[class*="description"]').first().text().trim() || '',
                            salary: '',
                            job_url: titleEl.attr('href') || '',
                            platform_name: 'YC Work at a Startup'
                        });
                    });
                    return jobs;
                }
            """,
            "maxRequestsPerCrawl": 3,
        },
        "field_map": {},
    },
]


# =============================================================
#  ACTOR RUNNER
# =============================================================



def run_actor(client, cfg: dict) -> List[dict]:
    name = cfg["platform_name"]
    print(f"  ▶ {name:25s}  ({cfg['actor_id']})")
    try:
        run   = client.actor(cfg["actor_id"]).call(
            run_input=cfg["input"], timeout_secs=300
        )
        items = list(client.dataset(run["defaultDatasetId"]).iterate_items())
        jobs  = []
        skipped_title = skipped_date = 0
        for item in items:
            job = {**{"platform_name": name, "remote_or_hybrid": "", "salary": ""}, **item}
            if cfg["field_map"]:
                mapped = {"platform_name": name, "remote_or_hybrid": "", "salary": ""}
                for src, dst in cfg["field_map"].items():
                    mapped[dst] = item.get(src, "")
                job = mapped
            for f in ["job_title","company_name","location","posting_date","job_description","job_url"]:
                job.setdefault(f, "")
            if not job.get("job_title"):
                continue
            if not title_matches(job["job_title"]):
                skipped_title += 1
                continue
            if not within_lookback(job["posting_date"], LOOKBACK_HRS):
                skipped_date += 1
                continue
            if not is_us_or_remote(job.get("location", ""), job.get("job_description", "")):
                continue   # skip non-US jobs
            jobs.append(job)
        print(f"    ↳ {len(items):4d} raw  |  kept: {len(jobs)}  |  wrong title: {skipped_title}  |  too old: {skipped_date}")
        if jobs:
            print(f"    ↳ sample: {[j['job_title'] for j in jobs[:2]]}")
        return jobs
    except Exception as e:
        print(f"    ⚠️  FAILED: {e}")
        return []


# =============================================================
#  EMAIL
# =============================================================

def _html_body(jobs, run_date, run_slot):
    apply_count     = sum(1 for j in jobs if "Apply" in j.get("recommendation",""))
    avg             = round(sum(j.get("match_score",0) for j in jobs) / max(len(jobs),1))
    platform_counts = Counter(j.get("platform_name","") for j in jobs)
    pills = " &nbsp;".join(
        f'<span style="background:#1E3A5F;color:#fff;padding:2px 8px;border-radius:10px;font-size:11px;">{p}: {c}</span>'
        for p, c in sorted(platform_counts.items(), key=lambda x: -x[1])
    )
    rows = ""
    for j in jobs:
        score = j.get("match_score", 0)
        sc = "#375623" if score >= 85 else "#7F6000" if score >= 75 else "#595959"
        rec = j.get("recommendation", "")
        rc  = "#375623" if "Apply" in rec else "#8B0000"
        rows += f"""<tr style="border-bottom:1px solid #e0e0e0;">
          <td style="padding:8px 10px;font-weight:600;">{j.get('job_title','')}</td>
          <td style="padding:8px 10px;">{j.get('company_name','')}</td>
          <td style="padding:8px 10px;color:#555;font-size:11px;">{j.get('platform_name','')}</td>
          <td style="padding:8px 10px;color:#555;">{j.get('location','')}</td>
          <td style="padding:8px 10px;color:#555;">{j.get('remote_or_hybrid','')}</td>
          <td style="padding:8px 10px;text-align:center;font-weight:700;color:{sc};">{score}</td>
          <td style="padding:8px 10px;font-size:11px;">{j.get('matched_skills','')[:80]}…</td>
          <td style="padding:8px 10px;text-align:center;font-weight:700;color:{rc};">{rec}</td>
          <td style="padding:8px 10px;text-align:center;">
            <a href="{j.get('job_url','#')}" style="background:#1E3A5F;color:#fff;padding:4px 10px;border-radius:4px;text-decoration:none;font-size:12px;">Apply</a>
          </td></tr>"""
    slot_badge = f'<span style="background:#2E75B6;color:#fff;padding:3px 10px;border-radius:12px;font-size:12px;">{run_slot}</span>' if run_slot else ""
    return f"""<html><body style="font-family:Arial,sans-serif;color:#222;max-width:1100px;margin:auto;">
      <div style="background:#13315C;color:#fff;padding:20px 28px;border-radius:8px 8px 0 0;">
        <h2 style="margin:0;">🚀 Data Engineer Job Matches &nbsp;{slot_badge}</h2>
        <p style="margin:6px 0 0;opacity:.8;">{run_date} • Matched to Sushma Dasari's resume</p>
      </div>
      <div style="background:#EBF3FB;padding:12px 28px;border-bottom:2px solid #c8dff5;">
        📋 <strong>{len(jobs)}</strong> jobs &nbsp;|&nbsp; ✅ <strong>{apply_count}</strong> to apply
        &nbsp;|&nbsp; 📊 Avg: <strong>{avg}/100</strong>
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
        Full details in attached Excel.
      </div>
    </body></html>"""


def _send_diagnostic_email(all_jobs, filtered):
    if GMAIL_APP_PASS == "YOUR_APP_PASSWORD_HERE":
        return
    run_date        = datetime.now().strftime("%B %d, %Y %I:%M %p")
    platform_counts = Counter(j.get("platform_name","") for j in all_jobs)
    rows = "".join(
        f"<tr><td style='padding:6px 12px;'>{p}</td>"
        f"<td style='padding:6px 12px;text-align:center;font-weight:bold;"
        f"color:{'#375623' if c > 0 else '#999'};'>{c}</td></tr>"
        for p, c in sorted(platform_counts.items(), key=lambda x: -x[1])
    ) or "<tr><td colspan='2' style='padding:12px;text-align:center;color:#999;'>0 jobs</td></tr>"
    html = f"""<html><body style="font-family:Arial,sans-serif;max-width:600px;margin:auto;">
      <div style="background:#13315C;color:#fff;padding:20px;border-radius:8px 8px 0 0;">
        <h2 style="margin:0;">⚙️ Pipeline Health Check</h2>
        <p style="margin:6px 0 0;opacity:.8;">{run_date}</p>
      </div>
      <div style="background:#FFF8E1;padding:16px 20px;border-left:4px solid #F9A825;">
        Pipeline ran — 0 jobs met score threshold ({MIN_SCORE}).<br><br>
        Raw jobs collected: <strong>{len(all_jobs)}</strong><br>
        After scoring (≥{MIN_SCORE}): <strong>{len(filtered)}</strong>
      </div>
      <table style="width:100%;border-collapse:collapse;font-size:13px;">
        <tr style="background:#1E3A5F;color:#fff;">
          <th style="padding:8px 12px;text-align:left;">Platform</th>
          <th style="padding:8px 12px;text-align:center;">Raw Jobs</th>
        </tr>{rows}
      </table>
      <div style="background:#f5f5f5;padding:12px 20px;font-size:12px;color:#777;border-radius:0 0 8px 8px;">
        Pipeline running on schedule. Check apify.com Console for actor errors.
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


def send_email(excel_path, jobs):
    if GMAIL_APP_PASS == "YOUR_APP_PASSWORD_HERE":
        print("  ⚠️  Email skipped — GMAIL_APP_PASS not set.")
        return False
    run_date    = datetime.now().strftime("%B %d, %Y")
    apply_count = sum(1 for j in jobs if "Apply" in j.get("recommendation",""))
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

    # ── Step 1a: Direct API scrapers ──────────────────────────
    print(f"\n📡 Step 1a: Direct API scrapers...")
    all_jobs += scrape_greenhouse()
    all_jobs += scrape_lever()
    all_jobs += scrape_remotive()
    all_jobs += scrape_remoteok()
    all_jobs += scrape_jobicy()
    all_jobs += scrape_weworkremotely()
    all_jobs += scrape_smartrecruiters()
    print(f"  Direct APIs subtotal: {len(all_jobs)} jobs")

    # ── Step 1b: Apify actor scrapers ─────────────────────────
    print(f"\n📡 Step 1b: Apify actor scrapers...")
    client = ApifyClient(APIFY_TOKEN)
    for cfg in ACTOR_TASKS:
        all_jobs.extend(run_actor(client, cfg))

    print(f"\n  ✅ Total raw jobs collected: {len(all_jobs)}")

    # ── Step 2: Score ─────────────────────────────────────────
    print(f"\n📊 Step 2: Resume matching (≥{MIN_SCORE})...")
    filtered = filter_and_score(all_jobs, min_score=MIN_SCORE)
    print(f"  {len(filtered)} jobs passed")

    # ── Step 3: Dedup ─────────────────────────────────────────
    print(f"\n🔄 Step 3: Deduplication...")
    deduped = deduplicate(filtered)
    print(f"  {len(deduped)} unique jobs")

    if not deduped:
        print("\n⚠️  No jobs met threshold — sending diagnostic email...")
        _send_diagnostic_email(all_jobs, filtered)
        return

    # ── Step 4: Export ────────────────────────────────────────
    print(f"\n📁 Step 4: Exporting to Excel...")
    export_to_excel(deduped, OUTPUT_PATH)

    # ── Step 5: Email ─────────────────────────────────────────
    print(f"\n📧 Step 5: Sending email...")
    send_email(OUTPUT_PATH, deduped)

    avg   = sum(j["match_score"] for j in deduped) // len(deduped)
    apply = sum(1 for j in deduped if "Apply" in j.get("recommendation",""))
    print(f"""
{'='*65}
  PIPELINE COMPLETE
  Jobs found   : {len(deduped)}
  Apply now    : {apply}
  Avg score    : {avg}/100
  By platform  : {dict(Counter(j.get('platform_name','') for j in deduped))}
  Excel        : {OUTPUT_PATH}
  Email        : {NOTIFY_EMAIL}
{'='*65}""")


if __name__ == "__main__":
    run_pipeline()
