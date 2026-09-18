"""
registry_writer.py — write the updated SKU Registry workbook.

The registry is the tool's memory: re-upload it next run and every confirmed
match is already locked, so the tool never asks about it again.
"""

from __future__ import annotations

import io
from datetime import date

import openpyxl
from openpyxl.formatting.rule import FormulaRule
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.datavalidation import DataValidation

from .registry import (
    DECISION_LINK,
    DECISIONS,
    SHEET_LOCKED,
    SHEET_NEW_ML,
    SHEET_NOT_SELLING,
    SHEET_NOT_YET,
    SHEET_REVIEW,
    SHEET_SUMMARY,
    SyncPlan,
    validation_summary,
)

# Hidden sheet holding the dropdown source lists. Referencing a real range
# (rather than an inline "a,b,c" formula) keeps the dropdowns working in both
# Excel and Google Sheets, and has no 255-character limit — which matters
# because the MP list runs to several hundred entries.
SHEET_LISTS = "_Lists"

# Spare rows below the data that also get the dropdown, so rows added by hand
# still validate.
SPARE_ROWS = 300

BAD_FILL = PatternFill("solid", fgColor="FFC7CE")   # decision set, MP missing
WARN_FILL = PatternFill("solid", fgColor="FFF2CC")  # MP filled, decision missing

MM_YELLOW = "FFE800"
MM_BLACK = "000000"

HDR_FILL = PatternFill("solid", fgColor=MM_BLACK)
HDR_FONT = Font(bold=True, color=MM_YELLOW, size=10)
TITLE_FONT = Font(bold=True, size=14)
BAND = PatternFill("solid", fgColor="FFFDE7")
THIN = Side(style="thin", color="D9D9D9")
BORDER = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)

COLUMNS = {
    SHEET_LOCKED: ["#", "MP Number", "Frontend Product Name (EN)", "Product UUID",
                   "SKU Code", "LOCKED Masterlist ID(s)", "ML Model(s)|Color",
                   "ML Available Qty", "Current Seller Stock", "Target Stock",
                   "# SKUs", "Status"],
    SHEET_NEW_ML: ["#", "Masterlist Stock Type ID", "Category", "Brand", "Model",
                   "Color", "Available Qty", "Suggested MP Matches",
                   "Link to MP Number", "Reviewer Decision", "Notes"],
    # Match Review keeps its column layout (Reviewer Decision stays column K)
    # but the decision column is deliberately left blank — see PARTNER below.
    SHEET_REVIEW: ["#", "MP Number", "Frontend Product Name (EN)",
                   "Backend Product Name (EN)", "Product UUID", "SKU Code", "Brand",
                   "Current Seller Stock", "Suggested Masterlist Matches",
                   "Corrected Masterlist ID", "Reviewer Decision", "Notes"],
    SHEET_NOT_SELLING: ["#", "Masterlist Stock Type ID", "Category", "Brand",
                        "Model", "Color", "Available Qty"],
    SHEET_NOT_YET: ["#", "Masterlist Stock Type ID", "Category", "Brand",
                    "Model", "Color", "Available Qty"],
}

WIDTHS = {
    "#": 6, "MP Number": 14, "Frontend Product Name (EN)": 34,
    "Backend Product Name (EN)": 46, "Product UUID": 38, "SKU Code": 18,
    "LOCKED Masterlist ID(s)": 22, "ML Model(s)|Color": 62, "ML Available Qty": 15,
    "Current Seller Stock": 18, "Target Stock": 13, "# SKUs": 9, "Status": 28,
    "Masterlist Stock Type ID": 22, "Category": 12, "Brand": 16, "Model": 42,
    "Color": 22, "Available Qty": 13, "Suggested MP Matches": 36,
    "Link to MP Number": 18, "Reviewer Decision": 26, "Notes": 30,
    "Suggested Masterlist Matches": 36,
    "Corrected Masterlist ID": 22,
}


def _write_sheet(ws, headers: list[str], rows: list[dict]) -> None:
    ws.append(headers)
    for i, h in enumerate(headers, start=1):
        c = ws.cell(row=1, column=i)
        c.fill, c.font = HDR_FILL, HDR_FONT
        c.alignment = Alignment(vertical="center", horizontal="center", wrap_text=True)
        ws.column_dimensions[get_column_letter(i)].width = WIDTHS.get(h, 18)
    ws.row_dimensions[1].height = 30

    for n, r in enumerate(rows, start=2):
        ws.append([r.get(h, "") for h in headers])
        if n % 2 == 0:
            for i in range(1, len(headers) + 1):
                ws.cell(row=n, column=i).fill = BAND
        for i in range(1, len(headers) + 1):
            ws.cell(row=n, column=i).border = BORDER

    ws.freeze_panes = "A2"
    if rows:
        ws.auto_filter.ref = f"A1:{get_column_letter(len(headers))}{len(rows) + 1}"


def _write_lists_sheet(wb, mp_numbers: list[str]) -> None:
    """Hidden sheet feeding the dropdowns."""
    ws = wb.create_sheet(SHEET_LISTS)
    ws["A1"] = "Reviewer Decision"
    for i, d in enumerate(DECISIONS, start=2):
        ws[f"A{i}"] = d
    ws["B1"] = "MP Number"
    for i, mp in enumerate(mp_numbers, start=2):
        ws[f"B{i}"] = mp
    ws.sheet_state = "hidden"


