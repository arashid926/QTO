"""Parametric take-off assemblies: one measured element generates all of its related items.

Every derived quantity carries a formula trace so a checking QS can follow it line by line.
Heights and depths come from levels (relative or survey levels, in metres), never typed per item.
Lengths are in m, areas in m², volumes in m³, reinforcement in kg.
"""

from __future__ import annotations

from dataclasses import dataclass

# ---------------------------------------------------------------- project defaults

GLOBALS = {
    "blinding_t": 0.075,          # blinding thickness (m)
    "bo_left": 0.10, "bo_right": 0.10, "bo_top": 0.10, "bo_bottom": 0.10,   # blinding offset per side (m)
    "eo_left": 0.30, "eo_right": 0.30, "eo_top": 0.30, "eo_bottom": 0.30,   # excavation offset (working space) per side (m)
    "offset_from": "Blinding edge",   # or "Footing face"
    "extra_depth": 0.0,           # extra excavation below the blinding (m)
    "refill": "Compacted granular fill",  # or "Lean concrete", "None"
    "batter": 0.0,                # side slope, horizontal per 1 vertical (0 = vertical sides with earthwork support)
    "bulking": 1.25,
    "waterproofing": "Bottom + sides",    # "None", "Bottom", "Sides", "Bottom + sides"
    "wp_lap": 0.10, "polythene_lap": 0.10, "mesh_lap": 0.15,
    "wall_void_threshold": 0.50,  # openings this size or smaller are not deducted from walls (m²)
    "slab_void_threshold": 0.50,  # openings this size or smaller are not deducted from slabs (m²)
    "lintel_bearing": 0.15,
    "rebar_foundation": 100.0, "rebar_beam": 150.0, "rebar_column": 180.0, "rebar_slab": 110.0,  # kg/m³, edit to suit
}

GLOBAL_LABELS = {
    "blinding_t": "Blinding thickness (m)",
    "bo_left": "Blinding offset — left (m)", "bo_right": "Blinding offset — right (m)",
    "bo_top": "Blinding offset — top (m)", "bo_bottom": "Blinding offset — bottom (m)",
    "eo_left": "Excavation offset — left (m)", "eo_right": "Excavation offset — right (m)",
    "eo_top": "Excavation offset — top (m)", "eo_bottom": "Excavation offset — bottom (m)",
    "offset_from": "Excavation offset measured from",
    "extra_depth": "Extra excavation depth below blinding (m)",
    "refill": "Refill to extra excavation",
    "batter": "Excavation side slope (horizontal per 1 vertical, 0 = vertical)",
    "bulking": "Bulking factor for disposal",
    "waterproofing": "Waterproofing to foundations",
    "wp_lap": "Waterproofing lap allowance", "polythene_lap": "Polythene lap allowance", "mesh_lap": "Mesh lap allowance",
    "wall_void_threshold": "Wall openings not deducted if ≤ (m²)",
    "slab_void_threshold": "Slab openings not deducted if ≤ (m²)",
    "lintel_bearing": "Lintel bearing each end (m)",
    "rebar_foundation": "Rebar ratio — foundations (kg/m³)", "rebar_beam": "Rebar ratio — beams (kg/m³)",
    "rebar_column": "Rebar ratio — columns (kg/m³)", "rebar_slab": "Rebar ratio — slabs (kg/m³)",
}
CHOICES = {
    "offset_from": ["Blinding edge", "Footing face"],
    "refill": ["Compacted granular fill", "Lean concrete", "None"],
    "waterproofing": ["Bottom + sides", "Bottom", "Sides", "None"],
}

# Levels per building. None means "not set": start level falls back to NGL, BGB to the start level.
LEVELS = {"NGL": 0.0, "start": None, "water_table": None, "BGB": None, "FFL": 0.0, "soffit": 3.0}
LEVEL_LABELS = {
    "NGL": "NGL — natural ground level", "start": "Excavation start level (blank = NGL)",
    "water_table": "Water table (blank = none)", "BGB": "Bottom of grade beam (blank = start level)",
    "FFL": "FFL — finished floor level", "soffit": "Slab soffit above (for wall heights)",
}

S_EXC, S_CON, S_WP, S_MAS = "05 Excavating and filling", "11 In-situ concrete works", "19 Waterproofing", "14 Masonry"
S_GRD, S_PRE = "06 Ground remediation and soil stabilisation", "13 Precast concrete"
S_FIN, S_DEC = "28 Floor, wall, ceiling and roof finishings", "29 Decoration"

# ---------------------------------------------------------------- templates

