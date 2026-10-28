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
    guides: list[dict] | None = None,
    highlight: list[str] | None = None,
    command: dict | None = None,
    fill: bool = False,
    toolbar: bool = True,
    key: str | None = None,
):
    """Show a drawing to measure on.

    mode: "count", "line", "area", "calibrate", "select", "pick" (select similar), "ruler" or "ruler_area"
    (check dimensions, never sent back). Points are image pixels. guides: display-only outlines
    [{"points", "closed", "color", "dash"}] such as extended blinding and excavation edges.
    highlight: measurement ids to emphasise (the rest fade). command: {"name": "reset" | "extents" | "window" | "rotate",
    "nonce"} runs once per nonce. fill: grow to the bottom of the browser window instead of using height.
    toolbar: False hides the floating pan/zoom buttons when the app drives them with commands ("pan", "window", "zoom_in",
    "zoom_out", "extents", "all", "undo", "finish", "cancel").
    Returns the last event: {"event": "add" | "calibrate" | "select" | "delete" | "pick", "points" | "shape" | "point", "id"}.
    """
    return _component(
        image=image, image_key=image_key, mode=mode, shapes=shapes, m_per_px=m_per_px, color=color, item=item,
        snap=snap or [], snap_on=snap_on, selected=selected, height=height, guides=guides or [], highlight=highlight or [],
        command=command, fill=fill, toolbar=toolbar, key=key, default=None,
    )
