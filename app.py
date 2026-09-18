"""
IShopChangi Stock Sync — v2
Mister Mobile · Dealer Inventory Bulk Update

Streamlit Community Cloud entry point.
    Main file path: app.py
"""

from __future__ import annotations

from datetime import date

import pandas as pd
import streamlit as st

from core import __version__
from core.brands import FAMILY_ALIASES, SUPPORTED_BRANDS
from core.ishopchangi import load_ishopchangi
from core.matching import gap_check
from core.pos import load_pos
from core.registry import (
    DECISION_LINK,
    DECISION_NOT_SELLING,
    DECISION_NOT_YET,
    DECISION_SKIP,
    DECISIONS,
    apply_new_ml_decisions,
    apply_review_decisions,
    build_plan,
    load_registry,
    validation_summary,
)
from core.registry_writer import build_registry_workbook
from core.writer import verify_written, write_bulk_file

st.set_page_config(
    page_title="IShopChangi Stock Sync · Mister Mobile",
    page_icon="🟡",
    layout="wide",
)

# ---------------------------------------------------------------------------
# Mister Mobile yellow & black
# ---------------------------------------------------------------------------
st.markdown(
    """
<style>
  :root { --mm-yellow:#FFE800; --mm-black:#000; }
  .block-container { padding-top:2rem; max-width:1500px; }

  .mm-banner{
    background:var(--mm-yellow); border-bottom:9px solid var(--mm-black);
    padding:1.1rem 1.5rem; display:flex; align-items:center; gap:1rem;
    margin-bottom:2rem;
  }
  .mm-logo{
    width:52px; height:52px; border-radius:50%; background:var(--mm-black);
    color:var(--mm-yellow); font-weight:900; font-size:1.15rem;
    display:flex; align-items:center; justify-content:center; flex:0 0 auto;
    letter-spacing:-.5px;
  }
  .mm-banner h1{
    margin:0; font-size:1.95rem; font-weight:800; color:var(--mm-black);
    line-height:1.1; letter-spacing:-.5px;
  }
  .mm-banner p{ margin:.15rem 0 0; font-size:.92rem; color:#333; font-weight:500; }

  .mm-step{ display:flex; gap:.6rem; align-items:flex-start; margin:.45rem 0; }
  .mm-num{
    background:var(--mm-black); color:#fff; width:1.45rem; height:1.45rem;
    border-radius:4px; font-size:.82rem; font-weight:700; flex:0 0 auto;
    display:flex; align-items:center; justify-content:center; margin-top:.1rem;
  }
  .mm-box-label{ font-weight:700; font-size:1rem; margin:.2rem 0 .3rem; }
  .mm-box-label span{
    background:var(--mm-black); color:#fff; border-radius:4px;
    padding:.05rem .45rem; margin-right:.4rem; font-size:.82rem;
  }

  div[data-testid="stMetric"]{
    background:#FFFDF0; border:1px solid #F0E08A; border-radius:8px;
    padding:.75rem .9rem;
  }
  div[data-testid="stMetricValue"]{ font-size:1.6rem; }

  .stButton>button, .stDownloadButton>button{
    background:var(--mm-yellow); color:var(--mm-black); border:2px solid var(--mm-black);
    font-weight:800; border-radius:6px; padding:.5rem 1.2rem;
  }
  .stButton>button:hover, .stDownloadButton>button:hover{
    background:var(--mm-black); color:var(--mm-yellow); border-color:var(--mm-black);
  }
  .stButton>button:disabled, .stDownloadButton>button:disabled{
    background:#eee; color:#999; border-color:#ccc;
  }
  .stTabs [aria-selected="true"]{
    background:var(--mm-yellow); border-bottom:3px solid var(--mm-black);
  }
  .mm-lock{
    background:#FFF8E1; border-left:6px solid var(--mm-yellow);
    padding:.85rem 1rem; border-radius:4px; font-weight:600;
  }
</style>
""",
    unsafe_allow_html=True,
)

st.markdown(
    f"""
<div class="mm-banner">
  <div class="mm-logo">MM</div>
  <div>
    <h1>IShopChangi Stock Sync</h1>
    <p>Mister Mobile · Dealer Inventory Bulk Update · v{__version__}</p>
  </div>
</div>
""",
    unsafe_allow_html=True,
)

