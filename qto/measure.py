"""On-screen take-off: buildings, measurement items (dimension groups), the QTO dimension sheet and its BOQ link.

Works like a QS dimension sheet: every measurement is a row with timesing, dimensions and a signed
quantity (deductions are negative). Each take-off item is a dimension group; its BOQ line quantity is
the sum of its rows, either for the whole project or separately for each building. Points are stored
in drawing units (PDF points, DXF image pixels or scan pixels) so they stay valid when the page is
rendered at a different resolution.
"""

from __future__ import annotations

import base64
import io
import json
import math
import uuid

import pandas as pd

from . import assemblies as asm
from . import disciplines as dz

TYPES = ["Count", "Length", "Area"]
CANVAS_MODE = {"Count": "count", "Length": "line", "Area": "area"}
PALETTE = ["#e11d48", "#2563eb", "#16a34a", "#f59e0b", "#9333ea", "#0891b2", "#ea580c", "#4f46e5", "#65a30d", "#db2777"]
PT_TO_M = 25.4 / 72.0 / 1000.0  # one PDF point on paper, in metres
SOURCE = "On-screen QTO"

QTO_COLUMNS = [
    "BOQ Ref", "Description", "Building", "Level", "Drawing", "Page", "Location", "Type", "Timesing", "Deduct",
    "Measured", "Width/Height (m)", "Depth/Thk (m)", "Unit", "Quantity", "Shape",
]

# Typical starting items: the second dimension turns a run into an area or volume, as a QS would.
PRESETS = {
    "Blank": ("", "Architectural", dz.UNCLASSIFIED, "Length", 0.0, 0.0),
    "Blockwork wall (length × height → m²)": ("200 mm blockwork wall", "Architectural", "14 Masonry", "Length", 3.0, 0.0),
    "Plaster / paint to walls (length × height → m²)": ("Internal plaster and paint to walls", "Architectural", "28 Floor, wall, ceiling and roof finishings", "Length", 3.0, 0.0),
    "Skirting (length → m)": ("Skirting", "Architectural", "28 Floor, wall, ceiling and roof finishings", "Length", 0.0, 0.0),
    "Floor finish (area → m²)": ("Floor tiling", "Architectural", "28 Floor, wall, ceiling and roof finishings", "Area", 0.0, 0.0),
    "Ceiling (area → m²)": ("Suspended ceiling", "Architectural", "30 Suspended ceilings", "Area", 0.0, 0.0),
    "Doors (count → nr)": ("Single leaf door", "Architectural", "24 Doors, shutters and hatches", "Count", 0.0, 0.0),
    "Windows (count → nr)": ("Window", "Architectural", "23 Windows, screens and lights", "Count", 0.0, 0.0),
    "RC slab (area × thickness → m³)": ("Reinforced concrete slab", "Structural", "11 In-situ concrete works", "Area", 0.0, 0.2),
    "RC strip footing (length × width × depth → m³)": ("Reinforced concrete strip footing", "Structural", "11 In-situ concrete works", "Length", 0.6, 0.4),
    "RC beam (length × width × depth → m³)": ("Reinforced concrete beam", "Structural", "11 In-situ concrete works", "Length", 0.3, 0.6),
    "RC columns (count → nr)": ("Reinforced concrete column", "Structural", "11 In-situ concrete works", "Count", 0.0, 0.0),
    "Excavation (area × depth → m³)": ("Excavation not exceeding 2 m deep", "Civil", "05 Excavating and filling", "Area", 0.0, 1.5),
    "Pipe / duct / cable run (length → m)": ("Pipe run", "MEP", "38 Mechanical services", "Length", 0.0, 0.0),
    "Light fittings (count → nr)": ("Light fitting", "MEP", "39 Electrical services", "Count", 0.0, 0.0),
    "Road pavement (area → m²)": ("Asphalt pavement", "Infrastructure", "35 Site works", "Area", 0.0, 0.0),
    "Kerb (length → m)": ("Precast concrete kerb", "Infrastructure", "35 Site works", "Length", 0.0, 0.0),
}


