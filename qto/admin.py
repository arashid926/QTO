"""System administration libraries: location constants, custom quantities, standard dimensions, codes, zones,
variables, units and subcontractor values — plus the workbook functions that use them.

Every library is a small table saved with the project so a QS office can reuse it across jobs.
"""

from __future__ import annotations

import ast
import operator
import re
from difflib import get_close_matches

import pandas as pd

from . import boq
from . import disciplines as dz

TABLES = {
    "Location Constants": {
        "columns": ["Location", "Factor", "Notes"],
        "rows": [{"Location": "Base (no adjustment)", "Factor": 1.00, "Notes": "Rates as entered"},
                 {"Location": "Remote site", "Factor": 1.15, "Notes": "Example: travel and logistics uplift"}],
        "help": "Regional cost factors. Use Workbooks → Function → Apply location factor to scale BOQ rates.",
    },
    "Custom Quantities": {
        "columns": ["Code", "Description", "Unit", "Quantity", "Discipline", "Work Section"],
        "rows": [{"Code": "PR-01", "Description": "Site establishment", "Unit": "item", "Quantity": 1.0,
                  "Discipline": "Civil", "Work Section": "01 Preliminaries"}],
        "help": "Quantities that are not measured from drawings (preliminaries, allowances). Add them to the BOQ from here.",
    },
    "Standard Dimensions": {
        "columns": ["Name", "Template", "L", "W", "D", "Notes"],
        "rows": [{"Name": "F1 pad 2.0×2.0×0.6", "Template": "isolated_footing", "L": 2.0, "W": 2.0, "D": 0.6, "Notes": ""},
                 {"Name": "F2 pad 1.5×1.5×0.5", "Template": "isolated_footing", "L": 1.5, "W": 1.5, "D": 0.5, "Notes": ""},
                 {"Name": "SF1 strip 0.6×0.4", "Template": "strip_footing", "L": 0.0, "W": 0.6, "D": 0.4, "Notes": ""}],
        "help": "Typical element sizes. Measure → Add can start a dimension group from one of these.",
    },
    "Code Library": {
        "columns": ["Code", "Description", "Unit", "Work Section"],
        "rows": [{"Code": "11.1.1", "Description": "Plain concrete blinding", "Unit": "m³", "Work Section": "11 In-situ concrete works"},
                 {"Code": "14.1.1", "Description": "Blockwork walls", "Unit": "m²", "Work Section": "14 Masonry"}],
        "help": "Item codes. Workbooks → Add can pick a code to fill the description, unit and section.",
    },
    "Standard Zones": {
        "columns": ["Zone", "Description"],
        "rows": [{"Zone": "GF", "Description": "Ground floor"}, {"Zone": "L1", "Description": "First floor"},
                 {"Zone": "RF", "Description": "Roof"}, {"Zone": "EXT", "Description": "External works"}],
        "help": "Zones / levels offered in the Level box of the Dimension tab.",
    },
    "Standard Variables": {
        "columns": ["Name", "Value", "Unit", "Notes"],
        "rows": [{"Name": "storey_h", "Value": 3.5, "Unit": "m", "Notes": "Floor-to-floor height"},
                 {"Name": "slab_t", "Value": 0.2, "Unit": "m", "Notes": "Typical slab thickness"}],
        "help": "Named values. Type them (or formulas such as storey_h - slab_t) into item parameters.",
    },
    "Unit of Measurement": {
        "columns": ["Unit", "Description"],
        "rows": [{"Unit": u, "Description": d} for u, d in [("nr", "Number"), ("m", "Linear metre"), ("m²", "Square metre"),
                                                         ("m³", "Cubic metre"), ("kg", "Kilogram"), ("t", "Tonne"),
                                                         ("item", "Item"), ("sum", "Lump sum")]],
        "help": "Units offered in the BOQ and workbook. Add any unit your office uses.",
    },
    "Subcontractor Values": {
        "columns": ["Subcontractor", "Work Section", "Description", "Unit", "Rate"],
        "rows": [{"Subcontractor": "Example Waterproofing LLC", "Work Section": "19 Waterproofing", "Description": "Membrane waterproofing",
                  "Unit": "m²", "Rate": 0.0}],
        "help": "Subcontractor quotations. Workbooks → Function → Apply subcontractor rates prices matching BOQ lines.",
    },
}


def defaults() -> dict[str, list[dict]]:
    return {name: [dict(r) for r in spec["rows"]] for name, spec in TABLES.items()}