TEMPLATES = {
    "isolated_footing": {
        "label": "Isolated footing (pad) + neck column", "trade": "Structural — substructure", "measure": "Count",
        "params": {"L": 2.0, "W": 2.0, "D": 0.6, "BOF": -1.5, "neck_b": 0.4, "neck_h": 0.4},
        "help": "Click each footing of this type. Generates excavation, blinding, waterproofing, concrete, formwork, rebar, neck column, backfill and disposal.",
    },
    "combined_footing": {
        "label": "Combined footing (outline)", "trade": "Structural — substructure", "measure": "Area",
        "params": {"D": 0.6, "BOF": -1.5},
        "help": "Trace the footing outline. Offsets are applied around the outline.",
    },
    "strip_footing": {
        "label": "Strip footing (centre-line)", "trade": "Structural — substructure", "measure": "Length",
        "params": {"W": 0.6, "D": 0.4, "BOF": -1.0},
        "help": "Trace the centre-line; corners are counted once by the centre-line method.",
    },
    "raft": {
        "label": "Raft foundation (outline)", "trade": "Structural — substructure", "measure": "Area",
        "params": {"D": 0.6, "BOF": -1.2},
        "help": "Trace the raft outline.",
    },
    "neck_column": {
        "label": "Neck column (count)", "trade": "Structural — substructure", "measure": "Count",
        "params": {"b": 0.4, "h": 0.4, "TOF": -0.9},
        "help": "From top of footing up to the bottom of grade beam (or the start level).",
    },
    "grade_beam": {
        "label": "Grade (tie) beam (clear length)", "trade": "Structural — substructure", "measure": "Length",
        "params": {"b": 0.3, "h": 0.6, "trench": 1.0},
        "help": "Measure between the faces of neck columns or columns. Bottom = BGB level (or start level − h). "
                "trench: 1 = include trench excavation, backfill and disposal; 0 = beam sits inside the footing excavation.",
    },
    "grade_slab": {
        "label": "Grade slab + polythene + granular fill", "trade": "Structural — substructure", "measure": "Area",
        "params": {"t": 0.15, "fill_t": 0.2, "mesh": 1.0},
        "help": "Trace the slab; measure openings as deductions (Deduction toggle). mesh: 1 = yes, 0 = no.",
    },
    "bulk_excavation": {
        "label": "Bulk excavation (area to level)", "trade": "Structural — substructure", "measure": "Area",
        "params": {"bottom_level": -1.0},
        "help": "Trace the excavation area; depth = start level − bottom level.",
    },
    "column": {
        "label": "Column (count per floor)", "trade": "Structural — superstructure", "measure": "Count",
        "params": {"b": 0.4, "h": 0.6, "SSL_bottom": 0.0, "SSL_top": 3.5, "slab_t": 0.2},
        "help": "Height = SSL top − SSL bottom, measured through the slab; formwork to the clear height.",
    },
    "beam": {
        "label": "Beam (clear span)", "trade": "Structural — superstructure", "measure": "Length",
        "params": {"b": 0.3, "h": 0.6, "slab_t": 0.2},
        "help": "h is the overall depth; only the part below the slab is measured.",
    },
    "suspended_slab": {
        "label": "Suspended slab (outline)", "trade": "Structural — superstructure", "measure": "Area",
        "params": {"t": 0.2, "column_area": 0.0, "beam_soffit_area": 0.0},
        "help": "Trace the slab; openings as deductions. column_area: column footprints to deduct (m²); beam_soffit_area: beam soffits to deduct from slab soffit formwork (m²).",
    },
    "blockwork_wall": {
        "label": "Blockwork wall with opening deductions", "trade": "Architectural", "measure": "Length",
        "params": {"thickness_mm": 200.0, "height": 0.0, "finish_faces": 2.0},
        "help": "Measure each wall run and type its wall reference (e.g. W-01) in Location. Height 0 = FFL to soffit from the levels. Assign doors/windows to wall references in the openings table.",
    },
}

PARAM_LABELS = {
    "L": "Length L (m)", "W": "Width W (m)", "D": "Depth D (m)", "BOF": "Bottom of footing level BOF",
    "neck_b": "Neck column b (m, 0 = none)", "neck_h": "Neck column h (m)", "b": "Width b (m)", "h": "Depth h (m)",
    "TOF": "Top of footing level TOF", "t": "Thickness t (m)", "fill_t": "Granular fill thickness (m)",
    "mesh": "Mesh reinforcement (1 = yes)", "bottom_level": "Excavation bottom level", "trench": "Trench excavation (1 = yes)",
    "SSL_bottom": "SSL bottom", "SSL_top": "SSL top", "slab_t": "Slab thickness (m)",
    "column_area": "Column footprints to deduct (m²)", "beam_soffit_area": "Beam soffits to deduct (m²)",
    "thickness_mm": "Block thickness (mm)", "height": "Wall height (m, 0 = from levels)", "finish_faces": "Faces to plaster/paint",
}


@dataclass
class Shape:
    """One measurement on the drawing, already scaled to metres."""
    count: float = 0.0
    length: float = 0.0
    area: float = 0.0
    perimeter: float = 0.0
    timesing: float = 1.0
    deduct: bool = False
    ref: str = ""  # wall reference / location


