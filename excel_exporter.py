"""
excel_exporter.py
=================
Exports scored jobs to data_engineer_jobs_last24h.xlsx
"""

from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter
from openpyxl.formatting.rule import ColorScaleRule
from datetime import datetime
from collections import Counter

C_NAVY   = "13315C"
C_HDR    = "1E3A5F"
C_WHITE  = "FFFFFF"
C_ALT    = "F2F7FC"
C_GREEN  = "D6EFCD"
C_AMBER  = "FFF3CD"
C_INFO   = "EBF3FB"
C_BDR    = "B0C4DE"

COLS = [
    ("Job Title",       32),
    ("Company",         22),
    ("Platform",        18),
    ("Location",        24),
    ("Work Mode",       12),
    ("Posting Date",    18),
    ("Match Score",     12),
    ("Matched Skills",  44),
    ("Missing Skills",  32),
    ("Recommendation",  15),
    ("Job URL",         45),
]


def _bdr():
    s = Side(style="thin", color=C_BDR)
    return Border(left=s, right=s, top=s, bottom=s)


def export_to_excel(jobs: list, path: str) -> str:
    wb = Workbook()
    _sheet_jobs(wb, jobs)
    _sheet_guide(wb, jobs)
    wb.save(path)
    print(f"✅ Exported {len(jobs)} jobs → {path}")
    return path


def _sheet_jobs(wb, jobs):
    ws = wb.active
    ws.title = "🔍 Job Matches"
    HDR = 5

    # Banner
    ws.merge_cells("A1:K1")
    c = ws["A1"]
    c.value     = ("🚀  DATA ENGINEER JOBS — UNITED STATES  •  "
                   "Sushma Dasari  •  Last 24 Hours")
    c.font      = Font(name="Arial", bold=True, size=14, color=C_WHITE)
    c.fill      = PatternFill("solid", fgColor=C_NAVY)
    c.alignment = Alignment(horizontal="center", vertical="center")
    ws.row_dimensions[1].height = 32

    # Meta
    apply    = sum(1 for j in jobs if "Apply"    in j.get("recommendation",""))
    consider = sum(1 for j in jobs if "Consider" in j.get("recommendation",""))
    ws.merge_cells("A2:K2")
    m = ws["A2"]
    m.value     = (f"Generated: {datetime.now().strftime('%B %d, %Y  %I:%M %p')}  •  "
                   f"{len(jobs)} jobs  •  ✅ {apply} Apply  •  ⚠️ {consider} Consider")
    m.font      = Font(name="Arial", italic=True, size=10, color="444444")
    m.fill      = PatternFill("solid", fgColor=C_INFO)
    m.alignment = Alignment(horizontal="center", vertical="center")
    ws.row_dimensions[2].height = 18
    ws.row_dimensions[3].height = 6
    ws.row_dimensions[4].height = 6

    # Headers
    for ci, (name, width) in enumerate(COLS, 1):
        cell = ws.cell(row=HDR, column=ci, value=name)
        cell.font      = Font(name="Arial", bold=True, size=10, color=C_WHITE)
        cell.fill      = PatternFill("solid", fgColor=C_HDR)
        cell.alignment = Alignment(horizontal="center", vertical="center",
                                   wrap_text=True)
        cell.border    = _bdr()
        ws.column_dimensions[get_column_letter(ci)].width = width
    ws.row_dimensions[HDR].height = 28

    # Rows
    for ri, j in enumerate(jobs):
        row = HDR + 1 + ri
        rec = j.get("recommendation", "")
        bg  = (C_GREEN if "Apply"   in rec else
               C_AMBER if "Consider" in rec else
               C_ALT   if ri % 2      else C_WHITE)
        score = j.get("match_score", 0)
        sc    = ("375623" if score >= 80 else
                 "7F6000" if score >= 60 else "595959")

        # Mark expanded-window jobs
        label = j.get("window_label", "")
        title_disp = j.get("job_title","")
        if "72h" in label:
            title_disp += " ⏰"   # clock = expanded window job

        vals = [
            title_disp,
            j.get("company_name",""),
            j.get("platform_name",""),
            j.get("location",""),
            j.get("remote_or_hybrid",""),
            j.get("posting_date",""),
            score,
            j.get("matched_skills",""),
            j.get("missing_skills",""),
            rec,
            j.get("job_url",""),
        ]
        for ci, val in enumerate(vals, 1):
            cell = ws.cell(row=row, column=ci, value=val)
            cell.border    = _bdr()
            cell.alignment = Alignment(vertical="top", wrap_text=True)
            cell.font      = Font(name="Arial", size=9)
            cell.fill      = PatternFill("solid", fgColor=bg)

            if ci == 7:   # Score
                cell.font      = Font(name="Arial", bold=True, size=11, color=sc)
                cell.alignment = Alignment(horizontal="center", vertical="center")

            if ci == 10:  # Rec
                rc = ("375623" if "Apply"   in rec else
                      "7F6000" if "Consider" in rec else "8B0000")
                cell.font      = Font(name="Arial", bold=True, size=10, color=rc)
                cell.alignment = Alignment(horizontal="center", vertical="center")

            if ci == 11 and val:  # URL
                cell.hyperlink = val
                cell.font      = Font(name="Arial", size=9,
                                      color="0563C1", underline="single")
                cell.value     = "🔗 Apply"

            if ci == 6:
                cell.alignment = Alignment(horizontal="center", vertical="top")

        ws.row_dimensions[row].height = 52

    ws.freeze_panes = f"A{HDR+1}"
    last = HDR + max(len(jobs), 1)
    ws.auto_filter.ref = f"A{HDR}:K{last}"

    if jobs:
        ws.conditional_formatting.add(
            f"G{HDR+1}:G{last}",
            ColorScaleRule(
                start_type="num", start_value=40,  start_color="FCE4D6",
                mid_type="num",   mid_value=65,    mid_color="FFEB9C",
                end_type="num",   end_value=100,   end_color="C6EFCE",
            )
        )


