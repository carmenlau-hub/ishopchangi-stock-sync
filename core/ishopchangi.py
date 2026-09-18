"""
ishopchangi.py — read an iShopChangi bulk stock export (download-job-file-*.xlsx).

Sheet `Data` layout:
    row 1 = UUID header
    row 2 = friendly name
    row 3 = FIELD CODE      <-- the only reliable way to find a column
    row 4+ = data

NEVER hard-code column letters. Export width varies with the columns selected:
a full export is 148 columns with stockQuantity at DL, but a filtered export
can be 123 columns with stockQuantity at CM. Writing "DL" on a narrow export
would overwrite 'Airport Staff Only' instead of stock.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

import openpyxl

from .brands import (
    CATEGORY_CAPACITY_FIELDS,
    FALLBACK_CAPACITY_FIELDS,
    FALLBACK_COLOUR_FIELDS,
    FALLBACK_RAM_FIELDS,
    canon_brand,
)

DATA_SHEET = "Data"
HEADER_ROWS = 3          # data starts on spreadsheet row 4

REQUIRED_FIELDS = ("productUUID", "mpNumber", "brand", "productGroupName [en]",
                   "name [en]", "shop_sku", "stockQuantity")

TELCO_HINTS = ("telco", "contract", "with plan", "m1", "singtel", "starhub", "simba")

CAP_RE = re.compile(r"(\d+)\s*(GB|TB)", re.I)
RAM_SLASH_RE = re.compile(r"(\d+)\s*(GB|TB)\s*/\s*(\d+)", re.I)
RAM_PLUS_RE = re.compile(r"\b(\d+)\s*\+\s*(\d+)\s*(GB|TB)", re.I)
RAM_WORD_RE = re.compile(r"\b(\d+)\s*GB\s*RAM", re.I)
NET_RE = re.compile(r"\b(5G|4G|LTE|Wi-?Fi|Cellular|Cell|GPS|Bluetooth)\b", re.I)


@dataclass
class Listing:
    row_no: int              # spreadsheet row number (1-based)
    product_uuid: str
    mp_number: str
    category: str            # full platform path
    leaf_category: str       # last path segment, lowercased
    brand_raw: str
    brand: str               # canonical
    frontend_name: str
    backend_name: str
    shop_sku: str
    current_stock: str       # as written in the file
    capacity: str
    ram: str
    colour: str
    network: str
    is_us_charger: bool
    looks_telco: bool


@dataclass
class IShopExport:
    listings: list[Listing] = field(default_factory=list)
    field_index: dict[str, int] = field(default_factory=dict)
    stock_qty_col: int = -1          # 0-based
    n_columns: int = 0
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def by_sku(self) -> dict[str, Listing]:
        return {l.shop_sku: l for l in self.listings}

    def by_uuid(self) -> dict[str, Listing]:
        return {l.product_uuid: l for l in self.listings}


def _norm_net(tok: str) -> str:
    t = (tok or "").upper().replace("-", "").replace(" ", "")
    if t in ("LTE", "4G"):
        return "4G"
    if t == "WIFI":
        return "WIFI"
    if t in ("CELL", "CELLULAR"):
        return "CELL"
    if t in ("GPS", "BLUETOOTH"):
        return "WIFI"
    return t


def norm_colour(s: str) -> str:
    s = str(s or "").upper()
    s = s.replace("GREY", "GRAY")
    s = re.sub(r"[^A-Z0-9]+", " ", s)
    return " ".join(s.split())


def parse_capacity_ram(*sources: str) -> tuple[str, str]:
    """
    Pull capacity + RAM out of any of several strings, handling all the formats
    the template uses: 256GB/12, 12+256GB, 16GB RAM 512GB, 4/128GB, 12+512GB.
    """
    cap = ram = ""
    for s in sources:
        s = str(s or "")
        if not s:
            continue
        if not ram:
            m = RAM_SLASH_RE.search(s)
            if m:
                # Keep the real unit — "1TB/16" is 1TB, not 1GB.
                cap = cap or f"{int(m.group(1))}{m.group(2).upper()}"
                ram = str(int(m.group(3)))
                continue
            m = RAM_PLUS_RE.search(s)
            if m:
                ram = str(int(m.group(1)))
                cap = cap or f"{int(m.group(2))}{m.group(3).upper()}"
                continue
            m = RAM_WORD_RE.search(s)
            if m:
                ram = str(int(m.group(1)))
        if not cap:
            caps = CAP_RE.findall(s)
            if caps:
                # largest value is the storage figure (RAM is always smaller)
                n, u = max(caps, key=lambda t: int(t[0]) * (1024 if t[1].upper() == "TB" else 1))
                cap = f"{int(n)}{u.upper()}"
    return cap, ram


def _fields_for_category(leaf: str) -> dict[str, tuple[str, ...]]:
    for key, spec in CATEGORY_CAPACITY_FIELDS.items():
        if key in leaf:
            return spec
    return {
        "ram": FALLBACK_RAM_FIELDS,
        "capacity": FALLBACK_CAPACITY_FIELDS,
        "colour": FALLBACK_COLOUR_FIELDS,
    }


def load_ishopchangi(path_or_buf) -> IShopExport:
    exp = IShopExport()
    wb = openpyxl.load_workbook(path_or_buf, read_only=True, data_only=True)
    if DATA_SHEET not in wb.sheetnames:
        exp.errors.append(
            f"Worksheet '{DATA_SHEET}' not found. Sheets present: {wb.sheetnames}"
        )
        wb.close()
        return exp
    rows = list(wb[DATA_SHEET].iter_rows(values_only=True))
    wb.close()

    if len(rows) <= HEADER_ROWS:
        exp.errors.append("iShopChangi export has no data rows below the 3 header rows.")
        return exp

    codes = [str(c).strip() if c is not None else "" for c in rows[2]]
    exp.n_columns = len(codes)
    exp.field_index = {c: i for i, c in enumerate(codes) if c}

    missing = [f for f in REQUIRED_FIELDS if f not in exp.field_index]
    if missing:
        exp.errors.append(
            "iShopChangi export is missing required field code(s) in row 3: "
            + ", ".join(missing)
        )
        return exp

    exp.stock_qty_col = exp.field_index["stockQuantity"]

    def g(row, code, default=""):
        i = exp.field_index.get(code)
        if i is None or i >= len(row):
            return default
        v = row[i]
        return default if v is None else str(v).strip()

    def first(row, codes_, default=""):
        for c in codes_:
            v = g(row, c)
            if v:
                return v
        return default

    for n, r in enumerate(rows[HEADER_ROWS:], start=HEADER_ROWS + 1):
        uuid = g(r, "productUUID")
        if not uuid:
            continue
        cat = g(r, "category")
        leaf = cat.split("/")[-1].strip().lower()
        spec = _fields_for_category(leaf)

        backend = g(r, "name [en]")
        frontend = g(r, "productGroupName [en]")

        ram_f = first(r, spec.get("ram", ()))
        cap_f = first(r, spec.get("capacity", ()))
        cap, ram = parse_capacity_ram(f"{cap_f} / {ram_f}" if ram_f else cap_f, backend)
        if ram_f and not ram:
            m = re.search(r"\d+", ram_f)
            if m:
                ram = m.group(0)

        colour = first(r, spec.get("colour", ())) or first(r, FALLBACK_COLOUR_FIELDS)
        if not colour:
            colour = ""

        net_m = NET_RE.search(f"{backend} {frontend}")
        network = _norm_net(net_m.group(1)) if net_m else ""

        low = f"{backend} {frontend}".lower()
        exp.listings.append(Listing(
            row_no=n,
            product_uuid=uuid,
            mp_number=g(r, "mpNumber"),
            category=cat,
            leaf_category=leaf,
            brand_raw=g(r, "brand"),
            brand=canon_brand(g(r, "brand")),
            frontend_name=frontend,
            backend_name=backend,
            shop_sku=g(r, "shop_sku"),
            current_stock=g(r, "stockQuantity", "0"),
            capacity=cap,
            ram=ram,
            colour=colour,
            network=network,
            is_us_charger="us charger" in low,
            looks_telco=any(h in low for h in TELCO_HINTS),
        ))

    oos = exp.field_index.get("outOfStockQuantity")
    if oos is not None:
        bad = [
            l.row_no for l, r in zip(exp.listings, rows[HEADER_ROWS:])
            if oos < len(r) and str(r[oos] or "0").strip() not in ("0", "")
        ]
        if bad:
            exp.warnings.append(
                f"{len(bad)} row(s) have outOfStockQuantity != 0 "
                f"(first few rows: {bad[:8]}). Left untouched."
            )

    telco = [l for l in exp.listings if l.looks_telco]
    if telco:
        exp.warnings.append(
            f"{len(telco)} listing(s) look like Telco/contract listings — "
            "iShopChangi should not sell Telco sets. Review: "
            + "; ".join(f"{l.mp_number} {l.backend_name}" for l in telco[:6])
        )

    return exp
