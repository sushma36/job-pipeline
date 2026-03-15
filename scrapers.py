"""
scrapers.py
===========
All job scrapers. Each returns List[dict] with these keys:
    job_title, company_name, location, remote_or_hybrid,
    posting_date, job_description, salary, job_url, platform_name
"""

import re
import time
import requests
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from typing import List, Optional

# ── Request headers ───────────────────────────────────────────
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/html, */*",
    "Accept-Language": "en-US,en;q=0.9",
}

# ── ATS company lists ─────────────────────────────────────────
GREENHOUSE_COMPANIES = [
    # Data tool companies (highest hit rate for DE roles)
    "databricks", "dbt-labs", "fivetran", "airbyte", "astronomer",
    "hightouch", "census", "anomalo", "monte-carlo", "metaplane",
    "atlan", "secoda", "stemma", "castor", "datafold",
    # Tech companies with large DE teams
    "stripe", "airbnb", "doordash", "coinbase", "notion", "figma",
    "plaid", "brex", "chime", "gusto", "rippling", "robinhood",
    "scale-ai", "datadog", "cloudflare", "retool", "benchling",
    "lyft", "reddit", "duolingo", "discord", "hubspot", "zendesk",
    "okta", "hashicorp", "elastic", "airtable", "zapier",
    "amplitude", "mixpanel", "heap", "segment",
    # Healthcare (strong match for Sushma)
    "tempus", "flatiron", "veeva", "commure", "health-gorilla",
]

LEVER_COMPANIES = [
    "netflix", "confluent", "starburst", "clickhouse",
    "benchling", "carta", "faire", "cohere",
    "samsara", "podium", "gladly",
]

SMARTRECRUITERS_COMPANIES = [
    "Snowflake", "HubSpot", "Okta", "Zendesk", "Talend",
]

# ── Title matching ────────────────────────────────────────────
# ALLOWLIST of DE-specific keywords
_DE_KEYWORDS = [
    "data engineer",
    "analytics engineer",
    "etl engineer",
    "etl developer",
    "data platform engineer",
    "big data engineer",
    "cloud data engineer",
    "data infrastructure engineer",
    "data pipeline engineer",
    "data warehouse engineer",
]

# BLOCKLIST — reject even if a keyword matched
_DISQUALIFY = [
    "phd", "research scientist", "data scientist", "business intelligence",
    "machine learning engineer", "ml engineer", "software engineer",
    "frontend", "backend", "security", "devops", "site reliability",
    "product manager", "recruiter", "sales", "marketing", "data analyst",
    "ai engineer", "research engineer",
]

def title_matches(title: str) -> bool:
    """Return True only for genuine Data Engineer role titles."""
    t = title.lower()
    if not any(kw in t for kw in _DE_KEYWORDS):
        return False
    if any(dq in t for dq in _DISQUALIFY):
        return False
    return True


# ── Location filter (ALLOWLIST — rejects non-US unless remote) ─
_REMOTE_SIGNALS = [
    "remote", "anywhere", "worldwide", "work from home", "wfh",
    "distributed", "us only", "usa only", "united states only",
    "north america", "global", "flexible",
]

_US_STATES = [
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

_STATE_ABBREVS = {
    "al","ak","az","ar","ca","co","ct","de","fl","ga","hi","id","il",
    "in","ia","ks","ky","la","me","md","ma","mi","mn","ms","mo","mt",
    "ne","nv","nh","nj","nm","ny","nc","nd","oh","ok","or","pa","ri",
    "sc","sd","tn","tx","ut","vt","va","wa","wv","wi","wy","dc",
}

_US_CITIES = [
    "new york","san francisco","seattle","chicago","boston","austin",
    "denver","atlanta","los angeles","washington","portland","miami",
    "dallas","houston","minneapolis","philadelphia","phoenix","san diego",
    "raleigh","nashville","salt lake","detroit","baltimore","san jose",
    "charlotte","indianapolis","columbus","memphis","louisville",
    "richmond","hartford","pittsburgh","cincinnati","kansas city",
    "new orleans","las vegas","albuquerque","tampa","orlando",
    "jacksonville","san antonio","fort worth","el paso","tucson",
    "fresno","sacramento","long beach","mesa","omaha",
]

def is_us_or_remote(location: str) -> bool:
    """
    ALLOWLIST approach: accept only if location is explicitly US or remote.
    Empty location = accept (many remote jobs have no location set).
    """
    if not location or not location.strip():
        return True

    loc = location.lower().strip()

    # Check remote signals first
    for sig in _REMOTE_SIGNALS:
        if sig in loc:
            return True

    # Check "united states" / "usa"
    if "united states" in loc or ", usa" in loc or " usa" in loc or "u.s.a" in loc:
        return True

    # Check full state names
    for state in _US_STATES:
        if state in loc:
            return True

    # Check state abbreviations as word tokens
    tokens = set(re.split(r'[\s,./\-]+', loc))
    if tokens & _STATE_ABBREVS:
        return True

    # Check major US cities
    for city in _US_CITIES:
        if city in loc:
            return True

    # Default: REJECT — can't confirm it's US or remote
    return False


# ── Date filter ───────────────────────────────────────────────
def within_lookback(date_str: str, hours: int = 48) -> bool:
    """Return True if date is within lookback window. Empty date = keep."""
    if not date_str or not date_str.strip():
        return True
    try:
        from dateutil import parser as dp
        from datetime import timezone
        dt  = dp.parse(str(date_str))
        now = datetime.now(timezone.utc) if dt.tzinfo else datetime.now()
        return (now - dt) <= timedelta(hours=hours)
    except Exception:
        return True  # can't parse = keep


# ── Job dict factory ──────────────────────────────────────────
def job(title, company, location, remote, date, description, salary, url, platform):
    return {
        "job_title":        title.strip() if title else "",
        "company_name":     company.strip() if company else "",
        "location":         location.strip() if location else "",
        "remote_or_hybrid": remote.strip() if remote else "",
        "posting_date":     date.strip() if date else "",
        "job_description":  description.strip() if description else "",
        "salary":           salary.strip() if salary else "",
        "job_url":          url.strip() if url else "",
        "platform_name":    platform,
    }


# ── HTTP helper ───────────────────────────────────────────────
def get(url: str, timeout: int = 20, params: dict = None) -> Optional[requests.Response]:
    for attempt in range(3):
        try:
            r = requests.get(url, timeout=timeout, headers=HEADERS, params=params)
            if r.status_code == 200:
                return r
            if r.status_code == 429:
                time.sleep(5 * (attempt + 1))
        except requests.exceptions.RequestException:
            time.sleep(2)
    return None


# ═══════════════════════════════════════════════════════════════
#  SCRAPER 1 — GREENHOUSE ATS
#  Public JSON API: boards-api.greenhouse.io
# ═══════════════════════════════════════════════════════════════
def scrape_greenhouse(hours: int = 48) -> List[dict]:
    print(f"  ▶ Greenhouse ATS ({len(GREENHOUSE_COMPANIES)} companies)...")
    results = []
    kept = skip_title = skip_loc = 0

    for company in GREENHOUSE_COMPANIES:
        r = get(f"https://boards-api.greenhouse.io/v1/boards/{company}/jobs?content=true")
        if not r:
            continue
        try:
            data = r.json()
        except Exception:
            continue

        for j in data.get("jobs", []):
            if not title_matches(j.get("title", "")):
                skip_title += 1
                continue
            loc = (j.get("location") or {}).get("name", "")
            if not is_us_or_remote(loc):
                skip_loc += 1
                continue
            date = j.get("updated_at", "") or j.get("created_at", "")
            kept += 1
            remote = "Remote" if "remote" in loc.lower() else "Hybrid"
            results.append(job(
                j.get("title", ""),
                company.replace("-", " ").title(),
                loc, remote, date,
                j.get("content", ""), "",
                j.get("absolute_url", ""),
                "Greenhouse ATS",
            ))

    print(f"    ↳ kept={kept} | skip_title={skip_title} | skip_loc={skip_loc}")
    return results


# ═══════════════════════════════════════════════════════════════
#  SCRAPER 2 — LEVER ATS
#  Public JSON API: api.lever.co
# ═══════════════════════════════════════════════════════════════
def scrape_lever(hours: int = 48) -> List[dict]:
    print(f"  ▶ Lever ATS ({len(LEVER_COMPANIES)} companies)...")
    results = []
    kept = skip_title = skip_loc = skip_age = 0

    for company in LEVER_COMPANIES:
        r = get(f"https://api.lever.co/v0/postings/{company}?mode=json")
        if not r:
            continue
        try:
            data = r.json()
            if not isinstance(data, list):
                continue
        except Exception:
            continue

        for j in data:
            if not title_matches(j.get("text", "")):
                skip_title += 1
                continue
            loc = (j.get("categories") or {}).get("location", "") or ""
            if not is_us_or_remote(loc):
                skip_loc += 1
                continue
            created = j.get("createdAt", 0)
            date_str = datetime.fromtimestamp(created / 1000).isoformat() if created else ""
            kept += 1
            results.append(job(
                j.get("text", ""),
                company.title(),
                loc,
                j.get("workplaceType", ""),
                date_str,
                j.get("descriptionPlain", ""), "",
                j.get("hostedUrl", ""),
                "Lever ATS",
            ))

    print(f"    ↳ kept={kept} | skip_title={skip_title} | skip_loc={skip_loc} | skip_age={skip_age}")
    return results


# ═══════════════════════════════════════════════════════════════
#  SCRAPER 3 — REMOTIVE
#  Free public API: remotive.com/api
# ═══════════════════════════════════════════════════════════════
def scrape_remotive(hours: int = 48) -> List[dict]:
    print(f"  ▶ Remotive...")
    r = get("https://remotive.com/api/remote-jobs?category=data&limit=100")
    if not r:
        print("    ↳ unreachable")
        return []

    results = []
    kept = skip_title = skip_age = skip_loc = 0

    for j in r.json().get("jobs", []):
        if not title_matches(j.get("title", "")):
            skip_title += 1
            continue
        if not within_lookback(j.get("publication_date", ""), hours):
            skip_age += 1
            continue
        loc = j.get("candidate_required_location", "Remote") or "Remote"
        if not is_us_or_remote(loc):
            skip_loc += 1
            continue
        kept += 1
        results.append(job(
            j.get("title", ""),
            j.get("company_name", ""),
            loc,
            "Remote",
            j.get("publication_date", ""),
            j.get("description", ""),
            j.get("salary", ""),
            j.get("url", ""),
            "Remotive",
        ))

    print(f"    ↳ kept={kept} | skip_title={skip_title} | skip_age={skip_age} | skip_loc={skip_loc}")
    return results


# ═══════════════════════════════════════════════════════════════
#  SCRAPER 4 — REMOTEOK
#  Free public API: remoteok.com/api
# ═══════════════════════════════════════════════════════════════
def scrape_remoteok(hours: int = 48) -> List[dict]:
    print(f"  ▶ RemoteOK...")
    tags = ["data-engineer", "analytics", "sql", "python", "spark", "airflow"]
    seen_urls: set = set()
    results = []
    kept = skip_title = skip_age = 0

    for tag in tags:
        r = get(f"https://remoteok.com/api?tag={tag}")
        if not r:
            continue
        try:
            data = r.json()
        except Exception:
            continue

        for j in data:
            if not isinstance(j, dict) or not j.get("position"):
                continue
            if not title_matches(j.get("position", "")):
                skip_title += 1
                continue
            if not within_lookback(j.get("date", ""), hours):
                skip_age += 1
                continue
            loc = j.get("location", "Remote")
            if not is_us_or_remote(loc):
                continue
            url = j.get("url", "")
            if not url.startswith("http"):
                url = f"https://remoteok.com{url}"
            if url in seen_urls:
                continue
            seen_urls.add(url)
            kept += 1
            sal = (f"${j['salary_min']}-${j['salary_max']}"
                   if j.get("salary_min") else "")
            results.append(job(
                j.get("position", ""),
                j.get("company", ""),
                j.get("location", "Remote"),
                "Remote",
                j.get("date", ""),
                " ".join(j.get("tags", [])),
                sal, url, "RemoteOK",
            ))
        time.sleep(1)  # avoid rate limit between tag requests

    print(f"    ↳ kept={kept} | skip_title={skip_title} | skip_age={skip_age}")
    return results


# ═══════════════════════════════════════════════════════════════
#  SCRAPER 5 — WEWORKREMOTELY
#  3 RSS feeds — parsed as XML directly
# ═══════════════════════════════════════════════════════════════
def scrape_weworkremotely(hours: int = 48) -> List[dict]:
    print(f"  ▶ WeWorkRemotely (RSS)...")
    feeds = [
        "https://weworkremotely.com/categories/remote-data-science-jobs.rss",
        "https://weworkremotely.com/categories/remote-programming-jobs.rss",
        "https://weworkremotely.com/categories/remote-devops-sysadmin-jobs.rss",
    ]
    results = []
    kept = skip_title = skip_age = 0

    for feed_url in feeds:
        r = get(feed_url)
        if not r:
            continue
        try:
            root = ET.fromstring(r.content)
        except ET.ParseError:
            continue

        for item in root.findall(".//item"):
            raw = re.sub(r"<!\[CDATA\[|\]\]>", "",
                         item.findtext("title") or "").strip()
            company = raw.split(":")[0].strip() if ":" in raw else ""
            title   = ":".join(raw.split(":")[1:]).strip() if ":" in raw else raw

            if not title_matches(title):
                skip_title += 1
                continue
            pub = item.findtext("pubDate", "")
            if not within_lookback(pub, hours):
                skip_age += 1
                continue

            # Grab <link> text node (it follows the tag in RSS)
            link = ""
            for child in item:
                if child.tag == "link":
                    link = (child.text or "").strip()
                    break
            if not link:
                link = item.findtext("guid", "")

            desc = re.sub(r"<[^>]+>", "",
                          item.findtext("description", ""))
            kept += 1
            results.append(job(
                title, company, "Remote", "Remote",
                pub, desc, "", link, "WeWorkRemotely",
            ))

    print(f"    ↳ kept={kept} | skip_title={skip_title} | skip_age={skip_age}")
    return results


# ═══════════════════════════════════════════════════════════════
#  SCRAPER 6 — JOBICY
#  Free public API: jobicy.com/api/v2
# ═══════════════════════════════════════════════════════════════
def scrape_jobicy(hours: int = 48) -> List[dict]:
    print(f"  ▶ Jobicy...")
    tags = ["data-engineer", "data", "python", "sql"]
    seen_urls: set = set()
    results = []
    kept = skip_title = skip_age = 0

    for tag in tags:
        r = get(f"https://jobicy.com/api/v2/remote-jobs?count=50&tag={tag}")
        if not r:
            continue
        try:
            data = r.json()
        except Exception:
            continue

        for j in data.get("jobs", []):
            if not title_matches(j.get("jobTitle", "")):
                skip_title += 1
                continue
            if not within_lookback(j.get("pubDate", ""), hours):
                skip_age += 1
                continue
            loc = j.get("jobGeo", "Remote") or "Remote"
            if not is_us_or_remote(loc):
                continue
            url = j.get("url", "")
            if url in seen_urls:
                continue
            seen_urls.add(url)
            kept += 1
            results.append(job(
                j.get("jobTitle", ""),
                j.get("companyName", ""),
                loc,
                "Remote",
                j.get("pubDate", ""),
                j.get("jobDescription", ""),
                str(j.get("annualSalaryMin", "")),
                url, "Jobicy",
            ))

    print(f"    ↳ kept={kept} | skip_title={skip_title} | skip_age={skip_age}")
    return results


# ═══════════════════════════════════════════════════════════════
#  SCRAPER 7 — SMARTRECRUITERS ATS
#  Free public REST API: api.smartrecruiters.com
# ═══════════════════════════════════════════════════════════════
def scrape_smartrecruiters(hours: int = 48) -> List[dict]:
    print(f"  ▶ SmartRecruiters ATS ({len(SMARTRECRUITERS_COMPANIES)} companies)...")
    results = []
    kept = skip_title = skip_loc = skip_age = 0

    for company in SMARTRECRUITERS_COMPANIES:
        r = get(
            f"https://api.smartrecruiters.com/v1/companies/{company}/postings"
            f"?status=PUBLIC&limit=100",
            params={"q": "data engineer"},
        )
        if not r:
            continue
        try:
            data = r.json()
        except Exception:
            continue

        for j in data.get("content", []):
            if not title_matches(j.get("name", "")):
                skip_title += 1
                continue
            loc_obj = j.get("location") or {}
            city    = loc_obj.get("city", "")
            country = loc_obj.get("country", "")
            loc_str = f"{city}, {country}".strip(", ")
            if not is_us_or_remote(loc_str):
                skip_loc += 1
                continue
            if not within_lookback(j.get("releasedDate", ""), hours):
                skip_age += 1
                continue
            kept += 1
            results.append(job(
                j.get("name", ""), company, loc_str, "", 
                j.get("releasedDate", ""), "", "",
                f"https://jobs.smartrecruiters.com/{company}/{j.get('id','')}",
                "SmartRecruiters ATS",
            ))

    print(f"    ↳ kept={kept} | skip_title={skip_title} | skip_loc={skip_loc} | skip_age={skip_age}")
    return results


# ═══════════════════════════════════════════════════════════════
#  SCRAPER 8 — INDEED (via Apify actor)
#  Actor: misceres/indeed-scraper
# ═══════════════════════════════════════════════════════════════
def scrape_indeed(apify_client, hours: int = 48) -> List[dict]:
    print(f"  ▶ Indeed (Apify actor)...")
    try:
        run = apify_client.actor("misceres/indeed-scraper").call(
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
        items = list(apify_client.dataset(run["defaultDatasetId"]).iterate_items())
        results = []
        kept = skip_title = skip_loc = skip_age = 0

        for item in items:
            if not title_matches(item.get("title", "")):
                skip_title += 1
                continue
            loc = item.get("location", "")
            if not is_us_or_remote(loc):
                skip_loc += 1
                continue
            if not within_lookback(item.get("postedAt", ""), hours):
                skip_age += 1
                continue
            kept += 1
            results.append(job(
                item.get("title", ""),
                item.get("company", ""),
                loc, "",
                item.get("postedAt", ""),
                item.get("description", ""),
                item.get("salary", ""),
                item.get("url", ""),
                "Indeed",
            ))

        print(f"    ↳ {len(items)} raw | kept={kept} | skip_title={skip_title} | skip_loc={skip_loc} | skip_age={skip_age}")
        return results
    except Exception as e:
        print(f"    ⚠️  Indeed failed: {e}")
        return []


# ═══════════════════════════════════════════════════════════════
#  SCRAPER 9 — MYVISAJOBS (via Apify cheerio-scraper)
#  H1B-sponsoring employers — important for Sushma
# ═══════════════════════════════════════════════════════════════
def scrape_myvisajobs(apify_client, hours: int = 48) -> List[dict]:
    print(f"  ▶ MyVisaJobs (Apify actor — H1B sponsors)...")
    try:
        run = apify_client.actor("apify/cheerio-scraper").call(
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
                            if (i === 0) return;
                            const cells = $(row).find('td');
                            if (cells.length < 3) return;
                            const a     = cells.eq(0).find('a').first();
                            const title = a.text().trim();
                            if (!title) return;
                            jobs.push({
                                job_title:    title,
                                company_name: cells.eq(1).text().trim(),
                                location:     cells.eq(2).text().trim(),
                                posting_date: cells.length > 3 ? cells.eq(3).text().trim() : '',
                                remote_or_hybrid: '',
                                salary: '',
                                job_description: 'H1B visa sponsorship available',
                                job_url: 'https://www.myvisajobs.com' + (a.attr('href') || ''),
                                platform_name: 'MyVisaJobs'
                            });
                        });
                        return jobs;
                    }
                """,
                "maxRequestsPerCrawl": 6,
            },
            timeout_secs=120,
        )
        items = list(apify_client.dataset(run["defaultDatasetId"]).iterate_items())
        results = []
        kept = skip_title = 0

        for item in items:
            if not title_matches(item.get("job_title", "")):
                skip_title += 1
                continue
            # MyVisaJobs is US-only by definition
            kept += 1
            item["platform_name"] = "MyVisaJobs"
            # Add H1B note to description
            item["job_description"] = "✅ H1B Visa Sponsorship Available — " + item.get("job_description", "")
            results.append(item)

        print(f"    ↳ {len(items)} raw | kept={kept} | skip_title={skip_title}")
        return results
    except Exception as e:
        print(f"    ⚠️  MyVisaJobs failed: {e}")
        return []


# ═══════════════════════════════════════════════════════════════
#  MASTER FUNCTION
# ═══════════════════════════════════════════════════════════════
def run_all_scrapers(apify_client, hours: int = 48) -> List[dict]:
    all_jobs = []

    # ── Direct API scrapers (no Apify usage) ──────────────────
    print("\n📡 Direct API scrapers (free, no Apify):")
    all_jobs += scrape_greenhouse(hours)
    all_jobs += scrape_lever(hours)
    all_jobs += scrape_remotive(hours)
    all_jobs += scrape_remoteok(hours)
    all_jobs += scrape_weworkremotely(hours)
    all_jobs += scrape_jobicy(hours)
    all_jobs += scrape_smartrecruiters(hours)
    print(f"  Subtotal: {len(all_jobs)} jobs")

    # ── Apify actor scrapers ──────────────────────────────────
    print("\n📡 Apify actor scrapers:")
    if apify_client:
        all_jobs += scrape_indeed(apify_client, hours)
        all_jobs += scrape_myvisajobs(apify_client, hours)

    # ── Deduplicate by URL then by company+title ───────────────
    seen_urls: set = set()
    seen_keys: set = set()
    unique = []
    for j in all_jobs:
        url = j.get("job_url", "").strip()
        key = (re.sub(r"\W", "", j.get("company_name", "").lower()) + "|" +
               re.sub(r"\W", "", j.get("job_title",    "").lower()))
        if url and url in seen_urls:
            continue
        if key in seen_keys:
            continue
        if url:
            seen_urls.add(url)
        seen_keys.add(key)
        unique.append(j)

    print(f"\n  ✅ Total unique jobs: {len(unique)}")
    return unique
