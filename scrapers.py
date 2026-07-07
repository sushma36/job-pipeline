"""
scrapers.py
===========
Rules:
  - Greenhouse / Lever : NO date filter. Their APIs return only currently
    open positions. We filter by created_at in post-processing.
  - Job boards (RemoteOK, WWR, Remotive, Jobicy): 24-hr filter.
  - Apify (Indeed, MyVisaJobs): 24-hr filter via actor param.
  - All sources: US-or-Remote location filter, DE title filter.

Each scraper prints one diagnostic line:
  source | raw | kept | skip_title | skip_loc | skip_age
"""

import re, time
import requests
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from typing import List, Optional

from dedup_utils import dedupe_jobs
from apify_config import PLATFORM_CONFIGS

# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/html, */*",
}

def _get(url: str, timeout: int = 20,
         params: dict = None) -> Optional[requests.Response]:
    for attempt in range(3):
        try:
            r = requests.get(url, headers=HEADERS, timeout=timeout, params=params)
            if r.status_code == 200:
                return r
            if r.status_code == 429:
                time.sleep(6 * (attempt + 1))
        except Exception:
            time.sleep(3)
    return None

# ---------------------------------------------------------------------------
# Date parsing — converts ANY timestamp format to UTC-aware datetime
# ---------------------------------------------------------------------------
def _parse_dt(raw) -> Optional[datetime]:
    """Parse any date string / epoch-ms / relative string → UTC datetime."""
    if not raw:
        return None
    raw = str(raw).strip()

    # epoch milliseconds (Lever uses this)
    if re.fullmatch(r"\d{13}", raw):
        try:
            return datetime.fromtimestamp(int(raw) / 1000, tz=timezone.utc)
        except Exception:
            pass

    # epoch seconds
    if re.fullmatch(r"\d{10}", raw):
        try:
            return datetime.fromtimestamp(int(raw), tz=timezone.utc)
        except Exception:
            pass

    # relative timestamps: "1 day ago", "2 hours ago", "Just posted", etc.
    rel = raw.lower()
    now = datetime.now(tz=timezone.utc)
    m = re.search(r"(\d+)\s*(second|minute|hour|day|week|month)", rel)
    if m:
        n, unit = int(m.group(1)), m.group(2)
        delta_map = {
            "second": timedelta(seconds=n),
            "minute": timedelta(minutes=n),
            "hour":   timedelta(hours=n),
            "day":    timedelta(days=n),
            "week":   timedelta(weeks=n),
            "month":  timedelta(days=n * 30),
        }
        return now - delta_map[unit]
    if any(w in rel for w in ("just posted", "today", "just now")):
        return now

    # ISO / RFC strings
    try:
        from dateutil import parser as dp
        dt = dp.parse(raw)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return None


def is_within_hours(raw_date, hours: int) -> bool:
    """
    Return True if the job was posted within `hours`.
    If date is missing/unparseable → True (keep the job).
    """
    if not raw_date:
        return True
    dt = _parse_dt(raw_date)
    if dt is None:
        return True
    now = datetime.now(tz=timezone.utc)
    return (now - dt) <= timedelta(hours=hours)


def fmt_date(raw) -> str:
    """Return ISO date string, or raw string if unparseable."""
    dt = _parse_dt(raw)
    return dt.strftime("%Y-%m-%d %H:%M UTC") if dt else str(raw or "")

# ---------------------------------------------------------------------------
# Title filter
# ---------------------------------------------------------------------------
_DE_TITLES = [
    "data engineer", "analytics engineer", "etl engineer", "etl developer",
    "data platform engineer", "big data engineer", "cloud data engineer",
    "data infrastructure engineer", "data pipeline engineer",
    "data warehouse engineer",
]
_DISQUALIFY = [
    "phd", "research scientist", "data scientist",
    "machine learning engineer", "ml engineer",
    "software engineer", "frontend", "backend",
    "security engineer", "devops", "site reliability",
    "product manager", "data analyst", "business intelligence",
    "ai engineer", "research engineer", "deep learning",
    "computer vision", "nlp engineer",
]

def _title_ok(title: str) -> bool:
    t = title.lower()
    return (any(kw in t for kw in _DE_TITLES) and
            not any(dq in t for dq in _DISQUALIFY))

