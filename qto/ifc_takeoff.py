"""3D BIM take-off from IFC models: IFC base quantities first, mesh geometry as a fallback."""

from __future__ import annotations

import os
import tempfile

import numpy as np
import pandas as pd

from . import disciplines as dz

try:
    import ifcopenshell
    import ifcopenshell.geom
    import ifcopenshell.util.element as ifc_element
    import ifcopenshell.util.unit as ifc_unit

    HAS_IFC = True
except ImportError:  # optional dependency
    HAS_IFC = False

QTO_KEYS = {
    "Length": ["Length", "NetLength", "GrossLength"],
    "Area": [
        "NetSideArea", "GrossSideArea", "NetFloorArea", "GrossFloorArea", "NetArea", "GrossArea",
        "NetSurfaceArea", "GrossSurfaceArea", "OuterSurfaceArea", "NetFootprintArea", "GrossFootprintArea", "Area",
    ],
    "Volume": ["NetVolume", "GrossVolume", "Volume"],
    "Weight": ["NetWeight", "GrossWeight", "Weight"],
}
GEOMETRY_LIMIT = 5000  # max elements measured from geometry, to keep large models responsive

M = dz.MEASURE_COLUMNS
COLUMNS = [
    "GlobalId", "IFC Class", "Name", "Type", "Storey", "Material", "Discipline", "Work Section",
    M["Count"], M["Length"], M["Area"], M["Volume"], M["Weight"], "Quantity source",
]


def open_model(data: bytes, filename: str):
    fd, tmp = tempfile.mkstemp(suffix=os.path.splitext(filename)[1] or ".ifc")
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
        return ifcopenshell.open(tmp)
    finally:
        try:
            os.unlink(tmp)
        except OSError:
            pass


def _unit_scales(model) -> tuple[float, float, float]:
    try:
        length = ifc_unit.calculate_unit_scale(model)
    except Exception:
        length = 1.0
    scales = []
    for unit_type, fallback in (("AREAUNIT", length**2), ("VOLUMEUNIT", length**3)):
        try:
            scales.append(ifc_unit.calculate_unit_scale(model, unit_type))
        except Exception:
            scales.append(fallback)
    return length, scales[0], scales[1]


def _pick(qtos: dict, keys: list[str]) -> float | None:
    for key in keys:
        for qto in qtos.values():
            value = qto.get(key)
            if isinstance(value, (int, float)) and value > 0:
                return float(value)
    return None


def _material_name(element) -> str:
    try:
        mat = ifc_element.get_material(element, should_skip_usage=True)
    except Exception:
        return ""
    if mat is None:
        return ""
    if mat.is_a("IfcMaterialList"):
        return ", ".join(m.Name or "" for m in mat.Materials)
    return getattr(mat, "Name", None) or getattr(mat, "LayerSetName", None) or ""


def _storey_name(element) -> str:
    try:
        container = ifc_element.get_container(element)
        if container is None and ifc_element.get_aggregate(element) is not None:
            container = ifc_element.get_container(ifc_element.get_aggregate(element))
        return (container.Name or "") if container else ""
    except Exception:
        return ""


def _type_name(element) -> str:
    try:
        element_type = ifc_element.get_type(element)
        return (element_type.Name or "") if element_type else ""
    except Exception:
        return ""


def _mesh_metrics(shape) -> tuple[float, float, float] | None:
    """Volume (m³), half surface area (m², ~side area of thin elements) and longest dimension (m)."""
    verts = np.asarray(shape.geometry.verts, dtype=float).reshape(-1, 3)
    faces = np.asarray(shape.geometry.faces, dtype=int).reshape(-1, 3)
    if len(faces) == 0:
        return None
    a, b, c = verts[faces[:, 0]], verts[faces[:, 1]], verts[faces[:, 2]]
    surface = 0.5 * np.linalg.norm(np.cross(b - a, c - a), axis=1).sum()
    volume = abs(np.einsum("ij,ij->i", a, np.cross(b, c)).sum()) / 6.0
    dims = verts.max(axis=0) - verts.min(axis=0)
    return float(volume), float(surface / 2.0), float(dims.max())


