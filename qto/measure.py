"""On-screen take-off: measurement items, the QTO dimension sheet and its link to the BOQ.

Works like a QS dimension sheet: every measurement is a row with timesing, dimensions and a signed
quantity (deductions are negative); each take-off item becomes one BOQ line whose quantity is the
sum of its rows. Points are stored in drawing units (PDF points, or pixels of an image drawing) so
they stay valid when the page is rendered at a different resolution.
"""

from __future__ import annotations

import base64
import io
import json
import math
import uuid

import pandas as pd

from . import disciplines as dz

TYPES = ["Count", "Length", "Area"]
CANVAS_MODE = {"Count": "count", "Length": "line", "Area": "area"}
PALETTE = ["#e11d48", "#2563eb", "#16a34a", "#f59e0b", "#9333ea", "#0891b2", "#ea580c", "#4f46e5", "#65a30d", "#db2777"]
PT_TO_M = 25.4 / 72.0 / 1000.0  # one PDF point on paper, in metres
SOURCE = "On-screen QTO"

QTO_COLUMNS = [
    "BOQ Ref", "Description", "Drawing", "Page", "Location", "Type", "Timesing", "Deduct",
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
    return {"items": [], "shapes": [], "calibration": {}, "seen": []}


def page_key(doc: str, page: int) -> str:
    return f"{doc}|{page}"


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
        "width": float(width or 0), "depth": float(depth or 0) if kind != "Count" else 0.0,
        "colour": PALETTE[(n - 1) % len(PALETTE)],
    }
    if kind != "Length":
        item["width"] = 0.0
    state["items"].append(item)
    return item


def item_by_id(state: dict, item_id: int) -> dict | None:
    return next((i for i in state["items"] if i["id"] == item_id), None)


def metres_per_unit_from_scale(ratio: float) -> float:
    """Drawing scale 1:ratio on a PDF at its paper size -> metres per PDF point."""
    return PT_TO_M * ratio


def calibrate(points: list, known_metres: float) -> float | None:
    d = math.dist(points[0], points[-1])
    return known_metres / d if d > 0 and known_metres > 0 else None


def add_shape(state: dict, item_id: int, doc: str, page: int, points: list) -> dict:
    shape = {
        "id": uuid.uuid4().hex[:10], "item_id": item_id, "doc": doc, "page": page,
        "points": [[round(float(x), 3), round(float(y), 3)] for x, y in points],
        "timesing": 1.0, "deduct": False, "location": "",
    }
    state["shapes"].append(shape)
    return shape


def _length(pts) -> float:
    return sum(math.dist(a, b) for a, b in zip(pts, pts[1:]))


def _area(pts) -> float:
    return abs(sum(x1 * y2 - x2 * y1 for (x1, y1), (x2, y2) in zip(pts, pts[1:] + pts[:1]))) / 2.0


def measured(shape: dict, item: dict, m_per_unit: float | None) -> float | None:
    """Raw measured value: number of points, metres of run, or square metres of area."""
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


def qto_sheet(state: dict) -> pd.DataFrame:
    """The dimension sheet: one row per measurement, grouped by take-off item."""
    rows = []
    for item in state["items"]:
        for shape in (s for s in state["shapes"] if s["item_id"] == item["id"]):
            mpu = state["calibration"].get(page_key(shape["doc"], shape["page"]))
            value = measured(shape, item, mpu)
            qty = quantity(shape, item, mpu)
            rows.append({
                "BOQ Ref": item["ref"], "Description": item["description"], "Drawing": shape["doc"],
                "Page": shape["page"] + 1, "Location": shape.get("location", ""), "Type": item["type"],
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
    """Apply edits made in the dimension sheet (timesing, deduct, location, deleted rows). Returns True if changed."""
    by_id = {s["id"]: s for s in state["shapes"]}
    keep = set(sheet["Shape"].dropna())
    changed = len(keep) != len(by_id)
    state["shapes"] = [s for s in state["shapes"] if s["id"] in keep]
    for _, row in sheet.iterrows():
        shape = by_id.get(row["Shape"])
        if shape is None:
            continue
        timesing = float(row["Timesing"]) if pd.notna(row["Timesing"]) and row["Timesing"] > 0 else 1.0
        new = {"timesing": timesing, "deduct": bool(row["Deduct"]), "location": "" if pd.isna(row["Location"]) else str(row["Location"])}
        if any(shape.get(k) != v for k, v in new.items()):
            shape.update(new)
            changed = True
    return changed


def boq_lines(state: dict) -> pd.DataFrame:
    """One BOQ line per take-off item, quantity = net total of its dimension-sheet rows."""
    sheet = qto_sheet(state)
    rows = []
    for item in state["items"]:
        part = sheet[sheet["BOQ Ref"] == item["ref"]]
        total = part["Quantity"].dropna().sum()
        if part.empty or total <= 0:
            continue
        rows.append({
            "Ref": item["ref"], "Discipline": item["discipline"], "Work Section": item["section"],
            "Description": item["description"], "Unit": item_unit(item["type"], item["width"], item["depth"]),
            "Quantity": round(float(total), 3), "Rate": 0.0, "Source": SOURCE,
        })
    return pd.DataFrame(rows, columns=["Ref", "Discipline", "Work Section", "Description", "Unit", "Quantity", "Rate", "Source"])


def to_json(state: dict) -> bytes:
    data = {k: state[k] for k in ("items", "shapes", "calibration")}
    return json.dumps({"format": "qto-studio-takeoff", "version": 1, **data}, indent=1).encode("utf-8")


def from_json(raw: bytes) -> dict:
    data = json.loads(raw.decode("utf-8"))
    if data.get("format") != "qto-studio-takeoff":
        raise ValueError("This is not a QTO Studio take-off file.")
    state = new_state()
    state["items"] = list(data.get("items", []))
    state["shapes"] = list(data.get("shapes", []))
    state["calibration"] = {k: float(v) for k, v in data.get("calibration", {}).items()}
    return state


def image_data_url(image, quality: int = 82) -> str:
    buffer = io.BytesIO()
    image.convert("RGB").save(buffer, format="JPEG", quality=quality, optimize=True)
    return "data:image/jpeg;base64," + base64.b64encode(buffer.getvalue()).decode("ascii")
