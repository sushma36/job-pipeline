"""
scrapers.py — All job scrapers for Data Engineer pipeline
=========================================================
Strategy per source:
  - ATS (Greenhouse, Lever): NO date filter — API only returns open jobs
  - Job boards (RemoteOK, WWR, Jobicy, Remotive): 7-day lookback
    because boards keep jobs listed for weeks; 24hr = almost always 0
  - Apify (Indeed, MyVisaJobs): 24hr filter via actor config
"""

import re, time
import requests
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from typing import List, Optional

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
    # Data tooling companies — highest DE job density
    "databricks", "dbt-labs", "fivetran", "airbyte", "astronomer",
    "hightouch", "census", "anomalo", "monte-carlo", "rudderstack",
    "lightdash", "preset", "cube-dev", "datafold", "re-data",
    # Tech companies with large DE teams
    "stripe", "airbnb", "doordash", "coinbase", "notion", "figma",
    "plaid", "brex", "chime", "gusto", "rippling", "robinhood",
    "scale-ai", "datadog", "cloudflare", "retool", "benchling",
    "lyft", "reddit", "duolingo", "discord", "hubspot", "zendesk",
    "okta", "elastic", "airtable", "zapier", "segment", "amplitude",
    # Healthcare (Sushma's domain)
    "tempus", "flatiron", "veeva", "commure",
    # Fintech
    "carta", "faire", "brex", "chime",
]

LEVER_COMPANIES = [
    "confluent", "starburst", "clickhouse", "benchling",
    "samsara", "podium", "gladly", "cohere", "weights-biases",
    "imply", "acryl-data", "atlan",
]

# ── Title matching ─────────────────────────────────────────────
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

_DISQUALIFY = [
    "phd", "research scientist", "data scientist", "machine learning engineer",
    "ml engineer", "software engineer", "frontend", "backend", "security",
    "devops", "site reliability", "product manager", "data analyst",
    "business intelligence", "ai engineer", "research engineer",
    "deep learning", "computer vision", "nlp engineer",
]

def title_matches(title: str) -> bool:
    t = title.lower()
    if not any(kw in t for kw in _DE_KEYWORDS):
        return False
    if any(dq in t for dq in _DISQUALIFY):
        return False
    return True

# ── Location filter (allowlist) ────────────────────────────────
_REMOTE_SIGNALS = [
    "remote", "anywhere", "worldwide", "work from home", "wfh",
    "distributed", "us only", "usa only", "north america", "global",
    "flexible", "united states", ", usa", " usa", "u.s.a",
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
    "new orleans","las vegas","tampa","orlando","jacksonville",
    "san antonio","fort worth","el paso","tucson","fresno","sacramento",
]

def is_us_or_remote(location: str) -> bool:
    if not location or not location.strip():
        return True
    loc = location.lower().strip()
    for sig in _REMOTE_SIGNALS:
        if sig in loc:
            return True
    for state in _US_STATES:
        if state in loc:
            return True
    tokens = set(re.split(r'[\s,./\-]+', loc))
    if tokens & _STATE_ABBREVS:
        return True
    for city in _US_CITIES:
        if city in loc:
            return True
    return False

# ── Date filter ────────────────────────────────────────────────
def within_lookback(date_str: str, hours: int) -> bool:
    if not date_str or not str(date_str).strip():
        return True
    try:
        from dateutil import parser as dp
        from datetime import timezone
        dt  = dp.parse(str(date_str))
        now = datetime.now(timezone.utc) if dt.tzinfo else datetime.now()
        return (now - dt) <= timedelta(hours=hours)
    except Exception:
        return True

# ── Helpers ────────────────────────────────────────────────────
def make_job(title, company, location, remote, date,
             description, salary, url, platform):
    return {
        "job_title":        (title       or "").strip(),
        "company_name":     (company     or "").strip(),
        "location":         (location    or "").strip(),
        "remote_or_hybrid": (remote      or "").strip(),
        "posting_date":     (date        or "").strip(),
        "job_description":  (description or "").strip(),
        "salary":           (salary      or "").strip(),
        "job_url":          (url         or "").strip(),
        "platform_name":    platform,
    }

