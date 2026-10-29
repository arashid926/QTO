"""Each project keeps its own buildings, drawings and calculations; each building its own drawings."""

from qto import boq, measure, project, rates


def make_project(name, n_buildings, files):
    state = {"boq": boq.empty(), "rates": rates.empty(), "mt": measure.new_state(), "p_name": name, project.CURRENCY_KEY: "AED",
             "files": {}, "models": {}, "hidden_layers": {}}
    for i in range(2, n_buildings + 1):
        measure.add_building(state["mt"], f"{name} block {i}")
    for doc, building in files:
        state["files"][doc] = f"{name}:{doc}".encode()
        measure.assign_drawing(state["mt"], doc, building)
    return state


def test_switching_projects_never_mixes_data():
    session = make_project("Project A", 5, [("A-GF.pdf", 1), ("A-roof.pdf", 5)])
    item = measure.add_assembly_item(session["mt"], "isolated_footing", "F1")
    measure.add_shape(session["mt"], item["id"], "A-GF.pdf", 0, [[1, 1]])
    session["mt_doc"], session["mt_pg_A-GF.pdf"], session["mt_building"] = "A-GF.pdf", 2, 5
    a = project.snapshot(session)
    b = project.snapshot(make_project("Project B", 10, [("B-plan.dxf", 7)]))

    project.restore(session, b)  # open B: A is closed
    assert session["p_name"] == "Project B" and len(session["mt"]["buildings"]) == 10
    assert set(session["files"]) == {"B-plan.dxf"} and session["mt"]["items"] == []
    assert "mt_doc" not in session and "mt_building" not in session and "mt_pg_A-GF.pdf" not in session

    project.restore(session, a)  # open A again: everything of A comes back, nothing of B
    assert session["p_name"] == "Project A" and len(session["mt"]["buildings"]) == 5
    assert session["files"] == {"A-GF.pdf": b"Project A:A-GF.pdf", "A-roof.pdf": b"Project A:A-roof.pdf"}
    assert len(session["mt"]["shapes"]) == 1 and session["p_id"] == a["id"] != b["id"]


def test_each_building_lists_only_its_drawings():
    state = make_project("A", 3, [("GF.pdf", 1), ("L1.pdf", 2), ("Roof.pdf", 2)])
    names = list(state["files"])
    assert measure.drawings_for(state["mt"], names, 1) == ["GF.pdf"]
    assert measure.drawings_for(state["mt"], names, 2) == ["L1.pdf", "Roof.pdf"]
    assert measure.drawings_for(state["mt"], names, 3) == []


def test_project_file_keeps_drawings_and_their_buildings():
    state = make_project("A", 2, [("GF.pdf", 2)])
    data = project.from_bytes(project.to_bytes(project.snapshot(state)))
    target = {"mt": measure.new_state()}
    project.restore(target, data)
    assert target["files"] == {"GF.pdf": b"A:GF.pdf"} and measure.drawing_building(target["mt"], "GF.pdf") == 2


def test_merge_renames_clashing_drawings_and_keeps_their_building():
    target = make_project("A", 1, [("plan.pdf", 1)])
    source = make_project("B", 2, [("plan.pdf", 2)])
    item = measure.add_item(source["mt"], "Wall", "Architectural", "14 Masonry", "Length")
    measure.add_shape(source["mt"], item["id"], "plan.pdf", 0, [[0, 0], [1, 0]], building=2)
    source["mt"]["calibration"]["plan.pdf|0"] = 0.01
    summary = project.merge(target, project.snapshot(source))
    assert summary["drawings"] == 1 and set(target["files"]) == {"plan.pdf", "plan (2).pdf"}
    shape = target["mt"]["shapes"][-1]
    assert shape["doc"] == "plan (2).pdf" and target["mt"]["calibration"]["plan (2).pdf|0"] == 0.01
    assert measure.drawing_building(target["mt"], "plan (2).pdf") == shape["building"] != 1


def test_rename_and_remove_drawing_follow_through():
    mt = measure.new_state()
    measure.assign_drawing(mt, "old.pdf", 1)
    item = measure.add_item(mt, "Slab", "Structural", "11 In-situ concrete works", "Area")
    measure.add_shape(mt, item["id"], "old.pdf", 0, [[0, 0], [1, 0], [1, 1]])
    mt["calibration"]["old.pdf|0"] = 0.02
    measure.rename_drawing(mt, "old.pdf", "new.pdf")
    assert mt["shapes"][0]["doc"] == "new.pdf" and mt["calibration"] == {"new.pdf|0": 0.02} and "new.pdf" in mt["drawings"]
    measure.remove_drawing(mt, "new.pdf")
    assert mt["calibration"] == {} and "new.pdf" not in mt["drawings"] and len(mt["shapes"]) == 1


def test_older_takeoffs_link_drawings_to_their_measured_building():
    mt = measure.new_state()
    b2 = measure.add_building(mt, "Block 2")
    item = measure.add_item(mt, "Door", "Architectural", "24 Doors, shutters and hatches", "Count")
    measure.add_shape(mt, item["id"], "B2-plan.pdf", 0, [[1, 1]], building=b2["id"])
    mt.pop("drawings")
    assert measure.drawing_building(measure.upgrade(mt), "B2-plan.pdf") == b2["id"]


def test_unique_file_names():
    assert project.unique_file("plan.pdf", {"plan.pdf"}) == "plan (2).pdf"
    assert project.unique_file("plan.pdf", {"plan.pdf", "plan (2).pdf"}) == "plan (3).pdf"
    assert project.unique_file("README", {"README"}) == "README (2)"
