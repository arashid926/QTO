import pandas as pd
import pytest

from qto import boq, measure, project, rates


def make_state():
    state = {"boq": boq.empty(), "rates": rates.empty(), "mt": measure.new_state(), "p_name": "Tower A",
             "p_client": "ACME", "p_location": "Dubai", "p_by": "QS", project.CURRENCY_KEY: "AED"}
    state["boq"] = boq.finalise(pd.DataFrame([{"Discipline": "Civil", "Description": "Excavation", "Unit": "m³",
                                               "Quantity": 120.0, "Rate": 28.0, "Source": "test"}]))
    state["rates"] = rates.tidy(pd.DataFrame([{"Description": "Excavation", "Unit": "m3", "Rate": 28}]))
    item = measure.add_item(state["mt"], "Doors", "Architectural", "24 Doors, shutters and hatches", "Count")
    measure.add_shape(state["mt"], item["id"], "plan.pdf", 0, [[1, 1], [2, 2]])
    return state


def test_snapshot_round_trip_through_file():
    state = make_state()
    data = project.from_bytes(project.to_bytes(project.snapshot(state)))
    target = {"mt": measure.new_state()}
    target["mt"]["seen"] = ["event-1"]
    project.restore(target, data)
    assert (target["p_name"], target["p_client"], target[project.CURRENCY_KEY]) == ("Tower A", "ACME", "AED")
    assert target["boq"].loc[0, "Amount"] == pytest.approx(120 * 28)
    assert target["rates"].loc[0, "Unit"] == "m³"
    assert measure.boq_lines(target["mt"])["Quantity"].tolist() == [2.0]
    assert target["mt"]["seen"] == ["event-1"]  # canvas events are not replayed in the new project
    assert target["details"] == {} and target["mt_ver"] == 1


def test_blank_project_and_file_name():
    data = project.blank("Al Barsha Villas", currency="AED", first_building="Villa Type A")
    target = {"mt": measure.new_state()}
    project.restore(target, data)
    assert target["boq"].empty and target["rates"].empty
    assert target["mt"]["buildings"][0]["name"] == "Villa Type A"
    assert project.file_name(data) == "Al_Barsha_Villas.qto.json"


def test_rejects_other_files():
    with pytest.raises(ValueError):
        project.from_bytes(b'{"format": "qto-studio-takeoff"}')
