"""QTO Studio — quantity take-off from 2D drawings, 3D models and schedules.

Run with:  streamlit run app.py
"""

from __future__ import annotations

import io

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st
from PIL import Image, ImageOps

from qto import __version__, boq, dxf_takeoff, ifc_takeoff, measure, mesh_takeoff, pdf_takeoff, rates, samples, schedules
from qto import disciplines as dz
from qto.canvas import measure_canvas

st.set_page_config(page_title="QTO Studio", page_icon="📐", layout="wide", initial_sidebar_state="expanded")

st.markdown(
    """
<style>
.block-container {padding-top: 1.4rem; padding-bottom: 3rem;}
.hero {background: linear-gradient(120deg, #0f172a 0%, #1e3a8a 55%, #0ea5e9 100%); color: #fff;
       padding: 1.5rem 2rem; border-radius: 18px; margin-bottom: 1.1rem; box-shadow: 0 10px 30px rgba(15,23,42,.22);}
.hero h1 {color: #fff; margin: 0; font-size: 2.1rem; letter-spacing: -.5px;}
.hero p {margin: .35rem 0 0; opacity: .88; font-size: 1.02rem;}
.chip {display: inline-block; background: rgba(255,255,255,.15); padding: .18rem .75rem; border-radius: 999px;
       margin: .7rem .35rem 0 0; font-size: .84rem;}
div[data-testid="stMetric"] {background: #fff; border: 1px solid #e2e8f0; border-radius: 14px; padding: .85rem 1rem;
                             box-shadow: 0 2px 8px rgba(15,23,42,.05);}
.card {background: #fff; border: 1px solid #e2e8f0; border-radius: 14px; padding: 1rem 1.2rem; height: 100%;
       box-shadow: 0 2px 8px rgba(15,23,42,.04);}
.card h4 {margin: .1rem 0 .35rem; color: #1e3a8a;}
.card p {margin: 0; color: #475569; font-size: .93rem;}
.stTabs [data-baseweb="tab-list"] {gap: .3rem;}
.stTabs [data-baseweb="tab"] {font-weight: 600; padding: .5rem 1rem; border-radius: 10px 10px 0 0;}
</style>
""",
    unsafe_allow_html=True,
)

M = dz.MEASURE_COLUMNS
CURRENCIES = ["USD", "AED", "SAR", "QAR", "OMR", "KWD", "BHD", "EUR", "GBP", "INR", "PKR", "EGP"]
BOLD = px.colors.qualitative.Bold
CHART_MARGIN = dict(t=40, l=0, r=0, b=0)
XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

ss = st.session_state
ss.setdefault("boq", boq.empty())
ss.setdefault("boq_ver", 0)
ss.setdefault("details", {})
ss.setdefault("rates", rates.empty())
ss.setdefault("rates_ver", 0)
ss.setdefault("rate_report", None)
ss.setdefault("legends", {})
ss.setdefault("mt", measure.new_state())
ss.setdefault("mt_selected", None)
ss.setdefault("mt_calibration_pts", None)
ss.setdefault("mt_ver", 0)


# ------------------------------------------------------------------ cached readers

@st.cache_data(show_spinner="Reading DXF drawing…", max_entries=8)
def cached_dxf(data: bytes, unit_override: float | None, explode: bool) -> dxf_takeoff.DxfResult:
    return dxf_takeoff.takeoff(data, unit_override, explode)


@st.cache_data(show_spinner=False, max_entries=8)
def cached_dxf_units(data: bytes) -> str:
    return dxf_takeoff.detect_units(dxf_takeoff.read_doc(data))[0]


@st.cache_data(show_spinner=False, max_entries=8)
def cached_pdf_pages(data: bytes) -> int:
    return pdf_takeoff.page_count(data)


@st.cache_data(show_spinner="Rendering page…", max_entries=16)
def cached_pdf_image(data: bytes, page: int, crop: tuple, highlight: tuple = ()):
    return pdf_takeoff.render_page(data, page, crop, highlight=highlight)


@st.cache_data(show_spinner="Preparing drawing for measuring…", max_entries=8)
def cached_measure_image(data: bytes, name: str, page: int, dpi: int) -> tuple[str, float, list[float]]:
    """(JPEG data URL, display pixels per drawing unit, flat snap-point list in display pixels)."""
    if name.lower().endswith(".pdf"):
        image, k = pdf_takeoff.render_for_measure(data, page, dpi)
        snap = [round(v * k, 1) for xy in pdf_takeoff.snap_points(data, page) for v in xy]
    else:
        image = Image.open(io.BytesIO(data))
        image = ImageOps.exif_transpose(image)
        k = min(1.0, 6000 / max(image.size))  # drawing units are the original image pixels
        if k < 1.0:
            image = image.resize((int(image.width * k), int(image.height * k)))
        snap = []
    return measure.image_data_url(image), k, snap


@st.cache_data(show_spinner="Measuring linework…", max_entries=16)
def cached_pdf_vectors(data: bytes, page: int, scale: float, crop: tuple) -> pd.DataFrame:
    return pdf_takeoff.measure_vectors(data, page, scale, crop)


@st.cache_data(show_spinner="Counting tags…", max_entries=16)
def cached_pdf_tags(data: bytes, tags: tuple[str, ...]) -> pd.DataFrame:
    return pdf_takeoff.count_tags(data, list(tags))


@st.cache_data(show_spinner="Looking for tables…", max_entries=16)
def cached_pdf_tables(data: bytes, page: int) -> list[pd.DataFrame]:
    return pdf_takeoff.extract_tables(data, page)


@st.cache_data(show_spinner="Reading IFC model — large models can take a minute…", max_entries=4)
def cached_ifc(data: bytes, name: str, fallback: bool) -> pd.DataFrame:
    return ifc_takeoff.takeoff(data, name, fallback)


@st.cache_data(show_spinner="Reading 3D mesh…", max_entries=4)
def cached_mesh(data: bytes, name: str, scale: float) -> pd.DataFrame:
    return mesh_takeoff.takeoff(data, name, scale)


@st.cache_data(show_spinner=False, max_entries=16)
def cached_schedule(data: bytes, name: str) -> dict[str, pd.DataFrame]:
    return schedules.read_schedule(data, name)


# ------------------------------------------------------------------ shared widgets

def add_to_boq(lines: pd.DataFrame, source: str, details: pd.DataFrame | None = None) -> None:
    """Add lines to the BOQ, replacing earlier lines from the same source(s) so re-adding never duplicates."""
    if lines.empty:
        st.warning("Nothing to add: tick at least one row with a quantity above zero.")
        return
    replaced = set(lines["Source"]) | {source}
    current = ss.boq[~ss.boq["Source"].isin(replaced)]
    ss.boq = boq.finalise(pd.concat([current, lines], ignore_index=True))
    ss.boq_ver += 1
    if details is not None:
        ss.details[source] = details
    st.toast(f"Added {len(lines)} items from {source}", icon="✅")