# ---------------------------------------------------------------------------
# Location filter — US or Remote allowlist
# ---------------------------------------------------------------------------
_REMOTE = [
    "remote", "us only", "usa only", "north america",
   "flexible", "united states", "u.s.a",
]
_STATES = [
    "alabama","alaska","arizona","arkansas","california","colorado",
    "connecticut","delaware","florida","georgia","hawaii","idaho",
    "illinois","indiana","iowa","kansas","kentucky","louisiana","maine",
    "maryland","massachusetts","michigan","minnesota","mississippi",
    "missouri","montana","nebraska","nevada","new hampshire","new jersey",
    "new mexico","new york","north carolina","north dakota","ohio",
    "oklahoma","oregon","pennsylvania","rhode island","south carolina",
    "south dakota","tennessee","texas","utah","vermont","virginia",
    "washington","west virginia","wisconsin","wyoming","district of columbia",
]
_ABBREVS = {
    "al","ak","az","ar","ca","co","ct","de","fl","ga","hi","id","il",
    "in","ia","ks","ky","la","me","md","ma","mi","mn","ms","mo","mt",
    "ne","nv","nh","nj","nm","ny","nc","nd","oh","ok","or","pa","ri",
    "sc","sd","tn","tx","ut","vt","va","wa","wv","wi","wy","dc",
}
_CITIES = [
    "new york","san francisco","seattle","chicago","boston","austin",
    "denver","atlanta","los angeles","washington","portland","miami",
    "dallas","houston","minneapolis","philadelphia","phoenix","san diego",
    "raleigh","nashville","salt lake","detroit","baltimore","san jose",
    "charlotte","indianapolis","columbus","memphis","louisville",
    "richmond","hartford","pittsburgh","cincinnati","kansas city",
    "new orleans","las vegas","tampa","orlando","jacksonville",
    "san antonio","fort worth","tucson","fresno","sacramento",
]

def _loc_ok(location: str) -> bool:
    if not location or not location.strip():
        return True          # blank = remote / not specified → keep
    loc = location.lower().strip()
    if any(sig in loc for sig in _REMOTE):
        return True
    if ", usa" in loc or " usa" in loc:
        return True
    if any(s in loc for s in _STATES):
        return True
    tokens = set(re.split(r"[\s,./\-]+", loc))
    if tokens & _ABBREVS:
        return True
    if any(c in loc for c in _CITIES):
        return True
    return False

# ---------------------------------------------------------------------------
# Job dict factory
# ---------------------------------------------------------------------------
def _job(title, company, location, remote, date_raw,
         description, salary, url, platform):
    return {
        "job_title":        (title       or "").strip(),
        "company_name":     (company     or "").strip(),
        "location":         (location    or "").strip(),
        "remote_or_hybrid": (remote      or "").strip(),
        "posting_date":     fmt_date(date_raw),
        "job_description":  (description or "").strip(),
        "salary":           (salary      or "").strip(),
        "job_url":          (url         or "").strip(),
        "platform_name":    platform,
    }

# ---------------------------------------------------------------------------
# ATS company lists
# ---------------------------------------------------------------------------
GREENHOUSE_COMPANIES = [
    # Data tooling — highest DE job density
    "databricks","dbt-labs","fivetran","airbyte","astronomer",
    "hightouch","census","anomalo","monte-carlo","rudderstack",
    "lightdash","datafold","preset","cube-dev",
    # Tech companies with large data teams
    "stripe","airbnb","doordash","coinbase","notion","figma",
    "plaid","brex","chime","gusto","rippling","robinhood",
    "scale-ai","datadog","cloudflare","retool","benchling",
    "lyft","reddit","duolingo","discord","hubspot","zendesk",
    "okta","elastic","airtable","zapier","segment","amplitude",
    "mixpanel","heap",
    # Healthcare — Sushma's domain
    "tempus","flatiron","veeva","commure",
    # Fintech
    "carta","faire",
]

LEVER_COMPANIES = [
    "confluent","starburst","clickhouse","benchling","samsara",
    "podium","gladly","cohere","weights-biases","imply","acryl-data",
    "atlan","hex","getcensus","tinybird","motherduck",
]

ASHBY_COMPANIES = [
    # Data/infra-heavy companies known to use Ashby
    "ramp","notion","linear","vanta","replit","cursor","deel",
    "harvey","modern-treasury","retool","substack","webflow",
    "openai","perplexity-ai","mercury","brex",
]


