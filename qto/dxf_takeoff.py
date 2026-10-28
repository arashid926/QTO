"""2D take-off from DXF drawings: lengths, areas and counts grouped by layer and block."""

from __future__ import annotations

import io
import math
from dataclasses import dataclass, field

import pandas as pd
from ezdxf import path as ezpath
from ezdxf import recover

from . import disciplines as dz

INSUNITS = {
    1: ("Inches", 0.0254),
    2: ("Feet", 0.3048),
    4: ("Millimetres", 0.001),
    5: ("Centimetres", 0.01),
    6: ("Metres", 1.0),
    10: ("Yards", 0.9144),
}
UNIT_CHOICES = {"Millimetres": 0.001, "Centimetres": 0.01, "Metres": 1.0, "Inches": 0.0254, "Feet": 0.3048}
ASSUMED_UNIT = ("Millimetres (assumed)", 0.001)

MEASURABLE = {"LINE", "LWPOLYLINE", "POLYLINE", "ARC", "CIRCLE", "ELLIPSE", "SPLINE", "HATCH"}
PREVIEW_POINT_LIMIT = 200_000
MAX_BLOCK_DEPTH = 8

L, A, C = dz.MEASURE_COLUMNS["Length"], dz.MEASURE_COLUMNS["Area"], dz.MEASURE_COLUMNS["Count"]


@dataclass
class DxfResult:
    layers: pd.DataFrame
    blocks: pd.DataFrame
    texts: pd.DataFrame
    markers: pd.DataFrame
    units_label: str
    scale_to_m: float
    entity_count: int
    preview: list = field(default_factory=list)  # [(layer, xs, ys)] in metres, None-separated


def read_doc(data: bytes):
    doc, _auditor = recover.read(io.BytesIO(data))
    return doc


def detect_units(doc) -> tuple[str, float]:
    return INSUNITS.get(doc.header.get("$INSUNITS", 0), ASSUMED_UNIT)


def _shoelace(pts) -> float:
    total = 0.0
    for (x1, y1), (x2, y2) in zip(pts, pts[1:] + pts[:1]):
        total += x1 * y2 - x2 * y1
    return abs(total) / 2.0


def _polyline_length(pts) -> float:
    return sum(math.dist(a, b) for a, b in zip(pts, pts[1:]))


def _is_closed(pts, tol) -> bool:
    return len(pts) >= 4 and math.dist(pts[0], pts[-1]) <= tol


def _flatten(entity, tol) -> list[list[tuple[float, float]]]:
    """Flatten an entity into 2D point lists, one per sub-path."""
    paths = ezpath.from_hatch(entity) if entity.dxftype() == "HATCH" else [ezpath.make_path(entity)]
    parts = []
    for p in paths:
        for sub in p.sub_paths() if p.has_sub_paths else [p]:
            pts = [(v.x, v.y) for v in sub.flattening(tol)]
            if len(pts) >= 2:
                parts.append(pts)
    return parts


def _hatch_area(parts, tol) -> float:
    """Outer boundary minus islands that sit inside it."""
    areas = sorted(((_shoelace(p), p) for p in parts if _is_closed(p, tol) or len(p) >= 3), key=lambda t: -t[0])
    if not areas:
        return 0.0
    outer_area, outer = areas[0]
    xs, ys = [x for x, _ in outer], [y for _, y in outer]
    total = outer_area
    for area, pts in areas[1:]:
        inside = all(min(xs) <= x <= max(xs) and min(ys) <= y <= max(ys) for x, y in pts)
        total += -area if inside else area
    return max(total, 0.0)


def _walk(entities, explode, parent_layer=None, depth=0):
    """Yield (entity, effective layer, block depth), optionally descending into block references."""
    for entity in entities:
        layer = entity.dxf.get("layer", "0")
        if parent_layer and layer == "0":
            layer = parent_layer
        yield entity, layer, depth
        if explode and entity.dxftype() == "INSERT" and depth < MAX_BLOCK_DEPTH:
            try:
                children = list(entity.virtual_entities())
            except Exception:
                continue
            yield from _walk(children, explode, layer, depth + 1)


def _plain_text(entity) -> str:
    try:
        return entity.plain_text() if entity.dxftype() == "MTEXT" else entity.dxf.text
    except Exception:
        return ""