def get(url: str, timeout: int = 20,
        params: dict = None) -> Optional[requests.Response]:
    for attempt in range(3):
        try:
            r = requests.get(url, timeout=timeout,
                             headers=HEADERS, params=params)
            if r.status_code == 200:
                return r
            if r.status_code == 429:
                time.sleep(5 * (attempt + 1))
        except Exception:
            time.sleep(2)
    return None


# ═══════════════════════════════════════════════════════════════
# 1. GREENHOUSE — No date filter (API = open jobs only)
# ═══════════════════════════════════════════════════════════════
def scrape_greenhouse() -> List[dict]:
    print(f"  ▶ Greenhouse ATS ({len(GREENHOUSE_COMPANIES)} companies)...")
    results = []
    kept = skip_title = skip_loc = 0

    for company in GREENHOUSE_COMPANIES:
        r = get(f"https://boards-api.greenhouse.io/v1/boards/{company}"
                f"/jobs?content=true", timeout=15)
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
            remote = "Remote" if "remote" in loc.lower() else "Hybrid"
            kept += 1
            results.append(make_job(
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
# 2. LEVER — No date filter (API = open jobs only)
# ═══════════════════════════════════════════════════════════════
def scrape_lever() -> List[dict]:
    print(f"  ▶ Lever ATS ({len(LEVER_COMPANIES)} companies)...")
    results = []
    kept = skip_title = skip_loc = 0

    for company in LEVER_COMPANIES:
        r = get(f"https://api.lever.co/v0/postings/{company}?mode=json",
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
            if not title_matches(j.get("text", "")):
                skip_title += 1
                continue
            loc = (j.get("categories") or {}).get("location", "") or ""
            if not is_us_or_remote(loc):
                skip_loc += 1
                continue
            created  = j.get("createdAt", 0)
            date_str = (datetime.fromtimestamp(created / 1000).isoformat()
                        if created else "")
            kept += 1
            results.append(make_job(
                j.get("text", ""),
                company.title(),
                loc,
                j.get("workplaceType", ""),
                date_str,
                j.get("descriptionPlain", ""), "",
                j.get("hostedUrl", ""),
                "Lever ATS",
            ))

    print(f"    ↳ kept={kept} | skip_title={skip_title} | skip_loc={skip_loc}")
    return results


# ═══════════════════════════════════════════════════════════════
# 3. REMOTEOK — 7-day lookback (board keeps old jobs listed)
# ═══════════════════════════════════════════════════════════════
def scrape_remoteok(hours: int = 24) -> List[dict]:
    print(f"  ▶ RemoteOK (24hr)...")
    tags = ["data-engineer", "analytics", "sql", "python", "spark", "airflow"]
    seen: set = set()
    results = []
    kept = skip_title = skip_age = 0

    for tag in tags:
        r = get(f"https://remoteok.com/api?tag={tag}", timeout=20)
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
            loc = j.get("location", "Remote") or "Remote"
            if not is_us_or_remote(loc):
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
            results.append(make_job(
                j.get("position", ""), j.get("company", ""),
                loc, "Remote", j.get("date", ""),
                " ".join(j.get("tags", [])), sal, url, "RemoteOK",
            ))
        time.sleep(1)

    print(f"    ↳ kept={kept} | skip_title={skip_title} | skip_age={skip_age}")
    return results


# ═══════════════════════════════════════════════════════════════
# 4. WEWORKREMOTELY — 7-day lookback
# ═══════════════════════════════════════════════════════════════
def scrape_weworkremotely(hours: int = 24) -> List[dict]:
    print(f"  ▶ WeWorkRemotely (24hr)...")
    feeds = [
        "https://weworkremotely.com/categories/remote-data-science-jobs.rss",
        "https://weworkremotely.com/categories/remote-programming-jobs.rss",
        "https://weworkremotely.com/categories/remote-devops-sysadmin-jobs.rss",
    ]
    results = []
    kept = skip_title = skip_age = 0

    for feed_url in feeds:
        r = get(feed_url, timeout=15)
        if not r:
            continue
        try:
            root = ET.fromstring(r.content)
        except ET.ParseError:
            continue
        for item in root.findall(".//item"):
            raw = re.sub(r"<!\[CDATA\[|\]\]>",
                         "", item.findtext("title") or "").strip()
            company = raw.split(":")[0].strip() if ":" in raw else ""
            title   = ":".join(raw.split(":")[1:]).strip() if ":" in raw else raw
            if not title_matches(title):
                skip_title += 1
                continue
            pub = item.findtext("pubDate", "")
            if not within_lookback(pub, hours):
                skip_age += 1
                continue
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
            results.append(make_job(
                title, company, "Remote", "Remote",
                pub, desc, "", link, "WeWorkRemotely",
            ))

    print(f"    ↳ kept={kept} | skip_title={skip_title} | skip_age={skip_age}")
    return results


# ═══════════════════════════════════════════════════════════════
# 5. REMOTIVE — 7-day lookback
# ═══════════════════════════════════════════════════════════════
def scrape_remotive(hours: int = 24) -> List[dict]:
    print(f"  ▶ Remotive (24hr)...")
    # Try multiple category URLs for best coverage
    urls = [
        "https://remotive.com/api/remote-jobs?category=data&limit=100",
        "https://remotive.com/api/remote-jobs?category=software-dev&limit=100",
    ]
    seen: set = set()
    results = []
    kept = skip_title = skip_age = skip_loc = 0

    for url in urls:
        r = get(url, timeout=20)
        if not r:
            continue
        try:
            jobs = r.json().get("jobs", [])
        except Exception:
            continue
        for j in jobs:
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
            url_job = j.get("url", "")
            if url_job in seen:
                continue
            seen.add(url_job)
            kept += 1
            results.append(make_job(
                j.get("title", ""),
                j.get("company_name", ""),
                loc, "Remote",
                j.get("publication_date", ""),
                j.get("description", ""),
                j.get("salary", ""),
                url_job, "Remotive",
            ))

    print(f"    ↳ kept={kept} | skip_title={skip_title} | skip_age={skip_age} | skip_loc={skip_loc}")
    return results


# ═══════════════════════════════════════════════════════════════
# 6. JOBICY — 7-day lookback
# ═══════════════════════════════════════════════════════════════
def scrape_jobicy(hours: int = 24) -> List[dict]:
    print(f"  ▶ Jobicy (24hr)...")
    tags = ["data-engineer", "data", "python", "sql", "analytics"]
    seen: set = set()
    results = []
    kept = skip_title = skip_age = skip_loc = 0

    for tag in tags:
        r = get(f"https://jobicy.com/api/v2/remote-jobs?count=50&tag={tag}",
                timeout=20)
        if not r:
            continue
        try:
            jobs = r.json().get("jobs", [])
        except Exception:
            continue
        for j in jobs:
            if not title_matches(j.get("jobTitle", "")):
                skip_title += 1
                continue
            if not within_lookback(j.get("pubDate", ""), hours):
                skip_age += 1
                continue
            loc = j.get("jobGeo", "Remote") or "Remote"
            if not is_us_or_remote(loc):
                skip_loc += 1
                continue
            url = j.get("url", "")
            if url in seen:
                continue
            seen.add(url)
            kept += 1
            results.append(make_job(
                j.get("jobTitle", ""),
                j.get("companyName", ""),
                loc, "Remote",
                j.get("pubDate", ""),
                j.get("jobDescription", ""),
                str(j.get("annualSalaryMin", "")),
                url, "Jobicy",
            ))

    print(f"    ↳ kept={kept} | skip_title={skip_title} | skip_age={skip_age} | skip_loc={skip_loc}")
    return results


# ═══════════════════════════════════════════════════════════════
# 7. INDEED — via Apify actor, 24hr filter
# ═══════════════════════════════════════════════════════════════
def scrape_indeed(client, hours: int = 24) -> List[dict]:
    print(f"  ▶ Indeed (Apify — 24hr)...")
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
            results.append(make_job(
                item.get("title", ""),
                item.get("company", ""),
                loc, "",
                item.get("postedAt", ""),
                item.get("description", ""),
                item.get("salary", ""),
                item.get("url", ""),
                "Indeed",
            ))
        print(f"    ↳ {len(items)} raw | kept={kept} | skip_title={skip_title} "
              f"| skip_loc={skip_loc} | skip_age={skip_age}")
        return results
    except Exception as e:
        print(f"    ⚠️  Indeed failed: {e}")
        return []


# ═══════════════════════════════════════════════════════════════
# 8. MYVISAJOBS — via Apify, H1B sponsors, 24hr
# ═══════════════════════════════════════════════════════════════
def scrape_myvisajobs(client) -> List[dict]:
    print(f"  ▶ MyVisaJobs (Apify — H1B sponsors)...")
    try:
        run = client.actor("apify/cheerio-scraper").call(
            run_input={
                "startUrls": [
                    {"url": "https://www.myvisajobs.com/Search-Data-Engineer-Jobs.htm"
                             "?Keyword=Data+Engineer&TimePosted=1"},
                    {"url": "https://www.myvisajobs.com/Search-Data-Engineer-Jobs.htm"
                             "?Keyword=Analytics+Engineer&TimePosted=1"},
                ],
                "pageFunction": """
                    async function pageFunction(context) {
                        const { $ } = context;
                        const jobs = [];
                        // Try multiple table selectors
                        const rows = $('table tr, .job-list tr, tr').filter(function() {
                            return $(this).find('a[href*="Job-"]').length > 0 ||
                                   $(this).find('a[href*="/job/"]').length > 0 ||
                                   $(this).find('td').length >= 3;
                        });
                        rows.each((i, row) => {
                            const cells = $(row).find('td');
                            if (cells.length < 2) return;
                            const a     = $(row).find('a').first();
                            const title = a.text().trim();
                            if (!title || title.length < 5) return;
                            const href  = a.attr('href') || '';
                            jobs.push({
                                job_title:    title,
                                company_name: cells.eq(1).text().trim(),
                                location:     cells.length > 2 ? cells.eq(2).text().trim() : 'United States',
                                posting_date: cells.length > 3 ? cells.eq(3).text().trim() : '',
                                remote_or_hybrid: '',
                                salary:       '',
                                job_description: 'H1B Visa Sponsorship Available',
                                job_url: href.startsWith('http') ? href : 'https://www.myvisajobs.com' + href,
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
        items = list(client.dataset(run["defaultDatasetId"]).iterate_items())
        results = []
        kept = skip_title = 0
        for item in items:
            if not title_matches(item.get("job_title", "")):
                skip_title += 1
                continue
            item["platform_name"] = "MyVisaJobs"
            item["job_description"] = "✅ H1B Visa Sponsorship Available"
            kept += 1
            results.append(item)
        print(f"    ↳ {len(items)} raw | kept={kept} | skip_title={skip_title}")
        return results
    except Exception as e:
        print(f"    ⚠️  MyVisaJobs failed: {e}")
        return []


# ═══════════════════════════════════════════════════════════════
# MASTER FUNCTION
# ═══════════════════════════════════════════════════════════════
def run_all_scrapers(apify_client, hours: int = 24) -> List[dict]:
    """
    hours = lookback window for all job boards (default 24hr).
    ATS scrapers (Greenhouse, Lever) have no date filter since
    their API only returns currently open positions.
    """
    all_jobs = []

    print("\n📡 ATS scrapers (all open jobs, no date filter):")
    all_jobs += scrape_greenhouse()
    all_jobs += scrape_lever()

    print("\n📡 Job board scrapers (24hr):")
    all_jobs += scrape_remoteok(hours=hours)
    all_jobs += scrape_weworkremotely(hours=hours)
    all_jobs += scrape_remotive(hours=hours)
    all_jobs += scrape_jobicy(hours=hours)
    print(f"  Subtotal: {len(all_jobs)} jobs")

    print("\n📡 Apify actor scrapers (24hr):")
    if apify_client:
        all_jobs += scrape_indeed(apify_client, hours=24)
        all_jobs += scrape_myvisajobs(apify_client)

    # Deduplicate by URL then company+title
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