# ===========================================================================
# SCRAPER 1 — GREENHOUSE  (no date filter — API returns only open jobs)
# ===========================================================================
def scrape_greenhouse(hours: int = 24) -> List[dict]:
    name = "Greenhouse ATS"
    print(f"  ▶ {name} ({len(GREENHOUSE_COMPANIES)} companies)...")
    results = []
    raw = kept = skip_title = skip_loc = skip_age = 0

    for company in GREENHOUSE_COMPANIES:
        r = _get(
            f"https://boards-api.greenhouse.io/v1/boards/{company}"
            f"/jobs?content=true", timeout=15
        )
        if not r:
            continue
        try:
            data = r.json()
        except Exception:
            continue

        for j in data.get("jobs", []):
            raw += 1
            if not _title_ok(j.get("title", "")):
                skip_title += 1
                continue
            loc = (j.get("location") or {}).get("name", "")
            if not _loc_ok(loc):
                skip_loc += 1
                continue
            # Use created_at for recency — updated_at changes on edits
            date_raw = j.get("created_at") or j.get("updated_at") or ""
            if not is_within_hours(date_raw, hours):
                skip_age += 1
                continue
            kept += 1
            results.append(_job(
                j.get("title",""),
                company.replace("-"," ").title(),
                loc,
                "Remote" if "remote" in loc.lower() else "Hybrid",
                date_raw,
                j.get("content",""), "",
                j.get("absolute_url",""),
                name,
            ))

    print(f"    {name:22s} | raw={raw:4d} | kept={kept:3d} | "
          f"skip_title={skip_title:4d} | skip_loc={skip_loc:3d} | skip_age={skip_age:3d}")
    return results


# ===========================================================================
# SCRAPER 2 — LEVER  (no date filter — API returns only open jobs)
# ===========================================================================
def scrape_lever(hours: int = 24) -> List[dict]:
    name = "Lever ATS"
    print(f"  ▶ {name} ({len(LEVER_COMPANIES)} companies)...")
    results = []
    raw = kept = skip_title = skip_loc = skip_age = 0

    for company in LEVER_COMPANIES:
        r = _get(f"https://api.lever.co/v0/postings/{company}?mode=json",
                 timeout=15)
        if not r:
            continue
        try:
            data = r.json()
            if not isinstance(data, list):
                continue
        except Exception:
            continue

        for j in data:
            raw += 1
            if not _title_ok(j.get("text", "")):
                skip_title += 1
                continue
            loc = (j.get("categories") or {}).get("location", "") or ""
            if not _loc_ok(loc):
                skip_loc += 1
                continue
            # createdAt is epoch-ms
            date_raw = j.get("createdAt", "")
            if not is_within_hours(date_raw, hours):
                skip_age += 1
                continue
            kept += 1
            results.append(_job(
                j.get("text",""),
                company.title(),
                loc,
                j.get("workplaceType",""),
                date_raw,
                j.get("descriptionPlain",""), "",
                j.get("hostedUrl",""),
                name,
            ))

    print(f"    {name:22s} | raw={raw:4d} | kept={kept:3d} | "
          f"skip_title={skip_title:4d} | skip_loc={skip_loc:3d} | skip_age={skip_age:3d}")
    return results


# ===========================================================================
# SCRAPER 2B — ASHBY  (no date filter — API returns only open jobs)
# Uses Ashby's genuinely public, no-auth REST API — no Apify actor needed.
# https://api.ashbyhq.com/posting-api/job-board/{slug}
# ===========================================================================
def scrape_ashby(hours: int = 24) -> List[dict]:
    name = "Ashby ATS"
    print(f"  ▶ {name} ({len(ASHBY_COMPANIES)} companies)...")
    results = []
    raw = kept = skip_title = skip_loc = skip_age = 0

    for company in ASHBY_COMPANIES:
        r = _get(
            f"https://api.ashbyhq.com/posting-api/job-board/{company}",
            timeout=15, params={"includeCompensation": "true"},
        )
        if not r:
            continue
        try:
            data = r.json()
            jobs = data.get("jobs", [])
        except Exception:
            continue

        for j in jobs:
            if not j.get("isListed", True):
                continue  # unlisted/draft — never surface these
            raw += 1
            title = j.get("title", "")
            if not _title_ok(title):
                skip_title += 1
                continue
            loc = j.get("location", "")
            if not _loc_ok(loc) and not j.get("isRemote"):
                skip_loc += 1
                continue
            date_raw = j.get("publishedAt", "")
            if not is_within_hours(date_raw, hours):
                skip_age += 1
                continue
            kept += 1
            comp = j.get("compensation", {}) or {}
            results.append(_job(
                title,
                company.replace("-", " ").title(),
                loc,
                j.get("workplaceType", "Remote" if j.get("isRemote") else ""),
                date_raw,
                j.get("descriptionPlain", ""),
                comp.get("compensationTierSummary", ""),
                j.get("jobUrl", ""),
                name,
            ))

    print(f"    {name:22s} | raw={raw:4d} | kept={kept:3d} | "
          f"skip_title={skip_title:4d} | skip_loc={skip_loc:3d} | skip_age={skip_age:3d}")
    return results


