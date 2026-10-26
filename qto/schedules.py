"""Import quantity schedules (Excel/CSV) and normalise them into BOQ lines."""

from __future__ import annotations

import io
import re

import pandas as pd

from . import disciplines as dz

FIELDS = ["Ref", "Description", "Unit", "Quantity", "Rate", "Work Section"]

COLUMN_SYNONYMS = {
    "Ref": ["ref", "reference", "item no", "item", "no", "code", "mark", "tag", "id", "s no", "sno", "sr no", "serial", "boq ref"],
    "Description": ["description", "item description", "desc", "particulars", "description of work", "name", "element", "family and type", "type", "family"],
    "Unit": ["unit", "units", "uom", "unit of measure"],
    "Quantity": ["quantity", "qty", "quantities", "total qty", "total quantity", "count", "nos", "number", "total", "volume", "area", "length"],
    "Rate": ["rate", "unit rate", "unit price", "price", "unit cost", "cost"],
    "Work Section": ["work section", "section", "trade", "category", "nrm", "nrm2", "work package"],
}

UNIT_ALIASES = {
    "m2": "m²", "sqm": "m²", "sq.m": "m²", "sq m": "m²", "sq.m.": "m²", "m^2": "m²",
    "m3": "m³", "cum": "m³", "cu.m": "m³", "cu m": "m³", "m^3": "m³",
    "lm": "m", "rm": "m", "rmt": "m", "mtr": "m", "lin.m": "m", "l.m": "m",
    "no": "nr", "nos": "nr", "no.": "nr", "each": "nr", "ea": "nr", "pcs": "nr", "pc": "nr", "number": "nr",
    "ton": "t", "tons": "t", "tonne": "t", "tonnes": "t", "mt": "t",
    "ls": "sum", "l.s": "sum", "lump sum": "sum", "lot": "item",
}


def _norm(text) -> str:
    return re.sub(r"[^a-z0-9 ]+", " ", str(text).lower()).strip()


def unique_columns(names) -> list[str]:
    seen: dict[str, int] = {}
    out = []
    for i, name in enumerate(names):
        base = str(name).strip() if name is not None and str(name).strip() and str(name) != "nan" else f"Column {i + 1}"
        seen[base] = seen.get(base, 0) + 1
        out.append(base if seen[base] == 1 else f"{base} ({seen[base]})")
    return out


def _apply_header(raw: pd.DataFrame) -> pd.DataFrame:
    """Find the header row (schedules often start with title rows) and tidy the table."""
    raw = raw.dropna(how="all").dropna(axis=1, how="all")
    if raw.empty:
        return raw
    header_row = 0
    min_filled = max(2, int(0.5 * raw.shape[1]))
    for pos in range(min(25, len(raw))):
        row = raw.iloc[pos]
        texts = [v for v in row if isinstance(v, str) and v.strip()]
        if len(texts) >= min_filled:
            header_row = pos
            break
    table = raw.iloc[header_row + 1:].copy()
    table.columns = unique_columns(raw.iloc[header_row].tolist())
    return table.dropna(how="all").reset_index(drop=True)


def read_schedule(data: bytes, filename: str) -> dict[str, pd.DataFrame]:
    """Return {sheet name: table} for a CSV or Excel schedule."""
    name = filename.lower()
    if name.endswith((".csv", ".txt")):
        for encoding in ("utf-8-sig", "cp1252", "latin-1"):
            try:
                raw = pd.read_csv(io.BytesIO(data), header=None, encoding=encoding, sep=None, engine="python")
                break
            except UnicodeDecodeError:
                continue
        return {"CSV": _apply_header(raw)}
    sheets = pd.read_excel(io.BytesIO(data), sheet_name=None, header=None)
    return {sheet: _apply_header(df) for sheet, df in sheets.items() if not df.dropna(how="all").empty}


def auto_map(columns) -> dict[str, str | None]:
    """Match schedule columns to standard fields: exact synonym first, then partial."""
    normalised = {c: _norm(c) for c in columns}
    mapping: dict[str, str | None] = {}
    used: set[str] = set()
    for exact in (True, False):
        for field in FIELDS:
            if mapping.get(field):
                continue
            for synonym in COLUMN_SYNONYMS[field]:
                hit = next(
                    (c for c, n in normalised.items() if c not in used and (n == synonym if exact else re.search(rf"\b{re.escape(synonym)}\b", n))),
                    None,
                )
                if hit:
                    mapping[field] = hit
                    used.add(hit)
                    break
    return {f: mapping.get(f) for f in FIELDS}


def to_number(series: pd.Series) -> pd.Series:
    cleaned = series.astype(str).str.replace(r"[,\s]", "", regex=True).str.replace(r"[^0-9.\-eE]", "", regex=True)
    return pd.to_numeric(cleaned, errors="coerce")


def normalise_unit(unit) -> str:
    if unit is None or (not isinstance(unit, str) and pd.isna(unit)):
        return ""
    text = str(unit).strip()
    return UNIT_ALIASES.get(text.lower(), text)


