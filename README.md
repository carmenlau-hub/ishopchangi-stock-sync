# IShopChangi Stock Sync — v2

Mister Mobile · ECSS · Dealer Inventory Bulk Update

Generates an IShopChangi bulk stock file from a POS masterlist export, using a
persistent SKU Registry so a confirmed match is never asked about again.

---

## Deploy (Streamlit Community Cloud)

1. Push this folder to GitHub.
2. share.streamlit.io → **New app** → pick the repo.
3. **Main file path:** `app.py`
4. Deploy. `requirements.txt` and `.streamlit/config.toml` are picked up
   automatically.

Run locally:

```bash
pip install -r requirements.txt
streamlit run app.py
```

Run the pipeline without the UI (what CI should do):

```bash
python test_pipeline.py stock_report.xlsx download-job-file-*.xlsx IShopChangi_Match_Review.xlsx
```

---

## Layout

```
app.py                     Streamlit UI (yellow/black, v1 layout preserved)
core/brands.py             ← THE ONLY FILE YOU EDIT TO ADD A BRAND
core/pos.py                POS stock_report reader (Column F, exclusions)
core/ishopchangi.py        bulk-file reader (columns resolved by row-3 field code)
core/matching.py           suggestion scorer + the gap check
core/registry.py           the 5-sheet SKU Registry, buckets, sync plan
core/registry_writer.py    writes the updated SKU Registry
core/writer.py             XML-patch writer + integrity verification
test_pipeline.py           end-to-end assertions
```

---

## Adding a brand (Samsung, Apple, or anything next)

Everything outside `core/brands.py` is brand-agnostic. To add a brand:

**1. Map the brand string** — iShopChangi writes brands inconsistently
(`APPLE`, `Xiaomi`, `One Plus`), and POS splits one retail brand across several
brand strings:

```python
BRAND_ALIASES = {
    "APPLE":   ("IPHONE", "IPAD", "APPLE", "APPLE WATCH"),
    "SAMSUNG": ("SAMSUNG", "SAMSUNG WATCH", "SAMSUNG TABLET"),
}
```

**2. Map each product family** — listing family → POS brand + model base:

```python
FAMILY_ALIASES = {
    "apple iphone 17 pro":      ("IPHONE",  "17 PRO NA"),
    "samsung galaxy z fold7":   ("SAMSUNG", "Z FOLD 7"),
}
```

**3. Only if the platform adds a new category** with its own capacity/RAM
columns, add a `CATEGORY_CAPACITY_FIELDS` entry.

No matching, syncing, writing or UI code changes. The existing Honor / Nothing /
OnePlus / Xiaomi behaviour is untouched by adding entries.

### A missing alias is silent data loss

An unaliased listing ships as `0` and looks like an ordinary out-of-stock row.
Two real incidents this caused:

- **17 Sep 2026** — `ONE PLUS | BUDS 4` appeared in POS with 13 + 12 units. No
  alias, so both listings shipped as `0`.
- **18 Sep 2026** — `XIAOMI | REDMI 17` (20 + 20 units), `SAMSUNG | S25 PLUS`,
  `XIAOMI | XIAOMI 17` and `XIAOMI | XIAOMI 17T PRO` were all unaliased.

So: **add an alias as soon as a POS family and a listing family plainly refer to
the same product, even if POS stock is 0 today.** An alias for an absent family
costs nothing — the lookup simply finds nothing.

The **Gap check** tab runs on every load at a threshold of **q ≥ 1** (not 3),
because a family returning with 1–2 units is buffered to `0` today and the miss
would be invisible.

---

## The rules this tool enforces

### Stock source

POS **Column F, "Available Quantity"**, only. Never Column G (Quantity), never
per-branch sums, never `Quantity − Reserved − Transit` — Column F already
accounts for them.

### Oversell buffer

After taking Column F, a quantity of **1 or 2 becomes 0**. Every buffered item is
listed in the UI before the download is offered. `test_pipeline.py` asserts no
`1` or `2` survives.

### Rows excluded from IShopChangi

| Excluded | Why |
|---|---|
| `Category = Used` | IShopChangi sells brand-new only |
| Apple `… A` rows | activated sets — **only `… NA` (non-activated) is sellable** |
| `TELCO` channel | IShopChangi does not sell Telco sets; PRIMARY pools only |
| `FREEBIE` / `FREEBIES` | giveaway units |
| Export sets | `JP TH TW HK CN KR MY VN US` as a whole word |

`W US 80W CHARGER` is stripped **before** the `US` export test — on OnePlus names
it means "bundled with a US charger", not an export set.

Unlike the other marketplaces, **Apple is not excluded on IShopChangi**.

### Locked rulings

