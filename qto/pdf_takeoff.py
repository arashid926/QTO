"""PDF drawing take-off: scaled vector measurement, legend reading, tag counting and table extraction."""

from __future__ import annotations

import io
import math
import re

import pandas as pd
import pdfplumber
from PIL import ImageDraw

from . import disciplines as dz

PT_TO_MM = 25.4 / 72.0
FULL_PAGE = (0.0, 0.0, 1.0, 1.0)
HIGHLIGHT = (236, 0, 140)
MAX_RENDER_SIDE = 6000  # px; large sheets are rendered at a lower resolution to stay responsive

L, A, C = dz.MEASURE_COLUMNS["Length"], dz.MEASURE_COLUMNS["Area"], dz.MEASURE_COLUMNS["Count"]


def page_count(data: bytes) -> int:
    with pdfplumber.open(io.BytesIO(data)) as pdf:
        return len(pdf.pages)


def _crop_bbox(page, crop):
    bx0, btop, bx1, bbottom = page.bbox
    w, h = bx1 - bx0, bbottom - btop
    x0, t0, x1, b0 = crop
    return (bx0 + x0 * w, btop + t0 * h, bx0 + x1 * w, btop + b0 * h)


def _hex(colour) -> str:
    try:
        if colour is None:
            return "#000000"
        if isinstance(colour, (int, float)):
            colour = [colour]
        vals = [float(v) for v in colour]
        if len(vals) == 1:
            r = g = b = vals[0]
        elif len(vals) == 3:
            r, g, b = vals
        elif len(vals) == 4:
            c, m, y, k = vals
            r, g, b = (1 - c) * (1 - k), (1 - m) * (1 - k), (1 - y) * (1 - k)
        else:
            return "other"
        return "#{:02x}{:02x}{:02x}".format(*(int(round(max(0.0, min(1.0, v)) * 255)) for v in (r, g, b)))
    except (TypeError, ValueError):
        return "other"


def _shoelace(pts) -> float:
    return abs(sum(x1 * y2 - x2 * y1 for (x1, y1), (x2, y2) in zip(pts, pts[1:] + pts[:1]))) / 2.0


def _length(pts) -> float:
    return sum(math.dist(a, b) for a, b in zip(pts, pts[1:]))


def _objects(region):
    """Yield (colour, line width, points, closed) for every vector object, points in page coordinates (top-down)."""
    def style(obj):
        filled_only = obj.get("fill") and not obj.get("stroke", True)
        colour = obj.get("non_stroking_color") if filled_only else obj.get("stroking_color")
        return _hex(colour), round(float(obj.get("linewidth") or 0), 2)

    for obj in region.lines:
        pts = [tuple(p) for p in obj.get("pts") or [(obj["x0"], obj["top"]), (obj["x1"], obj["bottom"])]]
        yield (*style(obj), pts, False)
    for obj in region.curves:
        pts = [tuple(p) for p in obj.get("pts") or []]
        if len(pts) >= 2:
            yield (*style(obj), pts, len(pts) > 2 and math.dist(pts[0], pts[-1]) < 0.5)
    for obj in region.rects:
        x0, t, x1, b = obj["x0"], obj["top"], obj["x1"], obj["bottom"]
        yield (*style(obj), [(x0, t), (x1, t), (x1, b), (x0, b), (x0, t)], True)


def _region(page, crop):
    return page.within_bbox(_crop_bbox(page, crop)) if tuple(crop) != FULL_PAGE else page


def render_page(data: bytes, page_no: int, crop=FULL_PAGE, resolution: int = 100, highlight: tuple = ()):
    """Render a page, outline the measured region in red and draw the ticked linework groups in magenta."""
    with pdfplumber.open(io.BytesIO(data)) as pdf:
        page = pdf.pages[page_no]
        image = page.to_image(resolution=resolution).original.convert("RGB")
        k = resolution / 72.0
        bx0, btop = page.bbox[0], page.bbox[1]
        draw = ImageDraw.Draw(image)
        if highlight:
            wanted = set(highlight)
            for colour, width, pts, _closed in _objects(_region(page, crop)):
                if (colour, width) in wanted:
                    draw.line([((x - bx0) * k, (y - btop) * k) for x, y in pts], fill=HIGHLIGHT, width=4)
    if tuple(crop) != FULL_PAGE:
        w, h = image.size
        x0, t0, x1, b0 = crop
        draw.rectangle([x0 * w, t0 * h, x1 * w, b0 * h], outline=(220, 38, 38), width=4)
    return image


def measure_vectors(data: bytes, page_no: int, scale: float, crop=FULL_PAGE) -> pd.DataFrame:
    """Measure lines, curves and rectangles on a page, grouped by colour and line weight.

    `scale` is the drawing scale denominator (100 for 1:100) at the PDF's paper size.
    """
    k = PT_TO_MM * scale / 1000.0  # PDF points -> metres on site
    rows = []
    with pdfplumber.open(io.BytesIO(data)) as pdf:
        for colour, width, pts, closed in _objects(_region(pdf.pages[page_no], crop)):
            rows.append({
                "Colour": colour, "Line width": width, "Length": _length(pts) * k,
                "Area": _shoelace(pts) * k * k if closed else 0.0, "Closed": closed,
            })

    columns = ["Bill", "Discipline", "Work Section", "Measure", "Description", "Factor", dz.DIM_COLUMN, "Colour", "Line width", C, L, A]
    df = pd.DataFrame(rows, columns=["Colour", "Line width", "Length", "Area", "Closed"])
    if df.empty:
        return pd.DataFrame(columns=columns)
    g = (
        df.groupby(["Colour", "Line width"])
        .agg(Count=("Length", "size"), Length=("Length", "sum"), Area=("Area", "sum"), Closed=("Closed", "sum"))
        .reset_index()
        .sort_values("Length", ascending=False)
    )
    g["Measure"] = ["Area" if cl >= 0.6 * n and a > 0 else "Length" for cl, n, a in zip(g["Closed"], g["Count"], g["Area"])]
    g["Bill"] = False
    g["Discipline"], g["Work Section"] = dz.DEFAULT_CLASS
    g["Description"] = [f"Linework {c} @ {w} pt" for c, w in zip(g["Colour"], g["Line width"])]
    g["Factor"] = 1.0
    g[dz.DIM_COLUMN] = 0.0
    g = g.rename(columns={"Length": L, "Area": A})
    return g[columns].reset_index(drop=True)


