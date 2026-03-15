"""
=============================================================
  scrapers.py — All job source scrapers
  Each scraper returns a list of normalized job dicts.
  All use direct HTTP APIs where possible (most reliable).
=============================================================
"""

import re
import time
import requests
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from typing import List, Optional

# ─── SHARED HEADERS ──────────────────────────────────────────
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/html, */*",
    "Accept-Language": "en-US,en;q=0.9",
}

# ─── ROLE KEYWORDS ───────────────────────────────────────────
ROLE_KEYWORDS = [
    "data engineer",
    "junior data engineer",
    "associate data engineer",
    "analytics engineer",
    "etl engineer",
    "etl developer",
    "data platform engineer",
    "big data engineer",
    "cloud data engineer",
    "data infrastructure engineer",
    "data pipeline engineer",
    "staff data engineer",
    "lead data engineer",
    "ml engineer",
    "machine learning engineer",
    "mlops engineer",
    "data warehouse engineer",
]

# ─── COMPANIES ON EACH ATS ───────────────────────────────────
GREENHOUSE_COMPANIES = [
    "stripe", "airbnb", "doordash", "coinbase", "notion", "figma",
    "plaid", "brex", "chime", "gusto", "rippling", "databricks",
    "fivetran", "dbt-labs", "astronomer", "airbyte", "census",
    "hightouch", "anomalo", "monte-carlo", "robinhood", "scale-ai",
    "datadog", "cloudflare", "vercel", "retool", "benchling",
    "lyft", "reddit", "duolingo", "discord", "hubspot", "zendesk",
    "okta", "hashicorp", "elastic", "airtable", "zapier", "segment",
    "amplitude", "mixpanel", "tempus", "flatiron", "veeva",
    "cockroachdb", "mongodb-inc", "clickhouse", "starburst",
    "confluent", "grafana", "samsara", "faire", "carta",
]

LEVER_COMPANIES = [
    "netflix", "lyft", "reddit", "twilio", "cloudflare",
    "confluent", "starburst", "clickhouse", "hashicorp",
    "benchling", "carta", "faire", "chime", "brex",
    "scale-ai", "cohere", "anthropic", "openai",
]

SMARTRECRUITERS_COMPANIES = [
    "Snowflake", "Twilio", "HubSpot", "Okta",
    "Zendesk", "Medallia", "Splunk", "Talend",
]

# ─── HELPERS ─────────────────────────────────────────────────

def title_matches(title: str) -> bool:
    t = title.lower()
    return any(kw in t for kw in ROLE_KEYWORDS)


def within_lookback(date_str: str, hours: int = 48) -> bool:
    """Return True if date is within lookback window (or unparseable)."""
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


def is_us_or_remote(location: str) -> bool:
    """Return True if job is in the US, remote, or location unspecified."""
    if not location:
        return True
    loc = location.lower()

    # Explicit rejections — non-US countries
    non_us = [
        "india", "bengaluru", "bangalore", "hyderabad", "mumbai",
        "delhi", "chennai", "pune", "kolkata", "canada", "toronto",
        "vancouver", "uk", "united kingdom", "london", "england",
        "germany", "berlin", "france", "paris", "australia", "sydney",
        "melbourne", "singapore", "japan", "china", "brazil", "mexico",
        "netherlands", "amsterdam", "ireland", "dublin", "poland",
        "spain", "madrid", "italy", "sweden", "norway", "denmark",
        "finland", "switzerland", "austria", "belgium", "israel",
    ]
    for country in non_us:
        if country in loc:
            return False

    # Accept remote / worldwide
    remote_words = ["remote", "anywhere", "worldwide", "global", "work from home",
                    "distributed", "us only", "north america"]
    for w in remote_words:
        if w in loc:
            return True

    # Accept US states and cities
    us_signals = [
        "united states", "usa", "u.s.", " al ", " ak ", " az ", " ar ",
        " ca ", " co ", " ct ", " de ", " fl ", " ga ", " hi ", " id ",
        " il ", " in ", " ia ", " ks ", " ky ", " la ", " me ", " md ",
        " ma ", " mi ", " mn ", " ms ", " mo ", " mt ", " ne ", " nv ",
        " nh ", " nj ", " nm ", " ny ", " nc ", " nd ", " oh ", " ok ",
        " or ", " pa ", " ri ", " sc ", " sd ", " tn ", " tx ", " ut ",
        " vt ", " va ", " wa ", " wv ", " wi ", " wy ",
        "new york", "san francisco", "seattle", "chicago", "boston",
        "austin", "denver", "atlanta", "los angeles", "washington dc",
        "washington, d", "portland", "miami", "dallas", "houston",
        "minneapolis", "philadelphia", "phoenix", "san diego", "raleigh",
        "nashville", "salt lake", "st. louis", "detroit", "baltimore",
        "connecticut", "california", "texas", "florida", "new jersey",
    ]
    for signal in us_signals:
        if signal in f" {loc} ":
            return True

    # Ambiguous — keep it (benefit of the doubt)
    return True


def make_job(title, company, location, remote, date,
             description, salary, url, platform) -> dict:
    return {
        "job_title":        title.strip(),
        "company_name":     company.strip(),
        "location":         location.strip(),
        "remote_or_hybrid": remote.strip() if remote else "",
        "posting_date":     date.strip() if date else "",
        "job_description":  description.strip() if description else "",
        "salary":           salary.strip() if salary else "",
        "job_url":          url.strip() if url else "",
        "platform_name":    platform,
    }


def safe_get(url: str, timeout: int = 20, retries: int = 2,
             headers: dict = None, params: dict = None):
    """GET with retry logic. Returns response or None."""
    h = headers or HEADERS
    for attempt in range(retries):
        try:
            r = requests.get(url, timeout=timeout, headers=h, params=params)
            if r.status_code == 200:
                return r
            if r.status_code in (429, 503):
                time.sleep(3 * (attempt + 1))
        except requests.exceptions.RequestException:
            time.sleep(2)
    return None


# ─────────────────────────────────────────────────────────────
#  SCRAPER 1 — GREENHOUSE ATS (public JSON API)
# ─────────────────────────────────────────────────────────────

def scrape_greenhouse(lookback_hours: int = 48) -> List[dict]:
    print(f"  ▶ Greenhouse ATS ({len(GREENHOUSE_COMPANIES)} companies)...")
    jobs = []
    matched = skipped_loc = skipped_title = skipped_age = 0

    for company in GREENHOUSE_COMPANIES:
        r = safe_get(
            f"https://boards-api.greenhouse.io/v1/boards/{company}/jobs?content=true"
        )
        if not r:
            continue
        try:
            data = r.json()
        except Exception:
            continue

        for j in data.get("jobs", []):
            title = j.get("title", "")
            if not title_matches(title):
                skipped_title += 1
                continue
            loc = j.get("location", {}).get("name", "") if j.get("location") else ""
            if not is_us_or_remote(loc):
                skipped_loc += 1
                continue
            date = j.get("updated_at", "") or j.get("created_at", "")
            if not within_lookback(date, lookback_hours):
                skipped_age += 1
                continue
            matched += 1
            jobs.append(make_job(
                title,
                company.replace("-", " ").title(),
                loc,
                "Remote" if "remote" in loc.lower() else "Hybrid",
                date,
                j.get("content", ""),
                "",
                j.get("absolute_url", ""),
                "Greenhouse ATS",
            ))

    print(f"    ↳ kept: {matched}  | "
          f"skipped title: {skipped_title}  | "
          f"skipped location: {skipped_loc}  | "
          f"skipped age: {skipped_age}")
    return jobs


# ─────────────────────────────────────────────────────────────
#  SCRAPER 2 — LEVER ATS (public JSON API)
# ─────────────────────────────────────────────────────────────

def scrape_lever(lookback_hours: int = 48) -> List[dict]:
    print(f"  ▶ Lever ATS ({len(LEVER_COMPANIES)} companies)...")
    jobs = []
    matched = skipped_loc = skipped_title = skipped_age = 0

    for company in LEVER_COMPANIES:
        r = safe_get(f"https://api.lever.co/v0/postings/{company}?mode=json")
        if not r:
            continue
        try:
            data = r.json()
            if not isinstance(data, list):
                continue
        except Exception:
            continue

        for j in data:
            title = j.get("text", "")
            if not title_matches(title):
                skipped_title += 1
                continue
            loc = j.get("categories", {}).get("location", "") or ""
            if not is_us_or_remote(loc):
                skipped_loc += 1
                continue
            created = j.get("createdAt", 0)
            date_str = (datetime.fromtimestamp(created / 1000).isoformat()
                        if created else "")
            if not within_lookback(date_str, lookback_hours):
                skipped_age += 1
                continue
            matched += 1
            jobs.append(make_job(
                title,
                company.title(),
                loc,
                j.get("workplaceType", ""),
                date_str,
                j.get("descriptionPlain", ""),
                "",
                j.get("hostedUrl", ""),
                "Lever ATS",
            ))

    print(f"    ↳ kept: {matched}  | "
          f"skipped title: {skipped_title}  | "
          f"skipped location: {skipped_loc}  | "
          f"skipped age: {skipped_age}")
    return jobs


# ─────────────────────────────────────────────────────────────
#  SCRAPER 3 — REMOTIVE (public API)
# ─────────────────────────────────────────────────────────────

def scrape_remotive(lookback_hours: int = 48) -> List[dict]:
    print(f"  ▶ Remotive...")
    r = safe_get("https://remotive.com/api/remote-jobs?category=data&limit=100")
    if not r:
        print("    ↳ API unreachable")
        return []

    jobs = []
    matched = skipped_title = skipped_age = 0
    for j in r.json().get("jobs", []):
        title = j.get("title", "")
        if not title_matches(title):
            skipped_title += 1
            continue
        if not within_lookback(j.get("publication_date", ""), lookback_hours):
            skipped_age += 1
            continue
        matched += 1
        jobs.append(make_job(
            title,
            j.get("company_name", ""),
            j.get("candidate_required_location", "Remote"),
            "Remote",
            j.get("publication_date", ""),
            j.get("description", ""),
            j.get("salary", ""),
            j.get("url", ""),
            "Remotive",
        ))

    print(f"    ↳ kept: {matched}  | skipped title: {skipped_title}  | skipped age: {skipped_age}")
    return jobs


# ─────────────────────────────────────────────────────────────
#  SCRAPER 4 — REMOTEOK (public API)
# ─────────────────────────────────────────────────────────────

def scrape_remoteok(lookback_hours: int = 48) -> List[dict]:
    print(f"  ▶ RemoteOK...")
    jobs_all = []
    tags = ["data-engineer", "analytics", "python", "sql", "spark", "airflow"]

    for tag in tags:
        r = safe_get(f"https://remoteok.com/api?tag={tag}",
                     headers={**HEADERS, "Accept": "application/json"})
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
                continue
            if not within_lookback(j.get("date", ""), lookback_hours):
                continue
            url = j.get("url", "")
            if not url.startswith("http"):
                url = f"https://remoteok.com{url}"
            jobs_all.append(make_job(
                j.get("position", ""),
                j.get("company", ""),
                j.get("location", "Remote"),
                "Remote",
                j.get("date", ""),
                " ".join(j.get("tags", [])),
                (f"${j['salary_min']}-${j['salary_max']}"
                 if j.get("salary_min") else ""),
                url,
                "RemoteOK",
            ))
        time.sleep(1)  # Rate limit between tag requests

    # Deduplicate by URL
    seen = set()
    unique = []
    for j in jobs_all:
        if j["job_url"] not in seen:
            seen.add(j["job_url"])
            unique.append(j)

    print(f"    ↳ kept: {len(unique)} (across {len(tags)} tags)")
    return unique


# ─────────────────────────────────────────────────────────────
#  SCRAPER 5 — WEWORKREMOTELY (RSS feed)
# ─────────────────────────────────────────────────────────────

def scrape_weworkremotely(lookback_hours: int = 48) -> List[dict]:
    print(f"  ▶ WeWorkRemotely...")
    feeds = [
        "https://weworkremotely.com/categories/remote-data-science-jobs.rss",
        "https://weworkremotely.com/categories/remote-programming-jobs.rss",
        "https://weworkremotely.com/categories/remote-devops-sysadmin-jobs.rss",
    ]
    jobs = []
    matched = skipped_title = skipped_age = 0

    for feed_url in feeds:
        r = safe_get(feed_url)
        if not r:
            continue
        try:
            root = ET.fromstring(r.content)
        except Exception:
            continue

        for item in root.findall(".//item"):
            raw = (item.findtext("title") or "").strip()
            raw = re.sub(r"<!\[CDATA\[|\]\]>", "", raw).strip()
            if ":" in raw:
                company = raw.split(":")[0].strip()
                title   = ":".join(raw.split(":")[1:]).strip()
            else:
                company, title = "", raw

            if not title_matches(title):
                skipped_title += 1
                continue
            pub = item.findtext("pubDate", "")
            if not within_lookback(pub, lookback_hours):
                skipped_age += 1
                continue

            # Get link from text node after <link>
            link = ""
            for child in item:
                if child.tag == "link":
                    link = (child.text or "").strip()
                    break
            if not link:
                link = item.findtext("guid", "")

            matched += 1
            jobs.append(make_job(
                title, company, "Remote", "Remote", pub,
                re.sub(r"<[^>]+>", "", item.findtext("description", "")),
                "", link, "WeWorkRemotely",
            ))

    print(f"    ↳ kept: {matched}  | skipped title: {skipped_title}  | skipped age: {skipped_age}")
    return jobs


# ─────────────────────────────────────────────────────────────
#  SCRAPER 6 — JOBICY (free public API)
# ─────────────────────────────────────────────────────────────

def scrape_jobicy(lookback_hours: int = 48) -> List[dict]:
    print(f"  ▶ Jobicy...")
    tags = ["data-engineer", "data", "python", "sql"]
    jobs_all = []

    for tag in tags:
        r = safe_get(f"https://jobicy.com/api/v2/remote-jobs?count=50&tag={tag}")
        if not r:
            continue
        try:
            data = r.json()
        except Exception:
            continue
        for j in data.get("jobs", []):
            if not title_matches(j.get("jobTitle", "")):
                continue
            if not within_lookback(j.get("pubDate", ""), lookback_hours):
                continue
            jobs_all.append(make_job(
                j.get("jobTitle", ""),
                j.get("companyName", ""),
                j.get("jobGeo", "Remote"),
                "Remote",
                j.get("pubDate", ""),
                j.get("jobDescription", ""),
                str(j.get("annualSalaryMin", "")),
                j.get("url", ""),
                "Jobicy",
            ))

    seen = set()
    unique = []
    for j in jobs_all:
        if j["job_url"] not in seen:
            seen.add(j["job_url"])
            unique.append(j)

    print(f"    ↳ kept: {len(unique)}")
    return unique


# ─────────────────────────────────────────────────────────────
#  SCRAPER 7 — SMARTRECRUITERS (public REST API)
# ─────────────────────────────────────────────────────────────

def scrape_smartrecruiters(lookback_hours: int = 48) -> List[dict]:
    print(f"  ▶ SmartRecruiters ATS ({len(SMARTRECRUITERS_COMPANIES)} companies)...")
    jobs = []
    matched = skipped_title = skipped_loc = skipped_age = 0

    for company in SMARTRECRUITERS_COMPANIES:
        r = safe_get(
            f"https://api.smartrecruiters.com/v1/companies/{company}"
            f"/postings?status=PUBLIC&limit=100",
            params={"q": "data engineer"},
        )
        if not r:
            continue
        try:
            data = r.json()
        except Exception:
            continue

        for j in data.get("content", []):
            title = j.get("name", "")
            if not title_matches(title):
                skipped_title += 1
                continue
            loc = j.get("location", {}) or {}
            location = f"{loc.get('city','')}, {loc.get('country','')}".strip(", ")
            if not is_us_or_remote(location):
                skipped_loc += 1
                continue
            if not within_lookback(j.get("releasedDate", ""), lookback_hours):
                skipped_age += 1
                continue
            matched += 1
            jobs.append(make_job(
                title, company, location, "", j.get("releasedDate", ""),
                "", "",
                f"https://jobs.smartrecruiters.com/{company}/{j.get('id','')}",
                "SmartRecruiters ATS",
            ))

    print(f"    ↳ kept: {matched}  | "
          f"skipped title: {skipped_title}  | "
          f"skipped location: {skipped_loc}  | "
          f"skipped age: {skipped_age}")
    return jobs


# ─────────────────────────────────────────────────────────────
#  SCRAPER 8 — INDEED via Apify actor
# ─────────────────────────────────────────────────────────────

def scrape_indeed_apify(client, lookback_hours: int = 48) -> List[dict]:
    """Uses misceres/indeed-scraper Apify actor."""
    print(f"  ▶ Indeed (Apify)...")
    try:
        run = client.actor("misceres/indeed-scraper").call(
            run_input={
                "queries": [
                    {"position": "Data Engineer",
                     "country": "US", "location": "United States", "maxItems": 50},
                    {"position": "Analytics Engineer",
                     "country": "US", "location": "United States", "maxItems": 30},
                    {"position": "ETL Engineer",
                     "country": "US", "location": "United States", "maxItems": 30},
                    {"position": "Data Platform Engineer",
                     "country": "US", "location": "United States", "maxItems": 20},
                ],
                "maxItems":   130,
                "timePosted": "last24hours",
            },
            timeout_secs=300,
        )
        items = list(client.dataset(run["defaultDatasetId"]).iterate_items())
        jobs  = []
        skipped_title = skipped_loc = skipped_age = 0
        for item in items:
            title = item.get("title", "")
            if not title_matches(title):
                skipped_title += 1
                continue
            loc = item.get("location", "")
            if not is_us_or_remote(loc):
                skipped_loc += 1
                continue
            if not within_lookback(item.get("postedAt", ""), lookback_hours):
                skipped_age += 1
                continue
            jobs.append(make_job(
                title,
                item.get("company", ""),
                loc,
                "",
                item.get("postedAt", ""),
                item.get("description", ""),
                item.get("salary", ""),
                item.get("url", ""),
                "Indeed",
            ))
        print(f"    ↳ {len(items)} raw  |  kept: {len(jobs)}  |  "
              f"skipped title: {skipped_title}  |  "
              f"skipped location: {skipped_loc}  |  "
              f"skipped age: {skipped_age}")
        return jobs
    except Exception as e:
        print(f"    ⚠️  Indeed FAILED: {e}")
        return []


# ─────────────────────────────────────────────────────────────
#  SCRAPER 9 — MYVISAJOBS via Apify cheerio-scraper
# ─────────────────────────────────────────────────────────────

def scrape_myvisajobs_apify(client, lookback_hours: int = 48) -> List[dict]:
    """H1B-sponsoring employers — uses Apify cheerio-scraper."""
    print(f"  ▶ MyVisaJobs (Apify)...")
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
                        $('table tr').each((i, row) => {
                            if (i === 0) return;
                            const cells = $(row).find('td');
                            if (cells.length < 3) return;
                            const a = cells.eq(0).find('a').first();
                            const title = a.text().trim();
                            if (!title) return;
                            jobs.push({
                                job_title:    title,
                                company_name: cells.eq(1).text().trim(),
                                location:     cells.eq(2).text().trim(),
                                posting_date: cells.length > 3 ? cells.eq(3).text().trim() : '',
                                salary: '', remote_or_hybrid: '',
                                job_description: 'H1B visa sponsorship available',
                                job_url: 'https://www.myvisajobs.com' + (a.attr('href') || ''),
                                platform_name: 'MyVisaJobs'
                            });
                        });
                        return jobs;
                    }
                """,
                "maxRequestsPerCrawl": 4,
            },
            timeout_secs=120,
        )
        items = list(client.dataset(run["defaultDatasetId"]).iterate_items())
        jobs  = []
        for item in items:
            title = item.get("job_title", "")
            if not title_matches(title):
                continue
            if not is_us_or_remote(item.get("location", "")):
                continue
            jobs.append(item)
        print(f"    ↳ {len(items)} raw  |  kept: {len(jobs)}")
        return jobs
    except Exception as e:
        print(f"    ⚠️  MyVisaJobs FAILED: {e}")
        return []


# ─────────────────────────────────────────────────────────────
#  MASTER SCRAPE FUNCTION
# ─────────────────────────────────────────────────────────────

def run_all_scrapers(apify_client, lookback_hours: int = 48) -> List[dict]:
    """
    Run all scrapers and return combined, deduplicated job list.
    Direct API scrapers run first (most reliable), then Apify actors.
    """
    all_jobs = []

    print("\n📡 Direct API scrapers (free, no Apify needed):")
    all_jobs += scrape_greenhouse(lookback_hours)
    all_jobs += scrape_lever(lookback_hours)
    all_jobs += scrape_remotive(lookback_hours)
    all_jobs += scrape_remoteok(lookback_hours)
    all_jobs += scrape_weworkremotely(lookback_hours)
    all_jobs += scrape_jobicy(lookback_hours)
    all_jobs += scrape_smartrecruiters(lookback_hours)
    print(f"  Direct API subtotal: {len(all_jobs)} jobs")

    print("\n📡 Apify actor scrapers:")
    if apify_client:
        all_jobs += scrape_indeed_apify(apify_client, lookback_hours)
        all_jobs += scrape_myvisajobs_apify(apify_client, lookback_hours)

    # Deduplicate by URL
    seen_urls = set()
    seen_keys = set()
    unique = []
    for job in all_jobs:
        url = job.get("job_url", "").strip()
        key = (
            re.sub(r"\s+", "", job.get("company_name", "").lower()) + "|" +
            re.sub(r"\s+", "", job.get("job_title", "").lower())
        )
        if url and url in seen_urls:
            continue
        if key in seen_keys:
            continue
        if url:
            seen_urls.add(url)
        seen_keys.add(key)
        unique.append(job)

    print(f"\n  ✅ Total unique jobs collected: {len(unique)}")
    return unique