def measured_editor(table: pd.DataFrame, key: str, info_columns: list[str]) -> pd.DataFrame:
    """Editable take-off table: tick rows, set discipline / section / what to measure."""
    measures = [c for c in M.values() if c in table.columns]
    config = {
        "Bill": st.column_config.CheckboxColumn("Bill", help="Include this row in the BOQ", width="small"),
        "Discipline": st.column_config.SelectboxColumn(options=dz.DISCIPLINES, required=True),
        "Work Section": st.column_config.SelectboxColumn("Work section (NRM2)", options=dz.NRM2_SECTIONS, required=True, width="medium"),
        "Measure": st.column_config.SelectboxColumn(options=[m for m, c in M.items() if c in measures], required=True, width="small",
                                                     help="Which quantity goes to the BOQ"),
        "Description": st.column_config.TextColumn("BOQ description", width="medium"),
        "Factor": st.column_config.NumberColumn("× Factor", min_value=0.0, step=0.05, format="%.2f", width="small",
                                                help="Multiplier, e.g. 0.5 when walls are drawn as two parallel lines"),
        dz.DIM_COLUMN: st.column_config.NumberColumn(min_value=0.0, step=0.05, format="%.2f", width="small",
                                                     help="Second dimension: wall height turns m into m², slab thickness turns m² into m³"),
    }
    for column in measures:
        config[column] = st.column_config.NumberColumn(format="%.0f" if column == M["Count"] else "%.2f")
    extras = [c for c in ("Factor", dz.DIM_COLUMN) if c in table.columns]
    view = table[["Bill", "Discipline", "Work Section", "Measure", "Description", *extras, *info_columns, *measures]]
    return st.data_editor(view, column_config=config, disabled=[*info_columns, *measures], hide_index=True, key=key)


def schedule_mapper(table: pd.DataFrame, key: str, discipline: str, source: str) -> None:
    """Map a schedule's columns to BOQ fields, preview the result and add it."""
    if table.empty:
        st.warning("This sheet is empty.")
        return
    auto = schedules.auto_map(table.columns)
    options = ["—", *table.columns]
    st.markdown("**Column mapping** — detected automatically, change if needed")
    mapping = {}
    for col, field in zip(st.columns(len(schedules.FIELDS)), schedules.FIELDS):
        default = options.index(auto[field]) if auto[field] in options else 0
        choice = col.selectbox(field, options, index=default, key=f"{key}_map_{field}")
        mapping[field] = None if choice == "—" else choice
    c1, c2 = st.columns(2)
    section = c1.selectbox("Work section when not in the file", ["Auto-detect from description", *dz.NRM2_SECTIONS[1:]], key=f"{key}_sec")
    unit = c2.selectbox("Unit when not in the file", dz.UNITS, key=f"{key}_unit")
    if not mapping["Description"] or not mapping["Quantity"]:
        st.info("Map at least the Description and Quantity columns.")
        return
    lines = schedules.normalise(table, mapping, discipline, source, None if section.startswith("Auto") else section, unit)
    st.caption(f"{len(lines)} billable rows found (rows without a quantity are skipped).")
    st.dataframe(lines[["Ref", "Work Section", "Description", "Unit", "Quantity", "Rate"]], hide_index=True, height=260)
    if st.button(f"➕ Add {len(lines)} rows to BOQ", key=f"{key}_add", type="primary", disabled=lines.empty):
        add_to_boq(boq.finalise(lines, sort=False), source, table)


def dxf_figure(result: dxf_takeoff.DxfResult) -> go.Figure:
    fig = go.Figure()
    palette = BOLD + px.colors.qualitative.Safe + px.colors.qualitative.Vivid
    for i, (layer, xs, ys) in enumerate(result.preview):
        fig.add_trace(go.Scattergl(x=xs, y=ys, mode="lines", name=layer, line=dict(width=1.3, color=palette[i % len(palette)])))
    for block, group in result.markers.groupby("Block"):
        fig.add_trace(go.Scattergl(x=group["X"], y=group["Y"], mode="markers", name=f"◼ {block}", marker=dict(size=8, symbol="square")))
    fig.update_layout(
        height=540, margin=dict(l=0, r=0, t=10, b=0), plot_bgcolor="#ffffff", paper_bgcolor="rgba(0,0,0,0)",
        xaxis=dict(showgrid=False, zeroline=False, title="m"),
        yaxis=dict(scaleanchor="x", scaleratio=1, showgrid=False, zeroline=False, title="m"),
        legend=dict(title="Layers / blocks"),
    )
    return fig


# ------------------------------------------------------------------ page sections

def render_dxf(name: str, data: bytes) -> None:
    detected = cached_dxf_units(data)
    o1, o2, _ = st.columns([1, 1, 2])
    unit_label = o1.selectbox("Drawing units", [f"Auto — {detected}", *dxf_takeoff.UNIT_CHOICES], key=f"u_{name}")
    explode = o2.toggle("Measure inside blocks", False, key=f"x_{name}", help="Also measure the lines that make up block references")
    override = None if unit_label.startswith("Auto") else dxf_takeoff.UNIT_CHOICES[unit_label]
    try:
        res = cached_dxf(data, override, explode)
    except Exception as exc:  # a malformed file should not take the app down
        st.error(f"Could not read this DXF: {exc}")
        return
    if "assumed" in res.units_label:
        st.warning("The drawing has no units set, so millimetres are assumed. Pick the correct units above if lengths look wrong.")

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Layers", len(res.layers))
    m2.metric("Measured objects", f"{res.entity_count:,}")
    m3.metric("Total line length", f"{res.layers[M['Length']].sum():,.1f} m")
    m4.metric("Block references", f"{len(res.markers):,}")
    st.plotly_chart(dxf_figure(res), key=f"fig_{name}")

    st.markdown("#### Layers")
    st.caption("Each layer is measured for length, closed area and count. Choose what to bill in **Measure**.")
    layers = measured_editor(res.layers, f"lay_{name}_{override}_{explode}", ["Layer", "Closed shapes", "Blocks"])
    st.markdown("#### Blocks (symbols)")
    if res.blocks.empty:
        blocks = res.blocks
        st.caption("No block references in this drawing.")
    else:
        blocks = measured_editor(res.blocks, f"blk_{name}_{override}_{explode}", ["Block", "Layers"])

    with st.expander("🔖 Count text tags (e.g. door marks D1, window marks W1)"):
        tags = st.text_input("Tags, comma separated", "D1, W1", key=f"tags_{name}")
        st.dataframe(dxf_takeoff.count_tags(res.texts, tags.split(",")), hide_index=True)

    if st.button("➕ Add ticked layers and blocks to BOQ", type="primary", key=f"add_{name}"):
        parts = [boq.from_measured(layers, f"{name} · layers")]
        if not blocks.empty:
            parts.append(boq.from_measured(blocks, f"{name} · blocks"))
            ss.details[f"{name} · blocks"] = res.blocks
        add_to_boq(pd.concat(parts, ignore_index=True), f"{name} · layers", res.layers)


