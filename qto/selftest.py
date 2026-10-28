"""Acceptance tests from the product specification, runnable inside the app and by pytest.

Each case states the expected value worked out by hand; the app's engine must reproduce it exactly
(to 3 decimal places).
"""

from __future__ import annotations

from . import assemblies as asm

TOL = 0.0005


def _q(items, code):
    return next((d.quantity for d in items if d.code == code), None)


def _pad(g=None, levels=None, bof=-1.5):
    items, issues = asm.compute("isolated_footing", "F1", {"L": 2.0, "W": 2.0, "D": 0.6, "BOF": bof, "neck_b": 0.4, "neck_h": 0.4},
                                [asm.Shape(count=4)], levels or {"NGL": 0.0}, {**asm.GLOBALS, **(g or {})})
    return items, issues


def cases() -> list[dict]:
    rows = []

    def check(test, item, expected, actual):
        ok = actual is not None and abs(actual - expected) <= TOL
        rows.append({"Test": test, "Item": item, "Expected": expected, "Actual": None if actual is None else round(actual, 3), "Pass": ok})

    base, _ = _pad()
    t1 = "1 Foundation from levels"
    for code, label, exp in [("BLD", "Blinding m³", 1.452), ("EXC", "Excavation m³", 49.392), ("CON", "Footing concrete m³", 9.600),
                             ("FWK", "Footing formwork m²", 19.200), ("NCC", "Neck column m³", 0.576), ("BKF", "Backfill m³", 37.764),
                             ("DSP", "Disposal m³", 14.535), ("CMP", "Compaction m²", 31.360)]:
        check(t1, label, exp, _q(base, code))
    deeper, _ = _pad(bof=-1.8)
    check(t1, "BOF −1.800 updates excavation m³", 4 * 2.8 * 2.8 * 1.875, _q(deeper, "EXC"))

    t2, _ = _pad({"blinding_t": 0.1, "bo_left": 0.15, "bo_right": 0.15, "bo_top": 0.15, "bo_bottom": 0.15,
                  "eo_left": 0.5, "eo_right": 0.5, "eo_top": 0.5, "eo_bottom": 0.5})
    check("2 Thicker blinding, wider offsets", "Blinding m³", 2.116, _q(t2, "BLD"))
    check("2 Thicker blinding, wider offsets", "Excavation m³", 69.696, _q(t2, "EXC"))

    t3, _ = _pad({"extra_depth": 0.15})
    for label, code, exp in [("Excavation m³", "EXC", 54.096), ("Granular refill m³", "RFL", 4.704),
                             ("Backfill m³", "BKF", 37.764), ("Disposal m³", "DSP", 20.415)]:
        check("3 Extra excavation", label, exp, _q(t3, code))

    t4, _ = _pad(levels={"NGL": 12.35}, bof=10.85)
    check("4 Survey levels", "Excavation m³", 49.392, _q(t4, "EXC"))
    check("4 Survey levels", "Backfill m³", 37.764, _q(t4, "BKF"))

    t5, _ = _pad({"eo_left": 0.0})
    check("5 Per-side offset", "Excavation m³", 44.100, _q(t5, "EXC"))

    slab = [asm.Shape(area=108.0, perimeter=42.0), asm.Shape(area=1.0, perimeter=4.0, deduct=True)]
    t6, _ = asm.compute("grade_slab", "GS", {"t": 0.15, "fill_t": 0.2, "mesh": 1.0}, slab, {}, asm.GLOBALS)
    for label, code, exp in [("Concrete m³", "CON", 16.050), ("Polythene m²", "POL", 117.700), ("Granular fill m³", "GRF", 21.400),
                             ("Power float (net area) m²", "PWF", 107.000)]:
        check("6 Grade slab", label, exp, _q(t6, code))

    t7, _ = asm.compute("grade_beam", "GB", {"b": 0.3, "h": 0.6}, [asm.Shape(length=5.6)], {}, asm.GLOBALS)
    check("7 Grade beam", "Concrete m³", 1.008, _q(t7, "CON"))
    check("7 Grade beam", "Side formwork m²", 6.720, _q(t7, "FWK"))
    # bottom = NGL − h = −0.600; depth 0.600 + 0.075 = 0.675; trench width 0.3 + 0.2 blinding + 0.6 working space = 1.1
    check("7 Grade beam", "Waterproofing under beam m²", 1.848, _q(t7, "WPB"))
    check("7 Grade beam", "Trench excavation m³", 4.158, _q(t7, "EXC"))
    check("7 Grade beam", "Backfill m³", 2.940, _q(t7, "BKF"))
    check(t1, "Extended perimeter at blinding edge m", 35.200, _q(base, "PBL"))
    check(t1, "Extended perimeter at excavation edge m", 44.800, _q(base, "PEX"))

    t8, _ = asm.compute("beam", "B1", {"b": 0.3, "h": 0.6, "slab_t": 0.2}, [asm.Shape(length=6.0)], {}, asm.GLOBALS)
    check("8 Beam under slab", "Concrete m³", 0.720, _q(t8, "CON"))
    check("8 Beam under slab", "Formwork m²", 6.600, _q(t8, "FWK"))

    t9, _ = asm.compute("column", "C1", {"b": 0.4, "h": 0.6, "SSL_bottom": 0.0, "SSL_top": 3.5, "slab_t": 0.2}, [asm.Shape(count=1)], {}, asm.GLOBALS)
    check("9 Column", "Concrete m³", 0.840, _q(t9, "CON"))
    check("9 Column", "Formwork m²", 6.600, _q(t9, "FWK"))

    t10, _ = asm.compute("strip_footing", "SF", {"W": 0.6, "D": 0.4, "BOF": -1.0}, [asm.Shape(length=10.0), asm.Shape(length=8.0)], {}, asm.GLOBALS)
    check("10 Strip footing", "Concrete m³", 4.320, _q(t10, "CON"))

    openings = [
        {"wall_ref": "W-01", "mark": "D1", "width": 0.9, "height": 2.1, "qty": 2},
        {"wall_ref": "W-01", "mark": "WN1", "width": 1.5, "height": 1.2, "qty": 1},
        {"wall_ref": "W-01", "mark": "SV", "width": 0.6, "height": 0.6, "qty": 1},
    ]
    t11, _ = asm.compute("blockwork_wall", "BW200", {"thickness_mm": 200, "height": 3.0, "finish_faces": 2},
                         [asm.Shape(length=10.0, ref="W-01")], {}, asm.GLOBALS, openings)
    check("11 Blockwork with schedule deductions", "Net blockwork m²", 24.420, _q(t11, "BLK"))
    check("11 Blockwork with schedule deductions", "Lintels m", 4.200, _q(t11, "LNT"))

    t12, _ = asm.compute("grade_slab", "GS", {"t": 0.20, "fill_t": 0.2, "mesh": 1.0}, slab, {}, asm.GLOBALS)
    check("12 Parametric update", "Slab 200 mm concrete m³", 21.400, _q(t12, "CON"))

    _, bad = _pad(bof=0.5)
    rows.append({"Test": "13 Error checks", "Item": "BOF above NGL is blocked", "Expected": 1, "Actual": int(any(i.severity == "Error" for i in bad)),
                 "Pass": any(i.severity == "Error" for i in bad)})
    _, orphan = asm.compute("blockwork_wall", "BW", {"height": 3.0}, [asm.Shape(length=5.0, ref="W-02")], {}, asm.GLOBALS,
                            [{"wall_ref": "W-99", "mark": "D1", "width": 0.9, "height": 2.1, "qty": 1}])
    rows.append({"Test": "13 Error checks", "Item": "Opening on an unmeasured wall is blocked", "Expected": 1,
                 "Actual": int(any(i.severity == "Error" for i in orphan)), "Pass": any(i.severity == "Error" for i in orphan)})
    return rows
