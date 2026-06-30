"""
run_pipeline.py
===============
Scrape → Score → Dedup → Export → Email
"""

import os, smtplib, ssl
from email.mime.multipart import MIMEMultipart
from email.mime.text       import MIMEText
from email.mime.base       import MIMEBase
from email                 import encoders
from datetime              import datetime
from collections           import Counter

try:
    from apify_client import ApifyClient
    HAS_APIFY = True
except ImportError:
    HAS_APIFY = False

from scrapers       import run_all_scrapers
from resume_matcher import filter_and_score, deduplicate
from excel_exporter import export_to_excel

# ── Config ────────────────────────────────────────────────────
APIFY_TOKEN    = os.environ.get("APIFY_TOKEN",    "")
GMAIL_USER     = os.environ.get("GMAIL_USER",     "sushma81932@gmail.com")
GMAIL_APP_PASS = os.environ.get("GMAIL_APP_PASS", "")
NOTIFY_EMAIL   = os.environ.get("NOTIFY_EMAIL",   "sushma81932@gmail.com")
RUN_SLOT       = os.environ.get("RUN_SLOT",       "")

WINDOW_HOURS   = 24      # primary scrape window
FALLBACK_HOURS = 72      # expand to this if < MIN_JOBS found
MIN_JOBS       = 10      # minimum jobs before expanding window
MIN_SCORE      = 50      # resume match threshold
FALLBACK_SCORE = 40      # auto-lower if < 10 jobs pass scoring
OUTPUT         = "data_engineer_jobs_last24h.xlsx"


# ── Email helpers ─────────────────────────────────────────────
def _build_html(jobs, run_date, slot, window):
    apply    = sum(1 for j in jobs if "Apply"    in j.get("recommendation",""))
    consider = sum(1 for j in jobs if "Consider" in j.get("recommendation",""))
    avg      = round(sum(j.get("match_score",0) for j in jobs)/max(len(jobs),1))
    expanded = sum(1 for j in jobs if "72h" in j.get("window_label",""))
    pcounts  = Counter(j.get("platform_name","") for j in jobs)
    pills    = " &nbsp;".join(
        f'<span style="background:#1E3A5F;color:#fff;padding:2px 8px;'
        f'border-radius:10px;font-size:11px;">{p}: {c}</span>'
        for p, c in sorted(pcounts.items(), key=lambda x: -x[1])
    )
    win_note = (f' <span style="background:#F9A825;color:#fff;padding:2px 8px;'
                f'border-radius:8px;font-size:11px;">⏰ {expanded} from 72h window</span>'
                if expanded else "")
    rows = ""
    for j in jobs:
        s   = j.get("match_score", 0)
        sc  = "#375623" if s >= 80 else "#7F6000" if s >= 60 else "#595959"
        rec = j.get("recommendation", "")
        rc  = "#375623" if "Apply" in rec else "#7F6000" if "Consider" in rec else "#8B0000"
        visa_icon = "🛂" if j.get("platform_name","") == "MyVisaJobs" else ""
        exp_icon  = "⏰" if "72h" in j.get("window_label","") else ""
        rows += f"""<tr style="border-bottom:1px solid #e0e0e0;">
          <td style="padding:8px 10px;font-weight:600;">{j.get('job_title','')} {visa_icon}{exp_icon}</td>
          <td style="padding:8px 10px;">{j.get('company_name','')}</td>
          <td style="padding:8px 10px;color:#555;font-size:11px;">{j.get('platform_name','')}</td>
          <td style="padding:8px 10px;color:#555;">{j.get('location','')}</td>
          <td style="padding:8px 10px;color:#555;">{j.get('remote_or_hybrid','')}</td>
          <td style="padding:8px 10px;text-align:center;font-weight:700;color:{sc};">{s}</td>
          <td style="padding:8px 10px;font-size:11px;">{j.get('matched_skills','')[:80]}…</td>
          <td style="padding:8px 10px;text-align:center;font-weight:700;color:{rc};">{rec}</td>
          <td style="padding:8px 10px;text-align:center;">
            <a href="{j.get('job_url','#')}" style="background:#1E3A5F;color:#fff;
               padding:4px 10px;border-radius:4px;text-decoration:none;font-size:12px;">Apply</a>
          </td></tr>"""

    badge = (f'<span style="background:#2E75B6;color:#fff;padding:3px 10px;'
             f'border-radius:12px;font-size:12px;">{slot}</span>' if slot else "")
    return f"""<html><body style="font-family:Arial,sans-serif;color:#222;max-width:1100px;margin:auto;">
      <div style="background:#13315C;color:#fff;padding:20px 28px;border-radius:8px 8px 0 0;">
        <h2 style="margin:0;">🚀 Data Engineer Jobs — United States &nbsp;{badge}</h2>
        <p style="margin:6px 0 0;opacity:.8;">{run_date} • Matched to Sushma Dasari's resume
          • 🛂 = H1B sponsorship • ⏰ = expanded 72h window</p>
      </div>
      <div style="background:#EBF3FB;padding:12px 28px;border-bottom:2px solid #c8dff5;">
        📋 <strong>{len(jobs)}</strong> jobs &nbsp;|&nbsp;
        ✅ <strong>{apply}</strong> Apply &nbsp;|&nbsp;
        ⚠️ <strong>{consider}</strong> Consider &nbsp;|&nbsp;
        📊 Avg: <strong>{avg}/100</strong>{win_note}
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
        🛂 = confirmed H1B sponsorship (MyVisaJobs) &nbsp;|&nbsp;
        ⏰ = found in 72h fallback window &nbsp;|&nbsp;
        Full details in attached Excel.
      </div>
    </body></html>"""


