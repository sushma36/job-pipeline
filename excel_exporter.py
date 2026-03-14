"""
=============================================================
  EXCEL EXPORTER — Generates data_engineer_jobs.xlsx
=============================================================
"""

import openpyxl
from openpyxl.styles import (
    Font, PatternFill, Alignment, Border, Side, GradientFill
)
from openpyxl.utils import get_column_letter
from openpyxl.styles.numbers import FORMAT_DATE_DATETIME
from openpyxl.formatting.rule import ColorScaleRule, CellIsRule
from datetime import datetime


# ─── COLOR PALETTE ──────────────────────────────────────────
C_HEADER_BG   = "1E3A5F"   # Deep navy
C_HEADER_FG   = "FFFFFF"   # White
C_APPLY_BG    = "D6EFCD"   # Soft green
C_SKIP_BG     = "FCE4D6"   # Soft red-orange
C_ALT_ROW     = "F2F7FC"   # Very light blue
C_WHITE       = "FFFFFF"
C_ACCENT      = "2E75B6"   # Mid blue (score bar)
C_BORDER      = "B0C4DE"   # Steel blue border
C_TITLE_BG    = "13315C"   # Dark navy title bar
C_SCORE_HIGH  = "375623"   # Dark green (score ≥ 85)
C_SCORE_MED   = "7F6000"   # Dark amber (score 70-84)
C_SUMMARY_BG  = "EBF3FB"   # Light info panel bg


# ─── COLUMN DEFINITIONS ─────────────────────────────────────
COLUMNS = [
    ("Job Title",       28),
    ("Company",         22),
    ("Platform",        18),
    ("Location",        22),
    ("Work Mode",       14),
    ("Posted Date",     14),
    ("Match Score",     13),
    ("Matched Skills",  40),
    ("Missing Skills",  32),
    ("Recommendation",  16),
    ("Job URL",         40),
]

SUMMARY_COLS = ["A", "B", "C", "D", "E"]


def _thin_border(color=C_BORDER):
    s = Side(style="thin", color=color)
    return Border(left=s, right=s, top=s, bottom=s)


def _bottom_border(color=C_BORDER):
    return Border(bottom=Side(style="thin", color=color))


def export_to_excel(jobs: list, output_path: str = "data_engineer_jobs.xlsx"):
    """
    Write scored+deduped jobs to a richly formatted Excel workbook.
    Creates two sheets:
      Sheet 1: Jobs (main results table)
      Sheet 2: How It Works (scoring guide + platform list)
    """
    wb = openpyxl.Workbook()

    _build_jobs_sheet(wb, jobs)
    _build_guide_sheet(wb, jobs)

    wb.save(output_path)
    print(f"✅ Exported {len(jobs)} jobs → {output_path}")
    return output_path


# ─── SHEET 1: JOBS ──────────────────────────────────────────