def new_state() -> dict:
    return {
        "items": [], "shapes": [], "calibration": {}, "seen": [],
        "buildings": [{"id": 1, "code": "B01", "name": "Building 1", "levels": dict(asm.LEVELS)}],
        "split_buildings": True,  # one BOQ line per item per building (when there is more than one building)
        "globals": dict(asm.GLOBALS),  # project defaults for blinding, offsets, laps, rebar ratios…
        "drawings": {},  # drawing name → {"building": id}: each building has its own drawings
    }


def page_key(doc: str, page: int) -> str:
    return f"{doc}|{page}"


# ---------------------------------------------------------------- drawings belong to a building

def drawing_building(state: dict, name: str) -> int:
    """The building a drawing belongs to (a drawing not yet assigned goes to the first building)."""
    ids = [b["id"] for b in state["buildings"]]
    entry = state.setdefault("drawings", {}).setdefault(name, {"building": ids[0]})
    if entry.get("building") not in ids:
        entry["building"] = ids[0]
    return entry["building"]


def assign_drawing(state: dict, name: str, building_id: int) -> None:
    state.setdefault("drawings", {})[name] = {"building": building_id}


def drawings_for(state: dict, names, building_id: int) -> list[str]:
    """Only the drawings of one building, in their upload order."""
    return [n for n in names if drawing_building(state, n) == building_id]


def rename_drawing(state: dict, old: str, new: str) -> None:
    """Rename a drawing everywhere: its building link, its measurements and its scale."""
    drawings = state.setdefault("drawings", {})
    if old in drawings:
        drawings[new] = drawings.pop(old)
    for shape in state["shapes"]:
        if shape["doc"] == old:
            shape["doc"] = new
    for key in [k for k in state["calibration"] if k.rsplit("|", 1)[0] == old]:
        state["calibration"][f"{new}|{key.rsplit('|', 1)[1]}"] = state["calibration"].pop(key)


def remove_drawing(state: dict, name: str) -> None:
    """Forget a drawing's building link and scale; its measurements stay in the take-off."""
    state.setdefault("drawings", {}).pop(name, None)
    for key in [k for k in state["calibration"] if k.rsplit("|", 1)[0] == name]:
        state["calibration"].pop(key)


# ---------------------------------------------------------------- buildings

def add_building(state: dict, name: str) -> dict:
    n = max((b["id"] for b in state["buildings"]), default=0) + 1
    levels = dict(state["buildings"][0].get("levels", asm.LEVELS)) if state["buildings"] else dict(asm.LEVELS)
    building = {"id": n, "code": f"B{n:02d}", "name": name.strip() or f"Building {n}", "levels": levels}
    state["buildings"].append(building)
    return building


def building_by_id(state: dict, building_id: int) -> dict:
    return next((b for b in state["buildings"] if b["id"] == building_id), state["buildings"][0])


def delete_building(state: dict, building_id: int) -> bool:
    """Remove an empty building. Buildings that still hold measurements are kept."""
    if len(state["buildings"]) <= 1 or any(s.get("building") == building_id for s in state["shapes"]):
        return False
    state["buildings"] = [b for b in state["buildings"] if b["id"] != building_id]
    for entry in state.setdefault("drawings", {}).values():  # its drawings move to the first building
        if entry.get("building") == building_id:
            entry["building"] = state["buildings"][0]["id"]
    return True


def splitting(state: dict) -> bool:
    return bool(state.get("split_buildings", True)) and len(state["buildings"]) > 1


def line_ref(state: dict, item: dict, building_id: int) -> str:
    """BOQ ref of an item's line: TO-001, or TO-001-B02 when bills are split by building."""
    return f"{item['ref']}-{building_by_id(state, building_id)['code']}" if splitting(state) else item["ref"]


# ---------------------------------------------------------------- items (dimension groups)

def item_unit(kind: str, width: float, depth: float) -> str:
    if kind == "Count":
        return "nr"
    order = 1 if kind == "Length" else 2
    order += (1 if width else 0) + (1 if depth else 0) if kind == "Length" else (1 if depth else 0)
    return ["m", "m²", "m³"][min(order, 3) - 1]


