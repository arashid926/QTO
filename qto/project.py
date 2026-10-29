"""Projects: bundle everything a QS works on (details, BOQ, rate library, take-off) into one file."""

from __future__ import annotations

import base64
import json
import uuid
from datetime import datetime

import pandas as pd

from . import boq, measure, rates

FIELDS = {"p_name": "Project", "p_client": "Client", "p_location": "Location", "p_by": "Prepared by", "p_standard": "Measurement standard"}
CURRENCY_KEY = "p_currency"
FORMAT = "qto-studio-project"
# Screen state that belongs to the open project; cleared when another project is opened so nothing carries over.
VIEW_KEYS = ("mt_doc", "mt_active", "mt_building", "mt_level", "mt_loc", "canvas_cmd", "model_pick",
             "pending_doc", "pending_active", "pending_building", "pending_model")


def _pack(files: dict) -> dict:
    return {name: base64.b64encode(data).decode("ascii") for name, data in (files or {}).items()}


def _unpack(files: dict) -> dict:
    return {name: base64.b64decode(text) for name, text in (files or {}).items()}


def blank(name: str, client: str = "", location: str = "", prepared_by: str = "", currency: str = "USD",
          first_building: str = "Building 1", standard: str = "RICS NRM2") -> dict:
    takeoff = measure.new_state()
    takeoff["buildings"][0]["name"] = first_building.strip() or "Building 1"
    return {
        "format": FORMAT, "version": 2, "id": uuid.uuid4().hex,
        "info": {"p_name": name.strip() or "New Project", "p_client": client, "p_location": location, "p_by": prepared_by,
                 "p_standard": standard},
        "currency": currency, "boq": [], "rates": [],
        "takeoff": {k: takeoff[k] for k in measure.TAKEOFF_KEYS if k in takeoff},
        "files": {}, "models": {}, "hidden_layers": {},
    }


def snapshot(state) -> dict:
    """Everything belonging to the open project, as plain JSON-ready data: details, BOQ, rates, take-off,
    libraries, and its own drawings and 3D models (base64), so projects never share or mix data."""
    takeoff = state["mt"]
    if not state.get("p_id"):
        state["p_id"] = uuid.uuid4().hex
    return {
        "format": FORMAT, "version": 2, "id": state["p_id"], "saved": datetime.now().isoformat(timespec="seconds"),
        "info": {k: state.get(k, "") for k in FIELDS},
        "currency": state.get(CURRENCY_KEY, "USD"),
        "boq": state["boq"].to_dict("records"),
        "rates": state["rates"].to_dict("records"),
        "takeoff": {k: takeoff[k] for k in measure.TAKEOFF_KEYS if k in takeoff},
        "admin": state.get("admin", {}),
        "files": _pack(state.get("files")),
        "models": _pack(state.get("models")),
        "hidden_layers": state.get("hidden_layers", {}),
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
    from . import admin

    state["admin"] = admin.upgrade(data.get("admin"))
    seen = state["mt"]["seen"] if "mt" in state else []
    state["mt"] = measure.from_dict(data.get("takeoff") or {})
    state["mt"]["seen"] = seen  # the canvas still holds its last event; don't replay it in the new project
    state["p_id"] = data.get("id") or uuid.uuid4().hex
    state["files"] = _unpack(data.get("files"))
    state["models"] = _unpack(data.get("models"))
    state["hidden_layers"] = dict(data.get("hidden_layers") or {})
    for name in state["files"]:  # drawings saved before buildings owned drawings go to the first building
        measure.drawing_building(state["mt"], name)
    for key, value in (("details", {}), ("rate_report", None), ("legends", {}), ("mt_selected", None),
                       ("mt_calibration_pts", None), ("dim_hl_item", None)):
        state[key] = value
    for key in list(state.keys()):  # the previous project's selections, pages and open drawing
        if key in VIEW_KEYS or str(key).startswith("mt_pg_"):
            del state[key]
    for key in ("boq_ver", "rates_ver", "mt_ver", "layer_ver", "proj_ver"):
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
    files, doc_map = state.setdefault("files", {}), {}
    for name, raw in _unpack(data.get("files")).items():  # the other project's drawings come too; a clashing name is renamed
        new = name if name not in files or files[name] == raw else unique_file(name, files)
        files[new] = raw
        if new != name:
            doc_map[name] = new
    summary = measure.merge_takeoff(state["mt"], measure.from_dict(data.get("takeoff") or {}), doc_map)
    summary["boq_lines"] = len(lines)
    summary["drawings"] = len(data.get("files") or {})
    for key in ("boq_ver", "rates_ver", "mt_ver"):
        state[key] = state.get(key, 0) + 1
    return summary


def unique_name(name: str, taken) -> str:
    candidate, n = name, 2
    while candidate in taken:
        candidate, n = f"{name} ({n})", n + 1
    return candidate


def unique_file(name: str, taken) -> str:
    """'plan.pdf' → 'plan (2).pdf' when the name is already used."""
    stem, dot, ext = name.rpartition(".")
    if not dot:
        stem, ext = name, ""
    n = 2
    while (candidate := f"{stem} ({n}){dot}{ext}") in taken:
        n += 1
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
