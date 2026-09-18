"""
matching.py — suggest POS masterlist SKUs for an iShopChangi listing and vice versa.

The v1 tool scored on raw token overlap, which is why "Apple iPhone 17 Pro" was
offered "NOTHING PHONE 4A PRO (53%)". Two things fix that here:

  1. Brand is a HARD GATE. A suggestion is never produced across brands.
  2. Family aliases decide the family; capacity / RAM / colour / network only
     rank candidates WITHIN a family.

A suggestion is never an automatic link. Only a reviewer decision writes to
Locked Matches.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .brands import (
    COLOUR_RULINGS,
    canon_brand,
    norm_family,
    pos_brands_for,
    resolve_family,
)
from .ishopchangi import Listing, norm_colour
from .pos import PosRow

BRANDWORDS = {"APPLE", "SAMSUNG", "GALAXY", "GOOGLE", "HONOR", "XIAOMI",
              "ONEPLUS", "ONE", "PLUS", "NOTHING", "OPPO", "BLACK", "SHARK",
              "REDMI", "PIXEL", "IPHONE", "IPAD"}
NOISE = {"5G", "4G", "LTE", "WIFI", "WI", "FI", "INCH", "IN", "GB", "TB", "RAM",
         "CELL", "CELLULAR", "GPS", "BLUETOOTH", "EDITION", "WITH", "US",
         "CHARGER", "PRIMARY", "TELCO", "NA", "A"}


def toks(s: str) -> set[str]:
    s = str(s or "").upper().replace("+", " PLUS ")
    s = re.sub(r"[^A-Z0-9]+", " ", s)
    return {t for t in s.split() if t and t not in BRANDWORDS and t not in NOISE}


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / max(len(a), len(b))


def ruled_colour(listing: Listing, colour: str) -> str:
    fam = norm_family(listing.backend_name or listing.frontend_name)
    low = str(colour or "").lower().strip()
    for (fam_sub, tmpl_colour), pos_colour in COLOUR_RULINGS.items():
        if fam_sub in fam and low == tmpl_colour:
            return pos_colour
    return colour


def colours_agree(listing: Listing, pos_row: PosRow) -> bool:
    a = norm_colour(ruled_colour(listing, listing.colour))
    b = norm_colour(pos_row.colour)
    if not a or not b:
        return False
    if a == b:
        return True
    at, bt = set(a.split()), set(b.split())
    return bool(at) and bool(bt) and (at <= bt or bt <= at)


def capacity_agrees(listing: Listing, pos_row: PosRow) -> bool:
    if not listing.capacity or not pos_row.capacity:
        return True                      # only compare when both sides have one
    return listing.capacity.upper() == pos_row.capacity.upper()


def ram_agrees(listing: Listing, pos_row: PosRow) -> bool:
    # POS omits RAM for iPads, iPhones and accessories while the template fills
    # 12GB/16GB — compare only when BOTH sides carry a value.
    if not listing.ram or not pos_row.ram:
        return True
    return str(listing.ram) == str(pos_row.ram)


def network_agrees(listing: Listing, pos_row: PosRow) -> bool:
    if not listing.network or not pos_row.network:
        return True                      # missing network token = wildcard
    if {listing.network, pos_row.network} <= {"WIFI", "4G", "CELL", "5G"}:
        return listing.network == pos_row.network
    return True


def us_charger_agrees(listing: Listing, pos_row: PosRow) -> bool:
    """
    Locked ruling 2: POS stock on a 'W US 80W CHARGER' row belongs ONLY to the
    listing whose name contains "With US Charger". The plain listing gets 0 even
    when POS shows healthy stock for the charger SKU.
    """
    return bool(listing.is_us_charger) == bool(pos_row.is_us_charger)


def _variant(capacity: str, ram: str, colour: str) -> str:
    """'256GB/12 Lemongrass' — just the part that distinguishes variants."""
    cap = f"{capacity}/{ram}" if capacity and ram else (capacity or "")
    return " ".join(p for p in (cap, colour) if p).strip()


@dataclass
class Suggestion:
    pos_row: PosRow
    score: float
    exact: bool
    reason: str
    same_family: bool = True

    def label(self) -> str:
        """
        Compact. The row being reviewed already shows the brand and model, so
        repeating the full POS model string on every suggestion made the cell
        unreadable. Only the variant, quantity and score are shown; the family
        is added back only when the suggestion is from a different family.
        """
        p = self.pos_row
        v = _variant(p.capacity, p.ram, p.colour) or p.model_raw
        if not self.same_family:
            v = f"{p.base} {v}".strip()
        return f"{p.stock_type_id} · {v} · q{p.available} · {int(self.score * 100)}%"


MIN_SUGGESTION_SCORE = 0.75      # below this it is noise, not a candidate
MAX_SUGGESTIONS = 3


def format_suggestions(sugg: list[Suggestion]) -> str:
    """
    One short cell. If an exact match exists, show ONLY the exact ones —
    listing five same-family wrong-capacity rows beside the right answer made
    the column unreadable and hid the answer. Otherwise show up to 3 genuine
    near-misses and nothing weaker.
    """
    exact = [s for s in sugg if s.exact]
    keep = exact or [s for s in sugg if s.score >= MIN_SUGGESTION_SCORE]
    return "  |  ".join(s.label() for s in keep[:MAX_SUGGESTIONS])


def suggest_for_listing(listing: Listing, pos_rows: list[PosRow],
                        limit: int = MAX_SUGGESTIONS) -> list[Suggestion]:
    """
    Rank candidate POS rows for one iShopChangi listing.
    Brand is a hard gate; family alias is a strong gate; the rest ranks.
    """
    allowed = set(pos_brands_for(listing.brand_raw))
    pool = [p for p in pos_rows if p.brand_raw.strip().upper() in
            {b.upper() for b in allowed} or p.brand == canon_brand(listing.brand_raw)]
    if not pool:
        return []

    alias = resolve_family(listing.backend_name, listing.brand_raw) \
        or resolve_family(listing.frontend_name, listing.brand_raw)

    out: list[Suggestion] = []
    lt = toks(listing.backend_name or listing.frontend_name)

    for p in pool:
        if not us_charger_agrees(listing, p):
            continue

        if alias:
            want_brand, want_base = alias
            # EXACT base equality only. A prefix match would let
            # "ONE PLUS 15 ANTI-REFLECTION TEMPERED GLASS SCREEN PROTECTOR"
            # satisfy the "ONE PLUS 15" alias and offer a screen protector's
            # stock to the phone listing. Channel suffixes (PRIMARY/TELCO),
            # capacity, RAM, network and trailing model codes are already
            # stripped out of p.base, so the bases should agree exactly.
            base_ok = p.base.upper() == want_base.upper()
            brand_ok = p.brand_raw.strip().upper() == want_brand.upper()
            if not (base_ok and brand_ok):
                continue
            fam_score = 1.0
        else:
            fam_score = _jaccard(lt, toks(p.base))
            if fam_score < 0.55:
                continue

        cap_ok = capacity_agrees(listing, p)
        ram_ok = ram_agrees(listing, p)
        net_ok = network_agrees(listing, p)
        col_ok = colours_agree(listing, p)

        parts, bits = [], []
        if cap_ok:
            parts.append(0.20)
        else:
            bits.append(f"capacity {listing.capacity or '?'}≠{p.capacity or '?'}")
        if ram_ok:
            parts.append(0.10)
        else:
            bits.append(f"RAM {listing.ram or '?'}≠{p.ram or '?'}")
        if net_ok:
            parts.append(0.10)
        else:
            bits.append(f"network {listing.network or '?'}≠{p.network or '?'}")
        if col_ok:
            parts.append(0.25)
        else:
            bits.append(f"colour {listing.colour or '?'}≠{p.colour or '?'}")

        score = fam_score * 0.35 + sum(parts)
        exact = bool(alias) and cap_ok and ram_ok and net_ok and col_ok
        out.append(Suggestion(
            pos_row=p,
            score=round(min(score, 1.0), 4),
            exact=exact,
            reason="exact" if exact else ("; ".join(bits) or "family only"),
            same_family=bool(alias),
        ))

    out.sort(key=lambda s: (s.exact, s.score, s.pos_row.available), reverse=True)
    if any(s.exact for s in out):
        out = [s for s in out if s.exact]
    return out[:limit]


def format_pos_suggestions(sugg: list[tuple[Listing, float, bool]]) -> str:
    """Compact cell for the New Masterlist SKUs tab — MP + variant + score."""
    exact = [t for t in sugg if t[2]]
    keep = exact or [t for t in sugg if t[1] >= MIN_SUGGESTION_SCORE]
    return "  |  ".join(
        f"{l.mp_number or '(no MP)'} · "
        f"{_variant(l.capacity, l.ram, l.colour) or l.backend_name} · "
        f"{int(sc * 100)}%"
        for l, sc, _ in keep[:MAX_SUGGESTIONS]
    )


def suggest_for_pos(pos_row: PosRow, listings: list[Listing],
                    limit: int = MAX_SUGGESTIONS) -> list[tuple[Listing, float, bool]]:
    """Reverse direction — rank listings for an unmatched POS masterlist SKU."""
    cb = canon_brand(pos_row.brand_raw)
    pool = [l for l in listings if canon_brand(l.brand_raw) == cb]
    if not pool:
        pool = listings

    out = []
    pt = toks(pos_row.base)
    for l in pool:
        alias = resolve_family(l.backend_name, l.brand_raw)
        if alias and alias[0].upper() == pos_row.brand_raw.strip().upper() \
                and pos_row.base.upper() == alias[1].upper():
            fam = 1.0
        else:
            fam = _jaccard(pt, toks(l.backend_name))
            if fam < 0.5:
                continue
        cap_ok = capacity_agrees(l, pos_row)
        ram_ok = ram_agrees(l, pos_row)
        col_ok = colours_agree(l, pos_row)
        net_ok = network_agrees(l, pos_row)
        if not us_charger_agrees(l, pos_row):
            continue
        score = (fam * 0.35 + 0.20 * cap_ok + 0.10 * ram_ok
                 + 0.10 * net_ok + 0.25 * col_ok)
        out.append((l, round(min(score, 1.0), 4),
                    fam == 1.0 and cap_ok and ram_ok and net_ok and col_ok))

    out.sort(key=lambda t: (t[2], t[1]), reverse=True)
    if any(t[2] for t in out):
        out = [t for t in out if t[2]]
    return out[:limit]


# ---------------------------------------------------------------------------
# THE GAP CHECK — a missing family alias is the failure mode of this job.
# It is silent: the listing simply reads 0 and looks out-of-stock.
# ---------------------------------------------------------------------------

def gap_check(pos_rows: list[PosRow], listings: list[Listing],
              linked_pos_ids: set[str], threshold: float = 0.8) -> dict:
    """
    Find POS rows that have stock but feed no listing, and flag any whose name
    strongly resembles a listing sitting at 0 — a probable missing alias.

    Threshold is q >= 1, not 3: a family returning with 1-2 units is buffered
    to 0 today, so the miss is invisible — but the alias must exist before it
    restocks properly tomorrow.
    """
    unfed = [p for p in pos_rows
             if not p.excluded and p.available >= 1
             and p.stock_type_id not in linked_pos_ids]

    aliased_keys = set()
    for l in listings:
        a = resolve_family(l.backend_name, l.brand_raw)
        if a:
            aliased_keys.add((a[0].upper(), a[1].upper()))

    zero_listings = [l for l in listings if str(l.current_stock).strip() in ("", "0")]

    probable, orphan = [], []
    for p in unfed:
        if (p.brand_raw.strip().upper(), p.base.upper()) in aliased_keys:
            continue                       # alias exists, just no linked row today
        hits = []
        for l in zero_listings:
            if canon_brand(l.brand_raw) != canon_brand(p.brand_raw):
                continue
            sc = _jaccard(toks(p.base), toks(norm_family(l.backend_name)))
            if sc >= threshold:
                hits.append((l, round(sc, 3)))
        if hits:
            hits.sort(key=lambda t: t[1], reverse=True)
            probable.append((p, hits[:3]))
        else:
            orphan.append(p)

    return {
        "probable_missing_alias": probable,
        "orphan_pos_stock": sorted(orphan, key=lambda p: -p.available),
        "n_unfed": len(unfed),
    }