1. **iPhone: NA pool only.** POS keeps `… NA` (non-activated, sealed) and `… A`
   (activated) per variant. IShopChangi sells NA only — confirmed by Mabel Yap,
   16 Sep 2026. Never fall back to an `A` row, even when NA is `0` and A has
   stock. Listing names carry no NA/A marker, so this is decided on the POS side.
2. **OnePlus `W US 80W CHARGER` is a different device.** That POS stock belongs
   only to the listing whose name contains "With US Charger". The plain
   `OnePlus 15 / 15R` listings get `0` even when POS shows healthy charger stock.
3. **Telco:** PRIMARY pools only. A model with a TELCO pool but no PRIMARY pool
   gets `0`. Listings that themselves look like Telco/contract listings are
   flagged in the UI.
4. **Honor Watch X5i:** `Durable Polymer White` → POS `WHITE`,
   `Durable Polymer Black` → POS `BLACK`.

### Name traps

`Honor Pad 20 Pro Paperlike Edition` ≠ `Honor Pad 20` · `Galaxy Watch7` ≠
`WATCH 8` · `AirPods Pro 2` ≠ `AIRPODS PRO 3` · `Honor X6e` ≠ `X6C`/`X7E` ·
`Z Flip7` ≠ `Z FLIP 7 FE` · `Redmi 17` ≠ `Redmi 17C` · `Xiaomi 17` ≠ `Xiaomi 17T`
· `Pixel 10 Pro` ≠ `Pixel 10 Pro XL`/`Pro Fold` · iPad `Cellular` and `Wi-Fi`
are separate pools.

Never borrow a neighbouring generation's quantity. Aliases match on an exact
normalised key, so `xiaomi 17`, `xiaomi 17t` and `xiaomi 17t pro` cannot collide.

### POS families come and go

A device can drop out of the POS report entirely and be restocked days later.
Every "this family has no POS pool" observation is **a fact about today only**,
never a rule. The tool never writes a permanent note to that effect, and the gap
check runs on every load rather than only when the template changes.

---

## The workflow (unchanged from v1)

```
   match  →  review  →  Reviewer Decision + MP link  →  LOCK  →  POS stock sync
                                                          ↑
                                          re-upload the SKU Registry next run
```

| Sheet | Behaviour |
|---|---|
| **Locked Matches** | Seller stock = **sum of Available Qty across every linked Masterlist SKU**. Never re-asked. |
| **Match Review** | Seller stock **left exactly as it is** until reviewed and confirmed. |
| **New Masterlist SKUs** | POS SKUs with stock that appear in none of Locked / Not Selling / Not on Yet. **Every row must have a decision before the export unlocks.** |
| **Not Selling in IShopChangi** | Parked by the reviewer. Never re-asked. |
| **Not on IShopChangi Yet** | Awaiting a listing. Never re-asked. |

Carry-forward is keyed on **Product UUID** (stable), falling back to `shop_sku`
then MP Number — never on row position.

Reviewer decisions: `Link to MP`, `Not Selling in IShopChangi`,
`Not on IShopChangi Yet`, `Skip`.

---

## Output integrity

Only the `stockQuantity` column is written.

`stockQuantity` is located by its **row-3 field code**, never by column letter.
Export width varies with the columns selected: a full export is 148 columns with
`stockQuantity` at `DL`, but a filtered export can be 123 columns with it at
`CM`. Writing "DL" on a narrow export would overwrite *Airport Staff Only*.

Re-saving with openpyxl rewrites ~45,000 cells (empty inline strings collapse to
blanks) and touches `ReferenceData`, so instead `core/writer.py` patches the Data
sheet's XML in place and copies every other zip member through byte-for-byte.
These cells are `t="inlineStr"` holding **strings**, so `<t>0</t>` is written, not
a numeric cell.

Before the download button appears, `verify_written()` proves:

- every non-Data zip member is byte-identical to the upload
- zero cells outside the stock column changed
- every written value equals the planned value
- no `1` or `2` survived the buffer
- no cell changed that was not planned

If any of that fails the export is refused rather than offered.

Deliverable: `iShopChangi_Stock_Update_DD-MM-YYYY.xlsx`.

---

## After uploading to IShopChangi

The marketplaces are ERP-linked. On TikTok a SKU with no POS record inherited
another variant's quantity (Honor Watch X5i Telco-White showed 43, which was
Basic-White's figure), and SKUs set to `0` came back as `1`.

So after each bulk upload, pull a fresh export and diff it **keyed on
`shop_sku`**, never on row position. Check the multi-listing-per-device pairs
first — the OnePlus 15 / 15R plain-vs-"With US Charger" rows and the three Honor
Pad 20 pools are where an over-ride surfaces.

A filtered 10-row export proves nothing about the other 709 — pull the full one.