@dataclass
class Derived:
    code: str
    description: str
    unit: str
    quantity: float
    formula: str
    section: str = S_CON
    bill: bool = True  # False for reference dimensions (e.g. extended perimeters) shown but not billed


@dataclass
class Issue:
    severity: str  # "Error" or "Warning"
    message: str


def n(x: float) -> str:
    """Number for a formula trace."""
    return f"{x:.3f}".rstrip("0").rstrip(".") if abs(x - round(x, 3)) < 1e-9 else f"{x:.4f}"


def depth_band(depth: float) -> str:
    for limit in (1, 2, 4, 6):
        if depth <= limit + 1e-9:
            return f"not exceeding {limit} m deep"
    return "exceeding 6 m deep"


def _g(globals_: dict, key: str):
    return globals_.get(key, GLOBALS[key])


def start_level(levels: dict) -> float:
    return levels["start"] if levels.get("start") is not None else levels.get("NGL", 0.0)


# ---------------------------------------------------------------- foundations

def _foundation(name: str, count: float, footing_area: float, footing_perim: float, D: float, BOF: float,
                levels: dict, g: dict, rect: tuple[float, float] | None, neck: tuple[float, float] | None = None,
                linear: float | None = None) -> tuple[list[Derived], list[Issue]]:
    """Shared engine for pads, strips, rafts and combined footings.

    rect=(L, W) gives exact per-side offsets; otherwise offsets are applied around the outline
    (area + perimeter × o + 4o², exact for rectangular and orthogonal outlines).
    linear=length means a strip measured on its centre-line (offsets on both sides of the width).
    """
    out, issues = [], []
    t, extra, bulk = _g(g, "blinding_t"), _g(g, "extra_depth"), _g(g, "bulking")
    bo = [_g(g, k) for k in ("bo_left", "bo_right", "bo_top", "bo_bottom")]
    eo = [_g(g, k) for k in ("eo_left", "eo_right", "eo_top", "eo_bottom")]
    from_blinding = _g(g, "offset_from") == "Blinding edge"
    top = start_level(levels)
    if BOF >= top:
        issues.append(Issue("Error", f"{name}: bottom of footing {n(BOF)} is not below the start level {n(top)}"))
        return out, issues
    depth = (top - BOF) + t + extra
    if depth > 6:
        issues.append(Issue("Warning", f"{name}: excavation depth {n(depth)} m is unusually deep"))

    # plan sizes
    if rect:
        L, W = rect
        bl_L, bl_W = L + bo[0] + bo[1], W + bo[2] + bo[3]
        base_L, base_W = (bl_L, bl_W) if from_blinding else (L, W)
        ex_L, ex_W = base_L + eo[0] + eo[1], base_W + eo[2] + eo[3]
        blind_area, blind_txt = count * bl_L * bl_W, f"{n(count)} × {n(bl_L)} × {n(bl_W)}"
        ex_area, ex_perim = count * ex_L * ex_W, count * 2 * (ex_L + ex_W)
        ex_txt = f"{n(count)} × {n(ex_L)} × {n(ex_W)}"
        perims = (count * 2 * (L + W), count * 2 * (bl_L + bl_W), ex_perim,
                  f"{n(count)} × 2 × ({n(L)} + {n(W)})", f"{n(count)} × 2 × ({n(bl_L)} + {n(bl_W)})", f"{n(count)} × 2 × ({n(ex_L)} + {n(ex_W)})")
    elif linear is not None:
        Wd = footing_area / linear if linear else 0.0
        bl_W = Wd + bo[0] + bo[1]
        ex_W = (bl_W if from_blinding else Wd) + eo[0] + eo[1]
        blind_area, blind_txt = linear * bl_W, f"{n(linear)} × {n(bl_W)}"
        ex_area, ex_perim = linear * ex_W, 2 * linear
        ex_txt = f"{n(linear)} × {n(ex_W)}"
        perims = (2 * linear + 2 * Wd, 2 * linear + 2 * bl_W, 2 * linear + 2 * ex_W,
                  f"2 × {n(linear)} + 2 × {n(Wd)}", f"2 × {n(linear)} + 2 × {n(bl_W)}", f"2 × {n(linear)} + 2 × {n(ex_W)}")
    else:
        ob, oe = sum(bo) / 4, sum(eo) / 4
        blind_area = footing_area + footing_perim * ob + 4 * ob * ob * count
        base_A, base_P = (blind_area, footing_perim + 8 * ob * count) if from_blinding else (footing_area, footing_perim)
        ex_area = base_A + base_P * oe + 4 * oe * oe * count
        ex_perim = base_P + 8 * oe * count
        blind_txt = f"({n(footing_area)} + {n(footing_perim)} × {n(ob)} + 4 × {n(ob)}² × {n(count)})"
        ex_txt = f"(offset outline area {n(ex_area)})"
        bl_perim = footing_perim + 8 * ob * count
        perims = (footing_perim, bl_perim, ex_perim, f"{n(footing_perim)}", f"{n(footing_perim)} + 8 × {n(ob)} × {n(count)}",
                  f"{n(bl_perim if from_blinding else footing_perim)} + 8 × {n(oe)} × {n(count)}")

    batter = _g(g, "batter")
    volume_ex = ex_area * depth
    vol_txt = f"{ex_txt} × {n(depth)}"
    if batter > 0 and rect:  # prismoidal: bottom, middle and top plan areas
        grow = batter * depth
        a1 = ex_L * ex_W
        am = (ex_L + grow) * (ex_W + grow)
        a2 = (ex_L + 2 * grow) * (ex_W + 2 * grow)
        volume_ex = count * depth / 6 * (a1 + 4 * am + a2)
        vol_txt = f"{n(count)} × {n(depth)}/6 × ({n(a1)} + 4×{n(am)} + {n(a2)}) [battered {n(batter)}:1]"

    depth_txt = f"({n(top)} − {n(BOF)}) + {n(t)} blinding" + (f" + {n(extra)} extra" if extra else "") + f" = {n(depth)} m"
    out.append(Derived("EXC", f"Excavation for {name}, {depth_band(depth)} (depth {n(depth)} m)", "m³", volume_ex,
                       f"depth {depth_txt}; volume = {vol_txt}", S_EXC))
    if batter == 0:
        out.append(Derived("EWS", f"Earthwork support to excavation for {name}", "m²", ex_perim * depth,
                           f"perimeter {n(ex_perim)} × depth {n(depth)}", S_EXC))
    bottom = BOF - t - extra
    if levels.get("water_table") is not None and bottom < levels["water_table"]:
        out.append(Derived("DEW", f"Dewatering to excavation for {name} (bottom {n(bottom)} below water table {n(levels['water_table'])})",
                           "item", 1.0, "excavation bottom below the water table", S_EXC))
    out.append(Derived("CMP", f"Trimming and compacting bottom of excavation for {name}", "m²", ex_area, f"{ex_txt}", S_EXC))
    for code, label, value, txt in (("PFT", "footing face", perims[0], perims[3]), ("PBL", "blinding edge (extended)", perims[1], perims[4]),
                                    ("PEX", "excavation edge (extended)", perims[2], perims[5])):
        out.append(Derived(code, f"Reference: perimeter of {name} at {label}", "m", value, txt, S_EXC, bill=False))
    out.append(Derived("ATT", f"Anti-termite treatment to bottom of excavation for {name}", "m²", ex_area, f"{ex_txt}", S_GRD))

    refill_vol = 0.0
    if extra > 0 and _g(g, "refill") != "None":
        refill_vol = ex_area * extra
        out.append(Derived("RFL", f"{_g(g, 'refill')} to extra excavation below {name}, {n(extra * 1000)} mm thick", "m³", refill_vol,
                           f"{ex_txt} × {n(extra)}", S_EXC if _g(g, "refill") != "Lean concrete" else S_CON))

    blinding = blind_area * t
    out.append(Derived("BLD", f"Plain concrete blinding {n(t * 1000)} mm thick under {name}", "m³", blinding,
                       f"{blind_txt} × {n(t)}", S_CON))
    concrete = footing_area * D
    conc_txt = f"{n(count)} × {n(rect[0])} × {n(rect[1])} × {n(D)}" if rect else f"{n(footing_area)} × {n(D)}"
    out.append(Derived("CON", f"Reinforced concrete in {name}", "m³", concrete, conc_txt, S_CON))
    out.append(Derived("FWK", f"Formwork to sides of {name}", "m²", footing_perim * D, f"perimeter {n(footing_perim)} × {n(D)}", S_CON))
    ratio = _g(g, "rebar_foundation")
    out.append(Derived("RBR", f"Reinforcement to {name} (ratio {n(ratio)} kg/m³)", "kg", concrete * ratio, f"{n(concrete)} m³ × {n(ratio)}", S_CON))

    wp, lap = _g(g, "waterproofing"), _g(g, "wp_lap")
    if wp in ("Bottom", "Bottom + sides"):
        out.append(Derived("WPB", f"Waterproofing membrane under {name} (incl. {n(lap * 100)}% laps)", "m²", footing_area * (1 + lap),
                           f"{n(footing_area)} × (1 + {n(lap)})", S_WP))
    if wp in ("Sides", "Bottom + sides"):
        out.append(Derived("WPS", f"Waterproofing membrane to sides of {name} (incl. {n(lap * 100)}% laps)", "m²",
                           footing_perim * D * (1 + lap), f"{n(footing_perim)} × {n(D)} × (1 + {n(lap)})", S_WP))

    buried = refill_vol + blinding + concrete
    buried_txt = [f"refill {n(refill_vol)}"] if refill_vol else []
    buried_txt += [f"blinding {n(blinding)}", f"footing {n(concrete)}"]
    if neck and neck[0] > 0 and neck[1] > 0:
        b, h = neck
        tof = BOF + D
        neck_top = levels["BGB"] if levels.get("BGB") is not None else top
        height = neck_top - tof
        if height < 0:
            issues.append(Issue("Error", f"{name}: neck column top {n(neck_top)} is below top of footing {n(tof)}"))
        elif height > 0:
            neck_vol = count * b * h * height
            out.append(Derived("NCC", f"Reinforced concrete in neck columns {n(b * 1000)}×{n(h * 1000)} mm to {name}", "m³", neck_vol,
                               f"{n(count)} × {n(b)} × {n(h)} × ({n(neck_top)} − {n(tof)})", S_CON))
            out.append(Derived("NCF", f"Formwork to neck columns of {name}", "m²", count * 2 * (b + h) * height,
                               f"{n(count)} × 2 × ({n(b)} + {n(h)}) × {n(height)}", S_CON))
            out.append(Derived("NCR", f"Reinforcement to neck columns of {name}", "kg", neck_vol * _g(g, "rebar_column"),
                               f"{n(neck_vol)} × {n(_g(g, 'rebar_column'))}", S_CON))
            below = max(0.0, min(neck_top, top) - tof)
            if below > 0:
                buried += count * b * h * below
                buried_txt.append(f"neck {n(count * b * h * below)}")
    backfill = volume_ex - buried
    if backfill < -1e-9:
        issues.append(Issue("Error", f"{name}: structure volume exceeds the excavation — check levels and offsets"))
    backfill = max(backfill, 0.0)
    out.append(Derived("BKF", f"Backfilling around {name} with excavated material, compacted in layers", "m³", backfill,
                       f"{n(volume_ex)} − ({' + '.join(buried_txt)})", S_EXC))
    out.append(Derived("DSP", f"Disposal of surplus excavated material from {name} off site (bulking {n(bulk)})", "m³",
                       (volume_ex - backfill) * bulk, f"({n(volume_ex)} − {n(backfill)}) × {n(bulk)}", S_EXC))
    return out, issues