def add_item(state: dict, description: str, discipline: str, section: str, kind: str,
             width: float = 0.0, depth: float = 0.0) -> dict:
    n = max((i["id"] for i in state["items"]), default=0) + 1
    item = {
        "id": n, "ref": f"TO-{n:03d}", "description": description.strip() or f"Take-off item {n}",
        "discipline": discipline, "section": section, "type": kind,
        "width": float(width or 0) if kind == "Length" else 0.0,
        "depth": float(depth or 0) if kind != "Count" else 0.0,
        "colour": PALETTE[(n - 1) % len(PALETTE)], "visible": True, "rate": 0.0,
    }
    state["items"].append(item)
    return item


def item_by_id(state: dict, item_id: int) -> dict | None:
    return next((i for i in state["items"] if i["id"] == item_id), None)


def add_assembly_item(state: dict, template: str, description: str = "", discipline: str = "Structural",
                      section: str = asm.S_CON) -> dict:
    """A dimension group that generates its related items (excavation, blinding, concrete…) from one measurement."""
    spec = asm.TEMPLATES[template]
    item = add_item(state, description or spec["label"], discipline, section, spec["measure"])
    item["assembly"] = template
    item["params"] = dict(spec["params"])
    item["openings"] = []
    item["rates"] = {}
    return item


def is_assembly(item: dict) -> bool:
    return bool(item.get("assembly")) and item["assembly"] in asm.TEMPLATES


# ---------------------------------------------------------------- scale and measurements

def metres_per_unit_from_scale(ratio: float) -> float:
    """Drawing scale 1:ratio on a PDF at its paper size -> metres per PDF point."""
    return PT_TO_M * ratio


def calibrate(points: list, known_metres: float) -> float | None:
    d = math.dist(points[0], points[-1])
    return known_metres / d if d > 0 and known_metres > 0 else None


def add_shape(state: dict, item_id: int, doc: str, page: int, points: list, building: int = 1, level: str = "") -> dict:
    shape = {
        "id": uuid.uuid4().hex[:10], "item_id": item_id, "doc": doc, "page": page,
        "points": [[round(float(x), 3), round(float(y), 3)] for x, y in points],
        "timesing": 1.0, "deduct": False, "location": "", "building": building, "level": level,
    }
    state["shapes"].append(shape)
    return shape


MANUAL_DOC = "Manual"


def add_manual(state: dict, item_id: int, value: float, building: int = 1, level: str = "", location: str = "",
               timesing: float = 1.0, deduct: bool = False) -> dict:
    """A typed dimension (no drawing): value in the item's base unit — nr, m or m²."""
    shape = add_shape(state, item_id, MANUAL_DOC, 0, [], building=building, level=level)
    shape.update({"manual": float(value), "location": location, "timesing": float(timesing or 1.0), "deduct": bool(deduct)})
    return shape


def _length(pts) -> float:
    return sum(math.dist(a, b) for a, b in zip(pts, pts[1:]))


def _area(pts) -> float:
    return abs(sum(x1 * y2 - x2 * y1 for (x1, y1), (x2, y2) in zip(pts, pts[1:] + pts[:1]))) / 2.0


def measured(shape: dict, item: dict, m_per_unit: float | None) -> float | None:
    """Raw measured value: number of points, metres of run, or square metres of area (or a typed manual value)."""
    if shape.get("manual") is not None:
        return float(shape["manual"])
    pts = shape["points"]
    if item["type"] == "Count":
        return float(len(pts))
    if not m_per_unit:
        return None
    if item["type"] == "Length":
        return _length(pts) * m_per_unit
    return _area(pts) * m_per_unit**2


def quantity(shape: dict, item: dict, m_per_unit: float | None) -> float | None:
    value = measured(shape, item, m_per_unit)
    if value is None:
        return None
    if item["type"] == "Length":
        value *= (item["width"] or 1.0) * (item["depth"] or 1.0)
    elif item["type"] == "Area":
        value *= item["depth"] or 1.0
    return value * float(shape.get("timesing") or 1.0) * (-1.0 if shape.get("deduct") else 1.0)


# ---------------------------------------------------------------- dimension sheet and BOQ