# ---------------------------------------------------------------------------
# How to use
# ---------------------------------------------------------------------------
st.header("How to use")
for n, txt in enumerate(
    [
        "<b>Upload</b> the POS Masterlist, the IShopChangi bulk stock file, and "
        "your SKU Registry below.",
        "<b>Review</b> the <i>New Masterlist SKUs</i> tab and set a Reviewer "
        "Decision for <i>every</i> row (Link to MP, Not Selling, Not on "
        "IShopChangi Yet, or Skip).",
        "<b>Confirm</b> the matches. The download stays locked until every New "
        "Masterlist SKU is reviewed.",
        "<b>Download</b> the bulk file and upload it in IShopChangi → Bulk Stock "
        "Update. Keep the updated SKU Registry — re-upload it next run so locked "
        "matches are never re-asked.",
    ],
    start=1,
):
    st.markdown(
        f'<div class="mm-step"><div class="mm-num">{n}</div><div>{txt}</div></div>',
        unsafe_allow_html=True,
    )

with st.expander("How matching works (IShopChangi rules)"):
    st.markdown(
        f"""
**Stock source** — POS **Column F, "Available Quantity"**, only. Never Column G,
never a sum of the branch columns, never Quantity − Reserved − Transit.

**Oversell buffer** — after taking Column F, a quantity of **1 or 2 becomes 0**.
Every buffered item is listed before you download.

**Rows excluded from IShopChangi**

| Excluded | Why |
|---|---|
| `Category = Used` | IShopChangi sells brand-new only |
| Apple `… A` rows | activated sets. **Only `… NA` (non-activated) is sellable** |
| `TELCO` channel | IShopChangi does not sell Telco sets — PRIMARY pools only |
| `FREEBIE` / `FREEBIES` | giveaway units, not sellable stock |
| Export sets | `JP TH TW HK CN KR MY VN US` as a whole word |

Unlike the other marketplaces, **Apple is not excluded on IShopChangi** — iPhone
and iPad are sold here, from the `NA` pool only.

**Match key** — family + capacity + RAM + network + colour, all of which must
agree. Brand is a hard gate, so a Nothing SKU can never be suggested for an
Apple listing. RAM is compared only when both sides carry a value (POS omits RAM
for iPads, iPhones and accessories). A listing with no confident match gets **0**,
never a guess.

**`W US 80W CHARGER`** — POS stock on a charger row belongs only to the listing
whose name says "With US Charger". The plain listing gets 0.

**Brand coverage** — {len(SUPPORTED_BRANDS)} brands, {len(FAMILY_ALIASES)} product
families: {", ".join(SUPPORTED_BRANDS)}. Adding a brand means adding entries to
`core/brands.py` only — no matching or sync logic changes.
"""
    )

st.divider()

# ---------------------------------------------------------------------------
# Uploads
# ---------------------------------------------------------------------------
c1, c2 = st.columns(2)
with c1:
    st.markdown(
        '<div class="mm-box-label"><span>1</span>POS Masterlist '
        "(stock_report*.xlsx)</div>",
        unsafe_allow_html=True,
    )
    pos_file = st.file_uploader("POS Masterlist", type="xlsx",
                               label_visibility="collapsed", key="pos")
with c2:
    st.markdown(
        '<div class="mm-box-label"><span>2</span>IShopChangi bulk stock file '
        "(download-job-file*.xlsx)</div>",
        unsafe_allow_html=True,
    )
    ish_file = st.file_uploader("IShopChangi export", type="xlsx",
                                label_visibility="collapsed", key="ish")

st.markdown(
    '<div class="mm-box-label"><span>3</span>SKU Registry '
    "(IShopChangi_Match_Review.xlsx — carries your locked matches forward)</div>",
    unsafe_allow_html=True,
)
reg_file = st.file_uploader("SKU Registry", type="xlsx",
                            label_visibility="collapsed", key="reg")

if not (pos_file and ish_file and reg_file):
    st.info(
        "Upload all three files to begin. The SKU Registry must contain the "
        "worksheets: Locked Matches, New Masterlist SKUs, Match Review, "
        "Not Selling in IShopChangi, Not on IShopChangi Yet."
    )
    st.stop()