def _sheet_guide(wb, jobs):
    ws = wb.create_sheet("📋 Guide & Stats")

    def hdr(r, text, span=3):
        ws.merge_cells(f"A{r}:{get_column_letter(span)}{r}")
        c = ws["A" + str(r)]
        c.value     = text
        c.font      = Font(name="Arial", bold=True, size=11, color=C_WHITE)
        c.fill      = PatternFill("solid", fgColor=C_HDR)
        c.alignment = Alignment(horizontal="center", vertical="center")
        c.border    = _bdr()
        ws.row_dimensions[r].height = 22

    def row(r, label, value, bg=C_WHITE):
        lc = ws.cell(row=r, column=1, value=label)
        lc.font = Font(name="Arial", bold=True, size=10)
        lc.fill = PatternFill("solid", fgColor=bg)
        lc.border = _bdr()
        vc = ws.cell(row=r, column=2, value=value)
        vc.font = Font(name="Arial", size=10)
        vc.fill = PatternFill("solid", fgColor=bg)
        vc.border = _bdr()
        vc.alignment = Alignment(wrap_text=True)
        ws.row_dimensions[r].height = 18

    alt = [C_ALT, C_WHITE]

    ws.merge_cells("A1:C1")
    t = ws["A1"]
    t.value     = "Pipeline Run Summary & Guide"
    t.font      = Font(name="Arial", bold=True, size=13, color=C_WHITE)
    t.fill      = PatternFill("solid", fgColor=C_NAVY)
    t.alignment = Alignment(horizontal="center", vertical="center")
    ws.row_dimensions[1].height = 28

    r = 3
    hdr(r, "📈 Run Statistics")
    pcounts  = Counter(j.get("platform_name","") for j in jobs)
    apply    = sum(1 for j in jobs if "Apply"   in j.get("recommendation",""))
    consider = sum(1 for j in jobs if "Consider" in j.get("recommendation",""))
    avg      = round(sum(j.get("match_score",0) for j in jobs)/max(len(jobs),1))
    visa     = sum(1 for j in jobs if j.get("platform_name","") == "MyVisaJobs")
    expanded = sum(1 for j in jobs if "72h" in j.get("window_label",""))
    for i, (lbl, val) in enumerate([
        ("Total Jobs Matched",    len(jobs)),
        ("✅ Apply",              apply),
        ("⚠️ Consider",           consider),
        ("Average Match Score",   f"{avg}/100"),
        ("🛂 H1B Sponsored",      visa),
        ("⏰ Expanded (72h)",     expanded),
        ("Generated",             datetime.now().strftime("%Y-%m-%d %H:%M")),
    ]):
        r += 1
        row(r, lbl, val, alt[i % 2])

    r += 2
    hdr(r, "🌐 Jobs by Platform")
    for i, (p, c) in enumerate(sorted(pcounts.items(), key=lambda x: -x[1])):
        r += 1
        row(r, p, c, alt[i % 2])

    r += 2
    hdr(r, "📊 Score Weights")
    for i, (lbl, pct, desc) in enumerate([
        ("Skills Overlap",   "40%", "Resume skills in JD"),
        ("Tech Stack",       "25%", "Python/Spark/Airflow/Snowflake/AWS/dbt..."),
        ("Experience Level", "15%", "Mid=90%, Junior=100%, Senior=65%"),
        ("Domain Relevance", "10%", "Healthcare / fintech / enterprise / cloud"),
        ("Education",        "10%", "MS CS = full score"),
    ]):
        r += 1
        bg = alt[i % 2]
        ws.cell(row=r, column=1, value=lbl).font  = Font(name="Arial", bold=True, size=10)
        ws.cell(row=r, column=1).fill              = PatternFill("solid", fgColor=bg)
        ws.cell(row=r, column=1).border            = _bdr()
        ws.cell(row=r, column=2, value=pct).font   = Font(name="Arial", bold=True,
                                                           size=10, color="1E3A5F")
        ws.cell(row=r, column=2).alignment         = Alignment(horizontal="center")
        ws.cell(row=r, column=2).fill              = PatternFill("solid", fgColor=bg)
        ws.cell(row=r, column=2).border            = _bdr()
        ws.cell(row=r, column=3, value=desc).font  = Font(name="Arial", size=10)
        ws.cell(row=r, column=3).fill              = PatternFill("solid", fgColor=bg)
        ws.cell(row=r, column=3).border            = _bdr()
        ws.row_dimensions[r].height = 18

    r += 2
    hdr(r, "ℹ️  Legend")
    for i, (sym, desc) in enumerate([
        ("⏰ in title", "Job found via 72-hr expanded window (< 10 jobs in 24h)"),
        ("🛂 in email", "Confirmed H1B sponsorship (from MyVisaJobs)"),
        ("✅ Apply",    "Match score ≥ 70 — strong match"),
        ("⚠️ Consider", "Match score 50-69 — decent match"),
        ("⛔ Skip",     "Match score < 50 — weak match"),
    ]):
        r += 1
        row(r, sym, desc, alt[i % 2])

    for col, w in [("A", 26), ("B", 14), ("C", 45)]:
        ws.column_dimensions[col].width = w