def qto_sheet(state: dict) -> pd.DataFrame:
    """The dimension sheet: one row per measurement, grouped by take-off item then building."""
    rows = []
    for item in state["items"]:
        order = {b["id"]: n for n, b in enumerate(state["buildings"])}
        shapes = sorted((s for s in state["shapes"] if s["item_id"] == item["id"]), key=lambda s: order.get(s.get("building", 1), 0))
        for shape in shapes:
            mpu = state["calibration"].get(page_key(shape["doc"], shape["page"]))
            value = measured(shape, item, mpu)
            qty = quantity(shape, item, mpu)
            rows.append({
                "BOQ Ref": line_ref(state, item, shape.get("building", 1)), "Description": item["description"],
                "Building": building_by_id(state, shape.get("building", 1))["name"], "Level": shape.get("level", ""),
                "Drawing": shape["doc"], "Page": shape["page"] + 1, "Location": shape.get("location", ""), "Type": item["type"],
                "Timesing": float(shape.get("timesing") or 1.0), "Deduct": bool(shape.get("deduct")),
                "Measured": None if value is None else round(value, 3),
                "Width/Height (m)": item["width"] if item["type"] == "Length" and item["width"] else None,
                "Depth/Thk (m)": item["depth"] if item["type"] != "Count" and item["depth"] else None,
                "Unit": item_unit(item["type"], item["width"], item["depth"]),
                "Quantity": None if qty is None else round(qty, 3),
                "Shape": shape["id"],
            })
    return pd.DataFrame(rows, columns=QTO_COLUMNS)


def update_from_sheet(state: dict, sheet: pd.DataFrame) -> bool:
    """Apply edits made in the dimension sheet (timesing, deduct, location, building, level, deleted rows)."""
    by_id = {s["id"]: s for s in state["shapes"]}
    by_name = {b["name"]: b["id"] for b in state["buildings"]}
    keep = set(sheet["Shape"].dropna())
    changed = len(keep) != len(by_id)
    state["shapes"] = [s for s in state["shapes"] if s["id"] in keep]
    for _, row in sheet.iterrows():
        shape = by_id.get(row["Shape"])
        if shape is None:
            continue
        timesing = float(row["Timesing"]) if pd.notna(row["Timesing"]) and row["Timesing"] > 0 else 1.0
        new = {
            "timesing": timesing, "deduct": bool(row["Deduct"]),
            "location": "" if pd.isna(row["Location"]) else str(row["Location"]),
            "level": "" if pd.isna(row.get("Level", "")) else str(row.get("Level", "")),
            "building": by_name.get(row.get("Building"), shape.get("building", 1)),
        }
        if any(shape.get(k) != v for k, v in new.items()):
            shape.update(new)
            changed = True
    return changed


def group_totals(state: dict) -> pd.DataFrame:
    """Net quantity of every dimension group, per building."""
    rows = []
    for item in state["items"]:
        for building in state["buildings"]:
            shapes = [s for s in state["shapes"] if s["item_id"] == item["id"] and s.get("building", 1) == building["id"]]
            if not shapes:
                continue
            qtys = [quantity(s, item, state["calibration"].get(page_key(s["doc"], s["page"]))) for s in shapes]
            rows.append({
                "Item": item["ref"], "Description": item["description"], "Building": building["name"],
                "Measurements": len(shapes), "Quantity": round(sum(q for q in qtys if q is not None), 3),
                "Unit": item_unit(item["type"], item["width"], item["depth"]),
            })
    return pd.DataFrame(rows, columns=["Item", "Description", "Building", "Measurements", "Quantity", "Unit"])


LINE_COLUMNS = ["Ref", "Discipline", "Work Section", "Description", "Unit", "Quantity", "Rate", "Source", "Key"]
DERIVED_COLUMNS = ["Ref", "Item", "Building", "Code", "Description", "Unit", "Quantity", "Formula", "Discipline", "Work Section", "Key", "Bill"]


