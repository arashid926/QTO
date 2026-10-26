import io

import pandas as pd

from qto import boq, rates


def make_boq(rows):
    return boq.finalise(pd.DataFrame(rows), sort=False)


LIBRARY = rates.tidy(pd.DataFrame([
    {"Code": "BW200", "Description": "200 mm thick blockwork wall in cement mortar", "Unit": "sqm", "Rate": 65},
    {"Code": "", "Description": "Ceramic floor tiles 600x600 mm on screed", "Unit": "m2", "Rate": 85},
    {"Code": "", "Description": "Reinforced concrete C40 in columns", "Unit": "m3", "Rate": 700},
    {"Code": "", "Description": "Unpriced item", "Unit": "nr", "Rate": None},
]))


def test_tidy_normalises_units_and_rates():
    assert LIBRARY["Unit"].tolist() == ["m²", "m²", "m³", "nr"]
    assert LIBRARY["Rate"].tolist() == [65.0, 85.0, 700.0, 0.0]


def test_empty_is_stable_under_tidy():
    assert rates.tidy(rates.empty(), drop_blank=False).equals(rates.empty())


def test_code_exact_and_similar_matching():
    lines = make_boq([
        {"Ref": "BW200", "Discipline": "Architectural", "Description": "Block wall", "Unit": "m²", "Quantity": 10},
        {"Discipline": "Architectural", "Description": "Ceramic floor tiles 600x600 mm on screed", "Unit": "m²", "Quantity": 5},
        {"Discipline": "Structural", "Description": "Reinforced concrete C40 columns", "Unit": "m³", "Quantity": 2},
        {"Discipline": "Structural", "Description": "Reinforced concrete C40 columns", "Unit": "m²", "Quantity": 2},
        {"Discipline": "MEP", "Description": "LED panel light", "Unit": "nr", "Quantity": 4},
    ])
    priced, report = rates.apply(lines, LIBRARY, min_score=0.8)
    assert priced["Rate"].tolist() == [65.0, 85.0, 700.0, 0.0, 0.0]  # wrong unit and unknown item stay unpriced
    assert report["Method"].tolist() == ["Code", "Exact", "Similar"]
    assert priced["Amount"].sum() == 65 * 10 + 85 * 5 + 700 * 2


def test_existing_rates_kept_unless_overwrite():
    lines = make_boq([{"Discipline": "Structural", "Description": "Reinforced concrete C40 in columns", "Unit": "m³", "Quantity": 1, "Rate": 999}])
    kept, report = rates.apply(lines, LIBRARY)
    assert kept.loc[0, "Rate"] == 999 and report.empty
    replaced, _ = rates.apply(lines, LIBRARY, overwrite=True)
    assert replaced.loc[0, "Rate"] == 700


def test_from_boq_and_merge():
    lines = make_boq([
        {"Discipline": "Civil", "Description": "Excavation for foundations", "Unit": "m³", "Quantity": 10, "Rate": 28},
        {"Ref": "C-099", "Discipline": "Civil", "Description": "Unpriced", "Unit": "m³", "Quantity": 1},
    ])
    saved = rates.from_boq(lines)
    assert saved["Description"].tolist() == ["Excavation for foundations"]
    assert saved.loc[0, "Code"] == ""  # auto-generated refs are not stored as codes
    updated = rates.merge(saved, saved.assign(Rate=30.0))
    assert len(updated) == 1 and updated.loc[0, "Rate"] == 30.0


def test_upload_round_trip_through_excel():
    data = rates.to_excel(LIBRARY, "USD")
    table = pd.read_excel(io.BytesIO(data))
    mapping = rates.auto_map(table.columns)
    assert mapping["Code"] == "Code" and mapping["Rate"] == "Rate (USD)" and mapping["Discipline"] == "Discipline"
    assert rates.from_table(table, mapping)["Rate"].tolist() == LIBRARY["Rate"].tolist()


def test_template_has_no_rates():
    t = rates.template()
    assert len(t) == 30 and t["Rate"].isna().all()
