"""
brands.py — the ONLY file you edit to add a brand.

Everything else in the app is brand-agnostic. To support a new brand you add:
  1. an entry in BRAND_ALIASES   (iShopChangi brand string -> POS brand string(s))
  2. family aliases in FAMILY_ALIASES  (listing family -> POS brand + model base)
  3. (rare) a category rule in CATEGORY_CAPACITY_FIELDS if the platform
     introduces a new category with its own capacity/RAM attribute columns.

No matching, syncing or UI code needs to change.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# 1. Brand normalisation
# ---------------------------------------------------------------------------
# iShopChangi writes brands inconsistently ("APPLE", "Xiaomi", "One Plus").
# POS splits a single retail brand across several brand strings
# (APPLE -> IPHONE / IPAD / APPLE / APPLE WATCH).
#
# Key   = normalised iShopChangi brand (upper, single-spaced)
# Value = ordered tuple of POS brand strings that may hold its stock
# ---------------------------------------------------------------------------

BRAND_ALIASES: dict[str, tuple[str, ...]] = {
    "APPLE":       ("IPHONE", "IPAD", "APPLE", "APPLE WATCH"),
    "SAMSUNG":     ("SAMSUNG", "SAMSUNG WATCH", "SAMSUNG TABLET"),
    "GOOGLE":      ("GOOGLE", "GOOGLE WATCH"),
    "HONOR":       ("HONOR", "HONOR TABLET"),
    "NOTHING":     ("NOTHING",),
    "ONE PLUS":    ("ONE PLUS",),
    "ONEPLUS":     ("ONE PLUS",),
    "XIAOMI":      ("XIAOMI", "XIAOMI TABLET"),
    "BLACK SHARK": ("XIAOMI",),          # POS files Black Shark under XIAOMI
    "OPPO":        ("OPPO", "OPPO WATCH"),
    "SONY":        ("SONY",),
    "DJI":         ("DJI",),
}

# Free-text brand spellings -> canonical BRAND_ALIASES key.
BRAND_SPELLINGS: dict[str, str] = {
    "APPLE": "APPLE", "IPHONE": "APPLE", "IPAD": "APPLE", "APPLE WATCH": "APPLE",
    "SAMSUNG": "SAMSUNG", "GALAXY": "SAMSUNG", "SAMSUNG WATCH": "SAMSUNG",
    "GOOGLE": "GOOGLE", "PIXEL": "GOOGLE", "GOOGLE WATCH": "GOOGLE",
    "HONOR": "HONOR", "HONOR TABLET": "HONOR",
    "NOTHING": "NOTHING", "CMF": "NOTHING",
    "ONE PLUS": "ONE PLUS", "ONEPLUS": "ONE PLUS", "1+": "ONE PLUS",
    "XIAOMI": "XIAOMI", "REDMI": "XIAOMI", "POCO": "XIAOMI",
    "BLACK SHARK": "BLACK SHARK", "BLACKSHARK": "BLACK SHARK",
    "OPPO": "OPPO", "OPPO WATCH": "OPPO",
    "SONY": "SONY", "DJI": "DJI",
}


def canon_brand(raw: str) -> str:
    """Normalise any brand spelling to a BRAND_ALIASES key."""
    s = " ".join(str(raw or "").upper().split())
    if s in BRAND_SPELLINGS:
        return BRAND_SPELLINGS[s]
    for spelling, canon in BRAND_SPELLINGS.items():
        if spelling in s:
            return canon
    return s


def pos_brands_for(ishop_brand: str) -> tuple[str, ...]:
    """POS brand strings that may hold stock for an iShopChangi brand."""
    return BRAND_ALIASES.get(canon_brand(ishop_brand), (canon_brand(ishop_brand),))


# ---------------------------------------------------------------------------
# 2. Family aliases: listing family -> (POS brand, POS model base)
# ---------------------------------------------------------------------------
# Keys are normalised by norm_family() below, so "Apple iPhone 17 Pro",
# "APPLE IPHONE 17 PRO" and "apple  iphone 17  pro" all hit the same entry.
#
# Aliases are matched by EXACT normalised key, so "xiaomi 17", "xiaomi 17t"
# and "xiaomi 17t pro" never collide.
#
# Adding an alias for a family POS does not currently stock is free and
# harmless (the lookup simply finds nothing). A MISSING alias is silent data
# loss — the listing ships as 0 and looks like an ordinary out-of-stock row.
# ---------------------------------------------------------------------------

FAMILY_ALIASES: dict[str, tuple[str, str]] = {
    # ---------------- APPLE ----------------------------------------------
    # iShopChangi sells NON-ACTIVATED sets only -> always alias to the POS
    # "... NA" base. Never fall back to an "... A" (activated) row, even when
    # the NA row is 0 and the A row has stock.  (Confirmed: Mabel Yap, 16 Sep 2026)
    "apple iphone 16":                  ("IPHONE", "16 NA"),
    "apple iphone 16 plus":             ("IPHONE", "16 PLUS NA"),
    "apple iphone 16 pro":              ("IPHONE", "16 PRO NA"),
    "apple iphone 16 pro max":          ("IPHONE", "16 PRO MAX NA"),
    "apple iphone 16e":                 ("IPHONE", "16E NA"),
    "apple iphone 17":                  ("IPHONE", "17 NA"),
    "apple iphone 17 pro":              ("IPHONE", "17 PRO NA"),
    "apple iphone 17 pro max":          ("IPHONE", "17 PRO MAX NA"),
    "apple iphone air":                 ("IPHONE", "AIR NA"),
    "apple ipad air 11 inch m4":        ("IPAD", "AIR 11.0 8 GEN M4 2026"),
    "apple ipad air 13 inch m4":        ("IPAD", "AIR 13.0 8 GEN M4 2026"),
    "apple ipad air 11 inch m2":        ("IPAD", "AIR 11.0 6 GEN M2 2024"),
    "apple ipad air 13 inch m2":        ("IPAD", "AIR 13.0 6 GEN M2 2024"),
    "apple ipad pro 11 inch m5":        ("IPAD", "PRO 11.0 8 GEN M5 2025"),
    "apple ipad pro 13 inch m5":        ("IPAD", "PRO 13.0 8 GEN M5 2025"),
    "apple ipad 11 inch a16":           ("IPAD", "11.0 11 GEN A16 2025"),
    "apple ipad mini a17 pro":          ("IPAD", "MINI 7 GEN A17 PRO 2024"),
    "apple airpods 4":                  ("APPLE", "AIRPODS 4"),
    "apple airpods 4 anc":              ("APPLE", "AIRPODS 4 ANC"),
    "apple airpods pro 3":              ("APPLE", "AIRPODS PRO 3"),
    "apple watch series 11":            ("APPLE WATCH", "SERIES 11"),
    "apple watch series 10":            ("APPLE WATCH", "SERIES 10"),
    "apple watch se 3":                 ("APPLE WATCH", "SE 3"),
    "apple watch ultra 3":              ("APPLE WATCH", "ULTRA 3"),
    "apple watch ultra 2":              ("APPLE WATCH", "ULTRA 2"),

    # ---------------- SAMSUNG --------------------------------------------
    "samsung galaxy s25":               ("SAMSUNG", "S25"),
    "samsung galaxy s25 plus":          ("SAMSUNG", "S25 PLUS"),
    "samsung galaxy s25 ultra":         ("SAMSUNG", "S25 ULTRA"),
    "samsung galaxy s25 fe":            ("SAMSUNG", "S25 FE"),
    "samsung galaxy s26":               ("SAMSUNG", "S26"),
    "samsung galaxy s26 plus":          ("SAMSUNG", "S26 PLUS"),
    "samsung galaxy s26 ultra":         ("SAMSUNG", "S26 ULTRA"),
    "samsung galaxy z fold7":           ("SAMSUNG", "Z FOLD 7"),
    "samsung galaxy z flip7":           ("SAMSUNG", "Z FLIP 7"),
    "samsung galaxy z flip7 fe":        ("SAMSUNG", "Z FLIP 7 FE"),
    "samsung galaxy a17":               ("SAMSUNG", "A17"),
    "samsung galaxy a36":               ("SAMSUNG", "A36"),
    "samsung galaxy a56":               ("SAMSUNG", "A56"),
    "samsung galaxy a57":               ("SAMSUNG", "A57"),
    "samsung galaxy tab s10 plus":      ("SAMSUNG", "TAB S10 PLUS"),
    "samsung galaxy tab s10 ultra":     ("SAMSUNG", "TAB S10 ULTRA"),
    "samsung galaxy tab s11":           ("SAMSUNG", "TAB S11"),
    "samsung galaxy tab s11 ultra":     ("SAMSUNG", "TAB S11 ULTRA"),
    "samsung galaxy tab a11":           ("SAMSUNG", "TAB A11"),
    "samsung galaxy watch7":            ("SAMSUNG WATCH", "WATCH 7"),
    "samsung galaxy watch8":            ("SAMSUNG WATCH", "WATCH 8"),
    "samsung galaxy watch8 classic":    ("SAMSUNG WATCH", "WATCH 8 CLASSIC"),
    "samsung galaxy watch ultra":       ("SAMSUNG WATCH", "WATCH ULTRA"),

    # ---------------- GOOGLE ---------------------------------------------
    "google pixel 9a":                  ("GOOGLE", "PIXEL 9A"),
    "google pixel 10":                  ("GOOGLE", "PIXEL 10"),
    "google pixel 10a":                 ("GOOGLE", "PIXEL 10A"),
    "google pixel 10 pro":              ("GOOGLE", "PIXEL 10 PRO"),
    "google pixel 10 pro xl":           ("GOOGLE", "PIXEL 10 PRO XL"),
    "google pixel 10 pro fold":         ("GOOGLE", "PIXEL 10 PRO FOLD"),
    "google pixel watch 3":             ("GOOGLE WATCH", "PIXEL WATCH 3"),
    "google pixel watch 4":             ("GOOGLE WATCH", "PIXEL WATCH 4"),

    # ---------------- HONOR ----------------------------------------------
    "honor 400 smart":                  ("HONOR", "HONOR 400 SMART"),
    "honor 500 smart":                  ("HONOR", "HONOR 500 SMART"),
    "honor 600":                        ("HONOR", "HONOR 600"),
    "honor 600 lite":                   ("HONOR", "HONOR 600 LITE"),
    "honor 600 pro":                    ("HONOR", "HONOR 600 PRO"),
    "honor magic 8 pro":                ("HONOR", "MAGIC 8 PRO"),
    "honor magic v3":                   ("HONOR", "MAGIC V3"),
    "honor magic v5":                   ("HONOR", "MAGIC V5"),
    "honor magic v6":                   ("HONOR", "MAGIC V6"),
    "honor magic 7 pro":                ("HONOR", "MAGIC 7 PRO"),
    "honor x5d plus":                   ("HONOR", "X5D PLUS"),
    "honor x6e":                        ("HONOR", "X6E"),
    "honor x7e":                        ("HONOR", "X7E"),
    "honor x9d":                        ("HONOR", "X9D"),
    "honor watch x5i":                  ("HONOR", "WATCH X5I"),
    "honor magic pad 4":                ("HONOR TABLET", "MAGIC PAD 4"),
    "honor pad 20":                     ("HONOR TABLET", "PAD 20"),
    "honor pad 20 pro":                 ("HONOR TABLET", "PAD 20 PRO"),
    # NOT the same product as "honor pad 20" — keep separate:
    "honor pad 20 pro paperlike edition": ("HONOR TABLET", "PAD 20 PRO PAPERLIKE EDITION"),

    # ---------------- NOTHING --------------------------------------------
    "nothing phone 2":                  ("NOTHING", "PHONE 2"),
    "nothing phone 3":                  ("NOTHING", "PHONE 3"),
    "nothing phone 3a":                 ("NOTHING", "PHONE 3A"),
    "nothing phone 3a pro":             ("NOTHING", "PHONE 3A PRO"),
    "nothing phone 4a":                 ("NOTHING", "PHONE 4A"),
    "nothing phone 4a pro":             ("NOTHING", "PHONE 4A PRO"),
    "nothing phone 4b":                 ("NOTHING", "PHONE 4B"),
    "nothing cmf phone 2 pro":          ("NOTHING", "CMF PHONE 2 PRO"),
    "nothing cmf buds":                 ("NOTHING", "CMF BUDS"),
    "nothing cmf headphone pro":        ("NOTHING", "CMF HEADPHONE PRO"),
    "nothing ear 3":                    ("NOTHING", "EAR 3 BUDS"),
    # Locked ruling 5: Ear (3a) is NOT Ear (3). POS 'EAR 3 BUDS' is Ear (3)
    # only. Ear (3a) has its own pool name and is 0 while POS carries none.
    "nothing ear 3a":                   ("NOTHING", "EAR 3A BUDS"),
    "nothing ear a":                    ("NOTHING", "EAR A BUDS"),
    "nothing headphone 1":              ("NOTHING", "HEADPHONE 1"),
    "nothing headphone a":              ("NOTHING", "HEADPHONE (A)"),

    # ---------------- ONE PLUS -------------------------------------------
    "oneplus 13s":                      ("ONE PLUS", "ONE PLUS 13S"),
    "oneplus 15":                       ("ONE PLUS", "ONE PLUS 15"),
    "oneplus 15r":                      ("ONE PLUS", "ONE PLUS 15R"),
    "oneplus nord 5":                   ("ONE PLUS", "NORD 5"),
    "oneplus nord 6":                   ("ONE PLUS", "NORD 6"),
    "oneplus buds 4":                   ("ONE PLUS", "BUDS 4"),
    "oneplus buds pro 3":               ("ONE PLUS", "BUDS PRO 3"),
    "oneplus nord buds 3r":             ("ONE PLUS", "NORD BUDS 3R"),
    "oneplus pad 4":                    ("ONE PLUS", "PAD 4"),
    "oneplus pad go 2":                 ("ONE PLUS", "PAD GO 2"),
    "oneplus airvooc 50w magnetic charger": ("ONE PLUS", "AIRVOOC 50W MAGNETIC CHARGER"),
    "oneplus watch 3":                  ("ONE PLUS", "WATCH 3"),

    # ---------------- XIAOMI ---------------------------------------------
    "xiaomi 15":                        ("XIAOMI", "XIAOMI 15"),
    "xiaomi 15t":                       ("XIAOMI", "XIAOMI 15T"),
    "xiaomi 15t pro":                   ("XIAOMI", "XIAOMI 15T PRO"),
    "xiaomi 17":                        ("XIAOMI", "XIAOMI 17"),
    "xiaomi 17t":                       ("XIAOMI", "XIAOMI 17T"),
    "xiaomi 17t pro":                   ("XIAOMI", "XIAOMI 17T PRO"),
    "xiaomi 17 ultra":                  ("XIAOMI", "XIAOMI 17 ULTRA"),
    "xiaomi pad 7":                     ("XIAOMI", "XIAOMI PAD 7"),
    "xiaomi pad 7 pro":                 ("XIAOMI", "XIAOMI PAD 7 PRO"),
    "xiaomi pad 8":                     ("XIAOMI", "XIAOMI PAD 8"),
    "xiaomi redmi 15c":                 ("XIAOMI", "REDMI 15C"),
    "xiaomi redmi 15":                  ("XIAOMI", "REDMI 15"),
    "xiaomi redmi 17":                  ("XIAOMI", "REDMI 17"),
    "xiaomi redmi 17c":                 ("XIAOMI", "REDMI 17C"),
    "xiaomi redmi a7":                  ("XIAOMI", "REDMI A7"),
    "xiaomi redmi note 14":             ("XIAOMI", "REDMI NOTE 14"),
    "xiaomi redmi note 15 pro plus":    ("XIAOMI", "REDMI NOTE 15 PRO PLUS"),
    "xiaomi redmi note 17":             ("XIAOMI", "REDMI NOTE 17"),
    "xiaomi redmi note 17 pro":         ("XIAOMI", "REDMI NOTE 17 PRO"),
    "xiaomi redmi note 17 pro max":     ("XIAOMI", "REDMI NOTE 17 PRO MAX"),
    "xiaomi redmi pad 2 9.7 in":        ("XIAOMI", "REDMI PAD 2 9.7"),
    "xiaomi redmi buds 8":              ("XIAOMI", "REDMI BUDS 8"),
    "xiaomi redmi headphones neo":      ("XIAOMI", "REDMI HEADPHONES NEO"),

    # ---------------- BLACK SHARK (filed under XIAOMI in POS) ------------
    "black shark funcooler 2 pro":      ("XIAOMI", "BLACK SHARK FUNCOOLER 2 PRO"),
    "black shark t23 earbuds":          ("XIAOMI", "BLACK SHARK T23"),
    "black shark pad 7":                ("XIAOMI", "BLACK SHARK PAD 7"),

    # ---------------- OPPO ------------------------------------------------
    "oppo reno 13f":                    ("OPPO", "RENO 13F"),
    "oppo reno 14f":                    ("OPPO", "RENO 14F"),
    "oppo reno 15f":                    ("OPPO", "RENO 15F"),
    "oppo reno 16":                     ("OPPO", "RENO 16"),
    "oppo reno 16f":                    ("OPPO", "RENO 16F"),
    "oppo find x9 pro":                 ("OPPO", "FIND X9 PRO"),
    "oppo find x9 ultra":               ("OPPO", "FIND X9 ULTRA"),
    "oppo find x9s":                    ("OPPO", "FIND X9S"),
    "oppo find n6":                     ("OPPO", "FIND N6"),
    "oppo a6":                          ("OPPO", "A6"),
    "oppo a6 pro":                      ("OPPO", "A6 PRO"),
    "oppo a6c":                         ("OPPO", "A6C"),
    "oppo a6x":                         ("OPPO", "A6X"),

    # -------------------------------------------------------------------
    # Older / current generations that are LISTED on iShopChangi.
    # POS may or may not stock them today — "no POS pool" is a fact about
    # today only, never a rule. An alias for an absent family costs nothing;
    # a MISSING alias ships the listing as 0 and looks like out-of-stock.
    # -------------------------------------------------------------------
    # Apple
    "apple ipad 10th generation":       ("IPAD", "10.0 10 GEN 2022"),
    "apple ipad 11th generation":       ("IPAD", "11.0 11 GEN 2025"),
    "apple ipad mini 7th generation":   ("IPAD", "MINI 7 GEN 2024"),
    "apple airpods pro 2 magsafe with usb c": ("APPLE", "AIRPODS PRO 2 MAGSAFE USB-C"),
    "apple airpods pro 2 magsafe with lightning": ("APPLE", "AIRPODS PRO 2 MAGSAFE"),
    "apple iphone 12":                  ("IPHONE", "12 NA"),
    "apple iphone 15":                  ("IPHONE", "15 NA"),
    "apple iphone 15 plus":             ("IPHONE", "15 PLUS NA"),
    "apple iphone 15 pro":              ("IPHONE", "15 PRO NA"),
    "apple iphone 15 pro max":          ("IPHONE", "15 PRO MAX NA"),
    "apple iphone 18":                  ("IPHONE", "18 NA"),
    "apple iphone 18 pro":              ("IPHONE", "18 PRO NA"),
    "apple iphone 18 pro max":          ("IPHONE", "18 PRO MAX NA"),
    "apple watch ultra 4":              ("APPLE WATCH", "ULTRA 4"),

    # Google — Pixel 9 and Pixel 11 families
    "google pixel 9":                   ("GOOGLE", "PIXEL 9"),
    "google pixel 9 pro":               ("GOOGLE", "PIXEL 9 PRO"),
    "google pixel 9 pro xl":            ("GOOGLE", "PIXEL 9 PRO XL"),
    "google pixel 9 pro fold":          ("GOOGLE", "PIXEL 9 PRO FOLD"),
    "google pixel 11":                  ("GOOGLE", "PIXEL 11"),
    "google pixel 11 pro":              ("GOOGLE", "PIXEL 11 PRO"),
    "google pixel 11 pro xl":           ("GOOGLE", "PIXEL 11 PRO XL"),
    "google pixel 11 pro fold":         ("GOOGLE", "PIXEL 11 PRO FOLD"),

    # Samsung — A-series, Z-series, Tab
    "samsung galaxy a07":               ("SAMSUNG", "A07"),
    "samsung galaxy a27":               ("SAMSUNG", "A27"),
    "samsung galaxy a37":               ("SAMSUNG", "A37"),
    "samsung galaxy s26 fe":            ("SAMSUNG", "S26 FE"),
    "samsung galaxy z flip8":           ("SAMSUNG", "Z FLIP 8"),
    "samsung galaxy z fold8":           ("SAMSUNG", "Z FOLD 8"),
    "samsung galaxy z fold8 ultra":     ("SAMSUNG", "Z FOLD 8 ULTRA"),
    "samsung galaxy buds 4":            ("SAMSUNG", "BUDS 4"),
    "samsung galaxy buds 4 pro":        ("SAMSUNG", "BUDS 4 PRO"),
    "samsung galaxy tab a11 plus":      ("SAMSUNG", "TAB A11 PLUS"),
    "samsung galaxy tab s9 fe":         ("SAMSUNG", "TAB S9 FE"),
    "samsung galaxy tab s9 fe plus":    ("SAMSUNG", "TAB S9 FE PLUS"),
    "samsung galaxy watch9":            ("SAMSUNG WATCH", "WATCH 9"),
    "samsung galaxy watch ultra 2":     ("SAMSUNG WATCH", "WATCH ULTRA 2"),

    # Honor — 200/400 series, Play, X-series, tablets
    "honor 200":                        ("HONOR", "HONOR 200"),
    "honor 200 lite":                   ("HONOR", "HONOR 200 LITE"),
    "honor 200 pro":                    ("HONOR", "HONOR 200 PRO"),
    "honor 400":                        ("HONOR", "HONOR 400"),
    "honor 400 lite":                   ("HONOR", "HONOR 400 LITE"),
    "honor 400 pro":                    ("HONOR", "HONOR 400 PRO"),
    "honor play 10":                    ("HONOR", "PLAY 10"),
    "honor x5b plus":                   ("HONOR", "X5B PLUS"),
    "honor x6c":                        ("HONOR", "X6C"),
    "honor x9c":                        ("HONOR", "X9C"),
    "honor magic 8 pro magnetic essentials kit": ("HONOR", "MAGIC 8 PRO MAGNETIC ESSENTIALS KIT"),
    "honor magic pad 2":                ("HONOR TABLET", "MAGIC PAD 2"),
    "honor magic pad 3":                ("HONOR TABLET", "MAGIC PAD 3"),
    "honor pad 9":                      ("HONOR TABLET", "PAD 9"),
    "honor pad 10":                     ("HONOR TABLET", "PAD 10"),
    "honor pad v9":                     ("HONOR TABLET", "PAD V9"),
    "honor pad x7":                     ("HONOR", "PAD X7"),
    "honor pad x8a":                    ("HONOR TABLET", "PAD X8A"),
    "honor pad x8b":                    ("HONOR TABLET", "PAD X8B"),
    "honor pad x9":                     ("HONOR TABLET", "PAD X9"),
    "honor pad x9a":                    ("HONOR TABLET", "PAD X9A"),

    # Nothing
    "nothing cmf clip pro":             ("NOTHING", "CMF CLIP PRO"),
    "nothing ear open":                 ("NOTHING", "EAR OPEN BUDS"),

    # OnePlus
    "oneplus 13":                       ("ONE PLUS", "ONE PLUS 13"),
    "oneplus 13r":                      ("ONE PLUS", "ONE PLUS 13R"),
    "oneplus nord 4":                   ("ONE PLUS", "NORD 4"),
    "oneplus nord buds 3":              ("ONE PLUS", "NORD BUDS 3"),
    "oneplus nord ce 4 lite":           ("ONE PLUS", "NORD CE 4 LITE"),
    "oneplus nord ce 5":                ("ONE PLUS", "NORD CE 5"),
    "oneplus bullets wireless z3":      ("ONE PLUS", "BULLETS WIRELESS Z3"),
    "oneplus pad lite":                 ("ONE PLUS", "PAD LITE"),

    # Xiaomi / Redmi
    "xiaomi redmi a5":                  ("XIAOMI", "REDMI A5"),
    "xiaomi redmi buds 6 active":       ("XIAOMI", "REDMI BUDS 6 ACTIVE"),
    "xiaomi redmi note 13 pro plus":    ("XIAOMI", "REDMI NOTE 13 PRO PLUS"),
    "xiaomi redmi note 15":             ("XIAOMI", "REDMI NOTE 15"),
    "xiaomi redmi note 15 pro":         ("XIAOMI", "REDMI NOTE 15 PRO"),
    "xiaomi redmi pad 2":               ("XIAOMI", "REDMI PAD 2"),
    "xiaomi redmi pad se":              ("XIAOMI", "REDMI PAD SE"),
    "xiaomi smart band 9 active":       ("XIAOMI", "SMART BAND 9 ACTIVE"),
    "xiaomi smart band 9 pro":          ("XIAOMI", "SMART BAND 9 PRO"),

    # Black Shark (POS files these under XIAOMI)
    "black shark earbuds t9":           ("XIAOMI", "BLACK SHARK EARBUDS T9"),
    "black shark magcooler 3 pro":      ("XIAOMI", "BLACK SHARK MAGCOOLER 3 PRO"),
    "black shark gt3 neo":              ("XIAOMI", "BLACK SHARK GT3 NEO"),
    "black shark green ghost gamepad":  ("XIAOMI", "BLACK SHARK GREEN GHOST GAMEPAD"),
    "black shark s1 pro smart watch":   ("XIAOMI", "BLACK SHARK S1 PRO SMART WATCH"),
}


# ---------------------------------------------------------------------------
# 3. Category -> capacity / RAM attribute columns
# ---------------------------------------------------------------------------
# iShopChangi stores capacity and RAM in DIFFERENT columns per category.
# Reading the wrong one silently drops the capacity from the match key.
# ---------------------------------------------------------------------------

CATEGORY_CAPACITY_FIELDS: dict[str, dict[str, tuple[str, ...]]] = {
    "mobile phones": {
        "ram":      ("RAM_Memory",),
        "capacity": ("level2saleMeasure-mobile",),
        "colour":   ("level1saleMeasure-smtde_clr", "SD_Colour_Family"),
    },
    "tablets": {
        "ram":      ("Tablets_RAM_Memory",),
        "capacity": ("level2saleMeasure-tablet_capacity",),
        "colour":   ("level1saleMeasure-smtde_clr", "SD_Colour_Family"),
    },
    "elect accessories": {
        "ram":      ("electAccessories_RAM_Memory",),
        "capacity": ("level2saleMeasure-elec_accessory",),
        "colour":   ("level1saleMeasure-access_clr", "Elec_Access_Colour_Family"),
    },
    "head & earphones": {
        "ram":      (),
        "capacity": (),
        "colour":   ("level1saleMeasure-audio", "Audio_Colour_Family"),
    },
    "watches & timepiece": {
        "ram":      (),
        "capacity": (),
        "colour":   ("level2saleMeasure-watches",),
        "size":     ("level1saleMeasure-watch_tmpc",),
    },
}

# Tried in order for any category not listed above.
FALLBACK_RAM_FIELDS = (
    "RAM_Memory", "Tablets_RAM_Memory", "electAccessories_RAM_Memory",
)
FALLBACK_CAPACITY_FIELDS = (
    "level2saleMeasure-mobile", "level2saleMeasure-tablet_capacity",
    "level2saleMeasure-elec_accessory",
)
FALLBACK_COLOUR_FIELDS = (
    "level1saleMeasure-smtde_clr", "level1saleMeasure-access_clr",
    "level1saleMeasure-audio", "level2saleMeasure-watches",
    "SD_Colour_Family", "Audio_Colour_Family", "Elec_Access_Colour_Family",
)


# ---------------------------------------------------------------------------
# 4. Locked rulings that are BRAND-SPECIFIC but not per-family
# ---------------------------------------------------------------------------

# Brands whose POS rows carry a non-activated / activated split.
# iShopChangi sells brand-new NON-ACTIVATED sets only.
ACTIVATION_SPLIT_BRANDS = {"APPLE"}

# POS model-base suffix meaning "non-activated, sealed" — the only pool we use.
NON_ACTIVATED_SUFFIX = "NA"
ACTIVATED_SUFFIX = "A"

# Colour rulings: (family_key_substring, template colour) -> POS colour
COLOUR_RULINGS: dict[tuple[str, str], str] = {
    ("honor watch x5i", "durable polymer white"): "WHITE",
    ("honor watch x5i", "durable polymer black"): "BLACK",
}


def norm_family(s: str) -> str:
    """Normalise a listing family name into a FAMILY_ALIASES key."""
    import re
    s = str(s or "").lower()
    s = s.replace("+", " plus ")
    s = s.replace("(", " ").replace(")", " ")
    s = re.sub(r"\b(\d+)[\s-]*inch\b", r"\1 inch", s)
    s = re.sub(r"[^a-z0-9.]+", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    # drop network / channel / capacity tokens that are not part of the family
    drop = {"5g", "4g", "lte", "wifi", "wi", "fi", "cellular", "cell", "gps",
            "bluetooth", "primary", "telco"}
    s = " ".join(t for t in s.split() if t not in drop)
    return s


def resolve_family(listing_name: str, brand: str) -> tuple[str, str] | None:
    """
    Look up a listing family in FAMILY_ALIASES.

    Exact normalised key first, then the longest alias that is a prefix of the
    normalised name (so "apple iphone 17 pro 256gb" still resolves), preferring
    the LONGEST match so "iphone 17 pro" never steals "iphone 17"'s rows.
    """
    key = norm_family(listing_name)
    if key in FAMILY_ALIASES:
        return FAMILY_ALIASES[key]

    cands = [a for a in FAMILY_ALIASES if key.startswith(a + " ") or key == a]
    if cands:
        return FAMILY_ALIASES[max(cands, key=len)]

    # Last resort: brand-scoped match on a WHOLE TOKEN SEQUENCE, longest wins.
    #
    # Plain substring containment is unsafe here: "nothing ear 3" is a
    # substring of "nothing ear 3a pink", which would hand Ear (3a) the
    # Ear (3) pool and break the locked ruling that they are different
    # products. Token-sequence matching makes "3" and "3a" distinct.
    cb = canon_brand(brand)
    kt = key.split()
    cands = []
    for a in FAMILY_ALIASES:
        if canon_brand(FAMILY_ALIASES[a][0]) != cb:
            continue
        at = a.split()
        if any(kt[i:i + len(at)] == at for i in range(len(kt) - len(at) + 1)):
            cands.append(a)
    if cands:
        return FAMILY_ALIASES[max(cands, key=len)]
    return None


def known_families_for(brand: str) -> list[str]:
    cb = canon_brand(brand)
    return sorted(
        a for a in FAMILY_ALIASES if canon_brand(FAMILY_ALIASES[a][0]) == cb
    )


SUPPORTED_BRANDS = sorted(BRAND_ALIASES)