def render_pdf(name: str, data: bytes) -> None:
    try:
        pages = cached_pdf_pages(data)
    except Exception as exc:
        st.error(f"Could not read this PDF: {exc}")
        return
    c1, c2, c3 = st.columns(3)
    page = int(c1.number_input("Page", 1, pages, 1, key=f"pg_{name}")) - 1
    scale = float(c2.number_input("Drawing scale  1 :", 1.0, 100000.0, 100.0, step=10.0, key=f"sc_{name}",
                                  help="Scale at the PDF's own paper size, e.g. 100 for 1:100 on A1"))
    c3.caption("Measured region (exclude title block / legend)")
    xr = c3.slider("Horizontal %", 0, 100, (0, 100), key=f"xr_{name}")
    yr = c3.slider("Vertical %", 0, 100, (0, 100), key=f"yr_{name}")
    crop = (xr[0] / 100, yr[0] / 100, xr[1] / 100, yr[1] / 100)

    legend_key = f"{name}|{page}"
    with st.expander("🗺️ Read the legend — name linework from the drawing's own key", expanded=legend_key in ss.legends):
        st.caption("Set the box around the legend (key) on this sheet. Each swatch is paired with the text beside it, "
                   "then linework of the same colour takes that name and is classified automatically.")
        l1, l2, l3 = st.columns([2, 2, 1])
        lx = l1.slider("Legend horizontal %", 0, 100, (70, 100), key=f"lx_{name}")
        ly = l2.slider("Legend vertical %", 0, 100, (0, 60), key=f"ly_{name}")
        l3.write("")
        if l3.button("🔎 Read legend", key=f"rl_{name}_{page}"):
            region = (lx[0] / 100, ly[0] / 100, lx[1] / 100, ly[1] / 100)
            ss.legends[legend_key] = pdf_takeoff.read_legend(data, page, region)
        if legend_key in ss.legends:
            legend = ss.legends[legend_key]
            if legend.empty:
                st.warning("No legend entries found in that box. Move the box over the swatches and their labels.")
            else:
                ss.legends[legend_key] = st.data_editor(legend, hide_index=True, key=f"lg_{legend_key}",
                                                        column_config={"Colour": st.column_config.TextColumn(disabled=True)})
                if st.button("✖ Stop using legend", key=f"lgx_{legend_key}"):
                    del ss.legends[legend_key]
                    st.rerun()

    vectors = cached_pdf_vectors(data, page, scale, crop)
    legend = ss.legends.get(legend_key)
    if legend is not None and not legend.empty and not vectors.empty:
        vectors = pdf_takeoff.apply_legend(vectors, legend)
    view_col, table_col = st.columns([3, 2])
    ticked: tuple = ()
    with table_col:
        st.markdown("#### Linework by colour and weight")
        if vectors.empty:
            st.warning("No vector linework found. This page is probably a scanned image — measure it in the "
                       "**✏️ On-screen Take-off** tab instead.")
        else:
            st.caption("Ticked groups are drawn in **magenta** on the drawing so you can see what is measured. "
                       "Use × Factor 0.5 for double-line walls and × Height/Thk to get wall areas or concrete volumes.")
            legend_tag = "" if legend is None else str(hash(tuple(legend["Label"])))
            edited = measured_editor(vectors, f"pdfv_{name}_{page}_{scale}_{crop}_{legend_tag}", ["Colour", "Line width"])
            ticked = tuple((c, w) for c, w, b in zip(edited["Colour"], edited["Line width"], edited["Bill"]) if b)
            if st.button("➕ Add ticked linework to BOQ", type="primary", key=f"addpdf_{name}"):
                add_to_boq(boq.from_measured(edited, f"{name} · p{page + 1}"), f"{name} · p{page + 1}", vectors)
    view_col.image(cached_pdf_image(data, page, crop, ticked),
                   caption=f"{name} — page {page + 1} · magenta = ticked linework · red box = measured region")

    t1, t2 = st.columns(2)
    with t1.expander("🔖 Count tags across all pages"):
        tags = st.text_input("Tags, comma separated", "D1, D2, W1, W2", key=f"ptags_{name}")
        st.dataframe(cached_pdf_tags(data, tuple(t.strip() for t in tags.split(",") if t.strip())), hide_index=True)
    with t2.expander("📋 Extract schedule tables from this page"):
        tables = cached_pdf_tables(data, page)
        if not tables:
            st.caption("No tables detected on this page.")
        for i, table in enumerate(tables):
            st.markdown(f"**Table {i + 1}**")
            disc = st.selectbox("Discipline", dz.DISCIPLINES, key=f"tdisc_{name}_{page}_{i}")
            schedule_mapper(table, f"pdft_{name}_{page}_{i}", disc, f"{name} · p{page + 1} table {i + 1}")


TOOLS = ["✏️ Measure", "🖐 Select / pan", "📏 Calibrate"]


def send_takeoff_to_boq() -> None:
    """Replace the on-screen QTO lines in the BOQ, keeping any rates already entered for them."""
    lines = measure.boq_lines(ss.mt)
    if lines.empty:
        st.warning("No measured quantities yet. Set the scale and measure at least one item.")
        return
    previous = ss.boq[ss.boq["Source"] == measure.SOURCE].set_index("Ref")["Rate"]
    lines["Rate"] = lines["Ref"].map(previous).fillna(0.0)
    add_to_boq(lines, measure.SOURCE)