# ===========================================================================
# SCRAPER 3 — REMOTEOK  (24-hr filter)
# ===========================================================================
def scrape_remoteok(hours: int = 24) -> List[dict]:
    name = "RemoteOK"
    print(f"  ▶ {name}...")
    tags = ["data-engineer", "analytics", "sql", "python", "spark", "airflow"]
    seen: set = set()
    results = []
    raw = kept = skip_title = skip_age = 0

    for tag in tags:
        r = _get(f"https://remoteok.com/api?tag={tag}", timeout=20)
        if not r:
            continue
        try:
            data = r.json()
        except Exception:
            continue
        for j in data:
            if not isinstance(j, dict) or not j.get("position"):
                continue
            raw += 1
            if not _title_ok(j.get("position", "")):
                skip_title += 1
                continue
            if not is_within_hours(j.get("date", ""), hours):
                skip_age += 1
                continue
            url = j.get("url", "")
            if not url.startswith("http"):
                url = f"https://remoteok.com{url}"
            if url in seen:
                continue
            seen.add(url)
            kept += 1
            sal = (f"${j['salary_min']}-${j['salary_max']}"
                   if j.get("salary_min") else "")
            results.append(_job(
                j.get("position",""), j.get("company",""),
                j.get("location","Remote"), "Remote",
                j.get("date",""),
                " ".join(j.get("tags",[])),
                sal, url, name,
            ))
        time.sleep(1)

    print(f"    {name:22s} | raw={raw:4d} | kept={kept:3d} | "
          f"skip_title={skip_title:4d} | skip_age={skip_age:3d}")
    return results


# ===========================================================================
# SCRAPER 4 — WEWORKREMOTELY  (24-hr filter)
# ===========================================================================
def scrape_weworkremotely(hours: int = 24) -> List[dict]:
    name = "WeWorkRemotely"
    print(f"  ▶ {name}...")
    feeds = [
        "https://weworkremotely.com/categories/remote-data-science-jobs.rss",
        "https://weworkremotely.com/categories/remote-programming-jobs.rss",
        "https://weworkremotely.com/categories/remote-devops-sysadmin-jobs.rss",
    ]
    results = []
    raw = kept = skip_title = skip_age = 0

    for feed_url in feeds:
        r = _get(feed_url, timeout=15)
        if not r:
            continue
        try:
            root = ET.fromstring(r.content)
        except ET.ParseError:
            continue
        for item in root.findall(".//item"):
            raw += 1
            raw_title = re.sub(r"<!\[CDATA\[|\]\]>",
                               "", item.findtext("title") or "").strip()
            company = raw_title.split(":")[0].strip() if ":" in raw_title else ""
            title   = ":".join(raw_title.split(":")[1:]).strip() if ":" in raw_title else raw_title
            if not _title_ok(title):
                skip_title += 1
                continue
            pub = item.findtext("pubDate", "")
            if not is_within_hours(pub, hours):
                skip_age += 1
                continue
            link = ""
            for child in item:
                if child.tag == "link":
                    link = (child.text or "").strip()
                    break
            if not link:
                link = item.findtext("guid", "")
            desc = re.sub(r"<[^>]+>", "", item.findtext("description",""))
            kept += 1
            results.append(_job(title, company, "Remote", "Remote",
                                pub, desc, "", link, name))

    print(f"    {name:22s} | raw={raw:4d} | kept={kept:3d} | "
          f"skip_title={skip_title:4d} | skip_age={skip_age:3d}")
    return results


# ===========================================================================
# SCRAPER 5 — REMOTIVE  (24-hr filter, two categories)
# ===========================================================================
def scrape_remotive(hours: int = 24) -> List[dict]:
    name = "Remotive"
    print(f"  ▶ {name}...")
    urls = [
        "https://remotive.com/api/remote-jobs?category=data&limit=100",
        "https://remotive.com/api/remote-jobs?category=software-dev&limit=100",
    ]
    seen: set = set()
    results = []
    raw = kept = skip_title = skip_age = skip_loc = 0

    for url in urls:
        r = _get(url, timeout=20)
        if not r:
            continue
        try:
            jobs = r.json().get("jobs", [])
        except Exception:
            continue
        for j in jobs:
            raw += 1
            if not _title_ok(j.get("title", "")):
                skip_title += 1
                continue
            if not is_within_hours(j.get("publication_date", ""), hours):
                skip_age += 1
                continue
            loc = j.get("candidate_required_location", "Remote") or "Remote"
            if not _loc_ok(loc):
                skip_loc += 1
                continue
            job_url = j.get("url", "")
            if job_url in seen:
                continue
            seen.add(job_url)
            kept += 1
            results.append(_job(
                j.get("title",""), j.get("company_name",""),
                loc, "Remote",
                j.get("publication_date",""),
                j.get("description",""),
                j.get("salary",""),
                job_url, name,
            ))

    print(f"    {name:22s} | raw={raw:4d} | kept={kept:3d} | "
          f"skip_title={skip_title:4d} | skip_age={skip_age:3d} | skip_loc={skip_loc:3d}")
    return results