def _add_review_controls(ws, headers: list[str], n_rows: int,
                         n_mp: int, partner_col: str) -> None:
    """
    Put a dropdown on Reviewer Decision, a dropdown on the column that must
    tally with it, and red/amber highlighting when the two disagree.

    partner_col is the header whose value 'Link to MP' requires:
      - New Masterlist SKUs -> 'Link to MP Number'
      - Match Review        -> 'Corrected Masterlist ID'
    """
    if "Reviewer Decision" not in headers:
        return

    last = max(n_rows + 1, 2) + SPARE_ROWS
    dec_col = get_column_letter(headers.index("Reviewer Decision") + 1)

    dv_dec = DataValidation(
        type="list",
        formula1=f"'{SHEET_LISTS}'!$A$2:$A${len(DECISIONS) + 1}",
        allow_blank=True,
        showDropDown=False,          # False = SHOW the in-cell dropdown arrow
    )
    dv_dec.error = ("Pick one of: " + ", ".join(DECISIONS) +
                    ". Typing anything else means the sync tool cannot read "
                    "this row.")
    dv_dec.errorTitle = "Invalid Reviewer Decision"
    dv_dec.prompt = ("Link to MP — confirm the match and lock it\n"
                     "Not Selling in IShopChangi — park it\n"
                     "Not on IShopChangi Yet — awaiting a listing\n"
                     "Skip — decide later")
    dv_dec.promptTitle = "Reviewer Decision"
    ws.add_data_validation(dv_dec)
    dv_dec.add(f"{dec_col}2:{dec_col}{last}")

    if partner_col not in headers:
        return
    p_col = get_column_letter(headers.index(partner_col) + 1)

    # MP Number gets a dropdown of the real MP numbers in today's export.
    if partner_col == "Link to MP Number" and n_mp:
        dv_mp = DataValidation(
            type="list",
            formula1=f"'{SHEET_LISTS}'!$B$2:$B${n_mp + 1}",
            allow_blank=True,
            showDropDown=False,
        )
        dv_mp.error = ("That MP Number is not in the IShopChangi export you "
                       "uploaded. Pick from the list.")
        dv_mp.errorTitle = "Unknown MP Number"
        ws.add_data_validation(dv_mp)
        dv_mp.add(f"{p_col}2:{p_col}{last}")

    lo, hi = sorted([dec_col, p_col])
    rng = f"{lo}2:{hi}{last}"

    # RED: decision is 'Link to MP' but the partner cell is empty -> nothing
    # can be locked, and the export stays blocked until it is filled.
    ws.conditional_formatting.add(rng, FormulaRule(
        formula=[f'AND(${dec_col}2="{DECISION_LINK}",${p_col}2="")'],
        fill=BAD_FILL, stopIfTrue=False,
    ))
    # AMBER: partner filled but no decision -> the link is ignored until a
    # decision is set.
    ws.conditional_formatting.add(rng, FormulaRule(
        formula=[f'AND(${p_col}2<>"",${dec_col}2="")'],
        fill=WARN_FILL, stopIfTrue=False,
    ))


def build_registry_workbook(plan: SyncPlan, source_names: dict[str, str],
                            mp_numbers: list[str] | None = None) -> bytes:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = SHEET_SUMMARY

    ws["B2"] = "IShopChangi Stock Bulk Update — SKU Registry"
    ws["B2"].font = TITLE_FONT
    ws["B3"] = f"Generated {date.today():%d %b %Y}"
    ws["B3"].font = Font(italic=True, size=9, color="666666")

    r = 5
    ws[f"B{r}"], ws[f"C{r}"] = "Category", "Count"
    for cell in (ws[f"B{r}"], ws[f"C{r}"]):
        cell.fill, cell.font = HDR_FILL, HDR_FONT
    r += 1
    for k, v in validation_summary(plan).items():
        ws[f"B{r}"], ws[f"C{r}"] = k, v
        r += 1

    r += 1
    ws[f"B{r}"] = "Source files"
    ws[f"B{r}"].font = Font(bold=True)
    r += 1
    for k, v in source_names.items():
        ws[f"B{r}"], ws[f"C{r}"] = k, v
        r += 1

    ws.column_dimensions["B"].width = 42
    ws.column_dimensions["C"].width = 48

    mps = sorted(set(mp_numbers or []))
    _write_lists_sheet(wb, mps)

    # Which column must tally with a 'Link to MP' decision.
    #
    # Only the New Masterlist SKUs tab gets the dropdowns. Match Review is a
    # read-only record: its Reviewer Decision column stays blank, because a
    # link can only be made from the POS side and Match Review is the case
    # where POS has nothing to link.
    PARTNER = {
        SHEET_NEW_ML: "Link to MP Number",
    }

    for name, rows in (
        (SHEET_LOCKED, plan.locked_rows),
        (SHEET_NEW_ML, plan.new_ml_rows),
        (SHEET_REVIEW, plan.review_rows),
        (SHEET_NOT_SELLING, plan.not_selling_rows),
        (SHEET_NOT_YET, plan.not_yet_rows),
    ):
        sheet = wb.create_sheet(name)
        _write_sheet(sheet, COLUMNS[name], rows)
        if name in PARTNER:
            _add_review_controls(sheet, COLUMNS[name], len(rows),
                                 len(mps), PARTNER[name])

    # Move _Lists to the end so the review tabs stay where Carmen expects them.
    wb.move_sheet(SHEET_LISTS, offset=len(wb.sheetnames))

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()