def render_takeoff(sources: dict[str, bytes]) -> None:
    mt = ss.mt
    if not sources:
        st.info("Upload a PDF drawing or a scanned plan image (PNG/JPG) above, or upload PDFs in the 📏 2D Drawings tab.")
        return

    top = st.columns([3, 1, 1, 1])
    doc = top[0].selectbox("Drawing", list(sources), key="mt_doc")
    data = sources[doc]
    is_pdf = doc.lower().endswith(".pdf")
    pages = cached_pdf_pages(data) if is_pdf else 1
    page = int(top[1].number_input("Page", 1, pages, 1, key=f"mt_pg_{doc}")) - 1
    detail = top[2].selectbox("Detail", ["Standard", "Fine", "Draft"], key="mt_dpi", disabled=not is_pdf,
                              help="Fine renders sharper text for small details but loads slower")
    snap_on = top[3].toggle("Snap to drawing", True, key="mt_snap", disabled=not is_pdf,
                            help="Clicks jump to the nearest line end or corner of the CAD drawing")
    image_url, k, snap = cached_measure_image(data, doc, page, {"Standard": 110, "Fine": 160, "Draft": 72}[detail])
    pkey = measure.page_key(doc, page)
    mpu = mt["calibration"].get(pkey)

    canvas_col, side = st.columns([3, 1])
    with side:
        st.markdown("##### 1 · Scale")
        if mpu:
            shown = f"1 : {mpu / measure.PT_TO_M:,.0f}" if is_pdf else f"{mpu * 1000:.2f} mm per pixel"
            st.success(f"Scale set — {shown}")
        else:
            st.warning("Set the scale before measuring lengths and areas. Counts work without it.")
        if is_pdf:
            s1, s2 = st.columns([3, 2])
            ratio = s1.number_input("Drawing scale 1 :", 1.0, 100000.0, 100.0, step=10.0, key=f"mt_ratio_{pkey}",
                                    help="Only valid if the PDF is at its original paper size. Calibrating is safer.")
            s2.write("")
            if s2.button("Apply", key=f"mt_ratio_apply_{pkey}"):
                mt["calibration"][pkey] = measure.metres_per_unit_from_scale(ratio)
                st.rerun()
        if ss.mt_calibration_pts:
            known = st.number_input("Real length of the line you clicked (m)", 0.001, 100000.0, 5.0, step=0.1, key="mt_known")
            c1, c2 = st.columns(2)
            if c1.button("✔ Set scale", type="primary", key="mt_cal_ok"):
                mt["calibration"][pkey] = measure.calibrate(ss.mt_calibration_pts, known)
                ss.mt_calibration_pts = None
                st.rerun()
            if c2.button("Cancel", key="mt_cal_cancel"):
                ss.mt_calibration_pts = None
                st.rerun()
        else:
            st.caption("Or choose **📏 Calibrate** below and click both ends of a known dimension.")

        st.markdown("##### 2 · Take-off item")
        with st.expander("➕ New item", expanded=not mt["items"]):
            preset = st.selectbox("Start from", list(measure.PRESETS), key="mt_preset")
            p_desc, p_disc, p_sec, p_kind, p_w, p_d = measure.PRESETS[preset]
            with st.form("mt_new_item"):
                desc = st.text_input("Description", p_desc)
                kind = st.selectbox("Measure by", measure.TYPES, index=measure.TYPES.index(p_kind))
                disc = st.selectbox("Discipline", dz.DISCIPLINES, index=dz.DISCIPLINES.index(p_disc))
                sec = st.selectbox("Work section (NRM2)", dz.NRM2_SECTIONS, index=dz.NRM2_SECTIONS.index(p_sec))
                w = st.number_input("Width / height (m)", 0.0, 1000.0, p_w, step=0.05,
                                    help="Lengths only: wall height → m², footing width (+ depth) → m³")
                d = st.number_input("Depth / thickness (m)", 0.0, 1000.0, p_d, step=0.05,
                                    help="Area × thickness → m³ (slabs, excavation); length × width × depth → m³")
                if st.form_submit_button("Create item", type="primary"):
                    item = measure.add_item(mt, desc, disc, sec, kind, w, d)
                    ss.mt_active = item["id"]
                    ss.mt_ver += 1
                    st.rerun()
        ids = [i["id"] for i in mt["items"]]
        if ss.get("mt_active") not in ids:
            ss.mt_active = ids[-1] if ids else None
        active = None
        if ids:
            def label(i):
                it = measure.item_by_id(mt, i)
                return f"{it['ref']} · {it['description']} ({measure.item_unit(it['type'], it['width'], it['depth'])})"
            active = measure.item_by_id(mt, st.selectbox("Measuring", ids, format_func=label, key="mt_active"))

        st.markdown("##### 3 · Tool")
        tool = st.radio("Tool", TOOLS, key="mt_tool", label_visibility="collapsed")
        n1, n2 = st.columns(2)
        timesing = n1.number_input("Timesing ×", 0.01, 1000.0, 1.0, step=1.0, key="mt_times",
                                   help="Applied to the next measurements, e.g. 4 for four identical floors")
        n2.write("")
        deduct = n2.toggle("Deduction", False, key="mt_deduct", help="Next measurements are subtracted, e.g. door and window openings")
        location = st.text_input("Location / note", "", key="mt_loc", placeholder="e.g. Ground floor, Grid A–C")

    if tool == TOOLS[2]:
        mode = "calibrate"
    elif tool == TOOLS[0] and active:
        mode = measure.CANVAS_MODE[active["type"]]
    else:
        mode = "select"

    page_shapes = [s for s in mt["shapes"] if s["doc"] == doc and s["page"] == page]
    canvas_shapes = []
    for s in page_shapes:
        it = measure.item_by_id(mt, s["item_id"])
        if it:
            canvas_shapes.append({
                "id": s["id"], "type": measure.CANVAS_MODE[it["type"]], "color": it["colour"], "deduct": s.get("deduct", False),
                "label": it["ref"] + (" (−)" if s.get("deduct") else ""), "points": [[x * k, y * k] for x, y in s["points"]],
            })

    with canvas_col:
        if tool == TOOLS[0] and not active:
            st.info("Create a take-off item on the right first (e.g. *Blockwork wall*), then measure it on the drawing.")
        event = measure_canvas(
            image=image_url, image_key=f"{doc}|{page}|{detail}", mode=mode, shapes=canvas_shapes,
            m_per_px=(mpu / k) if mpu else None, color=active["colour"] if active else "#e11d48",
            item=f"{active['ref']} {active['description']}" if active and mode != "calibrate" else "",
            snap=snap, snap_on=snap_on, selected=ss.mt_selected, height=720, key="mt_canvas",
        )

    if event and event.get("id") not in mt["seen"]:
        mt["seen"].append(event["id"])
        points = [[x / k, y / k] for x, y in event.get("points", [])]
        if event["event"] == "add" and active:
            shape = measure.add_shape(mt, active["id"], doc, page, points)
            shape.update({"timesing": float(timesing), "deduct": bool(deduct), "location": location})
            ss.mt_selected = shape["id"]
        elif event["event"] == "calibrate":
            ss.mt_calibration_pts = points
        elif event["event"] == "select":
            ss.mt_selected = event["shape"]
        elif event["event"] == "delete":
            mt["shapes"] = [s for s in mt["shapes"] if s["id"] != event["shape"]]
            ss.mt_selected = None
        ss.mt_ver += 1
        st.rerun()

    with side:
        shape = next((s for s in mt["shapes"] if s["id"] == ss.mt_selected), None)
        if shape:
            it = measure.item_by_id(mt, shape["item_id"])
            qty = measure.quantity(shape, it, mt["calibration"].get(measure.page_key(shape["doc"], shape["page"])))
            unit = measure.item_unit(it["type"], it["width"], it["depth"])
            st.markdown("##### Selected")
            st.markdown(f"**{it['ref']}** · {it['description']}  \n"
                        f"{'—' if qty is None else f'{qty:,.3f} {unit}'} · ×{shape['timesing']:g}"
                        f"{' · deduction' if shape.get('deduct') else ''}")
            if st.button("🗑️ Delete measurement", key=f"mt_del_{shape['id']}"):
                mt["shapes"] = [s for s in mt["shapes"] if s["id"] != shape["id"]]
                ss.mt_selected = None
                ss.mt_ver += 1
                st.rerun()

    st.markdown("#### 🧾 Take-off items")
    if mt["items"]:
        sheet = measure.qto_sheet(mt)
        rows = []
        for it in mt["items"]:
            part = sheet[sheet["BOQ Ref"] == it["ref"]]
            rows.append({
                "Ref": it["ref"], "Description": it["description"], "Discipline": it["discipline"], "Work Section": it["section"],
                "Type": it["type"], "Width/Height (m)": it["width"], "Depth/Thk (m)": it["depth"],
                "Measurements": len(part), "Quantity": round(float(part["Quantity"].dropna().sum()), 3),
                "Unit": measure.item_unit(it["type"], it["width"], it["depth"]),
            })
        edited_items = st.data_editor(
            pd.DataFrame(rows), key=f"mt_items_{ss.mt_ver}", hide_index=True, num_rows="dynamic",
            disabled=["Ref", "Type", "Measurements", "Quantity", "Unit"],
            column_config={
                "Discipline": st.column_config.SelectboxColumn(options=dz.DISCIPLINES, required=True),
                "Work Section": st.column_config.SelectboxColumn(options=dz.NRM2_SECTIONS, required=True, width="medium"),
                "Description": st.column_config.TextColumn(width="large"),
                "Width/Height (m)": st.column_config.NumberColumn(min_value=0.0, step=0.05, format="%.3f"),
                "Depth/Thk (m)": st.column_config.NumberColumn(min_value=0.0, step=0.05, format="%.3f"),
                "Quantity": st.column_config.NumberColumn(format="%.3f"),
            },
        )
        changed = False
        by_ref = {i["ref"]: i for i in mt["items"]}
        kept = {by_ref[r]["id"] for r in edited_items["Ref"].dropna() if r in by_ref}
        if len(kept) != len(mt["items"]):
            mt["items"] = [i for i in mt["items"] if i["id"] in kept]
            mt["shapes"] = [s for s in mt["shapes"] if s["item_id"] in kept]
            changed = True
        for _, r in edited_items.iterrows():
            it = by_ref.get(r["Ref"])
            if it is None or it["id"] not in kept:
                continue
            new = {
                "description": str(r["Description"] or it["description"]), "discipline": r["Discipline"] or it["discipline"],
                "section": r["Work Section"] or it["section"],
                "width": float(r["Width/Height (m)"] or 0) if it["type"] == "Length" else 0.0,
                "depth": float(r["Depth/Thk (m)"] or 0) if it["type"] != "Count" else 0.0,
            }
            if any(it[f] != v for f, v in new.items()):
                it.update(new)
                changed = True
        if changed:
            ss.mt_ver += 1
            st.rerun()
    else:
        st.caption("No take-off items yet.")

    st.markdown("#### 📋 QTO dimension sheet")
    st.caption("Every measurement as on a QS dimension sheet. Edit timesing, deduction or location here; "
               "delete a row to remove the measurement. Quantity = timesing × measured × width/height × depth/thickness.")
    sheet = measure.qto_sheet(mt)
    if sheet.empty:
        st.caption("Nothing measured yet.")
    else:
        # The measurement id rides along as the (hidden) index, so edits and deleted rows map back to shapes.
        edited_sheet = st.data_editor(
            sheet.set_index("Shape"), key=f"mt_sheet_{ss.mt_ver}", hide_index=True, num_rows="dynamic",
            disabled=[c for c in sheet.columns if c not in ("Timesing", "Deduct", "Location", "Shape")],
            column_config={
                "Timesing": st.column_config.NumberColumn(min_value=0.01, step=1.0, format="%g"),
                "Deduct": st.column_config.CheckboxColumn(),
                "Measured": st.column_config.NumberColumn(format="%.3f"),
                "Quantity": st.column_config.NumberColumn(format="%.3f"),
            },
        )
        if measure.update_from_sheet(mt, edited_sheet.rename_axis("Shape").reset_index()):
            ss.mt_ver += 1
            st.rerun()
        if sheet["Quantity"].isna().any():
            st.warning("Some lengths/areas have no quantity because their drawing page has no scale yet.")

    b1, b2, b3, b4 = st.columns(4)
    if b1.button("📤 Send take-off to BOQ", type="primary", disabled=sheet.empty):
        send_takeoff_to_boq()
    lines = measure.boq_lines(mt)
    b2.download_button("⬇️ QTO + BOQ workbook", boq.to_excel(lines, {k_: v for k_, v in project.items() if v}, currency, qto=sheet),
                       file_name="QTO_dimension_sheet.xlsx", mime=XLSX_MIME, disabled=lines.empty,
                       help="Dimension sheet with formulas, linked to a BOQ for these items")
    b3.download_button("💾 Save take-off", measure.to_json(mt), file_name="takeoff.qto.json", mime="application/json",
                       disabled=not mt["items"], help="Keep your measurements; open the file again later to continue")
    with b4.popover("📂 Open take-off"):
        saved = st.file_uploader("Saved take-off (.json)", type=["json"], key="mt_open")
        if saved is not None and st.button("Load (replaces current take-off)", key="mt_open_go"):
            try:
                loaded = measure.from_json(saved.getvalue())
                loaded["seen"] = mt["seen"]  # the canvas still holds its last event; don't replay it
                ss.mt = loaded
                ss.mt_selected = None
                ss.mt_ver += 1
                st.rerun()
            except (ValueError, KeyError) as exc:
                st.error(f"Could not open this file: {exc}")