def normalise(
    table: pd.DataFrame,
    mapping: dict[str, str | None],
    discipline: str,
    source: str,
    default_section: str | None = None,
    default_unit: str = "nr",
) -> pd.DataFrame:
    """Convert a mapped schedule into BOQ rows. Rows without a positive quantity are dropped."""
    def col(field):
        name = mapping.get(field)
        return table[name] if name in table else pd.Series([None] * len(table), index=table.index)

    out = pd.DataFrame({
        "Ref": col("Ref").fillna("").astype(str).str.strip(),
        "Description": col("Description").fillna("").astype(str).str.strip(),
        "Unit": col("Unit").map(normalise_unit) if mapping.get("Unit") else default_unit,
        "Quantity": to_number(col("Quantity")),
        "Rate": to_number(col("Rate")).fillna(0.0),
    })
    out["Unit"] = out["Unit"].replace("", default_unit).fillna(default_unit)
    sections = col("Work Section").fillna("").astype(str).str.strip()
    out["Work Section"] = [
        _match_section(s) or default_section or dz.classify(d, (discipline, dz.UNCLASSIFIED))[1]
        for s, d in zip(sections, out["Description"])
    ]
    out["Discipline"] = discipline
    out["Source"] = source
    out = out[(out["Quantity"] > 0) & (out["Description"] != "")]
    out["Ref"] = out["Ref"].replace("nan", "")
    return out.reset_index(drop=True)


def _match_section(text: str) -> str | None:
    """Accept '14', '14 Masonry' or 'Masonry' and return the full NRM2 section name."""
    text = str(text or "").strip()
    if not text:
        return None
    number = re.match(r"^(\d{1,2})\b", text)
    if number:
        key = number.group(1).zfill(2)
        return next((s for s in dz.NRM2_SECTIONS if s.startswith(key)), None)
    low = text.lower()
    return next((s for s in dz.NRM2_SECTIONS if low in s.lower()), None)


# Example items only: no rates, pricing comes from the user's rate library.
TEMPLATES = {
    "Architectural": [
        ("A-001", "200 mm thick blockwork wall in cement mortar 1:4", "m²", 450, "14 Masonry"),
        ("A-002", "Ceramic floor tiles 600x600 mm on 40 mm screed", "m²", 320, "28 Floor, wall, ceiling and roof finishings"),
        ("A-003", "Single leaf timber flush door 900x2100 mm complete", "nr", 24, "24 Doors, shutters and hatches"),
        ("A-004", "Aluminium sliding window 1500x1200 mm double glazed", "nr", 18, "23 Windows, screens and lights"),
        ("A-005", "Emulsion paint, two coats on plastered walls", "m²", 1400, "29 Decoration"),
        ("A-006", "Gypsum board suspended ceiling 600x600 mm", "m²", 300, "30 Suspended ceilings"),
    ],
    "Structural": [
        ("S-001", "Plain concrete C15 blinding 50 mm thick", "m³", 12, "11 In-situ concrete works"),
        ("S-002", "Reinforced concrete C35 in isolated footings", "m³", 85, "11 In-situ concrete works"),
        ("S-003", "Reinforced concrete C40 in columns", "m³", 38, "11 In-situ concrete works"),
        ("S-004", "Reinforced concrete C40 in suspended slabs 200 mm", "m³", 145, "11 In-situ concrete works"),
        ("S-005", "High yield steel reinforcement bars B500B", "t", 42, "11 In-situ concrete works"),
        ("S-006", "Formwork to soffits of slabs", "m²", 720, "11 In-situ concrete works"),
    ],
    "Civil": [
        ("C-001", "Site clearance and removal of topsoil 150 mm", "m²", 2500, "05 Excavating and filling"),
        ("C-002", "Excavation for foundations not exceeding 2 m deep", "m³", 640, "05 Excavating and filling"),
        ("C-003", "Approved backfill compacted in 250 mm layers", "m³", 410, "05 Excavating and filling"),
        ("C-004", "Disposal of surplus excavated material off site", "m³", 230, "05 Excavating and filling"),
        ("C-005", "Anti-termite soil treatment", "m²", 900, "06 Ground remediation and soil stabilisation"),
        ("C-006", "Chain link fence 2.1 m high on steel posts", "m", 220, "36 Fencing"),
    ],
    "MEP": [
        ("M-001", "uPVC soil pipe 110 mm dia. including fittings", "m", 180, "33 Drainage above ground"),
        ("M-002", "PPR cold water pipe 25 mm dia.", "m", 420, "38 Mechanical services"),
        ("M-003", "Ducted split AC unit 5 TR complete", "nr", 6, "38 Mechanical services"),
        ("M-004", "LED panel light 600x600 mm 40 W", "nr", 140, "39 Electrical services"),
        ("M-005", "13 A twin switched socket outlet", "nr", 95, "39 Electrical services"),
        ("M-006", "XLPE armoured cable 4C x 16 mm²", "m", 350, "39 Electrical services"),
    ],
    "Infrastructure": [
        ("I-001", "Asphalt wearing course 50 mm thick", "m²", 3200, "35 Site works"),
        ("I-002", "Aggregate road base 250 mm thick compacted", "m²", 3200, "35 Site works"),
        ("I-003", "Precast concrete kerb 150x300 mm", "m", 860, "35 Site works"),
        ("I-004", "uPVC sewer pipe 200 mm dia. in trench", "m", 540, "34 Drainage below ground"),
        ("I-005", "Precast concrete manhole 1200 mm dia., 2.5 m deep", "nr", 14, "34 Drainage below ground"),
        ("I-006", "Street light pole 8 m with LED luminaire", "nr", 26, "39 Electrical services"),
    ],
}


def template(discipline: str) -> pd.DataFrame:
    return pd.DataFrame(TEMPLATES[discipline], columns=["Item No", "Description", "Unit", "Qty", "Work Section"])