# ===========================================================================
# SCRAPER 6 — JOBICY  (24-hr filter, multiple tags)
# ===========================================================================
def scrape_jobicy(hours: int = 24) -> List[dict]:
    name = "Jobicy"
    print(f"  ▶ {name}...")
    tags = ["data-engineer", "data", "python", "sql", "analytics"]
    seen: set = set()
    results = []
    raw = kept = skip_title = skip_age = skip_loc = 0

    for tag in tags:
        r = _get(f"https://jobicy.com/api/v2/remote-jobs?count=50&tag={tag}",
                 timeout=20)
        if not r:
            continue
        try:
            jobs = r.json().get("jobs", [])
        except Exception:
            continue
        for j in jobs:
            raw += 1
            if not _title_ok(j.get("jobTitle", "")):
                skip_title += 1
                continue
            if not is_within_hours(j.get("pubDate", ""), hours):
                skip_age += 1
                continue
            loc = j.get("jobGeo", "Remote") or "Remote"
            if not _loc_ok(loc):
                skip_loc += 1
                continue
            url = j.get("url", "")
            if url in seen:
                continue
            seen.add(url)
            kept += 1
            results.append(_job(
                j.get("jobTitle",""), j.get("companyName",""),
                loc, "Remote",
                j.get("pubDate",""),
                j.get("jobDescription",""),
                str(j.get("annualSalaryMin","")),
                url, name,
            ))

    print(f"    {name:22s} | raw={raw:4d} | kept={kept:3d} | "
          f"skip_title={skip_title:4d} | skip_age={skip_age:3d} | skip_loc={skip_loc:3d}")
    return results


# ===========================================================================
# SCRAPER 7 — INDEED via Apify  (24-hr via actor param)
# ===========================================================================
def scrape_indeed(client, hours: int = 24) -> List[dict]:
    name = "Indeed"
    print(f"  ▶ {name} (Apify actor)...")
    try:
        run = client.actor("misceres/indeed-scraper").call(
            run_input={
                "queries": [
                    {"position": "Data Engineer",
                     "country": "US", "location": "United States", "maxItems": 50},
                    {"position": "Analytics Engineer",
                     "country": "US", "location": "United States", "maxItems": 30},
                    {"position": "ETL Engineer",
                     "country": "US", "location": "United States", "maxItems": 25},
                    {"position": "Data Platform Engineer",
                     "country": "US", "location": "United States", "maxItems": 25},
                ],
                "maxItems":   130,
                "timePosted": "last24hours",
            },
            timeout_secs=300,
        )
        items = list(client.dataset(run["defaultDatasetId"]).iterate_items())
        results = []
        raw = len(items)
        kept = skip_title = skip_loc = skip_age = 0
        for item in items:
            if not _title_ok(item.get("title", "")):
                skip_title += 1
                continue
            loc = item.get("location", "")
            if not _loc_ok(loc):
                skip_loc += 1
                continue
            if not is_within_hours(item.get("postedAt",""), hours):
                skip_age += 1
                continue
            kept += 1
            results.append(_job(
                item.get("title",""), item.get("company",""),
                loc, "",
                item.get("postedAt",""),
                item.get("description",""),
                item.get("salary",""),
                item.get("url",""),
                name,
            ))
        print(f"    {name:22s} | raw={raw:4d} | kept={kept:3d} | "
              f"skip_title={skip_title:4d} | skip_loc={skip_loc:3d} | skip_age={skip_age:3d}")
        return results
    except Exception as e:
        print(f"    {name:22s} | ⚠️  FAILED: {e}")
        return []