def _sum(shapes: list[Shape], attr: str, include_deduct: bool = False) -> float:
    total = 0.0
    for s in shapes:
        if s.deduct and not include_deduct:
            continue
        total += getattr(s, attr) * s.timesing * (-1 if s.deduct else 1)
    return total


def _areas(shapes: list[Shape], threshold: float) -> tuple[float, float, float, list[str]]:
    """Gross area, deducted openings, edge length (outer + deducted opening edges), notes."""
    gross = sum(s.area * s.timesing for s in shapes if not s.deduct)
    edges = sum(s.perimeter * s.timesing for s in shapes if not s.deduct)
    openings, notes = 0.0, []
    for s in shapes:
        if not s.deduct:
            continue
        if s.area <= threshold + 1e-9:
            notes.append(f"opening {n(s.area)} m² not deducted (≤ {n(threshold)} m²)")
            continue
        openings += s.area * s.timesing
        edges += s.perimeter * s.timesing
    return gross, openings, edges, notes


def compute(template: str, name: str, params: dict, shapes: list[Shape], levels: dict, g: dict,
            openings: list[dict] | None = None) -> tuple[list[Derived], list[Issue]]:
    """Derived items for one dimension group in one building."""
    p = {**TEMPLATES[template]["params"], **{k: v for k, v in params.items() if v is not None}}
    lv = {**LEVELS, **(levels or {})}
    issues: list[Issue] = []
    count = _sum(shapes, "count")
    length = _sum(shapes, "length")

    if template == "isolated_footing":
        L, W, D = p["L"], p["W"], p["D"]
        return _foundation(name, count, count * L * W, count * 2 * (L + W), D, p["BOF"], lv, g, rect=(L, W),
                           neck=(p["neck_b"], p["neck_h"]))
    if template in ("combined_footing", "raft"):
        area = _sum(shapes, "area")
        perim = sum(s.perimeter * s.timesing for s in shapes if not s.deduct)
        pieces = sum(s.timesing for s in shapes if not s.deduct)
        return _foundation(name, pieces, area, perim, p["D"], p["BOF"], lv, g, rect=None)
    if template == "strip_footing":
        return _foundation(name, 1, length * p["W"], 2 * length, p["D"], p["BOF"], lv, g, rect=None, linear=length)

    if template == "neck_column":
        top = lv["BGB"] if lv.get("BGB") is not None else start_level(lv)
        height = top - p["TOF"]
        if height <= 0:
            return [], [Issue("Error", f"{name}: top {n(top)} is not above TOF {n(p['TOF'])}")]
        vol = count * p["b"] * p["h"] * height
        return [
            Derived("CON", f"Reinforced concrete in {name}", "m³", vol, f"{n(count)} × {n(p['b'])} × {n(p['h'])} × ({n(top)} − {n(p['TOF'])})"),
            Derived("FWK", f"Formwork to {name}", "m²", count * 2 * (p["b"] + p["h"]) * height, f"{n(count)} × 2 × ({n(p['b'])} + {n(p['h'])}) × {n(height)}"),
            Derived("RBR", f"Reinforcement to {name}", "kg", vol * _g(g, "rebar_column"), f"{n(vol)} × {n(_g(g, 'rebar_column'))}"),
        ], issues

    if template == "grade_beam":
        b, h, t = p["b"], p["h"], _g(g, "blinding_t")
        bl_w = b + _g(g, "bo_left") + _g(g, "bo_right")
        vol = length * b * h
        out = [
            Derived("CON", f"Reinforced concrete in {name}", "m³", vol, f"{n(length)} × {n(b)} × {n(h)}"),
            Derived("FWK", f"Formwork to sides of {name}", "m²", 2 * length * h, f"2 × {n(length)} × {n(h)}"),
            Derived("RBR", f"Reinforcement to {name}", "kg", vol * _g(g, "rebar_beam"), f"{n(vol)} × {n(_g(g, 'rebar_beam'))}"),
            Derived("BLD", f"Plain concrete blinding {n(t * 1000)} mm thick under {name}", "m³", length * bl_w * t, f"{n(length)} × {n(bl_w)} × {n(t)}"),
        ]
        wp, lap = _g(g, "waterproofing"), _g(g, "wp_lap")
        if wp in ("Bottom", "Bottom + sides"):
            out.append(Derived("WPB", f"Waterproofing membrane under {name} (incl. {n(lap * 100)}% laps)", "m²", length * b * (1 + lap),
                               f"{n(length)} × {n(b)} × (1 + {n(lap)})", S_WP))
        if wp in ("Sides", "Bottom + sides"):
            out.append(Derived("WPS", f"Waterproofing to sides of {name} (incl. {n(lap * 100)}% laps)", "m²", 2 * length * h * (1 + lap),
                               f"2 × {n(length)} × {n(h)} × (1 + {n(lap)})", S_WP))
        out.append(Derived("PBL", f"Reference: length of {name} at blinding edges (both sides)", "m", 2 * length,
                           f"2 × {n(length)}", S_CON, bill=False))
        if p.get("trench", 1.0):
            top = start_level(lv)
            bottom = lv["BGB"] if lv.get("BGB") is not None else top - h
            if bottom < top:
                extra, bulk = _g(g, "extra_depth"), _g(g, "bulking")
                depth = (top - bottom) + t + extra
                ex_w = (bl_w if _g(g, "offset_from") == "Blinding edge" else b) + _g(g, "eo_left") + _g(g, "eo_right")
                exc = length * ex_w * depth
                buried = length * bl_w * t + length * b * min(h, top - bottom)
                refill = length * ex_w * extra if extra > 0 and _g(g, "refill") != "None" else 0.0
                buried += refill
                backfill = max(exc - buried, 0.0)
                out += [
                    Derived("EXC", f"Trench excavation for {name}, {depth_band(depth)} (depth {n(depth)} m)", "m³", exc,
                            f"{n(length)} × {n(ex_w)} × (({n(top)} − {n(bottom)}) + {n(t)}" + (f" + {n(extra)}" if extra else "") + ")", S_EXC),
                    Derived("CMP", f"Trimming and compacting bottom of trench for {name}", "m²", length * ex_w, f"{n(length)} × {n(ex_w)}", S_EXC),
                    Derived("BKF", f"Backfilling around {name} with excavated material", "m³", backfill,
                            f"{n(exc)} − (blinding + beam below start level" + (" + refill" if refill else "") + f" = {n(buried)})", S_EXC),
                    Derived("DSP", f"Disposal of surplus excavated material from {name} (bulking {n(bulk)})", "m³", (exc - backfill) * bulk,
                            f"({n(exc)} − {n(backfill)}) × {n(bulk)}", S_EXC),
                ]
                if refill:
                    out.append(Derived("RFL", f"{_g(g, 'refill')} to extra excavation below {name}", "m³", refill, f"{n(length)} × {n(ex_w)} × {n(extra)}", S_EXC))
        return out, issues

    if template == "grade_slab":
        gross, opens, edges, notes = _areas(shapes, _g(g, "slab_void_threshold"))
        net = gross - opens
        trace = f"net {n(gross)} − {n(opens)} = {n(net)} m²" + (f"; {'; '.join(notes)}" if notes else "")
        t, fill_t = p["t"], p["fill_t"]
        pol, mesh_lap = _g(g, "polythene_lap"), _g(g, "mesh_lap")
        out = [
            Derived("CON", f"Reinforced concrete in {name}, {n(t * 1000)} mm thick", "m³", net * t, f"{trace}; × {n(t)}"),
            Derived("POL", f"Polythene sheet (1000 gauge) under {name} (incl. {n(pol * 100)}% laps)", "m²", net * (1 + pol), f"{n(net)} × (1 + {n(pol)})"),
            Derived("GRF", f"Granular fill {n(fill_t * 1000)} mm thick under {name}, compacted", "m³", net * fill_t, f"{n(net)} × {n(fill_t)}", S_EXC),
            Derived("EFW", f"Edge formwork to {name}", "m²", edges * t, f"edges {n(edges)} × {n(t)}"),
            Derived("PWF", f"Power-floated finish to {name}", "m²", net, f"{n(net)}", S_FIN),
        ]
        if p["mesh"]:
            out.insert(3, Derived("MSH", f"Mesh reinforcement to {name} (incl. {n(mesh_lap * 100)}% laps)", "m²", net * (1 + mesh_lap), f"{n(net)} × (1 + {n(mesh_lap)})"))
        return out, issues

    if template == "bulk_excavation":
        area = _sum(shapes, "area")
        top = start_level(lv)
        depth = top - p["bottom_level"]
        if depth <= 0:
            return [], [Issue("Error", f"{name}: bottom level {n(p['bottom_level'])} is not below the start level {n(top)}")]
        vol, bulk = area * depth, _g(g, "bulking")
        return [
            Derived("EXC", f"Bulk excavation for {name}, {depth_band(depth)}", "m³", vol, f"{n(area)} × ({n(top)} − {n(p['bottom_level'])})", S_EXC),
            Derived("CMP", f"Trimming and compacting bottom of {name}", "m²", area, f"{n(area)}", S_EXC),
            Derived("DSP", f"Disposal of excavated material from {name} off site (bulking {n(bulk)})", "m³", vol * bulk, f"{n(vol)} × {n(bulk)}", S_EXC),
        ], issues

    if template == "column":
        height = p["SSL_top"] - p["SSL_bottom"]
        if height <= 0:
            return [], [Issue("Error", f"{name}: SSL top {n(p['SSL_top'])} is not above SSL bottom {n(p['SSL_bottom'])}")]
        b, h = p["b"], p["h"]
        vol = count * b * h * height
        return [
            Derived("CON", f"Reinforced concrete in {name} {n(b * 1000)}×{n(h * 1000)} mm", "m³", vol, f"{n(count)} × {n(b)} × {n(h)} × {n(height)}"),
            Derived("FWK", f"Formwork to {name}", "m²", count * 2 * (b + h) * (height - p["slab_t"]),
                    f"{n(count)} × 2 × ({n(b)} + {n(h)}) × ({n(height)} − {n(p['slab_t'])})"),
            Derived("RBR", f"Reinforcement to {name}", "kg", vol * _g(g, "rebar_column"), f"{n(vol)} × {n(_g(g, 'rebar_column'))}"),
        ], issues

    if template == "beam":
        b, below = p["b"], p["h"] - p["slab_t"]
        if below <= 0:
            return [], [Issue("Error", f"{name}: beam depth {n(p['h'])} is not more than the slab thickness {n(p['slab_t'])}")]
        vol = length * b * below
        return [
            Derived("CON", f"Reinforced concrete in {name} (below slab)", "m³", vol, f"{n(length)} × {n(b)} × ({n(p['h'])} − {n(p['slab_t'])})"),
            Derived("FWK", f"Formwork to sides and soffit of {name}", "m²", 2 * length * below + length * b,
                    f"2 × {n(length)} × {n(below)} + {n(length)} × {n(b)}"),
            Derived("RBR", f"Reinforcement to {name}", "kg", vol * _g(g, "rebar_beam"), f"{n(vol)} × {n(_g(g, 'rebar_beam'))}"),
        ], issues

    if template == "suspended_slab":
        gross, opens, edges, notes = _areas(shapes, _g(g, "slab_void_threshold"))
        net = gross - opens - p["column_area"]
        trace = f"{n(gross)} − openings {n(opens)} − columns {n(p['column_area'])} = {n(net)} m²" + (f"; {'; '.join(notes)}" if notes else "")
        vol = net * p["t"]
        return [
            Derived("CON", f"Reinforced concrete in {name}, {n(p['t'] * 1000)} mm thick", "m³", vol, f"{trace}; × {n(p['t'])}"),
            Derived("SFW", f"Soffit formwork to {name}", "m²", net - p["beam_soffit_area"], f"{n(net)} − beam soffits {n(p['beam_soffit_area'])}"),
            Derived("EFW", f"Edge formwork to {name}", "m²", edges * p["t"], f"edges {n(edges)} × {n(p['t'])}"),
            Derived("RBR", f"Reinforcement to {name}", "kg", vol * _g(g, "rebar_slab"), f"{n(vol)} × {n(_g(g, 'rebar_slab'))}"),
        ], issues

    if template == "blockwork_wall":
        return blockwork(name, p, shapes, lv, g, openings or [])

    raise KeyError(template)


