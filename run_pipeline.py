"""
run_pipeline.py
===============
Daily orchestrator: Scrape → Score → Dedup → Export → Email
"""

import os, smtplib, ssl
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders
from datetime import datetime
from collections import Counter

try:
    from apify_client import ApifyClient
    HAS_APIFY = True
except ImportError:
    HAS_APIFY = False

from scrapers        import run_all_scrapers
from resume_matcher  import filter_and_score, deduplicate
from excel_exporter  import export_to_excel

# ── Config ────────────────────────────────────────────────────
APIFY_TOKEN    = os.environ.get("APIFY_TOKEN",    "")
GMAIL_USER     = os.environ.get("GMAIL_USER",     "sushmads698@gmail.com")
GMAIL_APP_PASS = os.environ.get("GMAIL_APP_PASS", "")
NOTIFY_EMAIL   = os.environ.get("NOTIFY_EMAIL",   "sushmads698@gmail.com")
RUN_SLOT       = os.environ.get("RUN_SLOT",       "")

OUTPUT  = f"data_engineer_jobs_{datetime.now().strftime('%Y%m%d_%H%M')}.xlsx"
HOURS   = 168  # 7 days for job boards; ATS ignores date
MIN     = 50    # primary threshold
FALL    = 40    # fallback if fewer than 10 jobs pass
TARGET  = 10


def _html(jobs, run_date, slot):
    apply    = sum(1 for j in jobs if "Apply"   in j.get("recommendation",""))
    consider = sum(1 for j in jobs if "Consider" in j.get("recommendation",""))
    avg      = round(sum(j.get("match_score",0) for j in jobs)/max(len(jobs),1))
    pcounts  = Counter(j.get("platform_name","") for j in jobs)
    pills    = " &nbsp;".join(
        f'<span style="background:#1E3A5F;color:#fff;padding:2px 8px;'
        f'border-radius:10px;font-size:11px;">{p}: {c}</span>'
        for p,c in sorted(pcounts.items(), key=lambda x:-x[1])
    )
    rows = ""
    for j in jobs:
        s   = j.get("match_score",0)
        sc  = "#375623" if s>=80 else "#7F6000" if s>=60 else "#595959"
        rec = j.get("recommendation","")
        rc  = "#375623" if "Apply" in rec else "#7F6000" if "Consider" in rec else "#8B0000"
        visa = "🛂" if "MyVisaJobs" in j.get("platform_name","") else ""
        rows += f"""<tr style="border-bottom:1px solid #e0e0e0;">
          <td style="padding:8px 10px;font-weight:600;">{j.get('job_title','')} {visa}</td>
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
        <p style="margin:6px 0 0;opacity:.8;">{run_date} • Matched to Sushma Dasari's resume • 🛂 = H1B sponsorship</p>
      </div>
      <div style="background:#EBF3FB;padding:12px 28px;border-bottom:2px solid #c8dff5;">
        📋 <strong>{len(jobs)}</strong> jobs &nbsp;|&nbsp;
        ✅ <strong>{apply}</strong> Apply &nbsp;|&nbsp;
        ⚠️ <strong>{consider}</strong> Consider &nbsp;|&nbsp;
        📊 Avg: <strong>{avg}/100</strong>
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
        🛂 jobs from MyVisaJobs = confirmed H1B sponsorship history. Full details in Excel.
      </div>
    </body></html>"""