# ---------------------------------------------------------------------------
# Load
# ---------------------------------------------------------------------------
ish_bytes = ish_file.getvalue()

with st.spinner("Reading the three files…"):
    pos = load_pos(pos_file)
    exp = load_ishopchangi(ish_file)
    reg = load_registry(reg_file)

blocking = pos.errors + exp.errors + reg.errors
if blocking:
    st.error("**Cannot continue — a required file, worksheet or column is missing:**")
    for e in blocking:
        st.markdown(f"- {e}")
    st.stop()

with st.spinner("Matching against locked mappings…"):
    plan = build_plan(pos, exp, reg)

st.success(
    f"Read **{len(pos.rows)}** POS rows ({len(pos.usable)} sellable on IShopChangi) · "
    f"**{len(exp.listings)}** IShopChangi listings · "
    f"**{len(reg.locked)}** locked matches carried forward. "
    f"`stockQuantity` resolved to column index {exp.stock_qty_col} "
    f"of {exp.n_columns}."
)

# ---------------------------------------------------------------------------
# Validation summary
# ---------------------------------------------------------------------------
st.subheader("Validation summary")
s = validation_summary(plan)
cols = st.columns(4)
for i, (k, v) in enumerate(s.items()):
    cols[i % 4].metric(k, v)

for w in plan.warnings + exp.warnings:
    st.warning(w)

st.divider()

# ---------------------------------------------------------------------------
# Review tabs
# ---------------------------------------------------------------------------
tabs = st.tabs([
    f"🔒 Locked Matches ({len(plan.locked_rows)})",
    f"🆕 New Masterlist SKUs ({len(plan.new_ml_rows)})",
    f"🔍 Match Review ({len(plan.review_rows)})",
    f"🚫 Not Selling ({len(plan.not_selling_rows)})",
    f"📋 Not on IShopChangi Yet ({len(plan.not_yet_rows)})",
    "⚠️ Gap check",
])

with tabs[0]:
    st.caption(
        "Seller stock = **sum of Available Qty across every linked Masterlist SKU**. "
        "These are never re-asked."
    )
    st.dataframe(pd.DataFrame(plan.locked_rows), use_container_width=True,
                 hide_index=True, height=440)
    if plan.buffered:
        st.warning(
            f"**{len(plan.buffered)} listing(s) zeroed by the 1–2 unit oversell "
            "buffer** — read this before uploading:"
        )
        st.dataframe(pd.DataFrame(plan.buffered), use_container_width=True,
                     hide_index=True)
    if plan.double_fed:
        st.error("A POS row is feeding more than one listing:")
        st.dataframe(pd.DataFrame(plan.double_fed), use_container_width=True,
                     hide_index=True)
    if plan.unknown_ids:
        st.info(
            "Locked matches referencing Masterlist IDs that are not in today's "
            "POS report (they contributed 0 — POS families come and go, so this "
            "is a fact about today only):"
        )
        st.dataframe(pd.DataFrame(plan.unknown_ids), use_container_width=True,
                     hide_index=True)

with tabs[1]:
    st.caption(
        "POS SKUs with available stock that appear in none of Locked Matches / "
        "Not Selling / Not on IShopChangi Yet. **Every row needs a decision "
        "before the download unlocks.**"
    )
    if not plan.new_ml_rows:
        st.success("No new Masterlist SKUs — nothing to review.")
        new_ml_edited = pd.DataFrame(plan.new_ml_rows)
    else:
        mp_options = [""] + sorted(
            {l.mp_number for l in exp.listings if l.mp_number}
        )
        new_ml_edited = st.data_editor(
            pd.DataFrame(plan.new_ml_rows),
            use_container_width=True,
            hide_index=True,
            height=520,
            disabled=["#", "Masterlist Stock Type ID", "Category", "Brand",
                      "Model", "Color", "Available Qty",
                      "Suggested MP Matches"],
            column_config={
                "Suggested MP Matches": st.column_config.TextColumn(
                    "Suggested MP Matches", width="medium"),
                "Link to MP Number": st.column_config.SelectboxColumn(
                    "Link to MP Number", options=mp_options,
                    help="Required when the decision is 'Link to MP'"),
                "Reviewer Decision": st.column_config.SelectboxColumn(
                    "Reviewer Decision", options=[""] + list(DECISIONS),
                    required=False),
            },
            key="new_ml_editor",
        )
        plan.new_ml_rows = new_ml_edited.to_dict("records")

