import pytest

from qto import dxf_takeoff, geometry, samples


def test_offset_rectangle_both_windings():
    square = [(0, 0), (2, 0), (2, 2), (0, 2)]
    for pts in (square, list(reversed(square))):
        grown = geometry.offset_polygon(pts, 0.1)
        assert geometry.area(grown) == pytest.approx(2.2 * 2.2)
        assert geometry.perimeter(grown) == pytest.approx(8.8)
    assert geometry.area(geometry.offset_polygon(square, -0.5)) == pytest.approx(1.0)


def test_offset_l_shape_is_mitred():
    l_shape = [(0, 0), (4, 0), (4, 2), (2, 2), (2, 4), (0, 4)]
    grown = geometry.offset_polygon(l_shape, 0.5)
    # mitred offset of any orthogonal outline: area + perimeter × d + 4 d²  (5 convex corners − 1 re-entrant)
    assert geometry.area(grown) == pytest.approx(12 + 16 * 0.5 + 4 * 0.25)


def test_band_around_centre_line():
    band = geometry.outline_around([(0, 0), (10, 0), (10, 8)], 0.3)
    assert geometry.area(band) == pytest.approx(18 * 0.6)  # centre-line length × width


def test_rectangle_with_per_side_offsets():
    rect = geometry.rectangle((0, 0), 2, 2, (0.0, 0.3, 0.3, 0.3))
    xs, ys = [p[0] for p in rect], [p[1] for p in rect]
    assert (max(xs) - min(xs), max(ys) - min(ys)) == (pytest.approx(2.3), pytest.approx(2.6))


def test_pick_and_similar_on_sample_plan():
    objects = dxf_takeoff.drawing_objects(dxf_takeoff.takeoff(samples.sample_dxf_bytes(), None, True))
    doors = [o for o in objects if o["key"] == "block:DOOR-900"]
    assert len(doors) == 4
    hit = geometry.pick(objects, doors[0]["center"], tol=3)
    assert hit["key"] == "block:DOOR-900"
    assert len([o for o in objects if geometry.similar(hit, o)]) == 4

    columns = [o for o in objects if o["key"] == "layer:S-COLUMN"]
    assert len(columns) == 6 and all(o["closed"] for o in columns)
    picked = geometry.pick(objects, columns[0]["center"], tol=1)
    assert picked["key"] == "layer:S-COLUMN"
    assert len([o for o in objects if geometry.similar(picked, o)]) == 6  # same layer, same size


def test_similar_respects_size():
    a = {"kind": "path", "key": "layer:X", "closed": True, "area": 1.0, "perimeter": 4.0}
    b = {**a, "area": 1.5, "perimeter": 5.0}
    assert geometry.similar(a, a) and not geometry.similar(a, b)