def read_legend(data: bytes, page_no: int, region=FULL_PAGE) -> pd.DataFrame:
    """Pair each legend swatch (short line, hatch sample or filled box) with the text written to its right."""
    entries: dict[str, str] = {}
    with pdfplumber.open(io.BytesIO(data)) as pdf:
        area = _region(pdf.pages[page_no], region)
        width = area.bbox[2] - area.bbox[0]
        words = area.extract_words()
        for colour, _w, pts, _closed in _objects(area):
            xs, ys = [p[0] for p in pts], [p[1] for p in pts]
            if colour in entries or colour == "other" or max(xs) - min(xs) > 0.25 * width or max(ys) - min(ys) > 40:
                continue
            right, middle = max(xs), (min(ys) + max(ys)) / 2
            tolerance = max(4.0, (max(ys) - min(ys)) / 2 + 2)
            line = sorted(
                (w for w in words if abs((w["top"] + w["bottom"]) / 2 - middle) <= tolerance and right - 1 <= w["x0"] <= right + 120),
                key=lambda w: w["x0"],
            )
            label, last = [], None
            for w in line:
                if last is not None and w["x0"] - last > 15:
                    break
                label.append(w["text"])
                last = w["x1"]
            if label:
                entries[colour] = " ".join(label)
    return pd.DataFrame([{"Colour": c, "Label": t} for c, t in entries.items()], columns=["Colour", "Label"])


def apply_legend(vectors: pd.DataFrame, legend: pd.DataFrame) -> pd.DataFrame:
    """Name linework groups after the legend entry of the same colour and classify them from that name."""
    labels = dict(zip(legend["Colour"], legend["Label"]))
    out = vectors.copy()
    for i, colour in out["Colour"].items():
        label = labels.get(colour)
        if not label:
            continue
        discipline, section = dz.classify(label)
        out.at[i, "Description"] = label
        out.at[i, "Discipline"], out.at[i, "Work Section"] = discipline, section
        out.at[i, "Bill"] = True
        if dz.suggest_count(label):
            out.at[i, "Measure"] = "Count"
    return out


def snap_points(data: bytes, page_no: int, limit: int = 40_000) -> list[tuple[float, float]]:
    """Line ends and corners of the vector drawing, in page points from the top-left, for snapping."""
    seen, out = set(), []
    with pdfplumber.open(io.BytesIO(data)) as pdf:
        page = pdf.pages[page_no]
        bx0, btop = page.bbox[0], page.bbox[1]
        for _c, _w, pts, _closed in _objects(page):
            for x, y in pts:
                key = (round(x - bx0, 3), round(y - btop, 3))
                if key not in seen:
                    seen.add(key)
                    out.append(key)
                    if len(out) >= limit:
                        return out
    return out


def render_for_measure(data: bytes, page_no: int, dpi: int = 110):
    """(image, pixels per PDF point) for on-screen measuring; very large sheets get a lower resolution."""
    with pdfplumber.open(io.BytesIO(data)) as pdf:
        page = pdf.pages[page_no]
        longest = max(page.width, page.height)
        dpi = min(dpi, int(MAX_RENDER_SIDE * 72 / longest))
        image = page.to_image(resolution=dpi).original.convert("RGB")
    return image, image.size[0] / float(page.width)


def count_tags(data: bytes, tags: list[str], pages: list[int] | None = None) -> pd.DataFrame:
    """Count words that exactly match tags such as D1, W2, LT-01 across pages."""
    wanted = {t.strip().upper(): 0 for t in tags if t.strip()}
    with pdfplumber.open(io.BytesIO(data)) as pdf:
        for i, page in enumerate(pdf.pages):
            if pages is not None and i not in pages:
                continue
            for word in page.extract_words():
                text = re.sub(r"^[^\w]+|[^\w]+$", "", word["text"]).upper()
                if text in wanted:
                    wanted[text] += 1
    return pd.DataFrame([{"Tag": t, "Count": n} for t, n in wanted.items()], columns=["Tag", "Count"])


def extract_tables(data: bytes, page_no: int) -> list[pd.DataFrame]:
    """Pull tabular schedules (door schedules, BBS, fixture lists) out of a PDF page."""
    from .schedules import unique_columns

    tables = []
    with pdfplumber.open(io.BytesIO(data)) as pdf:
        for raw in pdf.pages[page_no].extract_tables():
            rows = [[(cell or "").replace("\n", " ").strip() for cell in row] for row in raw if any(row)]
            if len(rows) < 2:
                continue
            tables.append(pd.DataFrame(rows[1:], columns=unique_columns(rows[0])))
    return tables