def _build_jobs_sheet(wb, jobs):
    ws = wb.active
    ws.title = "🔍 Job Matches"

    # ── Title banner ──────────────────────────────────────────
    ws.merge_cells("A1:K1")
    title_cell = ws["A1"]
    title_cell.value = "🚀  DATA ENGINEER JOB MATCHES  •  Sushma Dasari  •  Last 24 Hours"
    title_cell.font = Font(name="Arial", bold=True, size=14, color=C_HEADER_FG)
    title_cell.fill = PatternFill("solid", fgColor=C_TITLE_BG)
    title_cell.alignment = Alignment(horizontal="center", vertical="center")
    ws.row_dimensions[1].height = 32

    # ── Metadata row ─────────────────────────────────────────
    ws.merge_cells("A2:K2")
    meta = ws["A2"]
    run_time = datetime.now().strftime("%B %d, %Y  %I:%M %p")
    meta.value = f"Generated: {run_time}  •  Match threshold: ≥ 70  •  Sorted: Newest first, then by match score"
    meta.font = Font(name="Arial", italic=True, size=10, color="555555")
    meta.fill = PatternFill("solid", fgColor="EBF3FB")
    meta.alignment = Alignment(horizontal="center", vertical="center")
    ws.row_dimensions[2].height = 18

    # ── Stats row ─────────────────────────────────────────────
    _write_stats_row(ws, jobs, row=3)

    # ── Column headers ────────────────────────────────────────
    header_row = 5
    for col_idx, (col_name, col_width) in enumerate(COLUMNS, start=1):
        cell = ws.cell(row=header_row, column=col_idx, value=col_name)
        cell.font      = Font(name="Arial", bold=True, size=10, color=C_HEADER_FG)
        cell.fill      = PatternFill("solid", fgColor=C_HEADER_BG)
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        cell.border    = _thin_border()
        ws.column_dimensions[get_column_letter(col_idx)].width = col_width
    ws.row_dimensions[header_row].height = 28

    # ── Data rows ─────────────────────────────────────────────
    for row_offset, job in enumerate(jobs):
        data_row = header_row + 1 + row_offset
        is_alt   = (row_offset % 2 == 1)
        is_apply = "Apply" in job.get("recommendation", "")

        row_bg = C_APPLY_BG if is_apply else (C_ALT_ROW if is_alt else C_WHITE)

        score = job.get("match_score", 0)
        score_color = C_SCORE_HIGH if score >= 85 else C_SCORE_MED

        values = [
            job.get("job_title", ""),
            job.get("company_name", ""),
            job.get("platform_name", ""),
            job.get("location", ""),
            job.get("remote_or_hybrid", ""),
            job.get("posting_date", ""),
            score,
            job.get("matched_skills", ""),
            job.get("missing_skills", ""),
            job.get("recommendation", ""),
            job.get("job_url", ""),
        ]

        for col_idx, value in enumerate(values, start=1):
            cell = ws.cell(row=data_row, column=col_idx, value=value)
            cell.border    = _thin_border()
            cell.alignment = Alignment(vertical="top", wrap_text=True)
            cell.font      = Font(name="Arial", size=9)

            # Row background
            if col_idx != 7:   # score column gets special treatment
                cell.fill = PatternFill("solid", fgColor=row_bg)

            # ── Score column: bold + colored ──────────────────
            if col_idx == 7:
                cell.font      = Font(name="Arial", bold=True, size=11, color=score_color)
                cell.alignment = Alignment(horizontal="center", vertical="center")
                cell.fill      = PatternFill("solid", fgColor=row_bg)

            # ── Recommendation column ─────────────────────────
            if col_idx == 10:
                cell.font      = Font(name="Arial", bold=True, size=10,
                                      color="375623" if is_apply else "8B0000")
                cell.alignment = Alignment(horizontal="center", vertical="center")

            # ── URL column: hyperlink style ────────────────────
            if col_idx == 11 and value:
                cell.hyperlink = value
                cell.font      = Font(name="Arial", size=9, color="0563C1", underline="single")
                cell.value     = "🔗 Open Job"

            # ── Date column ───────────────────────────────────
            if col_idx == 6:
                cell.alignment = Alignment(horizontal="center", vertical="top")

        ws.row_dimensions[data_row].height = 55

    # ── Freeze panes ──────────────────────────────────────────
    ws.freeze_panes = f"A{header_row + 1}"

    # ── Auto-filter ───────────────────────────────────────────
    last_row = header_row + len(jobs)
    ws.auto_filter.ref = f"A{header_row}:K{last_row}"

    # ── Color scale on Match Score column (G) ─────────────────
    if jobs:
        score_range = f"G{header_row + 1}:G{last_row}"
        ws.conditional_formatting.add(
            score_range,
            ColorScaleRule(
                start_type="num", start_value=70, start_color="FCE4D6",
                mid_type="num",   mid_value=80,   mid_color="FFEB9C",
                end_type="num",   end_value=100,  end_color="C6EFCE",
            )
        )


def _write_stats_row(ws, jobs, row: int):
    """Write a mini-summary stats bar above the table."""
    ws.merge_cells(f"A{row}:K{row}")
    ws.row_dimensions[row].height = 14  # spacer