with tabs[2]:
    st.caption(
        "IShopChangi listings with no locked match. **Seller stock is left "
        "exactly as it is** until you review and confirm. Set a decision here to "
        "lock a match for every future run."
    )
    review_edited = st.data_editor(
        pd.DataFrame(plan.review_rows).drop(columns=["_row_no", "_auto_exact"],
                                            errors="ignore"),
        use_container_width=True,
        hide_index=True,
        height=520,
        disabled=["#", "MP Number", "Frontend Product Name (EN)",
                  "Backend Product Name (EN)", "Product UUID", "SKU Code",
                  "Brand", "Current Seller Stock",
                  "Suggested Masterlist Matches"],
        column_config={
            "Suggested Masterlist Matches":
                st.column_config.TextColumn("Suggested Masterlist Matches",
                                            width="medium"),
            "Corrected Masterlist ID": st.column_config.TextColumn(
                "Corrected Masterlist ID",
                help="One or more POS Stock Type IDs, separated by ';'"),
            "Reviewer Decision": st.column_config.SelectboxColumn(
                "Reviewer Decision", options=[""] + list(DECISIONS)),
        },
        key="review_editor",
    )
    edited = review_edited.to_dict("records")
    for orig, ed in zip(plan.review_rows, edited):
        orig["Corrected Masterlist ID"] = ed.get("Corrected Masterlist ID", "")
        orig["Reviewer Decision"] = ed.get("Reviewer Decision", "")
        orig["Notes"] = ed.get("Notes", "")

with tabs[3]:
    st.caption("Parked by you as not sold on IShopChangi. Never re-asked.")
    st.dataframe(pd.DataFrame(plan.not_selling_rows), use_container_width=True,
                 hide_index=True, height=420)

with tabs[4]:
    st.caption("Awaiting an IShopChangi listing. Never re-asked.")
    st.dataframe(pd.DataFrame(plan.not_yet_rows), use_container_width=True,
                 hide_index=True, height=420)

with tabs[5]:
    st.caption(
        "A missing family alias is the silent failure of this job — the listing "
        "simply reads 0 and looks out-of-stock. This check runs at **q ≥ 1**, "
        "because a family returning with 1–2 units is buffered to 0 today and "
        "the miss would be invisible."
    )
    gap = gap_check(pos.rows, exp.listings, reg.linked_pos_ids())
    if gap["probable_missing_alias"]:
        st.error(
            f"**{len(gap['probable_missing_alias'])} probable missing alias(es).** "
            "Add them to `core/brands.py` → FAMILY_ALIASES and re-run."
        )
        st.dataframe(pd.DataFrame([
            {
                "POS ID": p.stock_type_id,
                "POS": f"{p.brand_raw} {p.model_raw} | {p.colour}",
                "Qty": p.available,
                "Resembles listing": hits[0][0].backend_name,
                "Score": hits[0][1],
            }
            for p, hits in gap["probable_missing_alias"]
        ]), use_container_width=True, hide_index=True)
    else:
        st.success("No missing aliases detected.")

    st.markdown(
        f"**{len(gap['orphan_pos_stock'])} POS row(s) with stock feed no "
        "IShopChangi listing.** Review that each genuinely has no listing — the "
        "ones with real stock are lost sales merchandising should list."
    )
    st.dataframe(pd.DataFrame([
        {"POS ID": p.stock_type_id, "Brand": p.brand_raw, "Model": p.model_raw,
         "Color": p.colour, "Available Qty": p.available}
        for p in gap["orphan_pos_stock"]
    ]), use_container_width=True, hide_index=True, height=360)

st.divider()

# ---------------------------------------------------------------------------
# Confirm + export gate
# ---------------------------------------------------------------------------
st.subheader("Confirm & export")

unreviewed = plan.unreviewed_new_ml
needs_mp = [
    r for r in plan.new_ml_rows
    if r.get("Reviewer Decision") == DECISION_LINK
    and not str(r.get("Link to MP Number") or "").strip()
]