def render_ifc(name: str, data: bytes) -> None:
    if not ifc_takeoff.HAS_IFC:
        st.error("IFC support needs the `ifcopenshell` package:  pip install ifcopenshell")
        return
    fallback = st.toggle("Measure from geometry when the model has no quantities", True, key=f"fb_{name}")
    try:
        elements = cached_ifc(data, name, fallback)
    except Exception as exc:
        st.error(f"Could not read this IFC model: {exc}")
        return
    if elements.empty:
        st.warning("No building elements found in this model.")
        return

    f1, f2 = st.columns(2)
    storeys = sorted(elements["Storey"].unique())
    pick_storeys = f1.multiselect("Storeys", storeys, default=storeys, key=f"st_{name}")
    discs = sorted(elements["Discipline"].unique(), key=lambda d: dz.DISCIPLINES.index(d) if d in dz.DISCIPLINES else 99)
    pick_discs = f2.multiselect("Disciplines", discs, default=discs, key=f"di_{name}")
    chosen = elements[elements["Storey"].isin(pick_storeys) & elements["Discipline"].isin(pick_discs)]

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Elements", f"{len(chosen):,}")
    m2.metric("Element classes", chosen["IFC Class"].nunique())
    m3.metric("Total volume", f"{chosen[M['Volume']].sum():,.2f} m³")
    m4.metric("From IFC quantities", f"{(chosen['Quantity source'] == 'IFC quantities').mean() * 100:.0f}%" if len(chosen) else "—")

    g1, g2 = st.columns(2)
    by_class = chosen.groupby(["IFC Class", "Discipline"]).size().reset_index(name="Elements").sort_values("Elements")
    g1.plotly_chart(px.bar(by_class, x="Elements", y="IFC Class", color="Discipline", orientation="h", title="Elements by class",
                           color_discrete_sequence=BOLD).update_layout(height=420, margin=CHART_MARGIN), key=f"cls_{name}")
    by_storey = chosen.groupby(["Storey", "Discipline"])[M["Volume"]].sum().reset_index()
    g2.plotly_chart(px.bar(by_storey, x="Storey", y=M["Volume"], color="Discipline", title="Volume by storey (m³)",
                           color_discrete_sequence=BOLD).update_layout(height=420, margin=CHART_MARGIN), key=f"sto_{name}")

    st.markdown("#### Take-off by element type")
    st.caption("Grouped by discipline, class, type and material. Walls default to area, concrete to volume, "
               "MEP runs to length, doors and fittings to count.")
    edited = measured_editor(ifc_takeoff.summarise(chosen), f"ifc_{name}_{fallback}_{len(chosen)}", ["IFC Class", "Type", "Material"])
    if st.button("➕ Add ticked element types to BOQ", type="primary", key=f"addifc_{name}"):
        add_to_boq(boq.from_measured(edited, name), name, chosen)
    with st.expander("🔍 All elements"):
        st.dataframe(chosen, hide_index=True)