# ===========================================================================
# SCRAPER 8 — LINKEDIN via Apify  (24-hr filter; needs LINKEDIN_COOKIE)
# ===========================================================================
def scrape_linkedin(client, li_at_cookie: str = "", hours: int = 24) -> List[dict]:
    # FIXED 2026-07-06: the actor curious_coder/linkedin-jobs-scraper is real,
    # but the previous input (searchQueries/cookie/postedAt fields) does not
    # match its actual schema at all. This actor scrapes LinkedIn's PUBLIC job
    # search and takes pre-built LinkedIn search URLs as input -- it doesn't
    # even use a cookie (that's a different, paid actor:
    # curious_coder/linkedin-jobs-search-scraper, $30/mo, for boolean search).
    # li_at_cookie is accepted for interface compatibility with run_pipeline.py
    # but currently unused by this actor -- kept as a param in case we switch
    # to the advanced/paid actor later.
    name = "LinkedIn"
    print(f"  ▶ {name} (Apify actor)...")
    date_filter = "r86400" if hours <= 24 else "r259200"  # seconds: 24h vs 72h
    search_urls = [
        f"https://www.linkedin.com/jobs/search/?keywords={kw.replace(' ', '%20')}"
        f"&location=United%20States&f_TPR={date_filter}&f_WT=2"  # f_WT=2 = remote
        for kw in ("Data Engineer", "Senior Data Engineer",
                   "Analytics Engineer", "ETL Engineer")
    ]
    try:
        run = client.actor("curious_coder/linkedin-jobs-scraper").call(
            run_input={"urls": search_urls, "count": 50},
            timeout_secs=300,
        )
        items = list(client.dataset(run["defaultDatasetId"]).iterate_items())
        results = []
        raw = len(items)
        kept = skip_title = skip_loc = skip_age = 0
        for item in items:
            title = item.get("title", "")
            if not _title_ok(title):
                skip_title += 1
                continue
            loc = item.get("location", "")
            if not _loc_ok(loc):
                skip_loc += 1
                continue
            if not is_within_hours(item.get("postedAt", "") or item.get("listedAt", ""), hours):
                skip_age += 1
                continue
            kept += 1
            results.append(_job(
                title, item.get("company", "") or item.get("companyName", ""),
                loc, item.get("workplaceType", ""),
                item.get("postedAt", "") or item.get("listedAt", ""),
                item.get("description", "") or item.get("descriptionText", ""),
                item.get("salary", ""),
                item.get("link", "") or item.get("jobUrl", ""),
                name,
            ))
        print(f"    {name:22s} | raw={raw:4d} | kept={kept:3d} | "
              f"skip_title={skip_title:4d} | skip_loc={skip_loc:3d} | skip_age={skip_age:3d}")
        return results
    except Exception as e:
        print(f"    {name:22s} | ⚠️  FAILED: {e}")
        return []


# ===========================================================================
# SCRAPER 9 — BUILT IN via Apify  (tech/startup-focused board, 24-hr filter)
# ===========================================================================
def scrape_builtin(client, hours: int = 24) -> List[dict]:
    name = "Built In"
    print(f"  ▶ {name} (Apify actor)...")
    try:
        # FIXED 2026-07-06: previous input used "searchUrls"/"maxItems", which
        # are NOT real fields on solidcode/builtin-scraper -- confirmed real
        # schema is searchQueries/location/remoteMode/maxResultsPerQuery/
        # fetchDescription. The wrong field names meant this actor was either
        # rejecting the input outright or silently falling back to defaults
        # and scraping something we never asked for.
        run = client.actor("solidcode/builtin-scraper").call(
            run_input={
                "searchQueries": ["data engineer", "analytics engineer"],
                "location": "",
                "remoteMode": "any",
                "postedWithinDays": 1 if hours <= 24 else 3,
                "maxResultsPerQuery": 100,
                "fetchDescription": True,
            },
            timeout_secs=180,
        )
        items = list(client.dataset(run["defaultDatasetId"]).iterate_items())
        results = []
        raw = len(items)
        kept = skip_title = skip_loc = skip_age = 0
        for item in items:
            title = item.get("title", "") or item.get("job_title", "")
            if not _title_ok(title):
                skip_title += 1
                continue
            loc = item.get("location", "")
            if not _loc_ok(loc):
                skip_loc += 1
                continue
            posted = item.get("postedAt", "") or item.get("date", "")
            if not is_within_hours(posted, hours):
                skip_age += 1
                continue
            kept += 1
            results.append(_job(
                title, item.get("company", "") or item.get("companyName", ""),
                loc, item.get("remote", ""),
                posted,
                item.get("description", ""),
                item.get("salary", ""),
                item.get("url", ""),
                name,
            ))
        print(f"    {name:22s} | raw={raw:4d} | kept={kept:3d} | "
              f"skip_title={skip_title:4d} | skip_loc={skip_loc:3d} | skip_age={skip_age:3d}")
        return results
    except Exception as e:
        print(f"    {name:22s} | ⚠️  FAILED: {e}")
        return []