def takeoff(data: bytes, filename: str, geometry_fallback: bool = True) -> pd.DataFrame:
    """One row per building element with its classification and quantities in metres."""
    model = open_model(data, filename)
    length_scale, area_scale, volume_scale = _unit_scales(model)
    elements = [
        e for e in model.by_type("IfcElement")
        if not e.is_a("IfcFeatureElement") and not e.is_a("IfcVirtualElement")
    ] + list(model.by_type("IfcSpace"))
    settings = ifcopenshell.geom.settings() if geometry_fallback else None
    geometry_budget = GEOMETRY_LIMIT

    rows = []
    for el in elements:
        cls = el.is_a()
        name = el.Name or ""
        try:
            qtos = ifc_element.get_psets(el, qtos_only=True) or {}
        except Exception:
            qtos = {}
        values = {m: _pick(qtos, QTO_KEYS[m]) for m in QTO_KEYS}
        source = "IFC quantities" if any(v is not None for v in values.values()) else ""
        if values["Length"] is not None:
            values["Length"] *= length_scale
        if values["Area"] is not None:
            values["Area"] *= area_scale
        if values["Volume"] is not None:
            values["Volume"] *= volume_scale

        primary = dz.IFC_PRIMARY_MEASURE.get(cls, "Count")
        if (
            settings is not None and geometry_budget > 0 and primary in ("Length", "Area", "Volume")
            and values[primary] is None and getattr(el, "Representation", None) is not None
        ):
            geometry_budget -= 1
            try:
                metrics = _mesh_metrics(ifcopenshell.geom.create_shape(settings, el))
            except Exception:
                metrics = None
            if metrics:
                volume, side_area, longest = metrics
                values["Volume"] = values["Volume"] or volume
                values["Area"] = values["Area"] or side_area
                values["Length"] = values["Length"] or longest
                source = "Geometry (approx.)"

        discipline, section = dz.classify_ifc(cls, f"{name} {_type_name(el)}")
        rows.append({
            "GlobalId": el.GlobalId,
            "IFC Class": cls,
            "Name": name,
            "Type": _type_name(el),
            "Storey": _storey_name(el),
            "Material": _material_name(el),
            "Discipline": discipline,
            "Work Section": section,
            M["Count"]: 1,
            M["Length"]: values["Length"] or 0.0,
            M["Area"]: values["Area"] or 0.0,
            M["Volume"]: values["Volume"] or 0.0,
            M["Weight"]: values["Weight"] or 0.0,
            "Quantity source": source or "—",
        })
    return pd.DataFrame(rows, columns=COLUMNS)


def summarise(elements: pd.DataFrame) -> pd.DataFrame:
    """Group elements by classification, type and material into billable lines."""
    by = ["Discipline", "Work Section", "IFC Class", "Type", "Material"]
    measures = list(M.values())
    columns = ["Bill", "Discipline", "Work Section", "Measure", "Description", "IFC Class", "Type", "Material", *measures]
    if elements.empty:
        return pd.DataFrame(columns=columns)
    g = elements.fillna({c: "" for c in by}).groupby(by)[measures].sum().reset_index()

    def measure(r):
        primary = dz.IFC_PRIMARY_MEASURE.get(r["IFC Class"], "Count")
        if primary == "Count" or r[M[primary]] > 0:
            return primary
        return next((m for m in ("Volume", "Area", "Length") if r[M[m]] > 0), "Count")

    def describe(r):
        base = r["Type"] or dz.pretty_name(r["IFC Class"].removeprefix("Ifc"))
        return f"{base} — {r['Material']}" if r["Material"] else base

    g["Measure"] = g.apply(measure, axis=1)
    g["Description"] = g.apply(describe, axis=1)
    g["Bill"] = True
    return g[columns]