def wall_height(p: dict, levels: dict) -> float:
    return p["height"] if p.get("height") else levels["soffit"] - levels["FFL"]


def blockwork(name: str, p: dict, shapes: list[Shape], levels: dict, g: dict, openings: list[dict]):
    """Per-wall gross area, schedule-driven opening deductions, lintels and finishes."""
    issues: list[Issue] = []
    height = wall_height(p, levels)
    if height <= 0:
        return [], [Issue("Error", f"{name}: wall height {n(height)} m — set the height or the FFL/soffit levels")]
    threshold, bearing = _g(g, "wall_void_threshold"), _g(g, "lintel_bearing")
    walls: dict[str, float] = {}
    for s in shapes:
        ref = s.ref.strip() or "(no reference)"
        walls[ref] = walls.get(ref, 0.0) + s.length * s.timesing * (-1 if s.deduct else 1)
    gross = sum(walls.values()) * height
    deducted, lintel_len, notes = 0.0, 0.0, []
    schedule = []
    for o in openings:
        ref, mark = str(o.get("wall_ref", "")).strip(), str(o.get("mark", "")).strip() or "?"
        w, h, qty = float(o.get("width") or 0), float(o.get("height") or 0), float(o.get("qty") or 0)
        if not ref or qty <= 0 or w <= 0 or h <= 0:
            continue
        if ref not in walls:
            issues.append(Issue("Error", f"{name}: opening {mark} is assigned to wall {ref}, which has no measured run"))
            continue
        if w * qty > walls[ref] + 1e-9:
            issues.append(Issue("Error", f"{name}: openings {mark} ({n(w)} m × {n(qty)}) are wider than wall {ref} ({n(walls[ref])} m)"))
        if h > height + 1e-9:
            issues.append(Issue("Error", f"{name}: opening {mark} is taller ({n(h)} m) than wall {ref} ({n(height)} m)"))
        area = w * h
        if area <= threshold + 1e-9:
            notes.append(f"{mark} {n(area)} m² not deducted (≤ {n(threshold)} m²)")
            continue
        deducted += area * qty
        lintel_len += (w + 2 * bearing) * qty
        schedule.append(f"{ref}: {n(qty)} × {mark} {n(w)}×{n(h)}")
    net = gross - deducted
    thick = p["thickness_mm"]
    faces = p.get("finish_faces", 2.0)
    trace = f"gross {n(sum(walls.values()))} m × {n(height)} m = {n(gross)}; openings {n(deducted)} ({'; '.join(schedule) or 'none'})"
    if notes:
        trace += f"; {'; '.join(notes)}"
    out = [Derived("BLK", f"{n(thick)} mm blockwork in {name}", "m²", net, trace, S_MAS)]
    if lintel_len:
        out.append(Derived("LNT", f"Precast concrete lintels to openings in {name} (bearing {n(bearing)} m each end)", "m", lintel_len,
                           "Σ qty × (width + 2 × bearing)", S_PRE))
    if faces:
        out.append(Derived("PLS", f"Plaster to {name}, {n(faces)} face(s)", "m²", net * faces, f"{n(net)} × {n(faces)}", S_FIN))
        out.append(Derived("PNT", f"Emulsion paint to {name}, {n(faces)} face(s)", "m²", net * faces, f"{n(net)} × {n(faces)}", S_DEC))
    return out, issues


def wall_schedule(p: dict, shapes: list[Shape], levels: dict, g: dict, openings: list[dict]) -> list[dict]:
    """Rows for the wall schedule report: one per wall reference."""
    height = wall_height(p, levels)
    threshold = _g(g, "wall_void_threshold")
    walls: dict[str, float] = {}
    for s in shapes:
        ref = s.ref.strip() or "(no reference)"
        walls[ref] = walls.get(ref, 0.0) + s.length * s.timesing * (-1 if s.deduct else 1)
    rows = []
    for ref, length in walls.items():
        mine = [o for o in openings if str(o.get("wall_ref", "")).strip() == ref]
        ded = sum(float(o["width"]) * float(o["height"]) * float(o["qty"]) for o in mine
                  if float(o.get("width") or 0) * float(o.get("height") or 0) > threshold + 1e-9)
        rows.append({
            "Wall ref": ref, "Length (m)": round(length, 3), "Height (m)": round(height, 3),
            "Gross (m²)": round(length * height, 3), "Openings deducted (m²)": round(ded, 3),
            "Net (m²)": round(length * height - ded, 3),
            "Openings": ", ".join(f"{o.get('qty')}×{o.get('mark')}" for o in mine),
        })
    return rows
