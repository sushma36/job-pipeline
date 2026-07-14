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
from bs4 import BeautifulSoup

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

def _title_ok(title) -> bool:
    t = _safe_str(title).lower()
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

def _loc_ok(location) -> bool:
    location = _safe_str(location)
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
def _safe_str(v) -> str:
    """Coerce any value to a safe string. Exists because some Apify actors
    return booleans for fields we treat as text (e.g. Wellfound's 'remote'
    field is a real Python bool, not a string) -- (v or "").strip() crashes
    on True specifically, since True is truthy so 'or' returns the bool
    itself, not the fallback empty string. Confirmed via the exact runtime
    error: 'bool' object has no attribute 'strip'."""
    if v is None:
        return ""
    if isinstance(v, bool):
        return "Remote" if v else ""
    return str(v)


def _job(title, company, location, remote, date_raw,
         description, salary, url, platform):
    return {
        "job_title":        _safe_str(title).strip(),
        "company_name":     _safe_str(company).strip(),
        "location":         _safe_str(location).strip(),
        "remote_or_hybrid": _safe_str(remote).strip(),
        "posting_date":     fmt_date(date_raw),
        "job_description":  _safe_str(description).strip(),
        "salary":           _safe_str(salary).strip(),
        "job_url":          _safe_str(url).strip(),
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
        # FIXED 2026-07-13 (again): the "keyword" field name came from Apify's
        # docs page, but the actual runtime log proved that's wrong too --
        # "Running site crawl country US, position undefined, location
        # United States" shows the actor checking for a field literally
        # named "position" at the top level, not "keyword". Docs vs. real
        # deployed behavior mismatch, same pattern as the run_timeout/
        # timeout_secs issue earlier. Trusting the runtime log over the docs.
        run = client.actor("misceres/indeed-scraper").call(
            run_input={
                "position": "Data Engineer",
                "country":  "US",
                "location": "United States",
                "maxItems": 100,
            },
            run_timeout=timedelta(seconds=300),
        )
        if run is None:
            raise RuntimeError("Actor run returned None (run may have failed or been aborted)")
        items = list(client.dataset(run.default_dataset_id).iterate_items())
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
def scrape_linkedin(client=None, li_at_cookie: str = "", hours: int = 24) -> List[dict]:
    # REWRITTEN 2026-07-14: dropped Apify entirely. LinkedIn exposes a public,
    # unauthenticated "guest" endpoint that serves the same job-card HTML
    # shown to logged-out visitors -- no login, no cookie, no Apify actor,
    # no cost. Confirmed against five independent sources describing the
    # same endpoint/params/CSS classes. client/li_at_cookie kept as unused
    # params so run_all_scrapers doesn't need to change its call site.
    name = "LinkedIn"
    print(f"  ▶ {name} (direct, no Apify)...")
    date_filter = "r86400" if hours <= 24 else "r259200"
    keywords = ("Data Engineer", "Senior Data Engineer",
                "Analytics Engineer", "ETL Engineer")
    results = []
    raw = kept = skip_title = skip_loc = skip_age = 0

    for kw in keywords:
        # Only the first page (0-24) per keyword -- enough volume without
        # pushing rate limits; LinkedIn throttles unauthenticated IPs hard
        # past a handful of requests.
        params = {
            "keywords": kw,
            "location": "United States",
            "f_TPR": date_filter,
            "start": 0,
        }
        r = _get("https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search",
                  timeout=15, params=params)
        if not r:
            continue
        try:
            soup = BeautifulSoup(r.text, "html.parser")
        except Exception:
            continue

        cards = soup.find_all("div", class_="base-card")
        if not cards:
            cards = soup.find_all("li")  # fallback shape seen in some responses

        for card in cards:
            raw += 1
            title_el = card.find("h3", class_="base-search-card__title")
            title = title_el.get_text(strip=True) if title_el else ""
            if not _title_ok(title):
                skip_title += 1
                continue

            loc_el = card.find("span", class_="job-search-card__location")
            loc = loc_el.get_text(strip=True) if loc_el else ""
            if not _loc_ok(loc):
                skip_loc += 1
                continue

            time_el = card.find("time")
            date_raw = time_el.get("datetime", "") if time_el else ""
            if not is_within_hours(date_raw, hours):
                skip_age += 1
                continue

            company_el = card.find("h4", class_="base-search-card__subtitle")
            link_el = card.find("a", class_="base-card__full-link") or card.find("a", href=True)

            kept += 1
            results.append(_job(
                title,
                company_el.get_text(strip=True) if company_el else "",
                loc, "",
                date_raw,
                "",  # guest endpoint doesn't include full description in the card
                "",
                (link_el.get("href", "").split("?")[0] if link_el else ""),
                name,
            ))
        time.sleep(1.5)  # be polite between keyword queries

    print(f"    {name:22s} | raw={raw:4d} | kept={kept:3d} | "
          f"skip_title={skip_title:4d} | skip_loc={skip_loc:3d} | skip_age={skip_age:3d}")
    return results


# ===========================================================================
# SCRAPER 9 — BUILT IN via Apify  (tech/startup-focused board, 24-hr filter)
# ===========================================================================
def _find_url(item: dict) -> str:
    """Try known field names first, then fall back to scanning for any key
    that looks like a URL field and whose value actually looks like a URL.
    Exists because several Apify actors' real output field names for the
    job link couldn't be confirmed without a live sample -- this adapts
    instead of guessing once and silently failing forever."""
    for key in ("url", "jobUrl", "link", "applyUrl", "detailUrl",
                "job_url", "href", "postUrl", "sourceUrl"):
        val = item.get(key)
        if val:
            return val
    for k, v in item.items():
        if isinstance(v, str) and v.startswith("http") and \
           any(t in k.lower() for t in ("url", "link", "href")):
            return v
    return ""


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
                "postedWithinDays": "1" if hours <= 24 else "3",
                "maxResultsPerQuery": 100,
                "fetchDescription": True,
            },
            run_timeout=timedelta(seconds=180),
        )
        if run is None:
            raise RuntimeError("Actor run returned None (run may have failed or been aborted)")
        items = list(client.dataset(run.default_dataset_id).iterate_items())
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
                _find_url(item),
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
            run_input=cfg["input"], run_timeout=timedelta(seconds=timeout_secs)
        )
        if run is None:
            raise RuntimeError("Actor run returned None (run may have failed or been aborted)")
        items = list(client.dataset(run.default_dataset_id).iterate_items())
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
            job_url = mapped.get("job_url", "") or _find_url(item)
            results.append(_job(
                title, mapped.get("company_name", ""),
                loc, mapped.get("remote_or_hybrid", ""),
                mapped.get("posting_date", ""),
                mapped.get("job_description", ""),
                mapped.get("salary", ""),
                job_url,
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

                        // Strategy 1: table rows (original guess)
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

                        // Strategy 2 (fallback): the table-row selector was a guess
                        // that returned zero results on a real run (confirmed:
                        // crawl succeeded, 0 items extracted) -- if the site
                        // isn't table-based, fall back to matching job-detail
                        // links by URL pattern instead of guessing CSS classes.
                        if (jobs.length === 0) {
                            $('a[href*="Job-"], a[href*="/Job/"], a[href*="JobId"]').each((i, el) => {
                                const title = $(el).text().trim();
                                if (!title || title.length < 5) return;
                                const href = $(el).attr('href') || '';
                                const card = $(el).closest('div, li, tr, article');
                                jobs.push({
                                    job_title:       title,
                                    company_name:    card.find('[class*="company" i]').first().text().trim(),
                                    location:        card.find('[class*="location" i]').first().text().trim() || 'United States',
                                    posting_date:    '',
                                    remote_or_hybrid:'',
                                    salary:          '',
                                    job_description: 'H1B Visa Sponsorship Available',
                                    job_url: href.startsWith('http') ? href : 'https://www.myvisajobs.com' + href,
                                    platform_name:   'MyVisaJobs'
                                });
                            });
                        }

                        return jobs;
                    }
                """,
                "maxRequestsPerCrawl": 6,
            },
            run_timeout=timedelta(seconds=120),
        )
        if run is None:
            raise RuntimeError("Actor run returned None (run may have failed or been aborted)")
        items = list(client.dataset(run.default_dataset_id).iterate_items())
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

    # LinkedIn — direct scrape of the public guest API, no Apify, no cost.
    # Runs regardless of Apify account status.
    all_jobs += _track("LinkedIn", lambda: scrape_linkedin(None, linkedin_cookie, hours))

    # Apify actors — 24-hr filter. If the Apify account is over its usage
    # limit, these will all fail gracefully (caught by _track) and just show
    # up as zero in the source-health banner -- doesn't block anything above.
    if apify_client:
        all_jobs += _track("Indeed", lambda: scrape_indeed(apify_client, hours))
        all_jobs += _track("MyVisaJobs", lambda: scrape_myvisajobs(apify_client))
        all_jobs += _track("Built In", lambda: scrape_builtin(apify_client, hours))

        # Previously configured but never wired in
        all_jobs += _track("Wellfound", lambda: scrape_via_config(apify_client, "wellfound", hours))
        all_jobs += _track("YC Startup", lambda: scrape_via_config(apify_client, "yc_startup", hours))
        all_jobs += _track("SimplyHired", lambda: scrape_via_config(apify_client, "simplyhired", hours))
        all_jobs += _track("Jooble", lambda: scrape_via_config(apify_client, "jooble", hours))
        all_jobs += _track("Handshake", lambda: scrape_via_config(apify_client, "handshake", hours))
        all_jobs += _track("Otta", lambda: scrape_via_config(apify_client, "otta", hours))
        all_jobs += _track("Remote Rocketship", lambda: scrape_via_config(apify_client, "remote_rocketship", hours))

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