def _build_diag_html(all_jobs, filtered, window, sources_stats):
    run_date = datetime.now().strftime("%B %d, %Y %I:%M %p")
    pcounts  = Counter(j.get("platform_name","") for j in all_jobs)
    def clr(c): return "#375623" if c > 0 else "#999"
    rows = "".join(
        f"<tr><td style='padding:6px 12px;'>{p}</td>"
        f"<td style='padding:6px 12px;text-align:center;font-weight:bold;"
        f"color:{clr(c)};'>{c}</td></tr>"
        for p, c in sorted(pcounts.items(), key=lambda x: -x[1])
    ) or "<tr><td colspan='2' style='padding:12px;text-align:center;'>No data</td></tr>"
    return f"""<html><body style="font-family:Arial,sans-serif;max-width:600px;margin:auto;">
      <div style="background:#13315C;color:#fff;padding:20px;border-radius:8px 8px 0 0;">
        <h2 style="margin:0;">⚙️ Pipeline Health Check</h2>
        <p style="margin:6px 0 0;opacity:.8;">{run_date} — window: {window}h</p>
      </div>
      <div style="background:#FFF8E1;padding:16px 20px;border-left:4px solid #F9A825;">
        Pipeline ran — 0 jobs met threshold.<br><br>
        Raw jobs scraped: <strong>{len(all_jobs)}</strong><br>
        After resume scoring: <strong>{len(filtered)}</strong>
      </div>
      <table style="width:100%;border-collapse:collapse;font-size:13px;">
        <tr style="background:#1E3A5F;color:#fff;">
          <th style="padding:8px 12px;text-align:left;">Platform</th>
          <th style="padding:8px 12px;text-align:center;">Raw Jobs</th>
        </tr>{rows}
      </table>
    </body></html>"""


def _send(subject, html_body, excel_path=None):
    if not GMAIL_APP_PASS:
        return False
    msg            = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = f"Job Pipeline <{GMAIL_USER}>"
    msg["To"]      = NOTIFY_EMAIL
    msg.attach(MIMEText(html_body, "html"))
    if excel_path and os.path.exists(excel_path):
        with open(excel_path, "rb") as f:
            part = MIMEBase("application", "octet-stream")
            part.set_payload(f.read())
        encoders.encode_base64(part)
        part.add_header("Content-Disposition",
                        f'attachment; filename="{os.path.basename(excel_path)}"')
        msg.attach(part)
    ctx = ssl.create_default_context()
    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465, context=ctx) as s:
            s.login(GMAIL_USER, GMAIL_APP_PASS.replace(" ", ""))
            s.sendmail(GMAIL_USER, NOTIFY_EMAIL, msg.as_string())
        print(f"  ✅ Email → {NOTIFY_EMAIL}")
        return True
    except smtplib.SMTPAuthenticationError:
        print("  ❌ Gmail auth failed — check GMAIL_APP_PASS")
        return False
    except Exception as e:
        print(f"  ❌ Email error: {e}")
        return False