def _diag_email(all_jobs, filtered):
    if not GMAIL_APP_PASS: return
    run_date = datetime.now().strftime("%B %d, %Y %I:%M %p")
    pcounts  = Counter(j.get("platform_name","") for j in all_jobs)
    def clr(c): return "#375623" if c > 0 else "#999"
    rows = "".join(
        f"<tr><td style='padding:6px 12px;'>{p}</td>"
        f"<td style='padding:6px 12px;text-align:center;font-weight:bold;"
        f"color:{clr(c)};'>{c}</td></tr>"
        for p,c in sorted(pcounts.items(), key=lambda x:-x[1])
    ) or "<tr><td colspan='2' style='padding:12px;text-align:center;'>No data</td></tr>"
    html = f"""<html><body style="font-family:Arial,sans-serif;max-width:600px;margin:auto;">
      <div style="background:#13315C;color:#fff;padding:20px;border-radius:8px 8px 0 0;">
        <h2 style="margin:0;">⚙️ Pipeline Health Check</h2>
        <p style="margin:6px 0 0;opacity:.8;">{run_date}</p>
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
    _send(f"⚙️ Job Pipeline — 0 matches | {run_date}", html, None)


def _send(subject, html_body, excel_path):
    if not GMAIL_APP_PASS: return False
    msg            = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = f"Job Pipeline <{GMAIL_USER}>"
    msg["To"]      = NOTIFY_EMAIL
    msg.attach(MIMEText(html_body, "html"))
    if excel_path:
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
            s.login(GMAIL_USER, GMAIL_APP_PASS.replace(" ",""))
            s.sendmail(GMAIL_USER, NOTIFY_EMAIL, msg.as_string())
        print(f"  ✅ Email → {NOTIFY_EMAIL}")
        return True
    except smtplib.SMTPAuthenticationError:
        print("  ❌ Gmail auth failed")
        return False
    except Exception as e:
        print(f"  ❌ Email error: {e}")
        return False


def run_pipeline():
    print("=" * 65)
    print(f"  DATA ENGINEER PIPELINE  —  {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    if RUN_SLOT: print(f"  {RUN_SLOT}")
    print(f"  US-only jobs  |  Lookback: {HOURS}hrs  |  Score threshold: ≥{MIN}")
    print("=" * 65)

    if not HAS_APIFY:
        print("❌ pip install apify-client"); return
    if not APIFY_TOKEN:
        print("❌ APIFY_TOKEN not set"); return

    # Step 1 — Scrape
    client   = ApifyClient(APIFY_TOKEN)
    all_jobs = run_all_scrapers(client, hours=HOURS)

    # Step 2 — Score
    print(f"\n📊 Step 2: Resume matching...")
    filtered = filter_and_score(all_jobs, min_score=MIN, fallback=FALL, target=TARGET)

    # Step 3 — Dedup
    print(f"\n🔄 Step 3: Dedup...")
    deduped = deduplicate(filtered)
    deduped.sort(key=lambda j: (j.get("posting_date",""), j["match_score"]), reverse=True)
    print(f"  {len(deduped)} unique jobs")

    if not deduped:
        print("\n⚠️  No jobs — sending diagnostic email...")
        _diag_email(all_jobs, filtered)
        return

    # Step 4 — Export
    print(f"\n📁 Step 4: Excel export...")
    export_to_excel(deduped, OUTPUT)

    # Step 5 — Email
    print(f"\n📧 Step 5: Email...")
    run_date    = datetime.now().strftime("%B %d, %Y")
    apply_count = sum(1 for j in deduped if "Apply" in j.get("recommendation",""))
    slot_tag    = f" | {RUN_SLOT}" if RUN_SLOT else ""
    _send(
        f"🔍 {len(deduped)} DE Jobs (US) — {apply_count} Apply | {run_date}{slot_tag}",
        _html(deduped, run_date, RUN_SLOT),
        OUTPUT,
    )

    # Summary
    avg  = sum(j["match_score"] for j in deduped) // len(deduped)
    visa = sum(1 for j in deduped if "MyVisaJobs" in j.get("platform_name",""))
    print(f"""
{'='*65}
  DONE  |  {len(deduped)} jobs  |  ✅ {apply_count} Apply  |  Avg {avg}/100
  🛂 H1B-sponsored: {visa} jobs (from MyVisaJobs)
  File : {OUTPUT}
{'='*65}""")


if __name__ == "__main__":
    run_pipeline()