if unreviewed:
    st.markdown(
        f'<div class="mm-lock">🔒 Export locked — <b>{len(unreviewed)} of '
        f"{len(plan.new_ml_rows)}</b> New Masterlist SKUs still have no Reviewer "
        "Decision. Set a decision for every row on the "
        "<i>New Masterlist SKUs</i> tab.</div>",
        unsafe_allow_html=True,
    )
    st.dataframe(
        pd.DataFrame(unreviewed)[
            ["Masterlist Stock Type ID", "Brand", "Model", "Color", "Available Qty"]
        ],
        use_container_width=True, hide_index=True, height=260,
    )
elif needs_mp:
    st.markdown(
        f'<div class="mm-lock">🔒 Export locked — {len(needs_mp)} row(s) are set '
        f'to "{DECISION_LINK}" but have no MP Number.</div>',
        unsafe_allow_html=True,
    )
else:
    st.success("All New Masterlist SKUs reviewed. Export unlocked.")

    if st.button("✅ Confirm matches & build bulk file", type="primary"):
        with st.spinner("Locking matches and building the bulk file…"):
            apply_review_decisions(plan, reg)
            final = apply_new_ml_decisions(plan, reg, exp, pos)

            if final.errors:
                for e in final.errors:
                    st.error(e)
                st.stop()

        if final.newly_locked:
            st.subheader("🔒 Newly locked matches")
            st.success(
                f"**{len(final.newly_locked)} match(es) locked in** from your "
                "New Masterlist SKUs decisions. They are written into the "
                "**Locked Matches** sheet of the registry below, so the sync "
                "reads them from now on and never asks again."
            )
            st.dataframe(pd.DataFrame(final.newly_locked),
                         use_container_width=True, hide_index=True)

            values = {r: v for r, v in final.stock_by_row.items() if v is not None}
            try:
                out_bytes, res = write_bulk_file(
                    ish_bytes, exp.stock_qty_col, values)
            except ValueError as ex:
                st.error(f"**Export aborted.** {ex}")
                st.stop()

            check = verify_written(ish_bytes, out_bytes, exp.stock_qty_col, values)

        st.subheader("Integrity check")
        if check["ok"]:
            st.success(
                f"Wrote **{check['cells_written']}** `stockQuantity` cells in "
                f"column **{check['column']}**. Every other cell, column, sheet, "
                "formula and style is byte-identical to the file you uploaded. "
                "No value of 1 or 2 survived the buffer."
            )
        else:
            st.error("Integrity check FAILED — do not upload this file.")
            st.json({k: v for k, v in check.items() if k != "ok"})
            st.stop()

        rows_untouched = len(exp.listings) - len(values)
        st.info(
            f"**{len(values)}** listings updated from locked matches · "
            f"**{rows_untouched}** left untouched (Match Review rows keep their "
            "existing seller stock)."
        )

        stamp = f"{date.today():%d-%m-%Y}"
        d1, d2 = st.columns(2)
        with d1:
            st.download_button(
                "⬇️ IShopChangi bulk file",
                data=out_bytes,
                file_name=f"iShopChangi_Stock_Update_{stamp}.xlsx",
                mime="application/vnd.openxmlformats-officedocument."
                     "spreadsheetml.sheet",
                type="primary",
            )
        with d2:
            st.download_button(
                "⬇️ Updated SKU Registry",
                data=build_registry_workbook(final, {
                    "POS Masterlist": pos_file.name,
                    "IShopChangi export": ish_file.name,
                    "SKU Registry in": reg_file.name,
                }),
                file_name=f"IShopChangi_Match_Review_{stamp}.xlsx",
                mime="application/vnd.openxmlformats-officedocument."
                     "spreadsheetml.sheet",
            )

        st.caption(
            "Keep the updated SKU Registry and re-upload it next run — that is "
            "what stops the tool asking about matches you have already confirmed."
        )

st.divider()
st.caption(
    "Mister Mobile · ECSS. Writes the `stockQuantity` column only. "
    "Post-upload, pull a fresh IShopChangi export and diff it on `shop_sku` — "
    "the marketplaces are ERP-linked and can over-ride an uploaded 0 back to 1."
)