# ── Main pipeline ─────────────────────────────────────────────
def run_pipeline():
    print("=" * 65)
    print(f"  DATA ENGINEER PIPELINE  —  {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    if RUN_SLOT:
        print(f"  {RUN_SLOT}")
    print(f"  Primary window: {WINDOW_HOURS}h  |  Fallback: {FALLBACK_HOURS}h if <{MIN_JOBS} jobs")
    print("=" * 65)

    if not HAS_APIFY:
        print("❌ pip install apify-client"); return
    if not APIFY_TOKEN:
        print("❌ APIFY_TOKEN not set"); return

    client = ApifyClient(APIFY_TOKEN)

    # ── Step 1: Scrape (24h) ──────────────────────────────────
    all_jobs = run_all_scrapers(client, hours=WINDOW_HOURS)
    window_used = WINDOW_HOURS
    window_label = "24h"

    # ── Fail-safe: expand to 72h if too few results ───────────
    if len(all_jobs) < MIN_JOBS:
        print(f"\n⚠️  Only {len(all_jobs)} raw jobs in {WINDOW_HOURS}h — "
              f"expanding to {FALLBACK_HOURS}h...")
        extra = run_all_scrapers(client, hours=FALLBACK_HOURS)
        # Mark expanded-window jobs
        seen_urls = {j.get("job_url","") for j in all_jobs}
        added = 0
        for j in extra:
            if j.get("job_url","") not in seen_urls:
                j["window_label"] = "72h"
                all_jobs.append(j)
                added += 1
        window_used  = FALLBACK_HOURS
        window_label = "72h"
        print(f"  Added {added} more jobs from {FALLBACK_HOURS}h window")

    print(f"\n  ✅ Total raw jobs: {len(all_jobs)}")

    # ── Step 2: Score ─────────────────────────────────────────
    print(f"\n📊 Step 2: Resume matching (≥{MIN_SCORE})...")
    filtered = filter_and_score(
        all_jobs,
        min_score    = MIN_SCORE,
        fallback     = FALLBACK_SCORE,
        target       = MIN_JOBS,
        window_label = window_label,
    )

    # ── Step 3: Dedup ─────────────────────────────────────────
    print(f"\n🔄 Step 3: Dedup...")
    deduped = deduplicate(filtered)
    deduped.sort(
        key=lambda j: (j.get("posting_date",""), j["match_score"]),
        reverse=True,
    )
    print(f"  {len(deduped)} unique jobs")

    # ── Diagnostics ───────────────────────────────────────────
    total_sources = 8   # Greenhouse, Lever, RemoteOK, WWR, Remotive, Jobicy, Indeed, MyVisaJobs
    apply    = sum(1 for j in deduped if "Apply"    in j.get("recommendation",""))
    consider = sum(1 for j in deduped if "Consider" in j.get("recommendation",""))
    visa     = sum(1 for j in deduped if j.get("platform_name","") == "MyVisaJobs")
    expanded = sum(1 for j in deduped if "72h" in j.get("window_label",""))
    avg      = sum(j["match_score"] for j in deduped) // max(len(deduped), 1)

    print(f"""
{'─'*65}
  DIAGNOSTICS
  Total sources scanned  : {total_sources}
  Total raw jobs scraped : {len(all_jobs)}
  Jobs within {window_used}h window : {len(all_jobs)}
  Jobs passing scoring   : {len(deduped)}
  ✅ Apply               : {apply}
  ⚠️  Consider           : {consider}
  🛂 H1B sponsored       : {visa}
  ⏰ From 72h fallback   : {expanded}
  Avg match score        : {avg}/100
{'─'*65}""")

    if not deduped:
        print("\n⚠️  0 jobs — sending diagnostic email...")
        html = _build_diag_html(all_jobs, filtered, window_used, {})
        _send(f"⚙️ Pipeline — 0 matches | {datetime.now().strftime('%b %d %Y')}", html)
        return

    # ── Step 4: Export ────────────────────────────────────────
    print(f"\n📁 Step 4: Excel export → {OUTPUT}...")
    export_to_excel(deduped, OUTPUT)

    # ── Step 5: Email ─────────────────────────────────────────
    print(f"\n📧 Step 5: Email...")
    run_date  = datetime.now().strftime("%B %d, %Y")
    slot_tag  = f" | {RUN_SLOT}" if RUN_SLOT else ""
    win_tag   = f" ⏰72h" if expanded else ""
    _send(
        f"🔍 {len(deduped)} DE Jobs (US{win_tag}) — {apply} Apply | {run_date}{slot_tag}",
        _build_html(deduped, run_date, RUN_SLOT, window_used),
        OUTPUT,
    )

    print(f"\n{'='*65}")
    print(f"  DONE — {len(deduped)} jobs | {apply} Apply | Avg {avg}/100")
    print(f"  File: {OUTPUT}")
    print(f"{'='*65}")


if __name__ == "__main__":
    run_pipeline()