def shapes_for(state: dict, item: dict, building_id: int | None) -> tuple[list[asm.Shape], int]:
    """Measurements of one item (in one building, or all) scaled to metres; also how many lack a scale."""
    out, unscaled = [], 0
    for s in state["shapes"]:
        if s["item_id"] != item["id"] or (building_id is not None and s.get("building", 1) != building_id):
            continue
        mpu = state["calibration"].get(page_key(s["doc"], s["page"]))
        pts = s["points"]
        shape = asm.Shape(timesing=float(s.get("timesing") or 1.0), deduct=bool(s.get("deduct")), ref=s.get("location", ""))
        if s.get("manual") is not None:  # typed dimension: the value is already in the base unit
            value = float(s["manual"])
            shape.count, shape.length, shape.area = (value, 0.0, 0.0) if item["type"] == "Count" else \
                (0.0, value, 0.0) if item["type"] == "Length" else (0.0, 0.0, value)
        elif item["type"] == "Count":
            shape.count = float(len(pts))
        elif not mpu:
            unscaled += 1
            continue
        elif item["type"] == "Length":
            shape.length = _length(pts) * mpu
        else:
            shape.area = _area(pts) * mpu**2
            shape.perimeter = _length(pts + pts[:1]) * mpu
        out.append(shape)
    return out, unscaled


def derived_items(state: dict) -> tuple[pd.DataFrame, list[dict]]:
    """Every item generated by the assemblies, per building, with its formula trace; plus issues found."""
    g = {**asm.GLOBALS, **state.get("globals", {})}
    rows, issues = [], []
    for item in (i for i in state["items"] if is_assembly(i)):
        merged: dict[str, dict] = {}
        for building in state["buildings"]:
            shapes, _ = shapes_for(state, item, building["id"])
            if not shapes:
                continue
            derived, problems = asm.compute(item["assembly"], item["description"], item.get("params", {}), shapes,
                                            building.get("levels", {}), g, item.get("openings"))
            issues += [{"Severity": p.severity, "Item": item["ref"], "Building": building["name"], "Message": p.message} for p in problems]
            for k, d in enumerate(derived, start=1):
                if splitting(state):
                    ref = f"{line_ref(state, item, building['id'])}.{k:02d}"
                    rows.append({"Ref": ref, "Item": item["ref"], "Building": building["name"], "Code": d.code,
                                 "Description": f"{d.description} — {building['name']}", "Unit": d.unit, "Quantity": d.quantity,
                                 "Formula": d.formula, "Discipline": item["discipline"], "Work Section": d.section,
                                 "Key": f"{item['id']}|{d.code}", "Bill": d.bill})
                else:  # one combined line per derived item across buildings
                    row = merged.setdefault(d.code, {"Ref": "", "Item": item["ref"], "Building": "All", "Code": d.code,
                                                     "Description": d.description, "Unit": d.unit, "Quantity": 0.0, "Formula": [],
                                                     "Discipline": item["discipline"], "Work Section": d.section,
                                                     "Key": f"{item['id']}|{d.code}", "Bill": d.bill})
                    row["Quantity"] += d.quantity
                    row["Formula"].append(f"{building['name']}: {d.formula}")
        for k, row in enumerate(merged.values(), start=1):
            row["Ref"] = f"{item['ref']}.{k:02d}"
            row["Formula"] = " | ".join(row["Formula"])
            rows.append(row)
    df = pd.DataFrame(rows, columns=DERIVED_COLUMNS)
    if not df.empty:
        df["Quantity"] = df["Quantity"].round(3)
    return df, issues


def boq_lines(state: dict) -> pd.DataFrame:
    """BOQ lines: plain items bill their dimension total; assembly items bill every derived item instead."""
    sheet = qto_sheet(state)
    rows = []
    for item in state["items"]:
        if is_assembly(item):
            continue
        groups = [(b, line_ref(state, item, b["id"])) for b in state["buildings"]] if splitting(state) else [(None, item["ref"])]
        for building, ref in groups:
            total = sheet.loc[sheet["BOQ Ref"] == ref, "Quantity"].dropna().sum()
            if total <= 0:
                continue
            description = item["description"] + (f" — {building['name']}" if building else "")
            rows.append({
                "Ref": ref, "Discipline": item["discipline"], "Work Section": item["section"],
                "Description": description, "Unit": item_unit(item["type"], item["width"], item["depth"]),
                "Quantity": round(float(total), 3), "Rate": float(item.get("rate") or 0.0), "Source": SOURCE,
                "Key": f"{item['id']}|",
            })
    derived, _ = derived_items(state)
    for _, d in derived.iterrows():
        if d["Quantity"] <= 0 or not d["Bill"]:  # reference dimensions are shown in the workbook, not billed
            continue
        item_id, code = d["Key"].split("|")
        item = item_by_id(state, int(item_id))
        rows.append({
            "Ref": d["Ref"], "Discipline": d["Discipline"], "Work Section": d["Work Section"], "Description": d["Description"],
            "Unit": d["Unit"], "Quantity": float(d["Quantity"]), "Rate": float((item or {}).get("rates", {}).get(code, 0.0)),
            "Source": SOURCE, "Key": d["Key"],
        })
    return pd.DataFrame(rows, columns=LINE_COLUMNS)


