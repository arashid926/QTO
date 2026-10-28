"""Projects: bundle everything a QS works on (details, BOQ, rate library, take-off) into one file."""

from __future__ import annotations

import json
from datetime import datetime

import pandas as pd

from . import boq, measure, rates

FIELDS = {"p_name": "Project", "p_client": "Client", "p_location": "Location", "p_by": "Prepared by", "p_standard": "Measurement standard"}
CURRENCY_KEY = "p_currency"
FORMAT = "qto-studio-project"


def blank(name: str, client: str = "", location: str = "", prepared_by: str = "", currency: str = "USD",
          first_building: str = "Building 1", standard: str = "RICS NRM2") -> dict:
    takeoff = measure.new_state()
    takeoff["buildings"][0]["name"] = first_building.strip() or "Building 1"
    return {
        "format": FORMAT, "version": 1,
        "info": {"p_name": name.strip() or "New Project", "p_client": client, "p_location": location, "p_by": prepared_by,
                 "p_standard": standard},
        "currency": currency, "boq": [], "rates": [],
        "takeoff": {k: takeoff[k] for k in measure.TAKEOFF_KEYS if k in takeoff},
    }


def snapshot(state) -> dict:
    """Everything belonging to the open project, as plain JSON-ready data."""
    takeoff = state["mt"]
    return {
        "format": FORMAT, "version": 1, "saved": datetime.now().isoformat(timespec="seconds"),
        "info": {k: state.get(k, "") for k in FIELDS},
        "currency": state.get(CURRENCY_KEY, "USD"),
        "boq": state["boq"].to_dict("records"),
        "rates": state["rates"].to_dict("records"),
        "takeoff": {k: takeoff[k] for k in measure.TAKEOFF_KEYS if k in takeoff},
    }


def restore(state, data: dict) -> None:
    """Load a project into the app state. Must run before the project widgets are drawn."""
    if data.get("format") != FORMAT:
        raise ValueError("This is not a QTO Studio project file.")
    for key in FIELDS:
        state[key] = data.get("info", {}).get(key, "RICS NRM2" if key == "p_standard" else "")
    state[CURRENCY_KEY] = data.get("currency", "USD")
    lines = pd.DataFrame(data.get("boq") or [], columns=boq.COLUMNS)
    state["boq"] = boq.finalise(lines) if not lines.empty else boq.empty()
    library = pd.DataFrame(data.get("rates") or [], columns=rates.COLUMNS)
    state["rates"] = rates.tidy(library, drop_blank=False) if not library.empty else rates.empty()
    seen = state["mt"]["seen"] if "mt" in state else []
    state["mt"] = measure.from_dict(data.get("takeoff") or {})
    state["mt"]["seen"] = seen  # the canvas still holds its last event; don't replay it in the new project
    for key, value in (("details", {}), ("rate_report", None), ("legends", {}), ("mt_selected", None), ("mt_calibration_pts", None)):
        state[key] = value
    for key in ("boq_ver", "rates_ver", "mt_ver"):
        state[key] = state.get(key, 0) + 1


def merge(state, data: dict) -> dict:
    """Bring another project into the open one: BOQ lines appended, rate library merged, take-off appended."""
    if data.get("format") != FORMAT:
        raise ValueError("This is not a QTO Studio project file.")
    lines = pd.DataFrame(data.get("boq") or [], columns=boq.COLUMNS)
    if not lines.empty:
        state["boq"] = boq.finalise(pd.concat([state["boq"], lines], ignore_index=True))
    library = pd.DataFrame(data.get("rates") or [], columns=rates.COLUMNS)
    if not library.empty:
        state["rates"] = rates.merge(state["rates"], library)
    summary = measure.merge_takeoff(state["mt"], measure.from_dict(data.get("takeoff") or {}))
    summary["boq_lines"] = len(lines)
    for key in ("boq_ver", "rates_ver", "mt_ver"):
        state[key] = state.get(key, 0) + 1
    return summary


def unique_name(name: str, taken) -> str:
    candidate, n = name, 2
    while candidate in taken:
        candidate, n = f"{name} ({n})", n + 1
    return candidate


def renamed(data: dict, name: str) -> dict:
    copy = json.loads(json.dumps(data, default=str))
    copy["info"]["p_name"] = name
    return copy


def to_bytes(data: dict) -> bytes:
    return json.dumps(data, indent=1, default=str).encode("utf-8")


def from_bytes(raw: bytes) -> dict:
    data = json.loads(raw.decode("utf-8"))
    if data.get("format") != FORMAT:
        raise ValueError("This is not a QTO Studio project file (.qto.json).")
    return data


def file_name(data: dict) -> str:
    name = "".join(ch if ch.isalnum() else "_" for ch in data["info"].get("p_name", "project")).strip("_") or "project"
    return f"{name}.qto.json"