def render_mesh(name: str, data: bytes) -> None:
    if not mesh_takeoff.HAS_TRIMESH:
        st.error("Mesh support needs the `trimesh` package:  pip install trimesh")
        return
    unit = st.selectbox("Model units", list(dxf_takeoff.UNIT_CHOICES), index=2, key=f"mu_{name}")
    try:
        objects = cached_mesh(data, name, dxf_takeoff.UNIT_CHOICES[unit])
    except Exception as exc:
        st.error(f"Could not read this model: {exc}")
        return
    if objects.empty:
        st.warning("No mesh objects found in this file.")
        return
    m1, m2, m3 = st.columns(3)
    m1.metric("Objects", len(objects))
    m2.metric("Watertight", int(objects["Watertight"].sum()))
    m3.metric("Total volume", f"{objects[M['Volume']].sum():,.2f} m³")
    if not objects["Watertight"].all():
        st.warning("Some objects are not closed (watertight), so their volume is unreliable — they default to surface area.")
    edited = measured_editor(objects, f"mesh_{name}_{unit}", ["Object", "Faces", "Watertight"])
    if st.button("➕ Add ticked objects to BOQ", type="primary", key=f"addmesh_{name}"):
        add_to_boq(boq.from_measured(edited, name), name, objects)


# ------------------------------------------------------------------ sidebar

with st.sidebar:
    st.markdown("## 📐 QTO Studio")
    st.caption(f"Version {__version__} · RICS NRM2 work sections")
    st.markdown("### Project")
    project = {
        "Project": st.text_input("Project name", "New Project"),
        "Client": st.text_input("Client", ""),
        "Location": st.text_input("Location", ""),
        "Prepared by": st.text_input("Prepared by", ""),
    }
    currency = st.selectbox("Currency", CURRENCIES)
    st.divider()
    if st.button("🗑️ Clear BOQ", disabled=ss.boq.empty):
        ss.boq, ss.details, ss.rate_report = boq.empty(), {}, None
        ss.boq_ver += 1
        st.rerun()
    with st.expander("Supported files"):
        st.markdown(
            "- **2D:** DXF (any version), vector PDF\n"
            "- **3D:** IFC 2x3 / IFC4 (BIM), OBJ, STL, PLY, GLB, OFF\n"
            "- **Schedules:** Excel (xlsx/xls), CSV\n\n"
            "**DWG?** Save as DXF from AutoCAD/BricsCAD, or convert with the free *ODA File Converter*.\n\n"
            "**Revit / Tekla / ArchiCAD / Civil 3D?** Export to IFC."
        )

st.markdown(
    f"""
<div class="hero">
  <h1>📐 QTO Studio</h1>
  <p>Quantity take-off from 2D drawings, 3D BIM models and schedules — straight into a priced Bill of Quantities.</p>
  {''.join(f'<span class="chip">{dz.DISCIPLINE_ICONS[d]} {d}</span>' for d in dz.DISCIPLINES)}
</div>
""",
    unsafe_allow_html=True,
)

tab_home, tab_2d, tab_measure, tab_3d, tab_sched, tab_rates, tab_boq = st.tabs(
    ["🏠 Dashboard", "📏 2D Drawings", "✏️ On-screen Take-off", "🧊 3D Models", "📋 Schedules", "💰 Rate Library", "📑 BOQ & Export"]
)

# ------------------------------------------------------------------ dashboard

with tab_home:
    data = ss.boq
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("BOQ items", f"{len(data):,}")
    c2.metric("Disciplines", data["Discipline"].nunique())
    c3.metric("Sources", data["Source"].nunique())
    c4.metric(f"Total ({currency})", f"{float(data['Amount'].sum()):,.2f}")

    if data.empty:
        st.markdown("#### How it works")
        steps = [
            ("1 · Upload", "Drop in DXF or PDF drawings, IFC or mesh models, and Excel/CSV schedules for each discipline."),
            ("2 · Review", "Quantities are measured by layer, block, element type or colour. Tick what to bill and pick the NRM2 section."),
            ("3 · Price", "Upload your rate library and apply it to the BOQ, or type rates in. Amounts and totals update instantly."),
            ("4 · Export", "Download a formatted Excel BOQ with a summary, one bill per discipline and the take-off details."),
        ]
        for col, (title, text) in zip(st.columns(4), steps):
            col.markdown(f'<div class="card"><h4>{title}</h4><p>{text}</p></div>', unsafe_allow_html=True)
        st.write("")
        st.info("New here? Open **📏 2D Drawings** and click **Load sample plan** to see a take-off in seconds.")
    else:
        left, right = st.columns(2)
        items = data.groupby(["Discipline", "Work Section"]).size().reset_index(name="Items")
        left.plotly_chart(
            px.sunburst(items, path=["Discipline", "Work Section"], values="Items", title="Items by discipline and work section",
                        color_discrete_sequence=BOLD).update_layout(margin=CHART_MARGIN, height=420),
            key="sunburst",
        )
        summ = boq.summary(data)
        if summ["Amount"].sum() > 0:
            fig = px.bar(summ, x="Discipline", y="Amount", text_auto=",.0f", title=f"Cost by discipline ({currency})",
                         color="Discipline", color_discrete_sequence=BOLD)
        else:
            fig = px.bar(summ, x="Discipline", y="Items", text_auto=True, title="Items by discipline (enter rates to see cost)",
                         color="Discipline", color_discrete_sequence=BOLD)
        right.plotly_chart(fig.update_layout(showlegend=False, margin=CHART_MARGIN, height=420), key="disc_bar")

# ------------------------------------------------------------------ 2D drawings