def takeoff(data: bytes, unit_override: float | None = None, explode_blocks: bool = False) -> DxfResult:
    doc = read_doc(data)
    units_label, scale = detect_units(doc)
    if unit_override:
        units_label = next((k for k, v in UNIT_CHOICES.items() if v == unit_override), "Custom")
        scale = unit_override
    tol = max(1e-6, 0.001 / scale)  # 1 mm, expressed in drawing units

    rows, inserts, texts = [], [], []
    preview: dict[str, tuple[list, list]] = {}
    preview_points = 0

    for entity, layer, depth in _walk(doc.modelspace(), explode_blocks):
        kind = entity.dxftype()
        if kind == "INSERT":
            point = entity.dxf.insert
            inserts.append({"Block": entity.dxf.name, "Layer": layer, "X": point.x * scale, "Y": point.y * scale, "Depth": depth})
            continue
        if kind in ("TEXT", "MTEXT"):
            texts.append({"Layer": layer, "Text": _plain_text(entity).strip()})
            continue
        if kind not in MEASURABLE:
            continue
        try:
            parts = _flatten(entity, tol)
        except Exception:
            continue
        if not parts:
            continue

        if kind == "HATCH":
            length, area, closed = 0.0, _hatch_area(parts, tol), True
        else:
            length = sum(_polyline_length(p) for p in parts)
            closed_parts = [p for p in parts if _is_closed(p, tol)]
            area, closed = sum(_shoelace(p) for p in closed_parts), bool(closed_parts)
        rows.append({"Layer": layer, "Type": kind, "Length": length * scale, "Area": area * scale**2, "Closed": closed})

        if preview_points < PREVIEW_POINT_LIMIT:
            xs, ys = preview.setdefault(layer, ([], []))
            for p in parts:
                xs.extend([x * scale for x, _ in p] + [None])
                ys.extend([y * scale for _, y in p] + [None])
                preview_points += len(p)

    ents = pd.DataFrame(rows, columns=["Layer", "Type", "Length", "Area", "Closed"])
    ins = pd.DataFrame(inserts, columns=["Block", "Layer", "X", "Y", "Depth"])
    top = ins[ins["Depth"] == 0]

    return DxfResult(
        layers=_layer_table(ents, top),
        blocks=_block_table(top),
        texts=pd.DataFrame(texts, columns=["Layer", "Text"]),
        markers=top[["Block", "Layer", "X", "Y"]].reset_index(drop=True),
        units_label=units_label,
        scale_to_m=scale,
        entity_count=len(ents) + len(top),
        preview=[(layer, xs, ys) for layer, (xs, ys) in sorted(preview.items())],
    )


def _layer_table(ents: pd.DataFrame, top_inserts: pd.DataFrame) -> pd.DataFrame:
    agg = ents.groupby("Layer").agg(
        Count=("Type", "size"), Length=("Length", "sum"), Area=("Area", "sum"), Closed=("Closed", "sum")
    )
    blocks = top_inserts.groupby("Layer").size().rename("Blocks")
    table = agg.join(blocks, how="outer").fillna(0).reset_index()
    if table.empty:
        return pd.DataFrame(columns=["Bill", "Discipline", "Work Section", "Measure", "Description", "Factor", dz.DIM_COLUMN,
                                     "Layer", C, L, A, "Closed shapes", "Blocks"])

    def measure(r):
        if dz.suggest_count(r["Layer"]) and r["Count"] > 0:
            return "Count"
        if r["Area"] > 0 and r["Closed"] >= 0.6 * r["Count"]:
            return "Area"
        return "Length" if r["Length"] > 0 else "Count"

    classes = table["Layer"].map(dz.classify)
    table["Discipline"] = [c[0] for c in classes]
    table["Work Section"] = [c[1] for c in classes]
    table["Measure"] = table.apply(measure, axis=1)
    table["Bill"] = [(not dz.is_annotation(n)) and (cnt > 0) for n, cnt in zip(table["Layer"], table["Count"])]
    table["Description"] = table["Layer"].map(dz.pretty_name)
    table["Factor"] = 1.0
    table[dz.DIM_COLUMN] = 0.0
    table = table.rename(columns={"Length": L, "Area": A, "Closed": "Closed shapes"})
    table[C] = table[C].astype(int)
    table["Closed shapes"] = table["Closed shapes"].astype(int)
    table["Blocks"] = table["Blocks"].astype(int)
    return table[["Bill", "Discipline", "Work Section", "Measure", "Description", "Factor", dz.DIM_COLUMN,
                  "Layer", C, L, A, "Closed shapes", "Blocks"]]


def _block_table(top_inserts: pd.DataFrame) -> pd.DataFrame:
    columns = ["Bill", "Discipline", "Work Section", "Measure", "Description", "Block", "Layers", C]
    if top_inserts.empty:
        return pd.DataFrame(columns=columns)
    table = (
        top_inserts.groupby("Block")
        .agg(Count=("Block", "size"), Layers=("Layer", lambda s: ", ".join(sorted(set(s)))))
        .reset_index()
    )
    classes = [dz.classify(f"{b} {lay}") for b, lay in zip(table["Block"], table["Layers"])]
    table["Discipline"] = [c[0] for c in classes]
    table["Work Section"] = [c[1] for c in classes]
    table["Measure"] = "Count"
    table["Bill"] = ~table["Block"].str.startswith("*")
    table["Description"] = table["Block"].map(dz.pretty_name)
    return table[columns]


