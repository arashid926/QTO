"""Interactive measuring canvas (Streamlit custom component, plain HTML/JS, no build step)."""

from __future__ import annotations

from pathlib import Path

import streamlit.components.v1 as components

_component = components.declare_component("qto_canvas", path=str(Path(__file__).parent / "frontend"))


def measure_canvas(
    image: str,
    image_key: str,
    mode: str,
    shapes: list[dict],
    m_per_px: float | None,
    color: str = "#e11d48",
    item: str = "",
    snap: list[float] | None = None,
    snap_on: bool = True,
    selected: str | None = None,
    height: int = 720,
    key: str | None = None,
):
    """Show a drawing to measure on.

    mode: "count", "line", "area", "calibrate" or "select". Points are image pixels.
    Returns the last event: {"event": "add" | "calibrate" | "select" | "delete", "points" | "shape", "id"}.
    """
    return _component(
        image=image, image_key=image_key, mode=mode, shapes=shapes, m_per_px=m_per_px, color=color, item=item,
        snap=snap or [], snap_on=snap_on, selected=selected, height=height, key=key, default=None,
    )