with tab_2d:
    top_l, top_r = st.columns([4, 1])
    uploads = top_l.file_uploader("Upload 2D drawings (DXF or PDF)", type=["dxf", "pdf"], accept_multiple_files=True, key="up_2d")
    top_r.write("")
    if top_r.button("✨ Load sample plan"):
        ss.sample_dxf = samples.sample_dxf_bytes()
    drawings = {f.name: f.getvalue() for f in uploads or []}
    if "sample_dxf" in ss:
        drawings = {"sample_plan.dxf": ss.sample_dxf, **drawings}

    if not drawings:
        st.info("Upload a DXF or PDF drawing to start. DWG files: save as DXF first (see sidebar).")
    else:
        name = st.selectbox("Drawing", list(drawings), key="drawing_pick")
        (render_dxf if name.lower().endswith(".dxf") else render_pdf)(name, drawings[name])

# ------------------------------------------------------------------ on-screen take-off

with tab_measure:
    st.caption("Measure directly on the drawing, the way a QS does in CostX or Bluebeam: set the scale, pick a take-off item, "
               "then click points (count), runs (length) or outlines (area). Every measurement lands on the QTO dimension sheet, "
               "which feeds the BOQ.")
    plans = st.file_uploader("Upload drawings to measure (PDF, or scanned plans as PNG/JPG)", type=["pdf", "png", "jpg", "jpeg"],
                             accept_multiple_files=True, key="up_measure")
    measure_sources = {n: d for n, d in drawings.items() if n.lower().endswith(".pdf")}
    measure_sources.update({f.name: f.getvalue() for f in plans or []})
    render_takeoff(measure_sources)

# ------------------------------------------------------------------ 3D models

with tab_3d:
    models = st.file_uploader("Upload 3D models (IFC, OBJ, STL, PLY, GLB, OFF)", type=["ifc", *mesh_takeoff.MESH_TYPES],
                              accept_multiple_files=True, key="up_3d")
    if not models:
        st.info("Upload an IFC model exported from Revit, ArchiCAD, Tekla, Civil 3D or Allplan for a full element-by-element take-off. "
                "Mesh formats (OBJ/STL/GLB) give volumes and surface areas per object.")
    else:
        name = st.selectbox("Model", [m.name for m in models], key="model_pick")
        payload = next(m for m in models if m.name == name).getvalue()
        (render_ifc if name.lower().endswith(".ifc") else render_mesh)(name, payload)

# ------------------------------------------------------------------ schedules

with tab_sched:
    st.caption("Upload the quantity schedules for each discipline — Revit/ArchiCAD schedules, bar bending schedules, "
               "door & window schedules, MEP fixture lists, earthworks or road quantities. Columns are matched automatically.")
    for discipline, sub in zip(dz.DISCIPLINES, st.tabs([f"{dz.DISCIPLINE_ICONS[d]} {d}" for d in dz.DISCIPLINES])):
        with sub:
            up_col, tpl_col = st.columns([4, 1])
            files = up_col.file_uploader(f"{discipline} schedules (Excel or CSV)", type=["xlsx", "xls", "csv"],
                                         accept_multiple_files=True, key=f"sch_{discipline}")
            template = schedules.template(discipline)
            tpl_col.download_button("⬇️ Template", template.to_csv(index=False).encode("utf-8-sig"),
                                    file_name=f"{discipline.lower()}_schedule_template.csv", mime="text/csv", key=f"tpl_{discipline}")
            if tpl_col.button("✨ Try sample", key=f"smp_{discipline}"):
                ss[f"sample_sched_{discipline}"] = True

            sources = [(f.name, f.getvalue()) for f in files or []]
            if ss.get(f"sample_sched_{discipline}"):
                sources.insert(0, (f"sample_{discipline.lower()}.csv", template.to_csv(index=False).encode("utf-8")))
            if not sources:
                st.info(f"Upload a {discipline.lower()} schedule, or download the template to see the expected layout.")
            for file_name, content in sources:
                with st.expander(f"📄 {file_name}", expanded=True):
                    try:
                        sheets = cached_schedule(content, file_name)
                    except Exception as exc:
                        st.error(f"Could not read this file: {exc}")
                        continue
                    if not sheets:
                        st.warning("No data found in this file.")
                        continue
                    sheet = st.selectbox("Sheet", list(sheets), key=f"sh_{discipline}_{file_name}") if len(sheets) > 1 else next(iter(sheets))
                    schedule_mapper(sheets[sheet], f"m_{discipline}_{file_name}_{sheet}", discipline, f"{file_name} · {sheet}")

# ------------------------------------------------------------------ rate library

with tab_rates:
    library = ss.rates
    c1, c2, c3 = st.columns(3)
    c1.metric("Library items", f"{len(library):,}")
    c2.metric("Items with a rate", f"{int((library['Rate'] > 0).sum()):,}")
    c3.metric("Disciplines", library.loc[library["Discipline"] != "", "Discipline"].nunique())
    st.caption("The library is kept only for this browser session. **Download it to keep it** and upload it again next time. "
               "Matching uses the item code first, then the closest description with the same unit.")

    up_col, dl_col = st.columns([3, 2])
    rate_file = up_col.file_uploader("Upload a rate library (Excel or CSV)", type=["xlsx", "xls", "csv"], key="up_rates")
    dl_col.write("")
    d1, d2, d3 = dl_col.columns(3)
    d1.download_button("⬇️ Template", rates.to_excel(rates.empty(), currency), file_name="rate_library_template.xlsx",
                       mime=XLSX_MIME, key="rate_tpl", help="Blank layout with example items. Fill in the Rate column.")
    d2.download_button("⬇️ Excel", rates.to_excel(library, currency), file_name="rate_library.xlsx", mime=XLSX_MIME,
                       key="rate_xlsx", disabled=library.empty)
    d3.download_button("⬇️ CSV", library.to_csv(index=False).encode("utf-8-sig"), file_name="rate_library.csv", mime="text/csv",
                       key="rate_csv", disabled=library.empty)

    if rate_file is not None:
        with st.expander(f"📄 {rate_file.name}", expanded=True):
            try:
                sheets = cached_schedule(rate_file.getvalue(), rate_file.name)
            except Exception as exc:
                st.error(f"Could not read this file: {exc}")
                sheets = {}
            if sheets:
                sheet = st.selectbox("Sheet", list(sheets), key="rate_sheet") if len(sheets) > 1 else next(iter(sheets))
                table = sheets[sheet]
                auto = rates.auto_map(table.columns)
                options = ["—", *table.columns]
                st.markdown("**Column mapping** — detected automatically, change if needed")
                mapping = {}
                for col, field in zip(st.columns(len(auto)), auto):
                    choice = col.selectbox(field, options, index=options.index(auto[field]) if auto[field] in options else 0,
                                           key=f"rmap_{rate_file.name}_{sheet}_{field}")
                    mapping[field] = None if choice == "—" else choice
                default_disc = st.selectbox("Discipline when not in the file", ["—", *dz.DISCIPLINES], key=f"rdisc_{rate_file.name}")
                if not mapping["Description"] or not mapping["Rate"]:
                    st.info("Map at least the Description and Rate columns.")
                else:
                    incoming = rates.from_table(table, mapping, None if default_disc == "—" else default_disc)
                    st.caption(f"{len(incoming)} items found, {int((incoming['Rate'] > 0).sum())} with a rate.")
                    st.dataframe(incoming, hide_index=True, height=220)
                    m1, m2, _ = st.columns([1, 1, 2])
                    if m1.button("➕ Merge into library", type="primary", key="rate_merge",
                                 help="Add these items; same description and unit replaces the old rate"):
                        ss.rates = rates.merge(ss.rates, incoming)
                        ss.rates_ver += 1
                        st.rerun()
                    if m2.button("♻️ Replace library", key="rate_replace"):
                        ss.rates = rates.merge(rates.empty(), incoming)
                        ss.rates_ver += 1
                        st.rerun()

    a1, a2, _ = st.columns([1, 1, 2])
    if a1.button("📥 Save BOQ rates to library", disabled=not (ss.boq["Rate"] > 0).any(),
                 help="Store the rates priced in the current BOQ so you can reuse them on the next project"):
        ss.rates = rates.merge(ss.rates, rates.from_boq(ss.boq))
        ss.rates_ver += 1
        st.rerun()
    if a2.button("🗑️ Clear library", disabled=library.empty):
        ss.rates = rates.empty()
        ss.rates_ver += 1
        st.rerun()

    st.markdown("#### Library")
    st.caption("Edit rates directly, or add and delete rows with the table toolbar.")
    edited_library = st.data_editor(
        ss.rates,
        key=f"rates_editor_{ss.rates_ver}",
        num_rows="dynamic",
        hide_index=True,
        height=420,
        column_config={
            "Code": st.column_config.TextColumn(width="small"),
            "Description": st.column_config.TextColumn(width="large"),
            "Unit": st.column_config.SelectboxColumn(options=sorted(set(dz.UNITS) | set(ss.rates["Unit"])), width="small"),
            "Rate": st.column_config.NumberColumn(f"Rate ({currency})", format="%.2f", min_value=0.0),
            "Discipline": st.column_config.SelectboxColumn(options=["", *dz.DISCIPLINES]),
            "Work Section": st.column_config.SelectboxColumn(options=["", *dz.NRM2_SECTIONS], width="medium"),
        },
    )
    updated_library = rates.tidy(edited_library, drop_blank=False)
    if not updated_library.equals(ss.rates):
        ss.rates = updated_library
        ss.rates_ver += 1
        st.rerun()

