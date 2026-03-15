"""
=============================================================
  run_pipeline.py — Main daily pipeline orchestrator
  Scrapes → Scores → Deduplicates → Exports → Emails
=============================================================
  ENV VARS REQUIRED:
    APIFY_TOKEN    — from apify.com → Settings → Integrations
    GMAIL_USER     — sushmads698@gmail.com
    GMAIL_APP_PASS — 16-char Gmail app password
    NOTIFY_EMAIL   — sushmads698@gmail.com
=============================================================
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

from scrapers       import run_all_scrapers
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
LOOKBACK_HRS   = 48   # look back 48hrs — catches everything since last run
MIN_SCORE      = 50   # primary threshold
FALLBACK_SCORE = 40   # auto-lower if fewer than 10 jobs pass
TARGET_COUNT   = 10   # minimum jobs to aim for


# =============================================================
#  EMAIL
# =============================================================

def _html_body(jobs: list, run_date: str, run_slot: str) -> str:
    apply_count   = sum(1 for j in jobs if "Apply"   in j.get("recommendation",""))
    consider_count= sum(1 for j in jobs if "Consider" in j.get("recommendation",""))
    avg           = round(sum(j.get("match_score",0) for j in jobs)/max(len(jobs),1))
    platform_counts = Counter(j.get("platform_name","") for j in jobs)
    pills = " &nbsp;".join(
        f'<span style="background:#1E3A5F;color:#fff;padding:2px 8px;'
        f'border-radius:10px;font-size:11px;">{p}: {c}</span>'
        for p,c in sorted(platform_counts.items(), key=lambda x:-x[1])
    )
    rows = ""
    for j in jobs:
        score = j.get("match_score",0)
        sc = "#375623" if score>=80 else "#7F6000" if score>=65 else "#595959"
        rec = j.get("recommendation","")
        rc  = "#375623" if "Apply" in rec else "#7F6000" if "Consider" in rec else "#8B0000"
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
            <a href="{j.get('job_url','#')}" style="background:#1E3A5F;color:#fff;
               padding:4px 10px;border-radius:4px;text-decoration:none;font-size:12px;">Apply</a>
          </td></tr>"""
    slot_badge = (
        f'<span style="background:#2E75B6;color:#fff;padding:3px 10px;'
        f'border-radius:12px;font-size:12px;">{run_slot}</span>'
        if run_slot else ""
    )
    return f"""<html><body style="font-family:Arial,sans-serif;color:#222;max-width:1100px;margin:auto;">
      <div style="background:#13315C;color:#fff;padding:20px 28px;border-radius:8px 8px 0 0;">
        <h2 style="margin:0;">🚀 Data Engineer Job Matches &nbsp;{slot_badge}</h2>
        <p style="margin:6px 0 0;opacity:.8;">{run_date} • Matched to Sushma Dasari's resume</p>
      </div>
      <div style="background:#EBF3FB;padding:12px 28px;border-bottom:2px solid #c8dff5;">
        📋 <strong>{len(jobs)}</strong> jobs matched &nbsp;|&nbsp;
        ✅ <strong>{apply_count}</strong> Apply &nbsp;|&nbsp;
        ⚠️ <strong>{consider_count}</strong> Consider &nbsp;|&nbsp;
        📊 Avg score: <strong>{avg}/100</strong>
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
        Full matched/missing skill details in the attached Excel file.
      </div>
    </body></html>"""