def wall_schedules(state: dict) -> pd.DataFrame:
    """Wall schedule of every blockwork assembly: one row per wall reference and building."""
    g = {**asm.GLOBALS, **state.get("globals", {})}
    rows = []
    for item in (i for i in state["items"] if i.get("assembly") == "blockwork_wall"):
        params = {**asm.TEMPLATES["blockwork_wall"]["params"], **item.get("params", {})}
        for building in state["buildings"]:
            shapes, _ = shapes_for(state, item, building["id"])
            if shapes:
                for row in asm.wall_schedule(params, shapes, {**asm.LEVELS, **building.get("levels", {})}, g, item.get("openings", [])):
                    rows.append({"Item": item["ref"], "Wall type": item["description"], "Building": building["name"], **row})
    return pd.DataFrame(rows)


def merge_takeoff(target: dict, source: dict, doc_map: dict | None = None) -> dict:
    """Append another take-off: buildings matched by name (added if new), items and measurements re-numbered.
    doc_map renames drawings whose name clashed with a drawing already in the target."""
    doc_map = doc_map or {}
    buildings = {b["name"]: b["id"] for b in target["buildings"]}
    building_map = {}
    for b in source.get("buildings", []):
        if b["name"] not in buildings:
            new = add_building(target, b["name"])
            new["levels"] = {**asm.LEVELS, **b.get("levels", {})}
            buildings[b["name"]] = new["id"]
        building_map[b["id"]] = buildings[b["name"]]
    item_map = {}
    for item in source.get("items", []):
        n = max((i["id"] for i in target["items"]), default=0) + 1
        copy = json.loads(json.dumps(item))
        copy.update({"id": n, "ref": f"TO-{n:03d}", "colour": PALETTE[(n - 1) % len(PALETTE)]})
        target["items"].append(copy)
        item_map[item["id"]] = n
    for shape in source.get("shapes", []):
        if shape["item_id"] not in item_map:
            continue
        copy = json.loads(json.dumps(shape))
        copy.update({"id": uuid.uuid4().hex[:10], "item_id": item_map[shape["item_id"]], "doc": doc_map.get(shape["doc"], shape["doc"]),
                     "building": building_map.get(shape.get("building", 1), target["buildings"][0]["id"])})
        target["shapes"].append(copy)
    for key, value in source.get("calibration", {}).items():
        doc, _, page = key.rpartition("|")
        target["calibration"].setdefault(f"{doc_map.get(doc, doc)}|{page}", value)
    for name, entry in source.get("drawings", {}).items():
        target.setdefault("drawings", {}).setdefault(
            doc_map.get(name, name), {"building": building_map.get(entry.get("building"), target["buildings"][0]["id"])})
    return {"items": len(item_map), "shapes": sum(1 for s in source.get("shapes", []) if s["item_id"] in item_map),
            "buildings": len(building_map)}


def set_rate(state: dict, key: str, rate: float) -> None:
    """Store a workbook rate: plain items keep one rate, assembly items one rate per derived item."""
    item_id, code = key.split("|")
    item = item_by_id(state, int(item_id))
    if item is None:
        return
    if code:
        item.setdefault("rates", {})[code] = rate
    else:
        item["rate"] = rate