# ------------------------------------------------------------------ BOQ

with tab_boq:
    if ss.boq.empty:
        st.info("The BOQ is empty. Add quantities from the 2D Drawings, 3D Models or Schedules tabs.")
    else:
        summ = boq.summary(ss.boq)
        cols = st.columns(len(summ) + 1)
        for col, (_, r) in zip(cols, summ.iterrows()):
            col.metric(f"{dz.DISCIPLINE_ICONS.get(r['Discipline'], '•')} {r['Discipline']}", f"{r['Amount']:,.2f}",
                       f"{r['Items']} items", delta_color="off")
        cols[-1].metric(f"Grand total ({currency})", f"{ss.boq['Amount'].sum():,.2f}")

        with st.expander("💰 Price from rate library", expanded=ss.rate_report is not None):
            if (ss.rates["Rate"] > 0).sum() == 0:
                st.info("Your rate library has no rates yet. Upload one in the **💰 Rate Library** tab.")
            else:
                p1, p2, p3 = st.columns([2, 1, 1])
                min_score = p1.slider("Minimum description match", 50, 100, 80, step=5, format="%d%%",
                                      help="Lower finds more matches but risks wrong ones. Code matches always count.")
                overwrite = p2.checkbox("Replace rates already entered", False)
                p3.write("")
                if p3.button("💰 Apply rates", type="primary"):
                    ss.boq, ss.rate_report = rates.apply(ss.boq, ss.rates, min_score / 100, overwrite)
                    ss.boq_ver += 1
                    st.rerun()
            if ss.rate_report is not None:
                st.success(f"Last run priced {len(ss.rate_report)} of {len(ss.boq)} lines. Check the 'Similar' matches below.")
                st.dataframe(ss.rate_report.drop(columns="Line"), hide_index=True, height=240)

        st.caption("Edit descriptions, quantities and rates directly. Add or delete rows with the table toolbar. Amounts recalculate automatically.")
        edited = st.data_editor(
            ss.boq,
            key=f"boq_editor_{ss.boq_ver}",
            num_rows="dynamic",
            hide_index=True,
            height=520,
            column_config={
                "Ref": st.column_config.TextColumn(width="small"),
                "Discipline": st.column_config.SelectboxColumn(options=dz.DISCIPLINES, required=True),
                "Work Section": st.column_config.SelectboxColumn(options=dz.NRM2_SECTIONS, width="medium"),
                "Description": st.column_config.TextColumn(width="large"),
                "Unit": st.column_config.SelectboxColumn(options=sorted(set(dz.UNITS) | set(ss.boq["Unit"])), width="small"),
                "Quantity": st.column_config.NumberColumn(format="%.3f", min_value=0.0),
                "Rate": st.column_config.NumberColumn(f"Rate ({currency})", format="%.2f", min_value=0.0),
                "Amount": st.column_config.NumberColumn(f"Amount ({currency})", format="%.2f", disabled=True),
                "Source": st.column_config.TextColumn(disabled=True),
            },
        )
        # Commit edits so amounts recalculate; a new editor key stops old edits being replayed.
        updated = boq.finalise(edited, sort=False)
        if not updated.equals(ss.boq):
            ss.boq = updated
            ss.boq_ver += 1
            st.rerun()

        b1, b2, b3, b4, _ = st.columns([1, 1, 1, 1, 1])
        if b1.button("↕️ Sort by discipline & section"):
            ss.boq = boq.finalise(ss.boq, sort=True)
            ss.boq_ver += 1
            st.rerun()
        if b2.button("🧹 Clear all rates", disabled=not (ss.boq["Rate"] > 0).any()):
            ss.boq = boq.finalise(ss.boq.assign(Rate=0.0), sort=False)
            ss.boq_ver += 1
            ss.rate_report = None
            st.rerun()
        safe_name = "".join(ch if ch.isalnum() else "_" for ch in project["Project"]).strip("_") or "project"
        b3.download_button(
            "⬇️ Excel BOQ",
            boq.to_excel(ss.boq, {k: v for k, v in project.items() if v}, currency, ss.details, qto=measure.qto_sheet(ss.mt)),
            file_name=f"{safe_name}_BOQ.xlsx",
            mime=XLSX_MIME,
            type="primary",
        )
        b4.download_button("⬇️ CSV", ss.boq.to_csv(index=False).encode("utf-8-sig"), file_name=f"{safe_name}_BOQ.csv", mime="text/csv")

st.markdown(
    "<div style='text-align:center;color:#94a3b8;font-size:.85rem;margin-top:2rem'>"
    "QTO Studio · open source · quantities are a measurement aid — always check them against the drawings.</div>",
    unsafe_allow_html=True,
)