# ===========================================================================
# SCRAPERS 11-16 — sites driven off apify_config.PLATFORM_CONFIGS
# (Wellfound, SimplyHired, Jooble, YC Work at a Startup, Handshake, Otta)
#
# Wellfound + YC Startup use dedicated, actively-maintained Apify actors —
# reasonably reliable.
# SimplyHired, Jooble, Handshake, Otta use the generic "apify/web-scraper"
# actor with hand-written CSS selectors against live site HTML — these WILL
# break whenever those sites change their markup, and Handshake/Otta also
# need headless Chrome + may be login-gated. Each is wrapped in try/except
# so a broken selector fails that one source, not the whole run.
# ===========================================================================
def scrape_via_config(client, config_key: str, hours: int = 24,
                       timeout_secs: int = 180) -> List[dict]:
    cfg = PLATFORM_CONFIGS.get(config_key)
    if not cfg:
        return []
    name = cfg.get("platform_name", config_key)
    print(f"  ▶ {name} (Apify actor)...")
    try:
        run = client.actor(cfg["actor"]).call(
            run_input=cfg["input"], timeout_secs=timeout_secs
        )
        items = list(client.dataset(run["defaultDatasetId"]).iterate_items())
        field_map = cfg.get("field_map")  # None => item keys already match our schema

        results = []
        raw = len(items)
        kept = skip_title = skip_loc = skip_age = 0
        for item in items:
            mapped = ({k: item.get(v, "") for k, v in field_map.items()}
                      if field_map else item)
            title = mapped.get("job_title", "")
            if not _title_ok(title):
                skip_title += 1
                continue
            loc = mapped.get("location", "")
            if not _loc_ok(loc):
                skip_loc += 1
                continue
            if not is_within_hours(mapped.get("posting_date", ""), hours):
                skip_age += 1
                continue
            kept += 1
            results.append(_job(
                title, mapped.get("company_name", ""),
                loc, mapped.get("remote_or_hybrid", ""),
                mapped.get("posting_date", ""),
                mapped.get("job_description", ""),
                mapped.get("salary", ""),
                mapped.get("job_url", ""),
                name,
            ))
        print(f"    {name:22s} | raw={raw:4d} | kept={kept:3d} | "
              f"skip_title={skip_title:4d} | skip_loc={skip_loc:3d} | skip_age={skip_age:3d}")
        return results
    except Exception as e:
        print(f"    {name:22s} | ⚠️  FAILED (site/selectors may have changed): {e}")
        return []


# ===========================================================================
# SCRAPER 17 — MYVISAJOBS via Apify  (H1B sponsors, 24-hr URL filter)
# ===========================================================================
def scrape_myvisajobs(client) -> List[dict]:
    name = "MyVisaJobs"
    print(f"  ▶ {name} (Apify — H1B sponsors)...")
    try:
        run = client.actor("apify/cheerio-scraper").call(
            run_input={
                "startUrls": [
                    {"url": "https://www.myvisajobs.com/Search-Data-Engineer-Jobs.htm"
                             "?Keyword=Data+Engineer&TimePosted=1"},
                    {"url": "https://www.myvisajobs.com/Search-Data-Engineer-Jobs.htm"
                             "?Keyword=Analytics+Engineer&TimePosted=1"},
                    {"url": "https://www.myvisajobs.com/Search-Data-Engineer-Jobs.htm"
                             "?Keyword=ETL+Engineer&TimePosted=1"},
                ],
                "pageFunction": """
                    async function pageFunction(context) {
                        const { $ } = context;
                        const jobs = [];
                        $('table tr').each((i, row) => {
                            const cells = $(row).find('td');
                            if (cells.length < 2) return;
                            const a = $(row).find('a[href]').first();
                            const title = a.text().trim();
                            if (!title || title.length < 5) return;
                            const href = a.attr('href') || '';
                            jobs.push({
                                job_title:       title,
                                company_name:    cells.eq(1).text().trim(),
                                location:        cells.length > 2 ? cells.eq(2).text().trim() : 'United States',
                                posting_date:    cells.length > 3 ? cells.eq(3).text().trim() : '',
                                remote_or_hybrid:'',
                                salary:          '',
                                job_description: 'H1B Visa Sponsorship Available',
                                job_url: href.startsWith('http') ? href : 'https://www.myvisajobs.com' + href,
                                platform_name:   'MyVisaJobs'
                            });
                        });
                        return jobs;
                    }
                """,
                "maxRequestsPerCrawl": 6,
            },
            timeout_secs=120,
        )
        items = list(client.dataset(run["defaultDatasetId"]).iterate_items())
        results = []
        raw = len(items)
        kept = skip_title = 0
        for item in items:
            if not _title_ok(item.get("job_title", "")):
                skip_title += 1
                continue
            item["platform_name"]    = name
            item["job_description"]  = "✅ H1B Visa Sponsorship Available"
            item.setdefault("remote_or_hybrid", "")
            item.setdefault("salary", "")
            item.setdefault("match_score", 0)
            kept += 1
            results.append(item)
        print(f"    {name:22s} | raw={raw:4d} | kept={kept:3d} | "
              f"skip_title={skip_title:4d}")
        return results
    except Exception as e:
        print(f"    {name:22s} | ⚠️  FAILED: {e}")
        return []


