"""
writer.py — write the updated bulk file WITHOUT disturbing the template.

Re-saving with openpyxl rewrites ~45,000 cells (empty inline strings collapse to
blanks) and touches ReferenceData, so the file iShopChangi receives is no longer
the file they issued. Instead we patch the Data sheet's XML in place and copy
every other zip member through byte-for-byte.

The stockQuantity cells are `t="inlineStr"` holding STRINGS, so we write
<t>0</t>, not a numeric cell.
"""

from __future__ import annotations

import io
import re
import shutil
import zipfile
from dataclasses import dataclass

from openpyxl.utils import get_column_letter

DATA_SHEET = "Data"


def _sheet_path_for(zf: zipfile.ZipFile, sheet_name: str) -> str:
    """Resolve sheet name -> xl/worksheets/sheetN.xml via workbook rels."""
    wb = zf.read("xl/workbook.xml").decode("utf-8", "replace")
    m = re.search(
        rf'<sheet[^>]*name="{re.escape(sheet_name)}"[^>]*r:id="([^"]+)"', wb
    )
    if not m:
        m = re.search(
            rf'<sheet[^>]*r:id="([^"]+)"[^>]*name="{re.escape(sheet_name)}"', wb
        )
    if not m:
        raise ValueError(f"Sheet {sheet_name!r} not found in workbook.xml")
    rid = m.group(1)
    rels = zf.read("xl/_rels/workbook.xml.rels").decode("utf-8", "replace")
    rm = re.search(rf'<Relationship[^>]*Id="{rid}"[^>]*Target="([^"]+)"', rels)
    if not rm:
        raise ValueError(f"Relationship {rid} not found")
    target = rm.group(1).lstrip("/")
    return target if target.startswith("xl/") else "xl/" + target


@dataclass
class WriteResult:
    written: int
    skipped_rows: list[int]
    stock_col_letter: str
    other_members_identical: bool
    changed_members: list[str]


def write_bulk_file(src_bytes: bytes, stock_col_index0: int,
                    values: dict[int, int]) -> tuple[bytes, WriteResult]:
    """
    src_bytes         the uploaded download-job-file-*.xlsx, unmodified
    stock_col_index0  0-based column index of stockQuantity (resolved from row 3)
    values            {spreadsheet_row_number: final_quantity}

    Rows absent from `values` (or mapped to None) are left exactly as they are —
    that is how Match Review rows keep their existing seller stock.
    """
    vals = {int(r): int(v) for r, v in values.items() if v is not None}
    letter = get_column_letter(stock_col_index0 + 1)

    zin = zipfile.ZipFile(io.BytesIO(src_bytes))
    sheet_path = _sheet_path_for(zin, DATA_SHEET)
    xml = zin.read(sheet_path).decode("utf-8")

    seen: set[int] = set()
    cell_re = re.compile(
        rf'<c r="{letter}(\d+)"([^>]*)>(.*?)</c>|<c r="{letter}(\d+)"([^>]*)/>',
        re.S,
    )

    def repl(m: re.Match) -> str:
        row = int(m.group(1) or m.group(4))
        if row not in vals:
            return m.group(0)
        seen.add(row)
        return (f'<c r="{letter}{row}" t="inlineStr">'
                f'<is><t>{vals[row]}</t></is></c>')

    new_xml = cell_re.sub(repl, xml)

    missing = sorted(set(vals) - seen)
    if missing:
        # A row we planned to write had no cell at that column. Rather than
        # inventing XML, refuse: silently dropping a quantity is the failure
        # mode this whole tool exists to prevent.
        raise ValueError(
            f"Could not locate column {letter} cells for row(s) {missing[:20]}"
            f"{' …' if len(missing) > 20 else ''}. Refusing to write a partial file."
        )

    out = io.BytesIO()
    changed = []
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zout:
        for item in zin.infolist():
            data = zin.read(item.filename)
            if item.filename == sheet_path:
                data = new_xml.encode("utf-8")
                changed.append(item.filename)
            zout.writestr(item, data)
    zin.close()

    return out.getvalue(), WriteResult(
        written=len(seen),
        skipped_rows=[],
        stock_col_letter=letter,
        other_members_identical=(changed == [sheet_path]),
        changed_members=changed,
    )


def verify_written(src_bytes: bytes, out_bytes: bytes, stock_col_index0: int,
                   values: dict[int, int]) -> dict:
    """
    Post-write proof, run before the file is offered for download:
      * every non-Data zip member is byte-identical
      * only stockQuantity cells differ
      * every written value equals the planned value
      * no 1 or 2 survives anywhere in the column
    """
    zin, zout = zipfile.ZipFile(io.BytesIO(src_bytes)), zipfile.ZipFile(io.BytesIO(out_bytes))
    sheet_path = _sheet_path_for(zin, DATA_SHEET)

    differing_members = [
        n for n in zin.namelist()
        if n != sheet_path and zin.read(n) != zout.read(n)
    ]
    letter = get_column_letter(stock_col_index0 + 1)

    def col_map(zf):
        xml = zf.read(sheet_path).decode("utf-8")
        return {
            int(m.group(1)): m.group(2)
            for m in re.finditer(
                rf'<c r="{letter}(\d+)"[^>]*><is><t>([^<]*)</t></is></c>', xml)
        }

    a, b = col_map(zin), col_map(zout)
    other_cells_changed = _count_non_column_diffs(zin, zout, sheet_path, letter)

    planned = {int(r): int(v) for r, v in values.items() if v is not None}
    mismatched = {r: (b.get(r), v) for r, v in planned.items() if b.get(r) != str(v)}
    unplanned = sorted(r for r in b if r in a and b[r] != a[r] and r not in planned)
    survivors = sorted(r for r, v in b.items() if v.strip() in ("1", "2"))

    zin.close()
    zout.close()
    return {
        "ok": not differing_members and not mismatched and not unplanned
              and not survivors and other_cells_changed == 0,
        "differing_zip_members": differing_members,
        "other_cells_changed": other_cells_changed,
        "mismatched": mismatched,
        "unplanned_changes": unplanned,
        "buffer_survivors": survivors,
        "cells_written": len(planned),
        "column": letter,
    }


def _count_non_column_diffs(zin, zout, sheet_path: str, letter: str) -> int:
    """Count cells outside the stock column whose XML differs."""
    pat = re.compile(r'<c r="([A-Z]+)(\d+)"([^>]*)>(.*?)</c>', re.S)

    def cells(zf):
        xml = zf.read(sheet_path).decode("utf-8")
        return {
            (m.group(1), m.group(2)): m.group(0)
            for m in pat.finditer(xml) if m.group(1) != letter
        }

    a, b = cells(zin), cells(zout)
    diff = sum(1 for k in a if a[k] != b.get(k))
    diff += len(set(b) - set(a))
    return diff


def save_bytes(path: str, data: bytes) -> None:
    """os.remove is not permitted on the mounted outputs folder — overwrite."""
    with open(path, "wb") as fh:
        fh.write(data)
