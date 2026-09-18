"""
registry.py — the SKU Registry workbook (IShopChangi_Match_Review.xlsx).

Five worksheets, and the whole point of them is that a confirmed match is
NEVER asked about again:

  Locked Matches               MP <-> one-or-more Masterlist Stock Type IDs.
                               Seller stock = SUM of Available Qty of every
                               linked Masterlist SKU.
  Match Review                 iShopChangi MPs not yet matched. Seller stock is
                               LEFT UNCHANGED until reviewed and confirmed.
  New Masterlist SKUs          POS SKUs with available stock that appear in
                               none of Locked / Not Selling / Not on Yet.
                               Every row must be reviewed before export.
  Not Selling in IShopChangi   POS SKUs the reviewer has parked.
  Not on IShopChangi Yet       POS SKUs awaiting a listing.

Carry-forward is keyed on Product UUID (stable) with shop_sku as a fallback,
never on row position.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

import openpyxl

from .brands import canon_brand
from .ishopchangi import IShopExport, Listing
from .pos import PosReport, PosRow

SHEET_LOCKED = "Locked Matches"
SHEET_NEW_ML = "New Masterlist SKUs"
SHEET_REVIEW = "Match Review"
SHEET_NOT_SELLING = "Not Selling in IShopChangi"
SHEET_NOT_YET = "Not on IShopChangi Yet"
SHEET_SUMMARY = "Summary"

REQUIRED_SHEETS = (SHEET_LOCKED, SHEET_NEW_ML, SHEET_REVIEW,
                   SHEET_NOT_SELLING, SHEET_NOT_YET)

DECISION_LINK = "Link to MP"
DECISION_NOT_SELLING = "Not Selling in IShopChangi"
DECISION_NOT_YET = "Not on IShopChangi Yet"
DECISION_SKIP = "Skip"
DECISIONS = (DECISION_LINK, DECISION_NOT_SELLING, DECISION_NOT_YET, DECISION_SKIP)

# Oversell safety buffer: when enabled, a POS Column F value of 1 or 2 is
# written as 0.
#
# DEFAULT IS OFF for this tool. Carmen's ruling, 18 Sep 2026: the stock sync
# tool writes POS Column F exactly, so iShopChangi always mirrors the POS
# report. Buffering is handled separately in the IShopChangi Inventory
# Adjustment project. Keeping two tools from both buffering the same number is
# the point — double-buffering would silently zero real stock.
BUFFER_CEILING = 2
APPLY_BUFFER_DEFAULT = False


def norm_decision(raw) -> str:
    """
    Map whatever is in the cell onto a canonical decision.

    The workbook ships with a dropdown, but a decision can still arrive
    hand-typed or pasted, and a decision the reader does not recognise is
    silently ignored — the row comes back unreviewed and the reviewer's work
    is lost. So match case-insensitively on the squashed text.
    """
    s = " ".join(str(raw or "").split()).lower()
    if not s:
        return ""
    for d in DECISIONS:
        if s == d.lower():
            return d
    # Tolerate the common shorthands and near-misses.
    if s.startswith("link"):
        return DECISION_LINK
    if "not selling" in s:
        return DECISION_NOT_SELLING
    if "not on" in s or "not yet" in s:
        return DECISION_NOT_YET
    if s.startswith("skip"):
        return DECISION_SKIP
    return ""


def split_ids(cell) -> list[str]:
    """'31415; 32771' -> ['31415', '32771']"""
    if cell in (None, ""):
        return []
    return [t for t in re.split(r"[;,/|]\s*|\s+", str(cell).strip()) if t]


@dataclass
class LockedMatch:
    mp_number: str
    product_uuid: str
    shop_sku: str
    frontend_name: str
    masterlist_ids: list[str] = field(default_factory=list)

    def key(self) -> str:
        return self.product_uuid or self.shop_sku or self.mp_number


@dataclass
class Registry:
    locked: dict[str, LockedMatch] = field(default_factory=dict)   # key -> match
    not_selling: set[str] = field(default_factory=set)             # masterlist ids
    not_yet: set[str] = field(default_factory=set)                 # masterlist ids
    review_decisions: dict[str, str] = field(default_factory=dict) # key -> decision
    skipped: dict[str, str] = field(default_factory=dict)          # ml id -> note
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def linked_pos_ids(self) -> set[str]:
        out: set[str] = set()
        for m in self.locked.values():
            out.update(m.masterlist_ids)
        return out


def _headers(ws) -> dict[str, int]:
    hdr = next(ws.iter_rows(min_row=1, max_row=1, values_only=True), ())
    return {str(h).strip(): i for i, h in enumerate(hdr) if h is not None}


def load_registry(path_or_buf) -> Registry:
    reg = Registry()
    wb = openpyxl.load_workbook(path_or_buf, read_only=True, data_only=True)

    missing = [s for s in REQUIRED_SHEETS if s not in wb.sheetnames]
    if missing:
        reg.errors.append(
            "SKU Registry is missing worksheet(s): " + ", ".join(missing)
            + f". Sheets present: {wb.sheetnames}"
        )
        wb.close()
        return reg

    # ---- Locked Matches -------------------------------------------------
    ws = wb[SHEET_LOCKED]
    h = _headers(ws)
    need = ["MP Number", "Product UUID", "LOCKED Masterlist ID(s)"]
    miss = [c for c in need if c not in h]
    if miss:
        reg.errors.append(f"'{SHEET_LOCKED}' is missing column(s): {', '.join(miss)}")
    else:
        for r in ws.iter_rows(min_row=2, values_only=True):
            if all(v in (None, "") for v in r):
                continue
            uuid = str(r[h["Product UUID"]] or "").strip()
            mp = str(r[h["MP Number"]] or "").strip()
            sku = str(r[h.get("SKU Code", -1)] or "").strip() if "SKU Code" in h else ""
            ids = split_ids(r[h["LOCKED Masterlist ID(s)"]])
            if not ids:
                continue
            m = LockedMatch(
                mp_number=mp,
                product_uuid=uuid,
                shop_sku=sku,
                frontend_name=str(r[h.get("Frontend Product Name (EN)", -1)] or "").strip()
                if "Frontend Product Name (EN)" in h else "",
                masterlist_ids=ids,
            )
            if not m.key():
                reg.warnings.append(
                    f"'{SHEET_LOCKED}' row with IDs {ids} has no Product UUID, "
                    "SKU Code or MP Number — skipped."
                )
                continue
            reg.locked[m.key()] = m

    # ---- parked buckets --------------------------------------------------
    for sheet, target in ((SHEET_NOT_SELLING, reg.not_selling),
                          (SHEET_NOT_YET, reg.not_yet)):
        ws = wb[sheet]
        h = _headers(ws)
        col = h.get("Masterlist Stock Type ID")
        if col is None:
            reg.errors.append(f"'{sheet}' is missing column 'Masterlist Stock Type ID'")
            continue
        for r in ws.iter_rows(min_row=2, values_only=True):
            if col < len(r) and r[col] not in (None, ""):
                target.add(str(r[col]).strip())

    # ---- New Masterlist SKUs: carry forward links AND skips ---------------
    # Without this, a SKU the reviewer linked here would be asked about again
    # tomorrow, and a Skip would have to be re-entered every single run.
    ws = wb[SHEET_NEW_ML]
    h = _headers(ws)
    if "Masterlist Stock Type ID" in h and "Reviewer Decision" in h:
        sid_c, dec_c = h["Masterlist Stock Type ID"], h["Reviewer Decision"]
        mp_c = h.get("Link to MP Number")
        note_c = h.get("Notes")
        for r in ws.iter_rows(min_row=2, values_only=True):
            if sid_c >= len(r) or r[sid_c] in (None, ""):
                continue
            sid = str(r[sid_c]).strip()
            dec = norm_decision(r[dec_c]) if dec_c < len(r) else ""
            if dec == DECISION_SKIP:
                reg.skipped[sid] = (
                    str(r[note_c] or "").strip()
                    if note_c is not None and note_c < len(r) else ""
                )
            elif dec == DECISION_NOT_SELLING:
                reg.not_selling.add(sid)
            elif dec == DECISION_NOT_YET:
                reg.not_yet.add(sid)
            elif dec == DECISION_LINK and mp_c is not None and mp_c < len(r):
                mp = str(r[mp_c] or "").strip()
                if not mp:
                    reg.warnings.append(
                        f"'{SHEET_NEW_ML}' row {sid} is set to '{DECISION_LINK}' "
                        "but has no Link to MP Number — it will be asked again."
                    )
                    continue
                # Key on MP here; resolved to a Product UUID in build_plan.
                existing = next(
                    (m for m in reg.locked.values() if m.mp_number == mp), None)
                if existing:
                    if sid not in existing.masterlist_ids:
                        existing.masterlist_ids.append(sid)
                else:
                    reg.locked[f"mp:{mp}"] = LockedMatch(
                        mp_number=mp, product_uuid="", shop_sku="",
                        frontend_name="", masterlist_ids=[sid],
                    )

    # ---- Match Review is a READ-ONLY record ------------------------------
    #
    # Carmen's ruling, 18 Sep 2026: all linking happens on the New Masterlist
    # SKUs tab only, and Match Review's Reviewer Decision column stays blank.
    #
    # The reason is that a link can only ever be made from the POS side: you
    # can only link a POS SKU that actually exists. Match Review lists the
    # opposite case — the listing exists on IShopChangi but POS has nothing
    # for it today — so there is nothing to link and the stock stays 0.
    #
    # Decisions written here are therefore deliberately NOT read. A previous
    # version read them, which let 359 listings be parked from this tab while
    # POS still held their stock.

    wb.close()
    return reg


# ---------------------------------------------------------------------------
# Building the working state for one run
# ---------------------------------------------------------------------------

@dataclass
class SyncPlan:
    """Everything the UI and the writer need, computed from the three files."""
    locked_rows: list[dict] = field(default_factory=list)
    review_rows: list[dict] = field(default_factory=list)
    new_ml_rows: list[dict] = field(default_factory=list)
    not_selling_rows: list[dict] = field(default_factory=list)
    not_yet_rows: list[dict] = field(default_factory=list)
    buffered: list[dict] = field(default_factory=list)
    double_fed: list[dict] = field(default_factory=list)
    unknown_ids: list[dict] = field(default_factory=list)
    stock_by_row: dict[int, int] = field(default_factory=dict)
    newly_locked: list[dict] = field(default_factory=list)
    parked_conflicts: list[dict] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def all_new_ml_reviewed(self) -> bool:
        return all(r.get("Reviewer Decision") in DECISIONS for r in self.new_ml_rows)

    @property
    def unreviewed_new_ml(self) -> list[dict]:
        return [r for r in self.new_ml_rows
                if r.get("Reviewer Decision") not in DECISIONS]


def build_plan(pos: PosReport, exp: IShopExport, reg: Registry,
               apply_buffer: bool = APPLY_BUFFER_DEFAULT) -> SyncPlan:
    plan = SyncPlan()
    plan.errors += pos.errors + exp.errors + reg.errors
    plan.warnings += exp.warnings + reg.warnings

    pos_by_id = pos.by_id()
    by_uuid = exp.by_uuid()
    by_sku = exp.by_sku()

    by_mp = {l.mp_number: l for l in exp.listings if l.mp_number}

    def find_listing(m: LockedMatch) -> Listing | None:
        return (by_uuid.get(m.product_uuid)
                or by_sku.get(m.shop_sku)
                or by_mp.get(m.mp_number))

    # Re-key any "mp:<number>" placeholder loaded from the New Masterlist SKUs
    # sheet onto its real Product UUID, so it behaves like any locked match.
    for key in [k for k in reg.locked if k.startswith("mp:")]:
        m = reg.locked[key]
        l = by_mp.get(m.mp_number)
        if l is None:
            continue
        reg.locked.pop(key)
        m.product_uuid, m.shop_sku = l.product_uuid, l.shop_sku
        m.frontend_name = l.frontend_name
        target = reg.locked.get(l.product_uuid)
        if target:
            for i in m.masterlist_ids:
                if i not in target.masterlist_ids:
                    target.masterlist_ids.append(i)
        else:
            reg.locked[l.product_uuid] = m

    fed_count: dict[str, list[str]] = {}

    # ---- Locked Matches: sum Available Qty across every linked SKU -------
    for key, m in reg.locked.items():
        listing = find_listing(m)
        if listing is None:
            plan.warnings.append(
                f"Locked match {m.mp_number or key} is not present in this "
                "iShopChangi export — no stock written for it."
            )
            continue

        # Every locked ID gets a line, in all three cases. A blank cell used to
        # mean "this ID is not in today's POS report", which is the single most
        # important thing to be able to see — it looked identical to a bug.
        total, detail, bad = 0, [], []
        for sid in m.masterlist_ids:
            p = pos_by_id.get(sid)
            if p is None:
                bad.append(sid)
                detail.append(f"{sid}: — NOT IN TODAY'S POS REPORT (counts as 0)")
                continue
            if p.excluded:
                detail.append(
                    f"{sid}: 0 EXCLUDED — {p.excluded} "
                    f"({p.brand_raw} {p.model_raw} | {p.colour})"
                )
                fed_count.setdefault(sid, []).append(m.mp_number or key)
                continue
            total += max(p.available, 0)
            detail.append(
                f"{sid}: {p.available} ({p.brand_raw} {p.model_raw} | {p.colour})"
            )
            fed_count.setdefault(sid, []).append(m.mp_number or key)

        if bad:
            plan.unknown_ids.append({
                "MP Number": m.mp_number, "Listing": listing.backend_name,
                "Unknown Masterlist ID(s)": ", ".join(bad),
            })
            plan.warnings.append(
                f"{m.mp_number or key}: Masterlist ID(s) {', '.join(bad)} are not in "
                "this POS report — contributed 0. (POS families come and go; "
                "this is a fact about today only.)"
            )

        final = total
        if apply_buffer and 1 <= total <= BUFFER_CEILING:
            final = 0
            plan.buffered.append({
                "Row": listing.row_no, "MP Number": m.mp_number,
                "SKU Code": listing.shop_sku, "Listing": listing.backend_name,
                "POS Qty": total, "Written": 0,
            })

        if len(bad) == len(m.masterlist_ids):
            status = "NOT IN POS TODAY"
        elif bad:
            status = f"PARTIAL — {len(bad)} ID(s) not in POS"
        elif final == 0 and total > 0:
            status = f"BUFFERED — POS {total} -> 0"
        elif total == 0:
            status = "ZERO STOCK"
        else:
            status = "OK"

        plan.stock_by_row[listing.row_no] = final
        plan.locked_rows.append({
            "#": len(plan.locked_rows) + 1,
            "MP Number": m.mp_number,
            "Frontend Product Name (EN)": listing.frontend_name,
            "Product UUID": listing.product_uuid,
            "SKU Code": listing.shop_sku,
            "LOCKED Masterlist ID(s)": "; ".join(m.masterlist_ids),
            "ML Model(s)|Color": " || ".join(detail),
            "ML Available Qty": total,
            "Current Seller Stock": listing.current_stock,
            "Target Stock": final,
            "# SKUs": len(m.masterlist_ids),
            "Status": status,
        })

    # A POS row must never feed two listings.
    for sid, mps in fed_count.items():
        if len(set(mps)) > 1:
            p = pos_by_id.get(sid)
            plan.double_fed.append({
                "Masterlist ID": sid,
                "POS": f"{p.brand_raw} {p.model_raw} | {p.colour}" if p else "?",
                "Fed to": ", ".join(sorted(set(mps))),
            })

    # ---- Match Review: unmatched listings, stock LEFT UNCHANGED ----------
    from .matching import format_suggestions, suggest_for_listing
    usable_pos = pos.usable
    for l in exp.listings:
        if l.product_uuid in reg.locked or l.shop_sku in reg.locked:
            continue
        if any(m.product_uuid == l.product_uuid for m in reg.locked.values()):
            continue
        sugg = suggest_for_listing(l, usable_pos)
        exact = sugg[0] if sugg and sugg[0].exact else None

        plan.review_rows.append({
            "#": len(plan.review_rows) + 1,
            "MP Number": l.mp_number,
            "Frontend Product Name (EN)": l.frontend_name,
            "Backend Product Name (EN)": l.backend_name,
            "Product UUID": l.product_uuid,
            "SKU Code": l.shop_sku,
            "Brand": l.brand_raw,
            "Current Seller Stock": l.current_stock,
            "Suggested Masterlist Matches": format_suggestions(sugg),
            # Reviewer Decision stays BLANK here by design — linking is done
            # on the New Masterlist SKUs tab only.
            "Reviewer Decision": "",
            "Notes": "",
            "_row_no": l.row_no,
            "_auto_exact": exact.pos_row.stock_type_id if exact else "",
        })
        # rule: leave existing seller stock untouched until reviewed
        plan.stock_by_row.setdefault(l.row_no, None)

    # ---- New Masterlist SKUs --------------------------------------------
    from .matching import format_pos_suggestions, suggest_for_pos

    linked = reg.linked_pos_ids()
    parked = reg.not_selling | reg.not_yet

    # RESCUE: a POS SKU parked as 'Not Selling' or 'Not on IShopChangi Yet'
    # that still has stock AND matches a real IShopChangi listing exactly was
    # parked by mistake — the listing plainly does exist. Bring it back here so
    # it can be re-linked, instead of leaving POS stock stranded off-platform.
    rescued: set[str] = set()
    for p in usable_pos:
        if p.available < 1 or p.stock_type_id not in parked:
            continue
        s = suggest_for_pos(p, exp.listings, limit=1)
        if s and s[0][2]:                      # [2] = exact
            rescued.add(p.stock_type_id)
            listing = s[0][0]
            plan.parked_conflicts.append({
                "Masterlist ID": p.stock_type_id,
                "POS": f"{p.brand_raw} {p.model_raw} | {p.colour}",
                "POS Qty": p.available,
                "Was": (DECISION_NOT_SELLING if p.stock_type_id in reg.not_selling
                        else DECISION_NOT_YET),
                "Matches MP": listing.mp_number,
                "Listing": listing.backend_name,
            })
    reg.not_selling -= rescued
    reg.not_yet -= rescued
    parked -= rescued

    accounted = linked | parked
    for p in usable_pos:
        if p.available < 1 or p.stock_type_id in accounted:
            continue
        sugg = suggest_for_pos(p, exp.listings)
        plan.new_ml_rows.append({
            "#": len(plan.new_ml_rows) + 1,
            "Masterlist Stock Type ID": p.stock_type_id,
            "Category": p.category,
            "Brand": p.brand_raw,
            "Model": p.model_raw,
            "Color": p.colour,
            "Available Qty": p.available,
            "Suggested MP Matches": format_pos_suggestions(sugg),
            "Link to MP Number": "",
            # A Skip made on an earlier run is remembered, so the reviewer is
            # not forced to re-enter it every single day.
            "Reviewer Decision": DECISION_SKIP if p.stock_type_id in reg.skipped else "",
            "Notes": (
                "WAS PARKED BY MISTAKE — the listing does exist, re-link it"
                if p.stock_type_id in rescued
                else reg.skipped.get(p.stock_type_id, "")
            ),
        })

    # ---- parked buckets, echoed back with today's quantities -------------
    for sid in sorted(reg.not_selling):
        p = pos_by_id.get(sid)
        plan.not_selling_rows.append(_parked_row(len(plan.not_selling_rows) + 1, sid, p))
    for sid in sorted(reg.not_yet):
        p = pos_by_id.get(sid)
        plan.not_yet_rows.append(_parked_row(len(plan.not_yet_rows) + 1, sid, p))

    return plan


def _parked_row(n: int, sid: str, p: PosRow | None) -> dict:
    return {
        "#": n,
        "Masterlist Stock Type ID": sid,
        "Category": p.category if p else "",
        "Brand": p.brand_raw if p else "",
        "Model": p.model_raw if p else "(not in today's POS report)",
        "Color": p.colour if p else "",
        "Available Qty": p.available if p else 0,
    }


def apply_new_ml_decisions(plan: SyncPlan, reg: Registry, exp: IShopExport,
                           pos: PosReport,
                           apply_buffer: bool = APPLY_BUFFER_DEFAULT) -> SyncPlan:
    """
    Fold reviewer decisions on New Masterlist SKUs into the registry, then
    recompute. Called after the reviewer finishes, before export.
    """
    by_mp = {l.mp_number: l for l in exp.listings if l.mp_number}
    newly: list[dict] = []

    for r in plan.new_ml_rows:
        dec = r.get("Reviewer Decision")
        sid = str(r["Masterlist Stock Type ID"])
        if dec == DECISION_LINK:
            mp = str(r.get("Link to MP Number") or "").strip()
            l = by_mp.get(mp)
            if l is None:
                plan.errors.append(
                    f"New Masterlist SKU {sid} is set to '{DECISION_LINK}' but "
                    f"MP Number {mp!r} is not in this iShopChangi export."
                )
                continue
            key = l.product_uuid
            # Fold in any placeholder the registry loaded under "mp:<number>"
            # before the MP had been resolved to a Product UUID.
            ph = reg.locked.pop(f"mp:{mp}", None)
            existing = reg.locked.get(key)
            if existing is None and ph is not None:
                ph.product_uuid = l.product_uuid
                ph.shop_sku = l.shop_sku
                ph.frontend_name = l.frontend_name
                reg.locked[key] = ph
                existing = ph
            elif ph is not None and existing is not None:
                for i in ph.masterlist_ids:
                    if i not in existing.masterlist_ids:
                        existing.masterlist_ids.append(i)

            if existing:
                if sid not in existing.masterlist_ids:
                    existing.masterlist_ids.append(sid)
                    newly.append({"Masterlist ID": sid, "MP Number": mp,
                                  "Listing": l.backend_name,
                                  "Action": "added to existing locked match"})
            else:
                reg.locked[key] = LockedMatch(
                    mp_number=l.mp_number, product_uuid=l.product_uuid,
                    shop_sku=l.shop_sku, frontend_name=l.frontend_name,
                    masterlist_ids=[sid],
                )
                newly.append({"Masterlist ID": sid, "MP Number": mp,
                              "Listing": l.backend_name,
                              "Action": "new locked match"})
        elif dec == DECISION_NOT_SELLING:
            reg.not_selling.add(sid)
        elif dec == DECISION_NOT_YET:
            reg.not_yet.add(sid)
        elif dec == DECISION_SKIP:
            # Remembered so the reviewer does not have to skip it again, but
            # still shown, because Skip means "decide later", not "resolved".
            reg.skipped[sid] = str(r.get("Notes") or "")

    final = build_plan(pos, exp, reg, apply_buffer=apply_buffer)
    final.newly_locked = newly
    final.errors += plan.errors
    return final


def apply_review_decisions(plan: SyncPlan, reg: Registry) -> None:
    """Fold Match Review decisions (link / park) into the registry."""
    for r in plan.review_rows:
        dec = str(r.get("Reviewer Decision") or "").strip()
        uuid = r["Product UUID"]
        if not dec:
            continue
        reg.review_decisions[uuid] = dec
        if dec == DECISION_LINK:
            ids = split_ids(r.get("Corrected Masterlist ID"))
            if ids:
                reg.locked[uuid] = LockedMatch(
                    mp_number=r["MP Number"], product_uuid=uuid,
                    shop_sku=r["SKU Code"],
                    frontend_name=r["Frontend Product Name (EN)"],
                    masterlist_ids=ids,
                )


def validation_summary(plan: SyncPlan) -> dict[str, int]:
    return {
        "Locked Matches updated": len(plan.locked_rows),
        "New Masterlist SKUs found": len(plan.new_ml_rows),
        "SKUs requiring review": len(plan.unreviewed_new_ml) + len(
            [r for r in plan.review_rows if not r.get("Reviewer Decision")]),
        "Not Selling in IShopChangi": len(plan.not_selling_rows),
        "Not on IShopChangi Yet": len(plan.not_yet_rows),
        "Listings with stock > 0": sum(
            1 for r in plan.locked_rows if r["Target Stock"] > 0),
        "Validation errors": len(plan.errors),
        "Unmatched / invalid records": len(plan.unknown_ids) + len(plan.double_fed),
    }