def frame(admin: dict, name: str) -> pd.DataFrame:
    df = pd.DataFrame(admin.get(name) or [], columns=TABLES[name]["columns"])
    numeric = {"Factor", "Quantity", "L", "W", "D", "Value", "Rate"} & set(df.columns)
    return df.astype({c: float for c in numeric})


def records(df: pd.DataFrame) -> list[dict]:
    return [{k: (None if pd.isna(v) else v) for k, v in row.items()} for row in df.to_dict("records")]


def upgrade(admin: dict | None) -> dict:
    admin = dict(admin or {})
    for name, rows in defaults().items():
        admin.setdefault(name, rows)
    return admin


def units(admin: dict) -> list[str]:
    extra = [str(u) for u in frame(admin, "Unit of Measurement")["Unit"].dropna() if str(u).strip()]
    return list(dict.fromkeys(dz.UNITS + extra))


def zones(admin: dict) -> list[str]:
    return [str(z) for z in frame(admin, "Standard Zones")["Zone"].dropna() if str(z).strip()]


def variables(admin: dict) -> dict[str, float]:
    out = {}
    for _, r in frame(admin, "Standard Variables").iterrows():
        name = str(r["Name"] or "").strip()
        if re.fullmatch(r"[A-Za-z_]\w*", name) and pd.notna(r["Value"]):
            out[name] = float(r["Value"])
    return out


# ---------------------------------------------------------------- safe expressions for parameters

_OPS = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.Div: operator.truediv,
        ast.Pow: operator.pow, ast.USub: operator.neg, ast.UAdd: operator.pos}


def evaluate(text, variables_: dict[str, float]) -> float:
    """Number, variable or arithmetic formula (e.g. 'storey_h - slab_t'). Raises ValueError otherwise."""
    if isinstance(text, (int, float)):
        return float(text)
    source = str(text).strip()
    if not source:
        raise ValueError("empty value")

    def walk(node):
        if isinstance(node, ast.Expression):
            return walk(node.body)
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
            return float(node.value)
        if isinstance(node, ast.Name):
            if node.id not in variables_:
                raise ValueError(f"unknown variable '{node.id}'")
            return variables_[node.id]
        if isinstance(node, ast.BinOp) and type(node.op) in _OPS:
            return _OPS[type(node.op)](walk(node.left), walk(node.right))
        if isinstance(node, ast.UnaryOp) and type(node.op) in _OPS:
            return _OPS[type(node.op)](walk(node.operand))
        raise ValueError(f"not allowed in a formula: {source}")

    try:
        return float(walk(ast.parse(source, mode="eval")))
    except SyntaxError as exc:
        raise ValueError(f"cannot read '{source}'") from exc
    except (ZeroDivisionError, OverflowError) as exc:
        raise ValueError(f"cannot calculate '{source}'") from exc


# ---------------------------------------------------------------- workbook functions

def apply_factor(lines: pd.DataFrame, factor: float, discipline: str | None = None) -> pd.DataFrame:
    out = lines.copy()
    mask = out["Discipline"] == discipline if discipline else pd.Series(True, index=out.index)
    out.loc[mask, "Rate"] = (out.loc[mask, "Rate"] * factor).round(2)
    return boq.finalise(out, sort=False)


def apply_markup(lines: pd.DataFrame, percent: float, discipline: str | None = None) -> pd.DataFrame:
    return apply_factor(lines, 1 + percent / 100.0, discipline)


def round_quantities(lines: pd.DataFrame, decimals: int, up: bool = True) -> pd.DataFrame:
    import math

    out = lines.copy()
    k = 10 ** decimals
    out["Quantity"] = [math.ceil(q * k - 1e-9) / k if up else round(q, decimals) for q in out["Quantity"]]
    return boq.finalise(out, sort=False)


def apply_subcontractors(lines: pd.DataFrame, subs: pd.DataFrame, overwrite: bool = False) -> tuple[pd.DataFrame, int]:
    """Price BOQ lines from subcontractor quotes: same work section and unit; description words decide between quotes."""
    out = lines.copy()
    priced = 0
    quotes = subs.dropna(subset=["Rate"])
    quotes = quotes[quotes["Rate"] > 0]
    for i, line in out.iterrows():
        if line["Rate"] > 0 and not overwrite:
            continue
        candidates = quotes[(quotes["Work Section"] == line["Work Section"]) & (quotes["Unit"] == line["Unit"])]
        if candidates.empty:
            continue
        words = set(re.findall(r"[a-z]+", str(line["Description"]).lower()))
        best = max(candidates.itertuples(), key=lambda q: len(words & set(re.findall(r"[a-z]+", str(q.Description).lower()))))
        out.at[i, "Rate"] = float(best.Rate)
        priced += 1
    return boq.finalise(out, sort=False), priced


