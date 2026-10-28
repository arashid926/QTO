import pandas as pd
import pytest

from qto import boq, measure, project, rates


def make_state(name, ngl=0.0):
    state = {"boq": boq.empty(), "rates": rates.empty(), "mt": measure.new_state(), "p_name": name, "p_client": "", "p_location": "",
             "p_by": "", "p_standard": "POMI", project.CURRENCY_KEY: "AED"}
    state["mt"]["buildings"][0]["name"] = "Villa A"
    state["mt"]["buildings"][0]["levels"]["NGL"] = ngl
    item = measure.add_assembly_item(state["mt"], "isolated_footing", "F1")
    measure.add_shape(state["mt"], item["id"], "plan.dxf", 0, [[1, 1], [2, 2]])
    state["boq"] = boq.finalise(pd.DataFrame([{"Discipline": "Civil", "Description": f"{name} item", "Unit": "m³", "Quantity": 1.0}]))
    return state


def test_merge_projects():
    target = make_state("Tower A")
    other = make_state("Tower B")
    block = measure.add_building(other["mt"], "Block B")
    item = measure.add_assembly_item(other["mt"], "grade_beam", "GB1")
    measure.add_shape(other["mt"], item["id"], "plan.dxf", 0, [[0, 0], [10, 0]], building=block["id"])
    summary = project.merge(target, project.snapshot(other))
    assert summary == {"items": 2, "shapes": 2, "buildings": 2, "boq_lines": 1}
    mt = target["mt"]
    assert [i["ref"] for i in mt["items"]] == ["TO-001", "TO-002", "TO-003"]  # re-numbered after the existing item
    assert [b["name"] for b in mt["buildings"]] == ["Villa A", "Block B"]  # same-name building reused, new one added
    gb_shape = next(s for s in mt["shapes"] if s["item_id"] == 3)
    assert gb_shape["building"] == mt["buildings"][1]["id"]
    assert len(target["boq"]) == 2 and target["mt_ver"] == 1


def test_copy_keeps_everything_under_a_new_name():
    state = make_state("Tower A")
    copy = project.renamed(project.snapshot(state), project.unique_name("Copy of Tower A", {"Copy of Tower A"}))
    assert copy["info"]["p_name"] == "Copy of Tower A (2)"
    assert copy["info"]["p_standard"] == "POMI"
    target = {"mt": measure.new_state()}
    project.restore(target, copy)
    assert target["p_standard"] == "POMI" and len(target["mt"]["items"]) == 1


def test_blank_project_records_standard():
    data = project.blank("X", standard="CESMM4")
    target = {"mt": measure.new_state()}
    project.restore(target, data)
    assert target["p_standard"] == "CESMM4"


def test_merge_rejects_other_files():
    with pytest.raises(ValueError):
        project.merge(make_state("A"), {"format": "something"})
