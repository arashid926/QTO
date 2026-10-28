import pandas as pd
import pytest

from qto import admin, boq, measure, project, rates


def lines():
    return boq.finalise(pd.DataFrame([
        {"Ref": "A1", "Discipline": "Structural", "Work Section": "11 In-situ concrete works", "Description": "Reinforced concrete in footings",
         "Unit": "m³", "Quantity": 10.123, "Rate": 100.0},
        {"Ref": "A2", "Discipline": "Architectural", "Work Section": "19 Waterproofing", "Description": "Membrane waterproofing under footings",
         "Unit": "m²", "Quantity": 50.0, "Rate": 0.0},
    ]), sort=False)


def test_defaults_cover_every_library_and_upgrade_keeps_edits():
    data = admin.defaults()
    assert set(data) == set(admin.TABLES)
    data["Standard Zones"] = [{"Zone": "B1", "Description": "Basement"}]
    up = admin.upgrade(data)
    assert admin.zones(up) == ["B1"] and "Code Library" in up
    assert admin.upgrade(None) == admin.defaults()


def test_units_extend_the_standard_list():
    data = admin.defaults()
    data["Unit of Measurement"].append({"Unit": "lm", "Description": "Linear metre (alt)"})
    units = admin.units(data)
    assert units[:3] == ["nr", "m", "m²"] and "lm" in units and len(units) == len(set(units))


def test_formulas_use_standard_variables():
    v = admin.variables(admin.defaults())
    assert v == {"storey_h": 3.5, "slab_t": 0.2}
    assert admin.evaluate("storey_h - slab_t", v) == pytest.approx(3.3)
    assert admin.evaluate("2 * (1.5 + 0.1)", v) == pytest.approx(3.2)
    assert admin.evaluate(0.6, v) == 0.6
    for bad in ("unknown + 1", "__import__('os')", "1/0", "", "3 +"):
        with pytest.raises(ValueError):
            admin.evaluate(bad, v)


def test_location_factor_and_markup():
    out = admin.apply_factor(lines(), 1.15)
    assert list(out["Rate"]) == [115.0, 0.0] and out.loc[0, "Amount"] == pytest.approx(10.123 * 115.0, abs=0.01)
    out = admin.apply_markup(lines(), 10, "Architectural")
    assert list(out["Rate"]) == [100.0, 0.0]  # structural line untouched
    assert list(admin.apply_markup(lines(), -50, "Structural")["Rate"]) == [50.0, 0.0]


def test_round_quantities_up_never_under_measures():
    assert list(admin.round_quantities(lines(), 1)["Quantity"]) == [10.2, 50.0]
    assert list(admin.round_quantities(lines(), 2, up=False)["Quantity"]) == [10.12, 50.0]


def test_subcontractor_rates_price_matching_lines():
    subs = admin.frame(admin.defaults(), "Subcontractor Values")
    subs.loc[0, "Rate"] = 22.5
    out, priced = admin.apply_subcontractors(lines(), subs)
    assert priced == 1 and list(out["Rate"]) == [100.0, 22.5]
    _, priced = admin.apply_subcontractors(out, subs)  # already priced, not overwritten
    assert priced == 0


def test_custom_quantities_become_boq_lines():
    custom = admin.frame(admin.defaults(), "Custom Quantities")
    out = admin.custom_to_boq(custom)
    assert len(out) == 1 and out.loc[0, "Source"] == "Custom quantities" and out.loc[0, "Unit"] == "item"


def test_spelling_suggests_construction_terms():
    fixes = admin.spelling(["Reinforced concreet in fotings", "Blockwork  walls"])
    found = dict(zip(fixes["Word"], fixes["Suggestion"]))
    assert found["concreet"] == "concrete" and found["fotings"] == "footings" and "(double space)" in found
    fixed = admin.apply_spelling(pd.DataFrame({"Description": ["Reinforced concreet in fotings", "Blockwork  walls"]}), fixes)
    assert list(fixed["Description"]) == ["Reinforced concrete in footings", "Blockwork walls"]


def test_change_case():
    df = pd.DataFrame({"Description": ["reinforced CONCRETE"]})
    assert admin.change_case(df, "Sentence case")["Description"][0] == "Reinforced concrete"
    assert admin.change_case(df, "UPPER CASE")["Description"][0] == "REINFORCED CONCRETE"


def test_manual_dimension_counts_like_a_measurement():
    mt = measure.new_state()
    item = measure.add_item(mt, "Skirting", "Architectural", "14 Masonry", "Length")
    measure.add_manual(mt, item["id"], 12.5, timesing=2)
    measure.add_manual(mt, item["id"], 1.5, deduct=True)
    sheet = measure.qto_sheet(mt)
    assert sheet["Quantity"].sum() == pytest.approx(12.5 * 2 - 1.5)
    assert list(sheet["Drawing"]) == [measure.MANUAL_DOC] * 2


def test_admin_libraries_saved_with_the_project():
    state = {"boq": boq.empty(), "rates": rates.empty(), "mt": measure.new_state(), "p_name": "P", project.CURRENCY_KEY: "USD",
             "admin": admin.defaults()}
    state["admin"]["Standard Zones"] = [{"Zone": "PODIUM", "Description": ""}]
    target = {"mt": measure.new_state()}
    project.restore(target, project.snapshot(state))
    assert admin.zones(target["admin"]) == ["PODIUM"]
    old = project.snapshot(state)
    old.pop("admin")  # projects saved before this version
    project.restore(target, old)
    assert target["admin"] == admin.defaults()