# ===========================================================================
# MASTER FUNCTION
# ===========================================================================
# ===========================================================================
# SOURCE-LEVEL STATS — tracks each source's yield so a source silently
# returning 0 for days (e.g. broken actor, expired token) is visible in the
# email report instead of only in GitHub Actions logs nobody checks daily.
# ===========================================================================
_SOURCE_STATS: List[tuple] = []  # (name, count)


def _track(name: str, fn) -> List[dict]:
    try:
        result = fn()
    except Exception as e:
        print(f"    {name:22s} | ⚠️  UNCAUGHT EXCEPTION: {e}")
        result = []
    _SOURCE_STATS.append((name, len(result)))
    return result


def get_source_stats() -> List[tuple]:
    return list(_SOURCE_STATS)


def run_all_scrapers(apify_client, hours: int = 24, linkedin_cookie: str = "") -> List[dict]:
    """
    Scrape all sources. hours=24 by default (per requirements).
    If total unique jobs < 10, caller should re-invoke with hours=72.
    """
    _SOURCE_STATS.clear()
    all_jobs: List[dict] = []

    print(f"\n{'─'*60}")
    print(f"  SCRAPING — window: {hours}hr | US+Remote only | DE titles only")
    print(f"{'─'*60}")
    print(f"  {'Source':22s} | {'raw':>4} | {'kept':>4} | details")
    print(f"  {'─'*22}─┼─{'─'*5}─┼─{'─'*5}─┼─{'─'*20}")

    # ATS — no date filter (API = open jobs only; we apply created_at filter)
    all_jobs += _track("Greenhouse", lambda: scrape_greenhouse(hours))
    all_jobs += _track("Lever", lambda: scrape_lever(hours))
    all_jobs += _track("Ashby ATS", lambda: scrape_ashby(hours))

    # Job boards — 24-hr filter
    all_jobs += _track("RemoteOK", lambda: scrape_remoteok(hours))
    all_jobs += _track("WeWorkRemotely", lambda: scrape_weworkremotely(hours))
    all_jobs += _track("Remotive", lambda: scrape_remotive(hours))
    all_jobs += _track("Jobicy", lambda: scrape_jobicy(hours))

    # Apify actors — 24-hr filter
    if apify_client:
        all_jobs += _track("Indeed", lambda: scrape_indeed(apify_client, hours))
        all_jobs += _track("MyVisaJobs", lambda: scrape_myvisajobs(apify_client))
        all_jobs += _track("LinkedIn", lambda: scrape_linkedin(apify_client, linkedin_cookie, hours))
        all_jobs += _track("Built In", lambda: scrape_builtin(apify_client, hours))

        # Previously configured but never wired in
        all_jobs += _track("Wellfound", lambda: scrape_via_config(apify_client, "wellfound", hours))
        all_jobs += _track("YC Startup", lambda: scrape_via_config(apify_client, "yc_startup", hours))
        all_jobs += _track("SimplyHired", lambda: scrape_via_config(apify_client, "simplyhired", hours))
        all_jobs += _track("Jooble", lambda: scrape_via_config(apify_client, "jooble", hours))
        all_jobs += _track("Handshake", lambda: scrape_via_config(apify_client, "handshake", hours))
        all_jobs += _track("Otta", lambda: scrape_via_config(apify_client, "otta", hours))
        all_jobs += _track("Remote Rocketship", lambda: scrape_via_config(apify_client, "remote_rocketship", hours))
        all_jobs += _track("Google Jobs", lambda: scrape_via_config(apify_client, "google_jobs", hours))

    # Print a "sources returning zero" summary right in the log, and it also
    # gets pulled into the email body by run_pipeline.py via get_source_stats()
    zero_sources = [n for n, c in _SOURCE_STATS if c == 0]
    if zero_sources:
        print(f"\n  ⚠️  {len(zero_sources)}/{len(_SOURCE_STATS)} sources returned "
              f"ZERO jobs this run: {', '.join(zero_sources)}")

    # Deduplicate: exact URL match, then fuzzy company+title match
    # (catches "Sr. Data Engineer" vs "Senior Data Engineer II - Remote"
    # showing up as separate rows from different boards)
    before = len(all_jobs)
    unique = dedupe_jobs(all_jobs)
    print(f"\n  🔄 Dedup: {before} raw → {len(unique)} unique "
          f"({before - len(unique)} duplicates removed)")

    return unique
