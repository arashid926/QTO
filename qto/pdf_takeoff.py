"""PDF drawing take-off: scaled vector measurement, tag counting and table extraction."""

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

L, A, C = dz.MEASURE_COLUMNS["Length"], dz.MEASURE_COLUMNS["Area"], dz.MEASURE_COLUMNS["Count"]


def page_count(data: bytes) -> int:
    with pdfplumber.open(io.BytesIO(data)) as pdf:
        return len(pdf.pages)


def _crop_bbox(page, crop):
    bx0, btop, bx1, bbottom = page.bbox
    w, h = bx1 - bx0, bbottom - btop
    x0, t0, x1, b0 = crop
    return (bx0 + x0 * w, btop + t0 * h, bx0 + x1 * w, btop + b0 * h)


def render_page(data: bytes, page_no: int, crop=FULL_PAGE, resolution: int = 100):
    """Render a page to a PIL image, outlining the measured region in red."""
    with pdfplumber.open(io.BytesIO(data)) as pdf:
        page = pdf.pages[page_no]
        image = page.to_image(resolution=resolution).original.convert("RGB")
    if tuple(crop) != FULL_PAGE:
        w, h = image.size
        x0, t0, x1, b0 = crop
        ImageDraw.Draw(image).rectangle([x0 * w, t0 * h, x1 * w, b0 * h], outline=(220, 38, 38), width=4)
    return image


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


def measure_vectors(data: bytes, page_no: int, scale: float, crop=FULL_PAGE) -> pd.DataFrame:
    """Measure lines, curves and rectangles on a page, grouped by stroke colour and line weight.

    `scale` is the drawing scale denominator (100 for 1:100) at the PDF's paper size.
    """
    k = PT_TO_MM * scale / 1000.0  # PDF points -> metres on site
    rows = []
    with pdfplumber.open(io.BytesIO(data)) as pdf:
        page = pdf.pages[page_no]
        region = page.within_bbox(_crop_bbox(page, crop)) if tuple(crop) != FULL_PAGE else page

        def add(obj, pts, closed):
            colour = obj.get("stroking_color") if obj.get("stroke", True) else obj.get("non_stroking_color")
            rows.append({
                "Colour": _hex(colour),
                "Line width": round(float(obj.get("linewidth") or 0), 2),
                "Length": _length(pts) * k,
                "Area": _shoelace(pts) * k * k if closed else 0.0,
                "Closed": closed,
            })

        for obj in region.lines:
            pts = [tuple(p) for p in obj.get("pts") or [(obj["x0"], obj["top"]), (obj["x1"], obj["bottom"])]]
            add(obj, pts, False)
        for obj in region.curves:
            pts = [tuple(p) for p in obj.get("pts") or []]
            if len(pts) >= 2:
                add(obj, pts, len(pts) > 2 and math.dist(pts[0], pts[-1]) < 0.5)
        for obj in region.rects:
            x0, t, x1, b = obj["x0"], obj["top"], obj["x1"], obj["bottom"]
            add(obj, [(x0, t), (x1, t), (x1, b), (x0, b), (x0, t)], True)

    columns = ["Bill", "Discipline", "Work Section", "Measure", "Description", "Colour", "Line width", C, L, A]
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
    g = g.rename(columns={"Length": L, "Area": A})
    return g[columns].reset_index(drop=True)


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
