"""3D take-off from mesh models (OBJ, STL, PLY, GLB, OFF): volumes, surface areas and sizes."""

from __future__ import annotations

import io

import pandas as pd

from . import disciplines as dz

try:
    import trimesh

    HAS_TRIMESH = True
except ImportError:  # optional dependency
    HAS_TRIMESH = False

MESH_TYPES = ["obj", "stl", "ply", "glb", "off"]
M = dz.MEASURE_COLUMNS


def takeoff(data: bytes, filename: str, scale_to_m: float = 1.0) -> pd.DataFrame:
    """One billable row per mesh object. Volumes are only reliable for watertight meshes."""
    ext = filename.rsplit(".", 1)[-1].lower()
    scene = trimesh.load(io.BytesIO(data), file_type=ext, force="scene")
    s = scale_to_m
    rows = []
    for node in scene.graph.nodes_geometry:
        transform, geometry_name = scene.graph[node]
        geometry = scene.geometry.get(geometry_name)
        if not isinstance(geometry, trimesh.Trimesh):
            continue
        mesh = geometry.copy()
        mesh.apply_transform(transform)
        watertight = bool(mesh.is_watertight)
        discipline, section = dz.classify(f"{node} {geometry_name}")
        rows.append({
            "Bill": True,
            "Discipline": discipline,
            "Work Section": section,
            "Measure": "Volume" if watertight else "Area",
            "Description": dz.pretty_name(node),
            "Object": node,
            "Faces": len(mesh.faces),
            "Watertight": watertight,
            M["Count"]: 1,
            M["Length"]: float(mesh.extents.max()) * s,
            M["Area"]: float(mesh.area) * s**2,
            M["Volume"]: abs(float(mesh.volume)) * s**3,
        })
    columns = ["Bill", "Discipline", "Work Section", "Measure", "Description", "Object", "Faces", "Watertight",
               M["Count"], M["Length"], M["Area"], M["Volume"]]
    return pd.DataFrame(rows, columns=columns)
