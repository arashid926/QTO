"""A small demo floor plan so the app can be tried without your own drawings."""

from __future__ import annotations

import io

import ezdxf

LAYERS = {
    "A-WALL": 7, "A-DOOR": 3, "A-WINDOW": 4, "A-FLOOR-FINISH": 30, "A-TAG": 7,
    "S-COLUMN": 1, "S-SLAB": 8, "M-PIPE-WATER": 5, "E-LIGHT": 2,
    "C-ROAD-KERB": 6, "I-SEWER": 140,
}


def _rect(x, y, w, h):
    return [(x, y), (x + w, y), (x + w, y + h), (x, y + h)]


def sample_dxf_bytes() -> bytes:
    """12 x 9 m single-storey building in millimetres, with site works below it."""
    doc = ezdxf.new("R2010", setup=True)
    doc.header["$INSUNITS"] = 4
    for name, colour in LAYERS.items():
        doc.layers.add(name, color=colour)

    door = doc.blocks.new("DOOR-900")
    door.add_line((0, 0), (900, 0))
    door.add_arc((0, 0), 900, 0, 90)
    window = doc.blocks.new("WIN-1200")
    window.add_lwpolyline(_rect(0, -100, 1200, 200), close=True)
    light = doc.blocks.new("LIGHT-600")
    light.add_lwpolyline(_rect(-300, -300, 600, 600), close=True)
    light.add_line((-300, -300), (300, 300))
    light.add_line((-300, 300), (300, -300))

    msp = doc.modelspace()
    wall = {"layer": "A-WALL"}
    msp.add_lwpolyline(_rect(0, 0, 12000, 9000), close=True, dxfattribs=wall)
    msp.add_lwpolyline(_rect(200, 200, 11600, 8600), close=True, dxfattribs=wall)
    for x in (5900, 6100):
        msp.add_line((x, 200), (x, 8800), dxfattribs=wall)
    for y in (4400, 4600):
        msp.add_line((6100, y), (11800, y), dxfattribs=wall)

    for x in (0, 5800, 11600):
        for y in (0, 8600):
            msp.add_lwpolyline(_rect(x, y, 400, 400), close=True, dxfattribs={"layer": "S-COLUMN"})

    hatch = msp.add_hatch(color=8, dxfattribs={"layer": "S-SLAB"})
    hatch.paths.add_polyline_path(_rect(0, 0, 12000, 9000), is_closed=True)

    for room in (_rect(200, 200, 5700, 8600), _rect(6100, 200, 5700, 4200), _rect(6100, 4600, 5700, 4200)):
        msp.add_lwpolyline(room, close=True, dxfattribs={"layer": "A-FLOOR-FINISH"})

    for (x, y, rot) in [(2500, 0, 0), (6000, 2000, 90), (6000, 6500, 90), (8500, 4500, 0)]:
        msp.add_blockref("DOOR-900", (x, y), dxfattribs={"layer": "A-DOOR", "rotation": rot})
        msp.add_text("D1", height=250, dxfattribs={"layer": "A-TAG"}).set_placement((x + 300, y + 400))
    for (x, y, rot) in [(900, 9000, 0), (3600, 9000, 0), (7500, 9000, 0), (12000, 1500, 90), (12000, 6000, 90), (8500, 0, 0)]:
        msp.add_blockref("WIN-1200", (x, y), dxfattribs={"layer": "A-WINDOW", "rotation": rot})
        msp.add_text("W1", height=250, dxfattribs={"layer": "A-TAG"}).set_placement((x + 300, y - 600))
    for (x, y) in [(1500, 2000), (4500, 2000), (1500, 6500), (4500, 6500), (7500, 2200), (10300, 2200), (7500, 6700), (10300, 6700)]:
        msp.add_blockref("LIGHT-600", (x, y), dxfattribs={"layer": "E-LIGHT"})

    msp.add_lwpolyline([(11800, 2000), (9000, 2000), (9000, 7000)], dxfattribs={"layer": "M-PIPE-WATER"})
    msp.add_line((-3000, -3000), (15000, -3000), dxfattribs={"layer": "C-ROAD-KERB"})
    msp.add_line((-3000, -6000), (15000, -6000), dxfattribs={"layer": "C-ROAD-KERB"})
    msp.add_line((-3000, -4500), (15000, -4500), dxfattribs={"layer": "I-SEWER"})

    stream = io.StringIO()
    doc.write(stream)
    return stream.getvalue().encode("utf-8")