def check_project(state: dict) -> pd.DataFrame:
    """Errors and warnings that must be fixed before the take-off can be trusted."""
    issues = []
    unscaled_pages = set()
    for s in state["shapes"]:
        item = item_by_id(state, s["item_id"])
        if item and item["type"] != "Count" and s.get("manual") is None and not state["calibration"].get(page_key(s["doc"], s["page"])):
            unscaled_pages.add((s["doc"], s["page"] + 1))
    for doc, page in sorted(unscaled_pages):
        issues.append({"Severity": "Error", "Item": "—", "Building": "—",
                       "Message": f"Drawing {doc}, page {page} has lengths or areas but no scale — they are left out of the quantities"})
    for item in state["items"]:
        if not any(s["item_id"] == item["id"] for s in state["shapes"]):
            issues.append({"Severity": "Warning", "Item": item["ref"], "Building": "—", "Message": f"{item['description']} has no measurements yet"})
    g = {**asm.GLOBALS, **state.get("globals", {})}
    for key in ("rebar_foundation", "rebar_beam", "rebar_column", "rebar_slab"):
        if not 40 <= float(g[key]) <= 300:
            issues.append({"Severity": "Warning", "Item": "Settings", "Building": "—",
                           "Message": f"{asm.GLOBAL_LABELS[key]} = {g[key]} is outside the usual 40–300 kg/m³ range"})
    _, derived_issues = derived_items(state)
    issues += derived_issues
    return pd.DataFrame(issues, columns=["Severity", "Item", "Building", "Message"])


# ---------------------------------------------------------------- files

def upgrade(state: dict) -> dict:
    """Fill in fields added in later versions so older take-off files keep working."""
    state.setdefault("seen", [])
    state.setdefault("calibration", {})
    state.setdefault("split_buildings", True)
    state["globals"] = {**asm.GLOBALS, **state.get("globals", {})}
    if not state.get("buildings"):
        state["buildings"] = [{"id": 1, "code": "B01", "name": "Building 1"}]
    for building in state["buildings"]:
        building["levels"] = {**asm.LEVELS, **building.get("levels", {})}
    for item in state.setdefault("items", []):
        item.setdefault("visible", True)
        item.setdefault("rate", 0.0)
        if item.get("assembly"):
            item.setdefault("params", dict(asm.TEMPLATES.get(item["assembly"], {}).get("params", {})))
            item.setdefault("openings", [])
            item.setdefault("rates", {})
    for shape in state.setdefault("shapes", []):
        shape.setdefault("building", state["buildings"][0]["id"])
        shape.setdefault("level", "")
    drawings = state.setdefault("drawings", {})
    for shape in state["shapes"]:  # older take-offs: a drawing belongs to the building it was measured for
        if shape["doc"] != MANUAL_DOC and shape["doc"] not in drawings:
            drawings[shape["doc"]] = {"building": shape["building"]}
    return state


def to_json(state: dict) -> bytes:
    data = {k: state[k] for k in TAKEOFF_KEYS if k in state}
    return json.dumps({"format": "qto-studio-takeoff", "version": 3, **data}, indent=1).encode("utf-8")


TAKEOFF_KEYS = ("items", "shapes", "calibration", "buildings", "split_buildings", "globals", "drawings")


def from_json(raw: bytes) -> dict:
    data = json.loads(raw.decode("utf-8"))
    if data.get("format") != "qto-studio-takeoff":
        raise ValueError("This is not a QTO Studio take-off file.")
    return from_dict(data)


def from_dict(data: dict) -> dict:
    state = new_state()
    state["items"] = list(data.get("items", []))
    state["shapes"] = list(data.get("shapes", []))
    state["calibration"] = {k: float(v) for k, v in data.get("calibration", {}).items()}
    if data.get("buildings"):
        state["buildings"] = list(data["buildings"])
    state["split_buildings"] = bool(data.get("split_buildings", True))
    state["globals"] = {**asm.GLOBALS, **data.get("globals", {})}
    state["drawings"] = {k: dict(v) for k, v in data.get("drawings", {}).items()}
    return upgrade(state)


def image_data_url(image, quality: int = 82) -> str:
    buffer = io.BytesIO()
    image.convert("RGB").save(buffer, format="JPEG", quality=quality, optimize=True)
    return "data:image/jpeg;base64," + base64.b64encode(buffer.getvalue()).decode("ascii")