def layer_names(result: DxfResult) -> list[str]:
    return sorted({layer for layer, _, _ in result.preview} | set(result.markers["Layer"]))


def render_image(result: DxfResult, max_side: int = 4000, margin: int = 40, hidden_layers=()):
    """Draw the measured geometry as an image for on-screen take-off.

    Returns (image, metres per pixel, flat list of snap points in pixels). The scale is exact,
    so a DXF needs no calibration before measuring.
    """
    from PIL import Image, ImageDraw

    frame = _frame(result, max_side, margin)
    if frame is None:
        return Image.new("RGB", (800, 600), "white"), 1.0, []
    to_px, px_per_m, width, height = frame
    image = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(image)

    hidden = set(hidden_layers)
    snap, seen = [], set()
    for _layer, px, py in result.preview:
        if _layer in hidden:  # layer switched off (the frame keeps its size so measurements stay in place)
            continue
        run = []
        for x, y in list(zip(px, py)) + [(None, None)]:
            if x is None:
                if len(run) > 1:
                    draw.line(run, fill=(20, 20, 20), width=2)
                for p in (run[:1] + run[-1:]) if len(run) > 12 else run:  # vertices, not every arc segment
                    key = (round(p[0], 3), round(p[1], 3))
                    if key not in seen and len(snap) < 80_000:
                        seen.add(key)
                        snap.extend(key)
                run = []
            else:
                run.append(to_px(x, y))
    for x, y, layer in zip(result.markers["X"], result.markers["Y"], result.markers["Layer"]):
        if layer in hidden:
            continue
        cx, cy = to_px(x, y)
        draw.rectangle([cx - 5, cy - 5, cx + 5, cy + 5], outline=(37, 99, 235), width=2)
        snap.extend((round(cx, 3), round(cy, 3)))
    return image, 1.0 / px_per_m, snap


def _frame(result: DxfResult, max_side: int = 4000, margin: int = 40):
    """(to_px, px_per_m, width, height) of the measuring image; shared by the renderer and object picking."""
    xs = [x for _, px, _ in result.preview for x in px if x is not None] + result.markers["X"].tolist()
    ys = [y for _, _, py in result.preview for y in py if y is not None] + result.markers["Y"].tolist()
    if not xs:
        return None
    x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
    px_per_m = (max_side - 2 * margin) / max(x1 - x0, y1 - y0, 1e-6)

    def to_px(x, y):
        return (margin + (x - x0) * px_per_m, margin + (y1 - y) * px_per_m)  # DXF y points up, image y down

    return to_px, px_per_m, int((x1 - x0) * px_per_m) + 2 * margin, int((y1 - y0) * px_per_m) + 2 * margin


def drawing_objects(result: DxfResult, max_side: int = 4000, margin: int = 40) -> list[dict]:
    """Every block reference and every drawn path, in measuring-image pixels, for 'select similar'."""
    from . import geometry

    frame = _frame(result, max_side, margin)
    if frame is None:
        return []
    to_px = frame[0]
    objects = []
    for block, layer, x, y in zip(result.markers["Block"], result.markers["Layer"], result.markers["X"], result.markers["Y"]):
        c = to_px(x, y)
        objects.append({"kind": "insert", "key": f"block:{block}", "label": f"block {block}", "pts": [c], "center": c,
                        "closed": False, "area": 0.0, "perimeter": 0.0})
    for layer, px, py in result.preview:
        run = []
        for x, y in list(zip(px, py)) + [(None, None)]:
            if x is not None:
                run.append(to_px(x, y))
                continue
            if len(run) > 1:
                closed = len(run) > 3 and math.dist(run[0], run[-1]) < 0.5
                pts = run[:-1] if closed else run
                objects.append({"kind": "path", "key": f"layer:{layer}", "label": f"layer {layer}", "pts": pts,
                                "center": geometry.centroid(pts), "closed": closed,
                                "area": geometry.area(pts) if closed else 0.0, "perimeter": geometry.perimeter(pts, closed)})
            run = []
    return objects


def count_tags(texts: pd.DataFrame, tags: list[str]) -> pd.DataFrame:
    """Count text labels such as door/window marks (D1, W2) placed on the drawing."""
    normalised = texts["Text"].astype(str).str.strip().str.upper()
    return pd.DataFrame(
        [{"Tag": t, "Count": int((normalised == t.strip().upper()).sum())} for t in tags if t.strip()],
        columns=["Tag", "Count"],
    )
