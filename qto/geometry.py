"""Plane geometry for take-off: offset (extended) outlines, distances and similarity of drawn objects.

Points are (x, y) tuples in any consistent unit. Offsets use mitred corners, which is exact for the
rectangular and orthogonal outlines that dominate foundation drawings.
"""

from __future__ import annotations

import math


def area(pts) -> float:
    return abs(signed_area(pts))


def signed_area(pts) -> float:
    return sum(x1 * y2 - x2 * y1 for (x1, y1), (x2, y2) in zip(pts, list(pts[1:]) + [pts[0]])) / 2.0


def perimeter(pts, closed: bool = True) -> float:
    ring = list(pts) + ([pts[0]] if closed else [])
    return sum(math.dist(a, b) for a, b in zip(ring, ring[1:]))


def centroid(pts) -> tuple[float, float]:
    return (sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts))


def _clean(pts, closed: bool):
    out = []
    for p in pts:
        if not out or math.dist(p, out[-1]) > 1e-9:
            out.append((float(p[0]), float(p[1])))
    if closed and len(out) > 2 and math.dist(out[0], out[-1]) < 1e-9:
        out.pop()
    return out


def _offset_lines(pts, d: float, closed: bool):
    """Offset every segment by d along its left normal; returns [(point, direction)]."""
    lines = []
    ring = pts + ([pts[0]] if closed else [])
    for a, b in zip(ring, ring[1:]):
        dx, dy = b[0] - a[0], b[1] - a[1]
        length = math.hypot(dx, dy)
        nx, ny = -dy / length, dx / length
        lines.append(((a[0] + nx * d, a[1] + ny * d), (dx, dy)))
    return lines


def _intersect(l1, l2):
    (p, r), (q, s) = l1, l2
    cross = r[0] * s[1] - r[1] * s[0]
    if abs(cross) < 1e-12:  # parallel segments: keep the end of the first
        return (q[0], q[1])
    t = ((q[0] - p[0]) * s[1] - (q[1] - p[1]) * s[0]) / cross
    return (p[0] + t * r[0], p[1] + t * r[1])


def offset_polygon(pts, d: float):
    """Outline grown outward by d (shrunk if d < 0)."""
    pts = _clean(pts, closed=True)
    if len(pts) < 3 or not d:
        return pts
    def grow(dist):
        lines = _offset_lines(pts, dist, closed=True)
        return [_intersect(lines[i - 1], lines[i]) for i in range(len(lines))]
    out = grow(d)
    if (area(out) < area(pts)) == (d > 0):  # wrong winding: offset the other way
        out = grow(-d)
    return out


def outline_around(pts, half_width: float):
    """Closed outline of a band of the given half-width centred on an open polyline (e.g. a strip footing)."""
    pts = _clean(pts, closed=False)
    if len(pts) < 2 or half_width <= 0:
        return []
    def side(dist):
        lines = _offset_lines(pts, dist, closed=False)
        out = [lines[0][0]]
        out += [_intersect(lines[i - 1], lines[i]) for i in range(1, len(lines))]
        last_p, last_r = lines[-1]
        out.append((last_p[0] + last_r[0], last_p[1] + last_r[1]))
        return out
    return side(half_width) + list(reversed(side(-half_width)))


def rectangle(center, length: float, width: float, extra=(0.0, 0.0, 0.0, 0.0)):
    """Axis-aligned rectangle centred on a point, grown by (left, right, top, bottom)."""
    cx, cy = center
    left, right, top, bottom = extra
    x0, x1 = cx - length / 2 - left, cx + length / 2 + right
    y0, y1 = cy - width / 2 - top, cy + width / 2 + bottom
    return [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]


def distance_to_path(p, pts, closed: bool) -> float:
    ring = list(pts) + ([pts[0]] if closed and len(pts) > 2 else [])
    best = math.inf
    for a, b in zip(ring, ring[1:]):
        dx, dy = b[0] - a[0], b[1] - a[1]
        l2 = dx * dx + dy * dy
        t = 0.0 if l2 == 0 else max(0.0, min(1.0, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / l2))
        best = min(best, math.hypot(p[0] - a[0] - t * dx, p[1] - a[1] - t * dy))
    if len(ring) == 1:
        best = math.dist(p, ring[0])
    return best


def inside(p, poly) -> bool:
    hit = False
    for i in range(len(poly)):
        (xi, yi), (xj, yj) = poly[i], poly[i - 1]
        if (yi > p[1]) != (yj > p[1]) and p[0] < (xj - xi) * (p[1] - yi) / (yj - yi) + xi:
            hit = not hit
    return hit


def similar(a: dict, b: dict, tol: float = 0.02) -> bool:
    """Two drawing objects match if they share a key (block / layer / pen) and, when closed, size."""
    if a["key"] != b["key"] or a["kind"] != b["kind"]:
        return False
    if a["kind"] == "insert" or not a["closed"]:
        return True
    if not b["closed"]:
        return False
    def close(x, y):
        return abs(x - y) <= tol * max(abs(x), abs(y), 1e-9)
    return close(a["area"], b["area"]) and close(a["perimeter"], b["perimeter"])


def pick(objects: list[dict], p, tol: float) -> dict | None:
    """The object under a click: a block insert near it first, then the nearest path within tol,
    else the smallest closed shape containing it."""
    inserts = [(math.dist(p, o["center"]), i) for i, o in enumerate(objects) if o["kind"] == "insert"]
    near = [t for t in inserts if t[0] <= tol]
    if near:
        return objects[min(near)[1]]
    best, best_d = None, tol
    for obj in objects:
        if obj["kind"] == "insert":
            continue
        d = distance_to_path(p, obj["pts"], obj["closed"])
        if d <= best_d:
            best, best_d = obj, d
    if best is None:
        containing = [o for o in objects if o["kind"] == "path" and o["closed"] and inside(p, o["pts"])]
        best = min(containing, key=lambda o: o["area"], default=None)
    return best