def custom_to_boq(custom: pd.DataFrame) -> pd.DataFrame:
    rows = custom.dropna(subset=["Quantity"])
    rows = rows[(rows["Quantity"] > 0) & rows["Description"].fillna("").astype(str).str.strip().ne("")]
    lines = pd.DataFrame({
        "Ref": rows["Code"].fillna("").astype(str), "Discipline": rows["Discipline"].fillna("Civil"),
        "Work Section": rows["Work Section"].fillna(dz.UNCLASSIFIED), "Description": rows["Description"],
        "Unit": rows["Unit"].fillna("item"), "Quantity": rows["Quantity"], "Rate": 0.0, "Source": "Custom quantities",
    })
    return boq.finalise(lines, sort=False)


def change_case(lines: pd.DataFrame, style: str) -> pd.DataFrame:
    out = lines.copy()
    fn = {"Sentence case": lambda s: s[:1].upper() + s[1:].lower() if s else s, "Title Case": str.title, "UPPER CASE": str.upper}[style]
    out["Description"] = out["Description"].astype(str).map(fn)
    return out


# ---------------------------------------------------------------- spelling

QS_WORDS = set("""
a above access aggregate air all allowance aluminium an and angle anti apron area as asphalt at backfill backfilling
bars base basin be beam beams bearing bed bedding below bitumen blinding block blocks blockwork board bolts bottom
brick brickwork building by cable cables carpet casing cast ceiling ceilings cement ceramic chamber channel clay
cleaning clear clearance coat coats column columns combined compacted compacting complete concrete connection
construction coping course courses cover covering curtain cut damp deep deduction depth description diameter disposal
door doors drain drainage duct ducts earth earthwork edge electrical emulsion excavated excavation external extra
fabric face faces fence fencing fill filling finish finishes fire fitting fittings fixed flat floor flooring footing
footings for formwork foundation foundations frame frames from gauge glass glazed glazing granular grade granite
gravel ground grout gypsum handrail height high hollow imported in including installation insulation internal into
joint joints kerb kerbs lap laps layer layers lean light lighting lining lintel lintels m material materials maximum
membrane mesh metal mm mortar neck not of off on opening openings or outlet over paint painting panel panels paving
per perimeter pipe pipes plain plaster plastering polythene power precast protection pvc rate ready ready-mixed rebar
reinforced reinforcement removal render retaining roof roofing room run screed sealant sections service sheet side
sides site skirting slab slabs soil soffit spoil steel stone strip structural surface surplus suspended switch
system tank termite thick thickness tile tiles tiling timber to top topsoil treatment trench trimming type under
upvc vertical wall walls water waterproofing width window windows with wood works
""".split())


def spelling(descriptions: list[str], extra_words=()) -> pd.DataFrame:
    """Words in BOQ descriptions that look misspelt, with the closest construction term as a suggestion."""
    known = QS_WORDS | {w.lower() for w in extra_words}
    rows, seen = [], set()
    for text in descriptions:
        for word in re.findall(r"[A-Za-z]{4,}", str(text)):
            low = word.lower()
            if low in known or low in seen:
                continue
            match = get_close_matches(low, known, n=1, cutoff=0.82)
            if match:
                seen.add(low)
                rows.append({"Word": word, "Suggestion": match[0], "Apply": True})
    issues = [{"Word": "(double space)", "Suggestion": "single space", "Apply": True}] if any("  " in str(t) for t in descriptions) else []
    return pd.DataFrame(rows + issues, columns=["Word", "Suggestion", "Apply"])


def apply_spelling(lines: pd.DataFrame, fixes: pd.DataFrame) -> pd.DataFrame:
    out = lines.copy()
    for _, fix in fixes[fixes["Apply"]].iterrows():
        if fix["Word"] == "(double space)":
            out["Description"] = out["Description"].astype(str).str.replace(r" {2,}", " ", regex=True)
            continue
        pattern = re.compile(rf"\b{re.escape(fix['Word'])}\b")
        out["Description"] = out["Description"].astype(str).map(lambda s: pattern.sub(fix["Suggestion"], s))
    return out
