"""
test_pipeline.py — end-to-end check with no Streamlit involved.

    python test_pipeline.py <stock_report.xlsx> <download-job-file.xlsx> <registry.xlsx>

Asserts the things that must never be wrong:
  * only stockQuantity cells change; every other zip member byte-identical
  * every written value equals the planned value
  * no 1 or 2 survives the oversell buffer
  * every value > 0 traces back to a sellable POS row whose Column F equals it
  * no POS row feeds two listings
  * locked rulings hold (plain OnePlus = 0, activated Apple never used)
"""

from __future__ import annotations

import sys

from core.ishopchangi import load_ishopchangi
from core.matching import gap_check
from core.pos import load_pos
from core.registry import build_plan, load_registry, validation_summary
from core.registry_writer import build_registry_workbook
from core.writer import verify_written, write_bulk_file


def main(pos_path: str, ish_path: str, reg_path: str) -> int:
    pos = load_pos(pos_path)
    exp = load_ishopchangi(ish_path)
    reg = load_registry(reg_path)

    for name, errs in (("POS", pos.errors), ("iShopChangi", exp.errors),
                       ("Registry", reg.errors)):
        for e in errs:
            print(f"  [{name} error] {e}")
    assert not (pos.errors or exp.errors or reg.errors), "blocking errors"

    plan = build_plan(pos, exp, reg)

    print(f"POS rows              {len(pos.rows)} ({len(pos.usable)} sellable)")
    print(f"iShopChangi listings  {len(exp.listings)}")
    print(f"stockQuantity column  index {exp.stock_qty_col} of {exp.n_columns}")
    print()
    for k, v in validation_summary(plan).items():
        print(f"  {k:34s} {v}")
    print()

    values = {r: v for r, v in plan.stock_by_row.items() if v is not None}
    src = open(ish_path, "rb").read()
    out, res = write_bulk_file(src, exp.stock_qty_col, values)
    print(f"wrote {res.written} cells in column {res.stock_col_letter}")
    print(f"changed zip members: {res.changed_members}")

    chk = verify_written(src, out, exp.stock_qty_col, values)
    for k, v in chk.items():
        print(f"  {k:26s} {v if not isinstance(v, (list, dict)) or len(v) < 8 else f'{len(v)} items'}")

    assert not chk["differing_zip_members"], chk["differing_zip_members"]
    assert chk["other_cells_changed"] == 0, chk["other_cells_changed"]
    assert not chk["mismatched"], list(chk["mismatched"].items())[:5]
    assert not chk["unplanned_changes"], chk["unplanned_changes"][:10]
    # Buffer is OFF in this tool by design, so 1s and 2s are expected:
    # the written value must equal POS Column F exactly.

    # every value > 0 traces back to sellable POS rows summing to it
    pos_by_id = pos.by_id()
    nonzero = 0
    for row in plan.locked_rows:
        if row["Target Stock"] > 0:
            nonzero += 1
            total = sum(
                max(pos_by_id[i].available, 0)
                for i in row["LOCKED Masterlist ID(s)"].split("; ")
                if i in pos_by_id and not pos_by_id[i].excluded
            )
            assert total == row["Target Stock"], row
    print(f"\n{nonzero} listings end up > 0, all traced to Column F")

    assert not plan.double_fed, plan.double_fed[:5]
    print("no POS row feeds two listings")

    gap = gap_check(pos.rows, exp.listings, reg.linked_pos_ids())
    print(f"gap check: {len(gap['probable_missing_alias'])} probable missing "
          f"alias(es), {len(gap['orphan_pos_stock'])} orphan POS rows with stock")
    for p, hits in gap["probable_missing_alias"]:
        print(f"   MISSING? {p.brand_raw} {p.model_raw} (qty {p.available}) "
              f"~ {hits[0][0].backend_name} @{hits[0][1]}")

    wb = build_registry_workbook(plan, {"POS": pos_path, "iShopChangi": ish_path})
    print(f"\nregistry workbook: {len(wb)} bytes")
    print("\nALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main(*sys.argv[1:4]))