def _send_diagnostic_email(all_jobs: list, filtered: list):
    """Email sent when 0 jobs pass — pipeline health check."""
    if GMAIL_APP_PASS == "YOUR_APP_PASSWORD_HERE":
        return
    run_date = datetime.now().strftime("%B %d, %Y %I:%M %p")
    platform_counts = Counter(j.get("platform_name","") for j in all_jobs)
    def color(c): return "#375623" if c > 0 else "#999"
    rows = "".join(
        f"<tr><td style='padding:6px 12px;'>{p}</td>"
        f"<td style='padding:6px 12px;text-align:center;font-weight:bold;"
        f"color:{color(c)};'>{c}</td></tr>"
        for p,c in sorted(platform_counts.items(), key=lambda x:-x[1])
    ) or "<tr><td colspan='2' style='padding:12px;text-align:center;color:#999;'>No data</td></tr>"
    html = f"""<html><body style="font-family:Arial,sans-serif;max-width:600px;margin:auto;">
      <div style="background:#13315C;color:#fff;padding:20px;border-radius:8px 8px 0 0;">
        <h2 style="margin:0;">⚙️ Pipeline Health Check</h2>
        <p style="margin:6px 0 0;opacity:.8;">{run_date}</p>
      </div>
      <div style="background:#FFF8E1;padding:16px 20px;border-left:4px solid #F9A825;">
        Pipeline ran but 0 jobs met the score threshold ({MIN_SCORE}).<br><br>
        Raw jobs collected: <strong>{len(all_jobs)}</strong><br>
        After resume scoring: <strong>{len(filtered)}</strong>
      </div>
      <table style="width:100%;border-collapse:collapse;font-size:13px;">
        <tr style="background:#1E3A5F;color:#fff;">
          <th style="padding:8px 12px;text-align:left;">Platform</th>
          <th style="padding:8px 12px;text-align:center;">Raw Jobs</th>
        </tr>{rows}
      </table>
      <div style="background:#f5f5f5;padding:12px 20px;font-size:12px;color:#777;border-radius:0 0 8px 8px;">
        Pipeline is alive and running on schedule.
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
            s.login(GMAIL_USER, GMAIL_APP_PASS.replace(" ",""))
            s.sendmail(GMAIL_USER, NOTIFY_EMAIL, msg.as_string())
        print(f"  ✅ Diagnostic email sent to {NOTIFY_EMAIL}")
    except Exception as e:
        print(f"  ❌ Diagnostic email failed: {e}")


def send_email(excel_path: str, jobs: list) -> bool:
    if GMAIL_APP_PASS == "YOUR_APP_PASSWORD_HERE":
        print("  ⚠️  Email skipped — GMAIL_APP_PASS not set.")
        return False
    run_date    = datetime.now().strftime("%B %d, %Y")
    apply_count = sum(1 for j in jobs if "Apply" in j.get("recommendation",""))
    slot_tag    = f" | {RUN_SLOT}" if RUN_SLOT else ""
    print(f"  📧 Sending to {NOTIFY_EMAIL}...")

    msg            = MIMEMultipart("alternative")
    msg["Subject"] = (f"🔍 {len(jobs)} DE Jobs — {apply_count} to Apply"
                      f" | {run_date}{slot_tag}")
    msg["From"]    = f"Job Pipeline <{GMAIL_USER}>"
    msg["To"]      = NOTIFY_EMAIL

    plain = (f"Data Engineer Jobs — {run_date}{slot_tag}\n"
             f"{len(jobs)} matched | {apply_count} to apply\n\n" +
             "\n".join(
                 f"[{j['match_score']}] {j['job_title']} @ "
                 f"{j['company_name']} ({j['platform_name']}) — {j['job_url']}"
                 for j in jobs))
    msg.attach(MIMEText(plain, "plain"))
    msg.attach(MIMEText(_html_body(jobs, run_date, RUN_SLOT), "html"))

    with open(excel_path, "rb") as f:
        part = MIMEBase("application", "octet-stream")
        part.set_payload(f.read())
    encoders.encode_base64(part)
    part.add_header("Content-Disposition",
                    f'attachment; filename="{os.path.basename(excel_path)}"')
    msg.attach(part)

    ctx = ssl.create_default_context()
    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465, context=ctx) as server:
            server.login(GMAIL_USER, GMAIL_APP_PASS.replace(" ",""))
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
    print(f"  DATA ENGINEER JOB PIPELINE  —  "
          f"{datetime.now().strftime('%Y-%m-%d %H:%M')}")
    if RUN_SLOT:
        print(f"  {RUN_SLOT}")
    print(f"  Lookback: {LOOKBACK_HRS}hrs  |  "
          f"Min score: {MIN_SCORE} (fallback: {FALLBACK_SCORE})")
    print("=" * 65)

    if not HAS_APIFY:
        print("❌ Run: pip install apify-client"); return
    if APIFY_TOKEN == "YOUR_APIFY_TOKEN_HERE":
        print("❌ Set APIFY_TOKEN environment variable."); return

    # ── Step 1: Scrape ────────────────────────────────────────
    client   = ApifyClient(APIFY_TOKEN)
    all_jobs = run_all_scrapers(client, lookback_hours=LOOKBACK_HRS)

    # ── Step 2: Score ─────────────────────────────────────────
    print(f"\n📊 Step 2: Resume matching...")
    filtered = filter_and_score(
        all_jobs,
        min_score      = MIN_SCORE,
        fallback_score = FALLBACK_SCORE,
        target_count   = TARGET_COUNT,
    )
    print(f"  {len(filtered)} jobs after scoring")

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

    # ── Summary ───────────────────────────────────────────────
    avg      = sum(j["match_score"] for j in deduped) // len(deduped)
    apply    = sum(1 for j in deduped if "Apply"   in j.get("recommendation",""))
    consider = sum(1 for j in deduped if "Consider" in j.get("recommendation",""))
    by_plat  = Counter(j.get("platform_name","") for j in deduped)
    print(f"""
{'='*65}
  PIPELINE COMPLETE
  Total jobs    : {len(deduped)}
  ✅ Apply      : {apply}
  ⚠️  Consider  : {consider}
  Avg score     : {avg}/100
  By platform   : {dict(by_plat)}
  Excel saved   : {OUTPUT_PATH}
  Email sent to : {NOTIFY_EMAIL}
{'='*65}""")


if __name__ == "__main__":
    run_pipeline()
