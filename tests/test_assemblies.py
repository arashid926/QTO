import pytest

from qto import assemblies as asm
from qto import measure, selftest


@pytest.mark.parametrize("case", selftest.cases(), ids=lambda c: f"{c['Test']} — {c['Item']}")
def test_acceptance(case):
    assert case["Pass"], f"expected {case['Expected']}, got {case['Actual']}"


def test_footing_through_takeoff_model():
    state = measure.new_state()
    item = measure.add_assembly_item(state, "isolated_footing", "F1 isolated footing")
    measure.add_shape(state, item["id"], "plan.dxf", 0, [[1, 1], [2, 2], [3, 3], [4, 4]])  # four footings clicked
    lines = measure.boq_lines(state).set_index("Ref")
    assert lines.loc["TO-001.01", "Description"].startswith("Excavation for F1 isolated footing")
    by_code = {k.split("|")[1]: q for k, q in zip(lines["Key"], lines["Quantity"])}
    assert by_code["EXC"] == pytest.approx(49.392)
    assert by_code["BKF"] == pytest.approx(37.764)

    item["params"]["BOF"] = -1.8  # parametric: change a level, everything follows
    by_code = {k.split("|")[1]: q for k, q in zip(measure.boq_lines(state)["Key"], measure.boq_lines(state)["Quantity"])}
    assert by_code["EXC"] == pytest.approx(4 * 2.8 * 2.8 * 1.875)


def test_buildings_have_their_own_levels():
    state = measure.new_state()
    second = measure.add_building(state, "Block B")
    second["levels"]["NGL"] = 0.5  # higher ground at block B
    item = measure.add_assembly_item(state, "isolated_footing", "F1")
    measure.add_shape(state, item["id"], "plan.dxf", 0, [[1, 1]], building=1)
    measure.add_shape(state, item["id"], "plan.dxf", 0, [[1, 1]], building=second["id"])
    derived, _ = measure.derived_items(state)
    exc = derived[derived["Code"] == "EXC"].set_index("Building")["Quantity"]
    assert exc["Building 1"] == pytest.approx(2.8 * 2.8 * 1.575)
    assert exc["Block B"] == pytest.approx(2.8 * 2.8 * 2.075)


def test_rates_per_derived_item():
    state = measure.new_state()
    item = measure.add_assembly_item(state, "grade_beam", "GB1")
    state["calibration"][measure.page_key("plan.pdf", 0)] = 0.01
    measure.add_shape(state, item["id"], "plan.pdf", 0, [[0, 0], [560, 0]])  # 5.6 m
    key = f"{item['id']}|CON"
    measure.set_rate(state, key, 700.0)
    lines = measure.boq_lines(state)
    concrete = lines[lines["Key"] == key].iloc[0]
    assert concrete["Quantity"] == pytest.approx(1.008) and concrete["Rate"] == 700.0


def test_project_check_flags_missing_scale_and_bad_levels():
    state = measure.new_state()
    item = measure.add_assembly_item(state, "isolated_footing", "F1")
    item["params"]["BOF"] = 0.5  # above NGL
    measure.add_shape(state, item["id"], "plan.dxf", 0, [[1, 1]])
    slab = measure.add_assembly_item(state, "grade_slab", "GS")
    measure.add_shape(state, slab["id"], "scan.png", 0, [[0, 0], [10, 0], [10, 10]])  # no scale on this page
    issues = measure.check_project(state)
    errors = issues[issues["Severity"] == "Error"]["Message"].tolist()
    assert any("not below the start level" in m for m in errors)
    assert any("no scale" in m for m in errors)


def test_wall_schedule():
    state = measure.new_state()
    wall = measure.add_assembly_item(state, "blockwork_wall", "BW200")
    wall["params"]["height"] = 3.0
    wall["openings"] = [{"wall_ref": "W-01", "mark": "D1", "width": 0.9, "height": 2.1, "qty": 2}]
    state["calibration"][measure.page_key("plan.pdf", 0)] = 0.01
    shape = measure.add_shape(state, wall["id"], "plan.pdf", 0, [[0, 0], [1000, 0]])
    shape["location"] = "W-01"
    schedule = measure.wall_schedules(state)
    row = schedule.iloc[0]
    assert (row["Wall ref"], row["Gross (m²)"], row["Net (m²)"]) == ("W-01", 30.0, pytest.approx(26.22))


def test_old_files_gain_globals_and_levels():
    state = measure.from_dict({"items": [], "shapes": [], "buildings": [{"id": 1, "code": "B01", "name": "Villa"}]})
    assert state["globals"]["blinding_t"] == asm.GLOBALS["blinding_t"]
    assert state["buildings"][0]["levels"]["NGL"] == 0.0