def _score_bar(score: int) -> str:
    filled = round(score / 10)
    return "█" * filled + "░" * (10 - filled) + f"  {score}%"


# ─── SHEET 2: GUIDE ──────────────────────────────────────────

def _build_guide_sheet(wb, jobs):
    ws = wb.create_sheet("📋 Scoring Guide")

    def _hdr(row, col, text, bg=C_HEADER_BG, fg=C_HEADER_FG, span=None):
        if span:
            ws.merge_cells(f"{get_column_letter(col)}{row}:{get_column_letter(col + span - 1)}{row}")
        cell = ws.cell(row=row, column=col, value=text)
        cell.font      = Font(name="Arial", bold=True, size=11, color=fg)
        cell.fill      = PatternFill("solid", fgColor=bg)
        cell.alignment = Alignment(horizontal="center", vertical="center")
        cell.border    = _thin_border()
        ws.row_dimensions[row].height = 22
        return cell

    def _row(row, col, label, value, bg=C_WHITE):
        lc = ws.cell(row=row, column=col, value=label)
        lc.font      = Font(name="Arial", bold=True, size=10)
        lc.fill      = PatternFill("solid", fgColor=bg)
        lc.alignment = Alignment(vertical="top")
        lc.border    = _thin_border()

        vc = ws.cell(row=row, column=col + 1, value=value)
        vc.font      = Font(name="Arial", size=10)
        vc.fill      = PatternFill("solid", fgColor=bg)
        vc.alignment = Alignment(vertical="top", wrap_text=True)
        vc.border    = _thin_border()
        ws.row_dimensions[row].height = 18

    # ── Title ──
    ws.merge_cells("A1:D1")
    t = ws["A1"]
    t.value     = "How This System Works — Scoring & Platform Guide"
    t.font      = Font(name="Arial", bold=True, size=13, color=C_HEADER_FG)
    t.fill      = PatternFill("solid", fgColor=C_TITLE_BG)
    t.alignment = Alignment(horizontal="center", vertical="center")
    ws.row_dimensions[1].height = 28

    # ── Scoring weights ──
    r = 3
    _hdr(r, 1, "📊 Match Score Weights (out of 100)", span=3)
    weights = [
        ("Skills Overlap",          "40%",  "Resume skills found in job description"),
        ("Tech Stack Match",         "25%",  "Python, Spark, Airflow, Snowflake, AWS, dbt, Kafka, etc."),
        ("Experience Level Fit",     "15%",  "Junior/Mid = high score; Senior/Management = lower score"),
        ("Domain Relevance",         "10%",  "Healthcare, enterprise, analytics, cloud domains"),
        ("Education Requirements",   "10%",  "MS CS = full score for BS/MS roles; PhD roles penalized"),
    ]
    alt = [C_ALT_ROW, C_WHITE]
    for i, (name, pct, desc) in enumerate(weights):
        r += 1
        bg = alt[i % 2]
        ws.cell(row=r, column=1, value=name).font  = Font(name="Arial", bold=True, size=10)
        ws.cell(row=r, column=1).fill              = PatternFill("solid", fgColor=bg)
        ws.cell(row=r, column=1).border            = _thin_border()
        ws.cell(row=r, column=2, value=pct).font   = Font(name="Arial", bold=True, size=10, color=C_ACCENT)
        ws.cell(row=r, column=2).alignment         = Alignment(horizontal="center")
        ws.cell(row=r, column=2).fill              = PatternFill("solid", fgColor=bg)
        ws.cell(row=r, column=2).border            = _thin_border()
        ws.cell(row=r, column=3, value=desc).font  = Font(name="Arial", size=10)
        ws.cell(row=r, column=3).fill              = PatternFill("solid", fgColor=bg)
        ws.cell(row=r, column=3).border            = _thin_border()
        ws.row_dimensions[r].height = 18

    # ── Platforms ──
    r += 2
    _hdr(r, 1, "🌐 Scraped Platforms", span=3)
    platforms = [
        ("Indeed",              "General",          "misceres/indeed-scraper",          "?t=1 for 24hr filter"),
        ("LinkedIn",            "Professional",     "curious_coder/linkedin-jobs-scraper","Session cookie needed"),
        ("Wellfound",           "Startup/VC",       "epctex/wellfound-scraper",          "Startup & seed-stage roles"),
        ("RemoteOK",            "Remote-first",     "epctex/remoteok-scraper",           "Public API available"),
        ("We Work Remotely",    "Remote-curated",   "epctex/we-work-remotely-scraper",   "Filter post-scrape by date"),
        ("Remotive",            "Remote-tech",      "apify/web-scraper",                 "Free public JSON API"),
        ("SimplyHired",         "Aggregator",       "apify/web-scraper",                 "?t=1 for 24hr filter"),
        ("Jooble",              "Aggregator-Intl",  "apify/web-scraper",                 "Has official API"),
        ("YC Work at a Startup","Startup",          "epctex/y-combinator-jobs-scraper",  "YC-backed companies only"),
        ("Handshake",           "Entry-level",      "apify/puppeteer-scraper",           "SPA — needs headless Chrome"),
        ("MyVisaJobs",          "Visa/H1B",         "apify/web-scraper",                 "Tracks H1B sponsorship history"),
        ("Otta",                "Growth-tech",      "apify/puppeteer-scraper",           "Login may be needed for JD"),
    ]
    _hdr(r + 1, 1, "Platform", bg="2E4057", span=1)
    _hdr(r + 1, 2, "Type", bg="2E4057", span=1)
    _hdr(r + 1, 3, "Apify Actor", bg="2E4057", span=1)
    _hdr(r + 1, 4, "Notes", bg="2E4057", span=1)
    r += 1
    for i, (name, ptype, actor, notes) in enumerate(platforms):
        r += 1
        bg = alt[i % 2]
        for c, val in enumerate([name, ptype, actor, notes], start=1):
            cell = ws.cell(row=r, column=c, value=val)
            cell.font      = Font(name="Arial", size=10, bold=(c == 1))
            cell.fill      = PatternFill("solid", fgColor=bg)
            cell.border    = _thin_border()
            cell.alignment = Alignment(vertical="top")
        ws.row_dimensions[r].height = 18

    # ── Run stats ──
    r += 2
    _hdr(r, 1, "📈 Run Statistics", span=2)
    apply_count = sum(1 for j in jobs if "Apply" in j.get("recommendation", ""))
    avg_score   = round(sum(j.get("match_score", 0) for j in jobs) / max(len(jobs), 1))
    platforms_hit = len(set(j.get("platform_name", "") for j in jobs))
    stats = [
        ("Total Jobs After Filtering",  len(jobs)),
        ("Recommended to Apply",        apply_count),
        ("Average Match Score",         f"{avg_score}/100"),
        ("Platforms Represented",       platforms_hit),
        ("Minimum Score Threshold",     "70 / 100"),
        ("Last Run",                    datetime.now().strftime("%Y-%m-%d %H:%M")),
    ]
    for i, (label, val) in enumerate(stats):
        r += 1
        bg = alt[i % 2]
        _row(r, 1, label, val, bg=bg)

    # ── Column widths ──
    ws.column_dimensions["A"].width = 25
    ws.column_dimensions["B"].width = 18
    ws.column_dimensions["C"].width = 35
    ws.column_dimensions["D"].width = 38


# ─── MAIN ────────────────────────────────────────────────────

if __name__ == "__main__":
    # Import sample data + run matcher
    import sys
    sys.path.insert(0, ".")
    from resume_matcher import SAMPLE_JOBS, filter_and_score, deduplicate

    filtered = filter_and_score(SAMPLE_JOBS, min_score=70)
    deduped  = deduplicate(filtered)

    path = export_to_excel(deduped, "data_engineer_jobs.xlsx")
    print(f"Wrote: {path}  ({len(deduped)} jobs)")
