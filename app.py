"""QTO Studio — professional quantity take-off from drawings, models and schedules.

Layout: left rail of views · ribbon tabs (File, Home, Drawings, Dimension, Workbook) · large working area.
Run with:  streamlit run app.py
"""

from __future__ import annotations

import io

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st
from PIL import Image, ImageOps

from qto import __version__, boq, dxf_takeoff, geometry, ifc_takeoff, measure, mesh_takeoff, pdf_takeoff, project, rates, samples, schedules, selftest
from qto import assemblies as asm
from qto import disciplines as dz
from qto.canvas import measure_canvas

st.set_page_config(page_title="QTO Studio", page_icon="📐", layout="wide", initial_sidebar_state="expanded")

st.markdown(
    """
<style>
.block-container {padding-top: .8rem; padding-bottom: 1.5rem; padding-left: 1.2rem; padding-right: 1.2rem; max-width: 100%;}
section[data-testid="stSidebar"] {min-width: 230px !important; max-width: 270px !important;}
.titlebar {display: flex; align-items: center; gap: .9rem; background: linear-gradient(90deg, #0f172a, #1e3a8a 70%, #0ea5e9);
           color: #fff; padding: .45rem 1rem; border-radius: 10px; margin-bottom: .3rem;}
.titlebar b {font-size: 1.02rem;} .titlebar span {opacity: .82; font-size: .84rem;}
.stTabs [data-baseweb="tab-list"] {gap: .15rem;}
.stTabs [data-baseweb="tab"] {font-weight: 600; padding: .3rem .9rem; border-radius: 8px 8px 0 0;}
div[data-testid="stTabs"] div[data-testid="stButton"] button, div[data-testid="stTabs"] div[data-testid="stDownloadButton"] button,
div[data-testid="stTabs"] div[data-testid="stPopover"] button {padding: .2rem .35rem; min-height: 2.3rem; font-size: .8rem;
  line-height: 1.15; white-space: normal;}
.statusbar {background: #0f172a; color: #e2e8f0; font-size: .8rem; padding: .3rem .8rem; border-radius: 8px; margin-top: .25rem;}
.statusbar b {color: #7dd3fc;}
div[data-testid="stMetric"] {background: #fff; border: 1px solid #e2e8f0; border-radius: 12px; padding: .6rem .9rem;}
.card {background: #fff; border: 1px solid #e2e8f0; border-radius: 14px; padding: 1rem 1.2rem; height: 100%;}
.card h4 {margin: .1rem 0 .35rem; color: #1e3a8a;} .card p {margin: 0; color: #475569; font-size: .93rem;}
</style>
""",
    unsafe_allow_html=True,
)

M = dz.MEASURE_COLUMNS
CURRENCIES = ["USD", "AED", "SAR", "QAR", "OMR", "KWD", "BHD", "EUR", "GBP", "INR", "PKR", "EGP"]
STANDARDS = ["RICS NRM2", "POMI", "CESMM4", "SMM7"]
BOLD = px.colors.qualitative.Bold
CHART_MARGIN = dict(t=40, l=0, r=0, b=0)
XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
MEASURABLE = (".pdf", ".dxf", ".png", ".jpg", ".jpeg")

NAV = ["🖼️ Drawing View", "📒 Workbook View", "🗂️ Dimension Group View", "✅ Project Check",
       "📏 2D Auto Take-off", "🧊 3D Models", "📋 Schedules", "💰 Rate Library", "📑 BOQ & Reports", "🏠 Dashboard"]
T_MEASURE, T_SIMILAR, T_LEN, T_AREA, T_SELECT, T_CAL = (
    "✏️ Measure", "🎯 Select similar", "📐 Check length", "⬛ Check area", "🖐 Select / pan", "📏 Calibrate")
TOOLS = [T_MEASURE, T_SIMILAR, T_LEN, T_AREA, T_SELECT, T_CAL]


def set_tool(tool: str):
    """Button callback: switch the measuring tool (runs before the tool selector is drawn)."""
    ss.mt_tool = tool
    ss.nav = NAV[0]

ss = st.session_state
for key, value in {"boq": boq.empty(), "boq_ver": 0, "details": {}, "rates": rates.empty(), "rates_ver": 0, "rate_report": None,
                   "legends": {}, "mt": measure.new_state(), "mt_selected": None, "mt_calibration_pts": None, "mt_ver": 0,
                   "projects": {}, "p_name": "New Project", "p_client": "", "p_location": "", "p_by": "",
                   project.CURRENCY_KEY: "USD", "p_standard": STANDARDS[0], "files": {}, "nav": NAV[0],
                   "account": {}, "opts": {"canvas_height": 760, "decimals": 3, "snap": True, "offsets": True,
                                            "currency": "USD", "standard": STANDARDS[0]}}.items():
    ss.setdefault(key, value)
ss["mt"] = measure.upgrade(ss["mt"])
if "nav_pending" in ss:  # set by dialogs, applied before the view selector is drawn
    ss.nav = ss.pop("nav_pending")

# A project switch is requested by a button, then applied here, before any project widget is drawn.
if "pending_project" in ss:
    pending = ss.pop("pending_project")
    current = project.snapshot(ss)
    ss.projects[current["info"]["p_name"]] = current
    try:
        project.restore(ss, pending)
        ss.projects[pending["info"]["p_name"]] = pending
        ss["project_msg"] = f"Opened project “{pending['info']['p_name']}”"
        if ss[project.CURRENCY_KEY] not in CURRENCIES:
            ss[project.CURRENCY_KEY] = "USD"
        if ss.p_standard not in STANDARDS:
            ss.p_standard = STANDARDS[0]
    except (ValueError, KeyError, TypeError) as exc:
        ss["project_msg"] = f"Could not open the project: {exc}"


def qfmt() -> str:
    """Quantity display format from ⚙️ Options (2 or 3 decimals)."""
    return f"%.{int(ss.opts.get('decimals', 3))}f"


def go_to(view: str):
    """Button callback: switch the left-rail view (runs before the widgets are drawn)."""
    ss.nav = view


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
def cached_measure_image(data: bytes, name: str, page: int, dpi: int) -> tuple[str, float, list[float], float | None]:
    """(JPEG data URL, display pixels per drawing unit, flat snap-point list in display pixels,
    known metres per drawing unit or None when the user has to set the scale)."""
    if name.lower().endswith(".dxf"):
        image, m_per_px, snap = dxf_takeoff.render_image(dxf_takeoff.takeoff(data, None, True))
        return measure.image_data_url(image), 1.0, snap, m_per_px
    if name.lower().endswith(".pdf"):
        image, k = pdf_takeoff.render_for_measure(data, page, dpi)
        snap = [round(v * k, 3) for xy in pdf_takeoff.snap_points(data, page) for v in xy]
    else:
        image = Image.open(io.BytesIO(data))
        image = ImageOps.exif_transpose(image)
        k = min(1.0, 6000 / max(image.size))  # drawing units are the original image pixels
        if k < 1.0:
            image = image.resize((int(image.width * k), int(image.height * k)))
        snap = []
    return measure.image_data_url(image), k, snap, None


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


@st.cache_data(show_spinner=False)
def cached_selftest() -> pd.DataFrame:
    return pd.DataFrame(selftest.cases())


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


def project_details() -> dict:
    return {k: v for k, v in {"Project": ss.p_name, "Client": ss.p_client, "Location": ss.p_location, "Prepared by": ss.p_by,
                              "Measurement standard": ss.p_standard}.items() if v}


def full_export(lines: pd.DataFrame) -> bytes:
    """BOQ workbook with the dimension sheet, derived items (formula trace) and wall schedule."""
    derived, _ = measure.derived_items(ss.mt)
    return boq.to_excel(lines, project_details(), ss[project.CURRENCY_KEY], ss.details, qto=measure.qto_sheet(ss.mt),
                        derived=derived, wall_schedule=measure.wall_schedules(ss.mt))


# ------------------------------------------------------------------ 2D auto take-off (DXF layers / PDF linework)

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
            st.warning("No vector linework found. This page is probably a scanned image — measure it in **🖼️ Drawing View** instead.")
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


# ------------------------------------------------------------------ take-off helpers

def send_takeoff_to_boq() -> None:
    """Replace the on-screen QTO lines in the BOQ. Workbook rates win; otherwise rates already in the BOQ are kept."""
    lines = measure.boq_lines(ss.mt)
    if lines.empty:
        st.warning("No measured quantities yet. Set the scale and measure at least one item.")
        return
    previous = ss.boq[ss.boq["Source"] == measure.SOURCE].set_index("Ref")["Rate"].to_dict()
    lines["Rate"] = [rate if rate > 0 else previous.get(ref, 0.0) for ref, rate in zip(lines["Ref"], lines["Rate"])]
    add_to_boq(lines.drop(columns="Key"), measure.SOURCE)


def item_label(item: dict) -> str:
    if measure.is_assembly(item):
        return f"{item['ref']} · {item['description']} ⚙ ({item['type'].lower()})"
    return f"{item['ref']} · {item['description']} ({measure.item_unit(item['type'], item['width'], item['depth'])})"


def measurable_files() -> list[str]:
    return [n for n in ss.files if n.lower().endswith(MEASURABLE)]


def current_drawing() -> tuple[str | None, int]:
    names = measurable_files()
    doc = ss.get("mt_doc") if ss.get("mt_doc") in names else (names[0] if names else None)
    return doc, int(ss.get(f"mt_pg_{doc}", 1)) - 1 if doc else 0


TEMPLATE_OPTIONS = {f"asm:{k}": f"⚙ {v['trade']}: {v['label']}" for k, v in asm.TEMPLATES.items()}
TEMPLATE_OPTIONS.update({f"preset:{k}": f"📐 Simple: {k}" for k in measure.PRESETS})


# Dialogs close themselves with st.rerun(), so they never cover the drawing (clicks on the drawing
# canvas cannot close a popover). Widget keys they change are applied through "pending_*" values.

@st.dialog("➕ New take-off item", width="large")
def new_item_dialog() -> None:
    kind = st.selectbox("Template", list(TEMPLATE_OPTIONS), format_func=TEMPLATE_OPTIONS.get)
    if kind.startswith("asm:"):
        st.caption(asm.TEMPLATES[kind[4:]]["help"])
    desc = st.text_input("Description (optional)", placeholder="e.g. F1 isolated footing, BW200 external wall").strip()
    if st.button("Create item", type="primary"):
        if kind.startswith("asm:"):
            key = kind[4:]
            discipline = "Architectural" if asm.TEMPLATES[key]["trade"] == "Architectural" else "Structural"
            section = asm.S_MAS if key == "blockwork_wall" else asm.S_CON
            item = measure.add_assembly_item(ss.mt, key, desc or asm.TEMPLATES[key]["label"], discipline, section)
        else:
            p_desc, p_disc, p_sec, p_kind, p_w, p_d = measure.PRESETS[kind[7:]]
            item = measure.add_item(ss.mt, desc or p_desc or "Take-off item", p_disc, p_sec, p_kind, p_w, p_d)
        ss.pending_active = item["id"]
        ss.nav_pending = NAV[0]
        ss.mt_ver += 1
        st.rerun()


@st.dialog("➕ Add building")
def building_dialog() -> None:
    name = st.text_input("Building name", placeholder="e.g. Villa Type A, Block B, Car park")
    st.caption("Levels are copied from the first building; edit them in 🗂️ Dimension Group View.")
    if st.button("Add building", type="primary"):
        ss.pending_building = measure.add_building(ss.mt, name)["id"]
        ss.mt_ver += 1
        st.rerun()


@st.dialog("⚙️ Item parameters", width="large")
def item_dialog(item_id: int) -> None:
    item_params_form(measure.item_by_id(ss.mt, item_id))


# ------------------------------------------------------------------ ribbon

# ---- File menu: every command opens a dialog that does the work and closes itself.

def blank_project(name: str, **info) -> dict:
    """New project data, pre-filled from the user's account and options."""
    data = project.blank(name, info.get("client", ""), info.get("location", ""),
                         info.get("prepared_by") or ss.account.get("name", ""), info.get("currency") or ss.opts["currency"],
                         info.get("building") or "Building 1", info.get("standard") or ss.opts["standard"])
    return data


def open_project_widgets(prefix: str) -> dict | None:
    """Pick a project from this session or a saved file; returns its data (or None)."""
    others = [name for name in ss.projects if name != ss.p_name]
    source = st.radio("From", ["Saved project file (.qto.json)", "Project opened in this session"], key=f"{prefix}_src", horizontal=True)
    if source.startswith("Saved"):
        saved = st.file_uploader("Project file", type=["json"], key=f"{prefix}_file")
        if saved is not None:
            try:
                return project.from_bytes(saved.getvalue())
            except (ValueError, UnicodeDecodeError) as exc:
                st.error(str(exc))
        return None
    if not others:
        st.caption("No other projects in this session yet.")
        return None
    return ss.projects[st.selectbox("Project", others, key=f"{prefix}_pick")]


@st.dialog("🆕 New")
def dlg_new() -> None:
    st.write("Start a blank project now. The open project stays in this session's list (📂 Open) — 💾 Save it to keep it.")
    name = st.text_input("Project name", "Untitled project")
    if st.button("Create", type="primary"):
        ss.pending_project = blank_project(name.strip() or "Untitled project")
        st.rerun()


@st.dialog("📂 Open")
def dlg_open() -> None:
    data = open_project_widgets("open")
    if data is not None and st.button(f"Open “{data['info'].get('p_name', 'project')}”", type="primary"):
        ss.pending_project = data
        st.rerun()


@st.dialog("📑 Copy")
def dlg_copy() -> None:
    st.write("Make a copy of the open project (details, BOQ, rate library and take-off).")
    taken = set(ss.projects) | {ss.p_name}
    name = st.text_input("Name of the copy", project.unique_name(f"Copy of {ss.p_name}", taken))
    open_it = st.checkbox("Open the copy now", True)
    if st.button("Copy", type="primary"):
        data = project.renamed(project.snapshot(ss), project.unique_name(name.strip() or f"Copy of {ss.p_name}", taken))
        ss.projects[data["info"]["p_name"]] = data
        if open_it:
            ss.pending_project = data
        else:
            ss.project_msg = f"Copied to “{data['info']['p_name']}” (📂 Open → this session)"
        st.rerun()


@st.dialog("🔀 Merge", width="large")
def dlg_merge() -> None:
    st.write("Bring another project into the open one: its BOQ lines are appended, its rate library merged, and its "
             "take-off items, buildings and measurements added (items are re-numbered).")
    data = open_project_widgets("merge")
    if data is not None and st.button(f"Merge “{data['info'].get('p_name', 'project')}” into “{ss.p_name}”", type="primary"):
        summary = project.merge(ss, data)
        ss.project_msg = (f"Merged: {summary['items']} items, {summary['shapes']} measurements, "
                          f"{summary['buildings']} buildings, {summary['boq_lines']} BOQ lines")
        st.rerun()


@st.dialog("🗑️ Delete")
def dlg_delete() -> None:
    others = [name for name in ss.projects if name != ss.p_name]
    if not others:
        st.info("There are no other projects in this session to delete. The open project can't be deleted — ✖️ Close it first.")
        return
    pick = st.selectbox("Project", others)
    st.caption("Removes it from this session's list only. Project files saved on your PC are not affected.")
    sure = st.checkbox(f"Yes, delete “{pick}”")
    if st.button("Delete", type="primary", disabled=not sure):
        ss.projects.pop(pick, None)
        ss.project_msg = f"Deleted “{pick}” from this session"
        st.rerun()


@st.dialog("ℹ️ Drawing properties", width="large")
def dlg_property() -> None:
    mt = ss.mt
    if not ss.files:
        st.info("No drawings loaded. 📥 Import → Drawings.")
        return
    rows = []
    for name, data in ss.files.items():
        pages = cached_pdf_pages(data) if name.lower().endswith(".pdf") else 1
        scaled = sum(1 for p in range(pages) if mt["calibration"].get(measure.page_key(name, p))) if not name.lower().endswith(".dxf") else pages
        rows.append({"Drawing": name, "Type": name.rsplit(".", 1)[-1].upper(), "Size (KB)": round(len(data) / 1024, 1), "Pages": pages,
                     "Scaled pages": scaled, "Measurements": sum(1 for s in mt["shapes"] if s["doc"] == name)})
    st.dataframe(pd.DataFrame(rows), hide_index=True)
    doc = st.selectbox("Drawing", list(ss.files), index=list(ss.files).index(ss.mt_doc) if ss.get("mt_doc") in ss.files else 0)
    new_name = st.text_input("Rename to", doc)
    a, b = st.columns(2)
    if a.button("✏️ Rename", disabled=not new_name.strip() or new_name.strip() == doc or new_name.strip() in ss.files):
        new_name = new_name.strip()
        ss.files = {(new_name if k == doc else k): v for k, v in ss.files.items()}
        for s in mt["shapes"]:
            if s["doc"] == doc:
                s["doc"] = new_name
        mt["calibration"] = {(measure.page_key(new_name, int(k.rsplit("|", 1)[1])) if k.startswith(f"{doc}|") else k): v
                             for k, v in mt["calibration"].items()}
        ss.pending_doc = new_name
        ss.mt_ver += 1
        st.rerun()
    sure = b.checkbox("Confirm remove")
    if b.button("🗑️ Remove drawing", disabled=not sure):
        ss.files.pop(doc, None)
        ss.project_msg = f"Removed {doc}. Its measurements stay in the take-off and reappear if the drawing is imported again."
        st.rerun()


@st.dialog("✖️ Close")
def dlg_close() -> None:
    st.write(f"Close “{ss.p_name}”? It stays in this session's list (📂 Open), but everything is lost when the browser "
             "closes unless you save it.")
    snapshot = project.snapshot(ss)
    st.download_button("💾 Save a copy first", project.to_bytes(snapshot), file_name=project.file_name(snapshot), mime="application/json")
    if st.button("Close project", type="primary"):
        ss.pending_project = blank_project("Untitled project")
        st.rerun()


@st.dialog("📥 Import", width="large")
def dlg_import() -> None:
    t_draw, t_proj, t_take, t_rate, t_sched = st.tabs(["Drawings", "Project file", "Take-off file", "Rate library", "Schedules"])
    with t_draw:
        files = st.file_uploader("PDF, DXF, or scanned plans (PNG/JPG)", type=["pdf", "dxf", "png", "jpg", "jpeg"],
                                 accept_multiple_files=True, key="imp_draw")
        st.caption("DWG: save as DXF first. PDFs and scans open with the 📏 Calibrate tool selected.")
        if files and st.button("Add drawings", type="primary"):
            for f in files:
                ss.files[f.name] = f.getvalue()
            ss.pending_doc = files[-1].name
            ss.nav_pending = NAV[0]
            if not files[-1].name.lower().endswith(".dxf"):
                ss.pending_tool = T_CAL
            st.rerun()
    with t_proj:
        saved = st.file_uploader("Project file (.qto.json)", type=["json"], key="imp_proj")
        if saved is not None:
            try:
                data = project.from_bytes(saved.getvalue())
                a, b = st.columns(2)
                if a.button("Open (replace)", type="primary"):
                    ss.pending_project = data
                    st.rerun()
                if b.button("Merge into this project"):
                    summary = project.merge(ss, data)
                    ss.project_msg = f"Merged {summary['items']} items and {summary['boq_lines']} BOQ lines"
                    st.rerun()
            except (ValueError, UnicodeDecodeError) as exc:
                st.error(str(exc))
    with t_take:
        saved = st.file_uploader("Take-off file (.json)", type=["json"], key="imp_take")
        if saved is not None:
            try:
                loaded = measure.from_json(saved.getvalue())
                a, b = st.columns(2)
                if a.button("Load (replace take-off)", type="primary"):
                    loaded["seen"] = ss.mt["seen"]
                    ss.mt, ss.mt_selected = loaded, None
                    ss.mt_ver += 1
                    st.rerun()
                if b.button("Merge into take-off"):
                    summary = measure.merge_takeoff(ss.mt, loaded)
                    ss.project_msg = f"Merged {summary['items']} items and {summary['shapes']} measurements"
                    ss.mt_ver += 1
                    st.rerun()
            except (ValueError, KeyError) as exc:
                st.error(str(exc))
    with t_rate:
        saved = st.file_uploader("Rate library (Excel or CSV)", type=["xlsx", "xls", "csv"], key="imp_rate")
        if saved is not None:
            sheets = cached_schedule(saved.getvalue(), saved.name)
            table = next(iter(sheets.values())) if sheets else pd.DataFrame()
            mapping = rates.auto_map(table.columns)
            if not mapping["Description"] or not mapping["Rate"]:
                st.warning("Description and Rate columns were not found — use 💰 Rate Library to map columns by hand.")
            else:
                incoming = rates.from_table(table, mapping)
                st.caption(f"{len(incoming)} items, {int((incoming['Rate'] > 0).sum())} with a rate.")
                if st.button("Merge into rate library", type="primary"):
                    ss.rates = rates.merge(ss.rates, incoming)
                    ss.rates_ver += 1
                    ss.project_msg = f"Rate library: {len(incoming)} items merged"
                    st.rerun()
    with t_sched:
        st.write("Schedules need a column-mapping step for each discipline.")
        if st.button("Go to 📋 Schedules", type="primary"):
            ss.nav_pending = NAV[6]
            st.rerun()


@st.dialog("📤 Export", width="large")
def dlg_export() -> None:
    lines = measure.boq_lines(ss.mt)
    snapshot = project.snapshot(ss)
    stem = project.file_name(snapshot)[:-9]
    exports = [
        ("📑 BOQ workbook (Excel)", "Summary, a bill per discipline, QTO dimension sheet, derived items, wall schedule",
         lambda: full_export(ss.boq), f"{stem}_BOQ.xlsx", XLSX_MIME, ss.boq.empty),
        ("📄 BOQ (CSV)", "Plain BOQ lines", lambda: ss.boq.to_csv(index=False).encode("utf-8-sig"), f"{stem}_BOQ.csv", "text/csv", ss.boq.empty),
        ("📒 QTO workbook (Excel)", "Take-off only: dimension sheet linked to a BOQ of its items",
         lambda: full_export(lines.drop(columns="Key")), f"{stem}_QTO.xlsx", XLSX_MIME, lines.empty),
        ("📋 Dimension sheet (CSV)", "Every measurement", lambda: measure.qto_sheet(ss.mt).to_csv(index=False).encode("utf-8-sig"),
         f"{stem}_dimensions.csv", "text/csv", not ss.mt["shapes"]),
        ("💾 Project file", "Everything, to open again later", lambda: project.to_bytes(snapshot), project.file_name(snapshot), "application/json", False),
        ("📐 Take-off file", "Take-off items, measurements, buildings and scales", lambda: measure.to_json(ss.mt), f"{stem}.takeoff.json",
         "application/json", not ss.mt["items"]),
        ("💰 Rate library (Excel)", "Your rates, to reuse on other projects", lambda: rates.to_excel(ss.rates, ss[project.CURRENCY_KEY]),
         f"{stem}_rates.xlsx", XLSX_MIME, ss.rates.empty),
    ]
    for label, help_text, make, file_name, mime, disabled in exports:
        a, b = st.columns([1.3, 2])
        a.download_button(label, b"" if disabled else make(), file_name=file_name, mime=mime, disabled=disabled,
                          use_container_width=True, key=f"exp_{file_name}")
        b.caption(help_text + (" — nothing to export yet" if disabled else ""))


@st.dialog("🏗️ New Project", width="large")
def dlg_new_project() -> None:
    with st.form("new_project"):
        a, b = st.columns(2)
        name = a.text_input("Project name", placeholder="e.g. Al Barsha Villas")
        client = b.text_input("Client")
        location = a.text_input("Location")
        by = b.text_input("Prepared by", ss.account.get("name", ""))
        currency = a.selectbox("Currency", CURRENCIES, index=CURRENCIES.index(ss.opts["currency"]))
        standard = b.selectbox("Measurement standard", STANDARDS, index=STANDARDS.index(ss.opts["standard"]))
        building = st.text_input("First building", "Building 1", help="Add more buildings later: Home tab → ➕ Building")
        st.caption("The open project stays in this session's list (📂 Open). 💾 Save it to keep it.")
        if st.form_submit_button("Create project", type="primary"):
            ss.pending_project = blank_project(name.strip() or "New Project", client=client, location=location, prepared_by=by,
                                               currency=currency, standard=standard, building=building)
            st.rerun()


@st.dialog("🧾 Project Property", width="large")
def dlg_project_property() -> None:
    t_info, t_param, t_build = st.tabs(["Details", "Parameters", "Buildings & levels"])
    with t_info:
        with st.form("project_info"):
            a, b = st.columns(2)
            values = {"p_name": a.text_input("Project name", ss.p_name), "p_client": b.text_input("Client", ss.p_client),
                      "p_location": a.text_input("Location", ss.p_location), "p_by": b.text_input("Prepared by", ss.p_by)}
            currency = a.selectbox("Currency", CURRENCIES, index=CURRENCIES.index(ss[project.CURRENCY_KEY]))
            standard = b.selectbox("Measurement standard", STANDARDS, index=STANDARDS.index(ss.p_standard))
            if st.form_submit_button("Save details", type="primary"):
                for key, value in values.items():
                    ss[key] = value.strip()
                ss[project.CURRENCY_KEY], ss.p_standard = currency, standard
                st.rerun()
    with t_param:
        globals_form()
    with t_build:
        st.dataframe(pd.DataFrame([{"Code": b["code"], "Building": b["name"], **{asm.LEVEL_LABELS[k]: b["levels"].get(k) for k in asm.LEVELS}}
                                   for b in ss.mt["buildings"]]), hide_index=True)
        if st.button("Edit in 🗂️ Dimension Group View"):
            ss.nav_pending = NAV[2]
            st.rerun()


@st.dialog("🛡️ System Administration", width="large")
def dlg_admin() -> None:
    import platform
    import sys

    a, b, c = st.columns(3)
    a.metric("QTO Studio", f"v{__version__}")
    b.metric("Streamlit", st.__version__)
    c.metric("Python", platform.python_version())
    size = sum(len(v) for v in ss.files.values()) / 1_048_576
    st.markdown("**This session**")
    st.dataframe(pd.DataFrame([
        {"What": "Drawings loaded", "Value": f"{len(ss.files)} ({size:.1f} MB)"},
        {"What": "Take-off items / measurements", "Value": f"{len(ss.mt['items'])} / {len(ss.mt['shapes'])}"},
        {"What": "BOQ lines / rate library items", "Value": f"{len(ss.boq)} / {len(ss.rates)}"},
        {"What": "Projects in session list", "Value": str(len(ss.projects))},
        {"What": "Platform", "Value": f"{platform.system()} · {sys.platform}"},
    ]), hide_index=True)
    results = cached_selftest()
    passed = int(results["Pass"].sum())
    (st.success if passed == len(results) else st.error)(f"Calculation self-test: {passed} of {len(results)} checks passed")
    st.caption("The app runs on Streamlit Community Cloud; nothing is stored on the server between sessions.")
    st.markdown("**Maintenance**")
    m1, m2, m3 = st.columns(3)
    if m1.button("🧹 Clear caches", help="Re-read drawings and re-run the self-test"):
        st.cache_data.clear()
        ss.project_msg = "Caches cleared"
        st.rerun()
    if m2.button("🗑️ Clear BOQ", disabled=ss.boq.empty):
        ss.boq, ss.details, ss.rate_report = boq.empty(), {}, None
        ss.boq_ver += 1
        st.rerun()
    sure = m3.checkbox("Confirm reset")
    if m3.button("♻️ Reset session", disabled=not sure, help="Clears every project, drawing and setting in this browser session"):
        for key in list(ss.keys()):
            del ss[key]
        st.rerun()


@st.dialog("👤 Account")
def dlg_account() -> None:
    st.caption("The free server has no sign-in. Your details stay in this browser session and are used as "
               "'Prepared by' on new projects and reports.")
    acc = ss.account
    with st.form("account"):
        values = {"name": st.text_input("Full name", acc.get("name", "")), "initials": st.text_input("Initials", acc.get("initials", "")),
                  "company": st.text_input("Company", acc.get("company", "")), "role": st.text_input("Role", acc.get("role", "Quantity Surveyor")),
                  "email": st.text_input("Email (optional)", acc.get("email", ""))}
        if st.form_submit_button("Save", type="primary"):
            ss.account = {k: v.strip() for k, v in values.items()}
            if not ss.p_by:
                ss.p_by = ss.account["name"]
            st.rerun()


@st.dialog("⚙️ Options")
def dlg_options() -> None:
    o = ss.opts
    with st.form("options"):
        height = st.slider("Drawing area height (px)", 500, 1400, int(o["canvas_height"]), 20)
        decimals = st.radio("Quantity decimals", [2, 3], index=[2, 3].index(o["decimals"]), horizontal=True)
        snap = st.checkbox("Snap to drawing by default", o["snap"])
        offsets = st.checkbox("Show extended perimeters (offsets) by default", o["offsets"])
        currency = st.selectbox("Default currency for new projects", CURRENCIES, index=CURRENCIES.index(o["currency"]))
        standard = st.selectbox("Default measurement standard", STANDARDS, index=STANDARDS.index(o["standard"]))
        if st.form_submit_button("Save options", type="primary"):
            ss.opts = {"canvas_height": height, "decimals": decimals, "snap": snap, "offsets": offsets,
                       "currency": currency, "standard": standard}
            st.rerun()


FILE_MENU = [
    ("🆕", "New", dlg_new), ("📂", "Open", dlg_open), ("📑", "Copy", dlg_copy), ("🔀", "Merge", dlg_merge),
    ("🗑️", "Delete", dlg_delete), ("ℹ️", "Property", dlg_property), ("✖️", "Close", dlg_close),
    ("📥", "Import", dlg_import), ("📤", "Export", dlg_export), ("🏗️", "New Project", dlg_new_project),
    ("🧾", "Project Property", dlg_project_property), ("🛡️", "System Admin", dlg_admin), ("👤", "Account", dlg_account),
    ("⚙️", "Option", dlg_options),
]


def ribbon_file() -> None:
    cols = st.columns(len(FILE_MENU) + 1)
    for col, (icon, name, dialog) in zip(cols, FILE_MENU):
        if col.button(f"{icon} {name}", key=f"file_{name}", use_container_width=True, help=name):
            dialog()
    snapshot = project.snapshot(ss)
    cols[-1].download_button("💾 Save", project.to_bytes(snapshot), file_name=project.file_name(snapshot), mime="application/json",
                             use_container_width=True, help="Download the whole project to open again later — the server keeps nothing")


def globals_form() -> None:
    """Project-wide defaults used by every assembly (blinding, offsets, excavation, laps, rebar)."""
    g = ss.mt["globals"]
    with st.form("globals"):
        st.markdown("**Foundation defaults**")
        a, b = st.columns(2)
        new = {"blinding_t": a.number_input(asm.GLOBAL_LABELS["blinding_t"], 0.0, 1.0, float(g["blinding_t"]), 0.005, format="%.3f"),
               "extra_depth": b.number_input(asm.GLOBAL_LABELS["extra_depth"], 0.0, 5.0, float(g["extra_depth"]), 0.05, format="%.3f")}
        st.caption("Blinding offset beyond the footing face, per side (m)")
        cols = st.columns(4)
        for col, side in zip(cols, ("left", "right", "top", "bottom")):
            new[f"bo_{side}"] = col.number_input(side.title(), 0.0, 2.0, float(g[f"bo_{side}"]), 0.05, format="%.3f", key=f"g_bo_{side}")
        st.caption("Excavation offset (working space), per side (m)")
        cols = st.columns(4)
        for col, side in zip(cols, ("left", "right", "top", "bottom")):
            new[f"eo_{side}"] = col.number_input(side.title(), 0.0, 5.0, float(g[f"eo_{side}"]), 0.05, format="%.3f", key=f"g_eo_{side}")
        a, b = st.columns(2)
        new["offset_from"] = a.selectbox(asm.GLOBAL_LABELS["offset_from"], asm.CHOICES["offset_from"], index=asm.CHOICES["offset_from"].index(g["offset_from"]))
        new["refill"] = b.selectbox(asm.GLOBAL_LABELS["refill"], asm.CHOICES["refill"], index=asm.CHOICES["refill"].index(g["refill"]))
        a, b = st.columns(2)
        new["batter"] = a.number_input(asm.GLOBAL_LABELS["batter"], 0.0, 5.0, float(g["batter"]), 0.1, format="%.2f")
        new["bulking"] = b.number_input(asm.GLOBAL_LABELS["bulking"], 1.0, 2.0, float(g["bulking"]), 0.05, format="%.2f")
        new["waterproofing"] = st.selectbox(asm.GLOBAL_LABELS["waterproofing"], asm.CHOICES["waterproofing"],
                                            index=asm.CHOICES["waterproofing"].index(g["waterproofing"]))
        st.markdown("**Laps, thresholds and reinforcement**")
        cols = st.columns(3)
        for col, key in zip(cols, ("wp_lap", "polythene_lap", "mesh_lap")):
            new[key] = col.number_input(asm.GLOBAL_LABELS[key], 0.0, 1.0, float(g[key]), 0.01, format="%.2f")
        cols = st.columns(3)
        for col, key in zip(cols, ("wall_void_threshold", "slab_void_threshold", "lintel_bearing")):
            new[key] = col.number_input(asm.GLOBAL_LABELS[key], 0.0, 10.0, float(g[key]), 0.05, format="%.2f")
        cols = st.columns(4)
        for col, key in zip(cols, ("rebar_foundation", "rebar_beam", "rebar_column", "rebar_slab")):
            new[key] = col.number_input(asm.GLOBAL_LABELS[key].replace("Rebar ratio — ", ""), 0.0, 500.0, float(g[key]), 5.0, format="%.0f")
        if st.form_submit_button("Apply to project", type="primary"):
            g.update(new)
            ss.mt_ver += 1
            st.rerun()


def ribbon_home(issue_count: int) -> None:
    mt = ss.mt
    c = st.columns([2.2, 1, 1.2, 1, 1, 1, 1.2])
    if c[1].button("➕ Building", use_container_width=True):
        building_dialog()
    if "pending_building" in ss:
        ss.mt_building = ss.pop("pending_building")
    ids = [b["id"] for b in mt["buildings"]]
    if ss.get("mt_building") not in ids:
        ss.mt_building = ids[0]
    names = {b["id"]: f"🏢 {b['name']}" for b in mt["buildings"]}
    c[0].selectbox("Building", ids, format_func=names.get, key="mt_building", label_visibility="collapsed",
                   help="New measurements are booked to this building")
    c[2].text_input("Level", key="mt_level", placeholder="Level, e.g. GF", label_visibility="collapsed",
                    help="Floor or level for new measurements, e.g. GF, L1, Roof")
    c[3].button("🖼️ Drawing", use_container_width=True, on_click=go_to, args=(NAV[0],))
    c[4].button("📒 Workbook", use_container_width=True, on_click=go_to, args=(NAV[1],))
    c[5].button("🗂️ Groups", use_container_width=True, on_click=go_to, args=(NAV[2],))
    c[6].button(f"✅ Check ({issue_count})" if issue_count else "✅ Check: OK", use_container_width=True,
                type="primary" if issue_count else "secondary", on_click=go_to, args=(NAV[3],))


def ribbon_drawings() -> None:
    mt = ss.mt
    c = st.columns([1.1, 2.4, 0.8, 1, 0.8, 1.1, 1.5])
    with c[0].popover("📂 Drawings", use_container_width=True):
        uploads = st.file_uploader("Add drawings (PDF, DXF, PNG/JPG scans)", type=["pdf", "dxf", "png", "jpg", "jpeg"],
                                   accept_multiple_files=True, key="up_files")
        new = [f for f in uploads or [] if f.name not in ss.files]
        for f in new:
            ss.files[f.name] = f.getvalue()
        if new:  # open the new drawing straight away; PDFs and scans start with the calibrate tool
            ss.mt_doc = new[-1].name
            ss.nav_pending = NAV[0]
            if not new[-1].name.lower().endswith(".dxf"):
                ss.mt_tool = T_CAL
            st.rerun()
        if st.button("✨ Load sample plan", key="load_sample"):
            ss.files["sample_plan.dxf"] = samples.sample_dxf_bytes()
            ss.mt_doc = "sample_plan.dxf"
            st.rerun()
        if ss.files:
            gone = st.selectbox("Remove a drawing", ["—", *ss.files], key="rm_file")
            if gone != "—" and st.button("Remove", key="rm_file_go"):
                ss.files.pop(gone, None)
                st.rerun()
        st.caption("DWG: save as DXF first. Revit/ArchiCAD/Tekla: export IFC for 🧊 3D Models.")
    names = measurable_files()
    if not names:
        c[1].caption("No drawings yet — use 📂 Drawings to add files or load the sample plan.")
        return
    if "pending_doc" in ss:  # set by File → Import / Property dialogs
        ss.mt_doc = ss.pop("pending_doc")
    if ss.get("mt_doc") not in names:
        ss.mt_doc = names[0]
    doc = c[1].selectbox("Drawing", names, key="mt_doc", label_visibility="collapsed")
    is_pdf, is_dxf = doc.lower().endswith(".pdf"), doc.lower().endswith(".dxf")
    pages = cached_pdf_pages(ss.files[doc]) if is_pdf else 1
    c[2].selectbox("Page", list(range(1, pages + 1)), key=f"mt_pg_{doc}", label_visibility="collapsed",
                   format_func=lambda p: f"Page {p}")
    c[3].selectbox("Detail", ["Standard", "Fine", "Draft"], key="mt_dpi", disabled=not is_pdf, label_visibility="collapsed")
    c[4].toggle("Snap", ss.opts["snap"], key="mt_snap", disabled=not (is_pdf or is_dxf), help="Snap clicks to line ends and corners")
    c[5].toggle("Offsets", ss.opts["offsets"], key="mt_guides", help="Show extended perimeters: footing face, blinding edge (dashed blue) "
                                                       "and excavation edge (dotted orange) around foundation items")
    page = int(ss.get(f"mt_pg_{doc}", 1)) - 1
    pkey = measure.page_key(doc, page)
    mpu = mt["calibration"].get(pkey)
    with c[6].popover(("📏 Scale ✓" if mpu or is_dxf else "📏 Set scale ⚠"), use_container_width=True):
        if mpu:
            shown = f"1 : {mpu / measure.PT_TO_M:,.0f}" if is_pdf else "exact, from DXF units" if is_dxf else f"{mpu * 1000:.2f} mm per pixel"
            st.success(f"Scale set — {shown}")
        st.button("📏 Calibrate now", type="primary", key="cal_ribbon", on_click=set_tool, args=(T_CAL,),
                  help="Then click both ends of a known dimension on the drawing and type its real length")
        if is_pdf:
            ratio = st.number_input("or drawing scale 1 :", 1.0, 100000.0, 100.0, step=10.0, key=f"mt_ratio_{pkey}",
                                    help="Only valid if the PDF is at its original paper size. Calibrating is safer.")
            if st.button("Apply scale", key=f"mt_ratio_apply_{pkey}"):
                mt["calibration"][pkey] = measure.metres_per_unit_from_scale(ratio)
                st.rerun()
        st.caption("Check any dimension afterwards with Dimension tab → 📐 Check length.")


def ribbon_dimension() -> None:
    mt = ss.mt
    if "pending_tool" in ss:  # set by the File → Import dialog
        ss.mt_tool = ss.pop("pending_tool")
    st.radio("Tool", TOOLS, key="mt_tool", horizontal=True, label_visibility="collapsed",
             help="Measure the active item · Select similar objects · Check a length or area without billing it · Select/pan · Calibrate")
    c = st.columns([0.01, 3.2, 1, 1, 0.9, 0.9, 1.6])
    if c[2].button("➕ New item", use_container_width=True):
        new_item_dialog()
    if "pending_active" in ss:
        ss.mt_active = ss.pop("pending_active")
    ids = [i["id"] for i in mt["items"]]
    if ss.get("mt_active") not in ids:
        ss.mt_active = ids[-1] if ids else None
    if ids:
        c[1].selectbox("Measuring", ids, format_func=lambda i: item_label(measure.item_by_id(mt, i)), key="mt_active",
                       label_visibility="collapsed")
        if c[3].button("⚙️ Item", use_container_width=True):
            item_dialog(ss.mt_active)
    else:
        c[1].caption("No items yet — click ➕ New item")
    c[4].number_input("× Times", 0.01, 1000.0, 1.0, step=1.0, key="mt_times", label_visibility="collapsed",
                      help="Timesing for the next measurements, e.g. 4 for four identical floors")
    c[5].toggle("Deduct", False, key="mt_deduct", help="Next measurements are subtracted (openings)")
    c[6].text_input("Location", key="mt_loc", placeholder="Location / wall ref", label_visibility="collapsed",
                    help="Grid or location; for blockwork, the wall reference (e.g. W-01)")


def item_params_form(item: dict | None) -> None:
    if item is None:
        return
    with st.form(f"item_params_{item['id']}_{ss.mt_ver}"):
        st.markdown(f"**{item['ref']}** · {item_label(item)}")
        desc = st.text_input("Description", item["description"])
        values = {}
        if measure.is_assembly(item):
            st.caption(asm.TEMPLATES[item["assembly"]]["help"])
            params = {**asm.TEMPLATES[item["assembly"]]["params"], **item.get("params", {})}
            cols = st.columns(2)
            for i, (key, value) in enumerate(params.items()):
                values[key] = cols[i % 2].number_input(asm.PARAM_LABELS.get(key, key), value=float(value), step=0.05, format="%.3f")
        else:
            a, b = st.columns(2)
            values["width"] = a.number_input("Width / height (m)", 0.0, 1000.0, float(item["width"]), 0.05, disabled=item["type"] != "Length")
            values["depth"] = b.number_input("Depth / thickness (m)", 0.0, 1000.0, float(item["depth"]), 0.05, disabled=item["type"] == "Count")
        if st.form_submit_button("Save", type="primary"):
            item["description"] = desc.strip() or item["description"]
            if measure.is_assembly(item):
                item["params"] = values
            else:
                item.update(values)
            ss.mt_ver += 1
            st.rerun()
    if item.get("assembly") == "blockwork_wall":
        st.caption("Doors and windows for this wall type are assigned in 🗂️ Dimension Group View → Openings.")


def ribbon_workbook() -> None:
    mt = ss.mt
    lines = measure.boq_lines(mt)
    c = st.columns([1.3, 1.4, 1.2, 1.2, 1.4, 2])
    if c[0].button("📤 Send to BOQ", type="primary", use_container_width=True, disabled=lines.empty):
        send_takeoff_to_boq()
    c[1].download_button("⬇️ QTO workbook", full_export(lines.drop(columns="Key")) if not lines.empty else b"",
                         file_name="QTO_workbook.xlsx", mime=XLSX_MIME, disabled=lines.empty, use_container_width=True,
                         help="Dimension sheet, derived items with formulas, wall schedule and a linked BOQ")
    c[2].download_button("💾 Take-off", measure.to_json(mt), file_name="takeoff.qto.json", mime="application/json",
                         disabled=not mt["items"], use_container_width=True, help="Only the take-off; File → Save keeps everything")
    with c[3].popover("📂 Take-off", use_container_width=True):
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
    c[4].button("💰 Price from library", use_container_width=True, on_click=go_to, args=(NAV[8],))
    split = c[5].toggle("Separate lines per building", mt.get("split_buildings", True), key=f"wb_split_{ss.mt_ver}")
    if split != mt.get("split_buildings", True):
        mt["split_buildings"] = split
        ss.mt_ver += 1
        st.rerun()


# ------------------------------------------------------------------ views: on-screen take-off

@st.cache_data(show_spinner="Finding drawing objects…", max_entries=8)
def cached_objects(data: bytes, name: str, page: int) -> list[dict]:
    """Blocks and paths of a CAD-based drawing, in drawing units, for 'select similar'."""
    if name.lower().endswith(".dxf"):
        return dxf_takeoff.drawing_objects(dxf_takeoff.takeoff(data, None, True))
    if name.lower().endswith(".pdf"):
        return pdf_takeoff.drawing_objects(data, page)
    return []


def select_similar(mt: dict, item: dict, doc: str, page: int, data: bytes, event: dict, k: float, building: int, level: str) -> str:
    """Measure every object that matches the one clicked: same block, or same layer/pen and size."""
    objects = cached_objects(data, doc, page)
    if not objects:
        return "Select similar needs a CAD-based drawing (DXF or vector PDF); scanned images have no objects to match."
    point = (event["point"][0] / k, event["point"][1] / k)
    hit = geometry.pick(objects, point, float(event.get("tol", 12)) / k)
    if hit is None:
        return "Nothing found under the click — zoom in and click directly on a line, block or outline."
    matches = [o for o in objects if geometry.similar(hit, o)]
    existing = {tuple(map(tuple, s["points"])) for s in mt["shapes"] if s["item_id"] == item["id"] and s["doc"] == doc and s["page"] == page}
    extra = {"timesing": float(ss.get("mt_times", 1.0)), "deduct": bool(ss.get("mt_deduct")), "location": ss.get("mt_loc", "")}
    added = 0
    if item["type"] == "Count":
        points = [[round(o["center"][0], 3), round(o["center"][1], 3)] for o in matches]
        if tuple(map(tuple, points)) not in existing:
            measure.add_shape(mt, item["id"], doc, page, points, building=building, level=level).update(extra)
            added = len(points)
    else:
        for o in matches:
            if item["type"] == "Area" and not o["closed"]:
                continue
            pts = [list(p) for p in o["pts"]] + ([list(o["pts"][0])] if item["type"] == "Length" and o["closed"] else [])
            pts = [[round(x, 3), round(y, 3)] for x, y in pts]
            if tuple(map(tuple, pts)) in existing:
                continue
            measure.add_shape(mt, item["id"], doc, page, pts, building=building, level=level).update(extra)
            added += 1
    if not added:
        return f"No new objects added — matching {hit['label']} objects are already measured for {item['ref']}."
    what = {"Count": "nr", "Length": "runs", "Area": "areas"}[item["type"]]
    return f"Added {added} {what} matching {hit['label']} to {item['ref']} {item['description']}"


def guides_for(mt: dict, doc: str, page: int, k: float, mpu: float | None) -> list[dict]:
    """Extended outlines of foundation assemblies: footing face, blinding edge (dashed) and excavation edge (dotted)."""
    if not mpu:
        return []
    u = 1.0 / mpu  # drawing units per metre
    g = {**asm.GLOBALS, **mt.get("globals", {})}
    bo = [g[f"bo_{s}"] for s in ("left", "right", "top", "bottom")]
    eo = [g[f"eo_{s}"] for s in ("left", "right", "top", "bottom")]
    from_blinding = g["offset_from"] == "Blinding edge"
    ex = [(b if from_blinding else 0.0) + e for b, e in zip(bo, eo)]
    bo_avg, ex_avg = sum(bo) / 4, sum(ex) / 4
    styles = {"face": ("#475569", [2, 3]), "blinding": ("#0ea5e9", [7, 4]), "excavation": ("#f97316", [2, 5])}
    out = []

    def add(points, kind, closed=True):
        if points:
            color, dash = styles[kind]
            out.append({"points": [[x * k, y * k] for x, y in points], "closed": closed, "color": color, "dash": dash})

    for s in mt["shapes"]:
        if s["doc"] != doc or s["page"] != page or s.get("deduct"):
            continue
        it = measure.item_by_id(mt, s["item_id"])
        if not it or not it.get("visible", True) or not measure.is_assembly(it):
            continue
        p = {**asm.TEMPLATES[it["assembly"]]["params"], **it.get("params", {})}
        pts = [tuple(q) for q in s["points"]]
        kind = it["assembly"]
        if kind == "isolated_footing":
            L, W = p["L"] * u, p["W"] * u
            for c in pts:
                add(geometry.rectangle(c, L, W), "face")
                add(geometry.rectangle(c, L, W, [b * u for b in bo]), "blinding")
                add(geometry.rectangle(c, L, W, [e * u for e in ex]), "excavation")
        elif kind in ("combined_footing", "raft") and len(pts) > 2:
            add(geometry.offset_polygon(pts, bo_avg * u), "blinding")
            add(geometry.offset_polygon(pts, ex_avg * u), "excavation")
        elif kind == "strip_footing" and len(pts) > 1:
            add(geometry.outline_around(pts, p["W"] / 2 * u), "face")
            add(geometry.outline_around(pts, (p["W"] / 2 + bo_avg) * u), "blinding")
            add(geometry.outline_around(pts, (p["W"] / 2 + ex_avg) * u), "excavation")
        elif kind == "grade_beam" and len(pts) > 1:
            add(geometry.outline_around(pts, p["b"] / 2 * u), "face")
            add(geometry.outline_around(pts, (p["b"] / 2 + bo_avg) * u), "blinding")
            if p.get("trench", 1.0):
                add(geometry.outline_around(pts, (p["b"] / 2 + ex_avg) * u), "excavation")
        if len(out) > 3000:
            break
    return out


def view_drawing() -> None:
    mt = ss.mt
    doc, page = current_drawing()
    if doc is None:
        st.info("**Start here:** Drawings tab → 📂 Drawings → add a PDF, DXF or scanned plan, or ✨ Load sample plan. "
                "Then Dimension tab → ➕ New item (e.g. *Isolated footing*), and click on the drawing.")
        return
    data = ss.files[doc]
    is_pdf = doc.lower().endswith(".pdf")
    detail = ss.get("mt_dpi", "Standard")
    try:
        image_url, k, snap, known_scale = cached_measure_image(data, doc, page, {"Standard": 110, "Fine": 160, "Draft": 72}[detail])
    except Exception as exc:
        st.error(f"Could not open this drawing for measuring: {exc}")
        return
    pkey = measure.page_key(doc, page)
    if known_scale and pkey not in mt["calibration"]:
        mt["calibration"][pkey] = known_scale  # DXF coordinates are real-world, so the scale is exact
    mpu = mt["calibration"].get(pkey)
    active = measure.item_by_id(mt, ss.get("mt_active")) if ss.get("mt_active") else None
    tool = ss.get("mt_tool", T_MEASURE)
    building, level = ss.get("mt_building", 1), ss.get("mt_level", "")

    if ss.mt_calibration_pts:
        a, b, c = st.columns([3, 1, 1])
        known = a.number_input("📏 Real length of the line you clicked (m)", 0.001, 100000.0, 5.0, step=0.1, key="mt_known")
        b.write("")
        if b.button("✔ Set scale", type="primary", key="mt_cal_ok"):
            mt["calibration"][pkey] = measure.calibrate(ss.mt_calibration_pts, known)
            ss.mt_calibration_pts = None
            st.rerun()
        c.write("")
        if c.button("Cancel", key="mt_cal_cancel"):
            ss.mt_calibration_pts = None
            st.rerun()
    elif not mpu and tool != T_CAL:
        a, b, c = st.columns([3, 1.2, 1.6])
        a.warning("**This drawing has no scale yet.** Calibrate on a known dimension (recommended) or enter the drawing scale. "
                  "Counts work without a scale.")
        b.write("")
        b.button("📏 Calibrate now", type="primary", key="cal_now", on_click=set_tool, args=(T_CAL,), use_container_width=True)
        if is_pdf:
            ratio = c.number_input("or drawing scale 1 :", 1.0, 100000.0, 100.0, step=10.0, key=f"mt_ratio_v_{pkey}")
            if c.button("Apply scale", key=f"mt_ratio_v_go_{pkey}"):
                mt["calibration"][pkey] = measure.metres_per_unit_from_scale(ratio)
                st.rerun()
    elif tool == T_CAL:
        st.info("📏 **Calibrate:** click both ends of a dimension you know (a grid line or a dimensioned wall), then type its real length.")
    if tool in (T_MEASURE, T_SIMILAR) and not active:
        st.info("Dimension tab → ➕ New item first (e.g. *Isolated footing* or *Blockwork wall*), then click on the drawing.")
    if "sim_msg" in ss:
        st.toast(ss.pop("sim_msg"), icon="🎯")

    modes = {T_CAL: "calibrate", T_LEN: "ruler", T_AREA: "ruler_area", T_SELECT: "select"}
    if tool in modes:
        mode = modes[tool]
    elif active:
        mode = "pick" if tool == T_SIMILAR else measure.CANVAS_MODE[active["type"]]
    else:
        mode = "select"
    show_code = len(mt["buildings"]) > 1
    canvas_shapes = []
    for s in (s for s in mt["shapes"] if s["doc"] == doc and s["page"] == page):
        it = measure.item_by_id(mt, s["item_id"])
        if it and it.get("visible", True):
            code = f" {measure.building_by_id(mt, s.get('building', 1))['code']}" if show_code else ""
            ref = f" {s['location']}" if s.get("location") and it.get("assembly") == "blockwork_wall" else ""
            canvas_shapes.append({
                "id": s["id"], "type": measure.CANVAS_MODE[it["type"]], "color": it["colour"], "deduct": s.get("deduct", False),
                "label": it["ref"] + code + ref + (" (−)" if s.get("deduct") else ""), "points": [[x * k, y * k] for x, y in s["points"]],
            })
    event = measure_canvas(
        image=image_url, image_key=f"{doc}|{page}|{detail}", mode=mode, shapes=canvas_shapes,
        m_per_px=(mpu / k) if mpu else None, color=active["colour"] if active else "#e11d48",
        item=f"{active['ref']} {active['description']}" if active and mode != "calibrate" else "",
        snap=snap, snap_on=ss.get("mt_snap", True), selected=ss.mt_selected, height=int(ss.opts["canvas_height"]), key="mt_canvas",
        guides=guides_for(mt, doc, page, k, mpu) if ss.get("mt_guides", True) else [],
    )
    if event and event.get("id") not in mt["seen"]:
        mt["seen"].append(event["id"])
        points = [[x / k, y / k] for x, y in event.get("points", [])]
        if event["event"] == "add" and active:
            shape = measure.add_shape(mt, active["id"], doc, page, points, building=building, level=level)
            shape.update({"timesing": float(ss.get("mt_times", 1.0)), "deduct": bool(ss.get("mt_deduct")), "location": ss.get("mt_loc", "")})
            ss.mt_selected = shape["id"]
        elif event["event"] == "calibrate":
            ss.mt_calibration_pts = points
        elif event["event"] == "select":
            ss.mt_selected = event["shape"]
        elif event["event"] == "delete":
            mt["shapes"] = [s for s in mt["shapes"] if s["id"] != event["shape"]]
            ss.mt_selected = None
        elif event["event"] == "pick" and active:
            ss.sim_msg = select_similar(mt, active, doc, page, data, event, k, building, level)
        ss.mt_ver += 1
        st.rerun()

    scale_txt = ("—" if not mpu else f"1:{mpu / measure.PT_TO_M:,.0f}" if is_pdf else "exact (DXF)" if doc.lower().endswith(".dxf")
                 else f"{mpu * 1000:.2f} mm/px")
    bname = measure.building_by_id(mt, building)["name"]
    status = (f"<b>Scale</b> {scale_txt} · <b>Building</b> {bname}{' · ' + level if level else ''} · <b>Item</b> "
              f"{item_label(active) if active else '—'} · <b>Tool</b> {tool} · ×{ss.get('mt_times', 1.0):g}"
              f"{' · DEDUCT' if ss.get('mt_deduct') else ''}")
    shape = next((s for s in mt["shapes"] if s["id"] == ss.mt_selected), None)
    if shape:
        it = measure.item_by_id(mt, shape["item_id"])
        qty = measure.quantity(shape, it, mt["calibration"].get(measure.page_key(shape["doc"], shape["page"]))) if it else None
        if it and measure.is_assembly(it):
            base = measure.measured(shape, it, mt["calibration"].get(measure.page_key(shape["doc"], shape["page"])))
            sel = f"{it['ref']}: {'—' if base is None else f'{base:,.3f}'} {measure.item_unit(it['type'], 0, 0)} measured (see 📒 Workbook for derived items)"
        else:
            sel = f"{it['ref']}: {'—' if qty is None else f'{qty:,.3f}'} {measure.item_unit(it['type'], it['width'], it['depth'])}" if it else ""
        status += f" · <b>Selected</b> {sel}"
    a, b = st.columns([6, 1])
    a.markdown(f"<div class='statusbar'>{status}</div>", unsafe_allow_html=True)
    if shape and b.button("🗑️ Delete", key=f"mt_del_{shape['id']}", use_container_width=True):
        mt["shapes"] = [s for s in mt["shapes"] if s["id"] != shape["id"]]
        ss.mt_selected = None
        ss.mt_ver += 1
        st.rerun()


def view_groups() -> None:
    """Dimension groups: buildings and levels → take-off items and their parameters → openings → measurements."""
    mt = ss.mt
    sheet = measure.qto_sheet(mt)

    st.markdown("#### 🏢 Buildings and levels")
    st.caption("Heights and depths are calculated from these levels. Blank start level = NGL; blank BGB = start level.")
    counts = {b["name"]: int((sheet["Building"] == b["name"]).sum()) for b in mt["buildings"]}
    rows = [{"Code": b["code"], "Building": b["name"], "Measurements": counts[b["name"]], **{k: b["levels"].get(k) for k in asm.LEVELS}}
            for b in mt["buildings"]]
    level_cfg = {k: st.column_config.NumberColumn(asm.LEVEL_LABELS[k], format="%.3f", step=0.05) for k in asm.LEVELS}
    frame = pd.DataFrame(rows).astype({k: float for k in asm.LEVELS})  # blank levels become NaN, not text
    edited_b = st.data_editor(frame, key=f"mt_buildings_{ss.mt_ver}", hide_index=True, disabled=["Code", "Measurements"],
                              column_config={"Building": st.column_config.TextColumn(width="medium", required=True), **level_cfg})
    changed = False
    for b, (_, r) in zip(mt["buildings"], edited_b.iterrows()):
        name = str(r["Building"] or "").strip()
        if name and name != b["name"]:
            b["name"], changed = name, True
        for key in asm.LEVELS:
            value = None if pd.isna(r[key]) else float(r[key])
            if key in ("NGL", "FFL", "soffit") and value is None:
                value = asm.LEVELS[key]
            if b["levels"].get(key) != value:
                b["levels"][key], changed = value, True
    if changed:
        ss.mt_ver += 1
        st.rerun()
    empty = [b for b in mt["buildings"] if counts[b["name"]] == 0]
    if len(mt["buildings"]) > 1 and empty:
        with st.popover("🗑️ Remove empty building"):
            gone = st.selectbox("Building", [b["id"] for b in empty], format_func=lambda i: measure.building_by_id(mt, i)["name"])
            if st.button("Remove", key="mt_rm_building"):
                measure.delete_building(mt, gone)
                ss.mt_ver += 1
                st.rerun()

    st.markdown("#### 🗂️ Dimension groups")
    if not mt["items"]:
        st.caption("No take-off items yet. Dimension tab → ➕ New item.")
        return
    totals = measure.group_totals(mt)
    rows = []
    for it in mt["items"]:
        part = totals[totals["Item"] == it["ref"]]
        rows.append({
            "Show": bool(it.get("visible", True)), "Ref": it["ref"], "Description": it["description"],
            "Template": asm.TEMPLATES[it["assembly"]]["label"] if measure.is_assembly(it) else "Simple",
            "Discipline": it["discipline"], "Work Section": it["section"], "Type": it["type"],
            "Measurements": int(part["Measurements"].sum()), "Measured": round(float(part["Quantity"].sum()), 3),
            "Unit": measure.item_unit(it["type"], 0 if measure.is_assembly(it) else it["width"], 0 if measure.is_assembly(it) else it["depth"]),
        })
    edited_items = st.data_editor(
        pd.DataFrame(rows), key=f"mt_items_{ss.mt_ver}", hide_index=True, num_rows="dynamic",
        disabled=["Ref", "Template", "Type", "Measurements", "Measured", "Unit"],
        column_config={
            "Show": st.column_config.CheckboxColumn(help="Show this group on the drawing", width="small"),
            "Discipline": st.column_config.SelectboxColumn(options=dz.DISCIPLINES, required=True),
            "Work Section": st.column_config.SelectboxColumn(options=dz.NRM2_SECTIONS, required=True, width="medium"),
            "Description": st.column_config.TextColumn(width="large"),
            "Measured": st.column_config.NumberColumn(format="%.3f"),
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
        new = {"visible": bool(r["Show"]), "description": str(r["Description"] or it["description"]),
               "discipline": r["Discipline"] or it["discipline"], "section": r["Work Section"] or it["section"]}
        if any(it.get(f) != v for f, v in new.items()):
            it.update(new)
            changed = True
    if changed:
        ss.mt_ver += 1
        st.rerun()

    assemblies_ = [it for it in mt["items"] if measure.is_assembly(it)]
    if assemblies_:
        st.markdown("#### ⚙️ Assembly parameters")
        st.caption("Change a parameter and every derived quantity (excavation, blinding, concrete…) updates without re-measuring.")
        for it in assemblies_:
            spec = asm.TEMPLATES[it["assembly"]]
            with st.expander(f"{it['ref']} · {it['description']} — {spec['label']}"):
                st.caption(spec["help"])
                params = {**spec["params"], **it.get("params", {})}
                table = pd.DataFrame([{"Parameter": asm.PARAM_LABELS.get(k, k), "Value": float(v), "_k": k} for k, v in params.items()])
                edited = st.data_editor(table.set_index("_k"), key=f"ap_{it['id']}_{ss.mt_ver}", disabled=["Parameter"],
                                        column_config={"_index": None, "Value": st.column_config.NumberColumn(format="%.3f", step=0.05)})
                new_params = {k: float(v) for k, v in edited["Value"].items() if pd.notna(v)}
                if new_params != {k: float(v) for k, v in params.items()}:
                    it["params"] = new_params
                    ss.mt_ver += 1
                    st.rerun()
                if it["assembly"] == "blockwork_wall":
                    render_openings(it)

    st.markdown("#### 🌳 By building")
    for b in mt["buildings"]:
        part = sheet[sheet["Building"] == b["name"]]
        with st.expander(f"🏢 {b['name']} ({b['code']}) — {len(part)} measurements", expanded=len(mt["buildings"]) == 1):
            if part.empty:
                st.caption("Nothing measured in this building yet.")
                continue
            for it in mt["items"]:
                rows_it = part[(part["Description"] == it["description"]) & part["BOQ Ref"].str.startswith(it["ref"])]
                if rows_it.empty:
                    continue
                unit = measure.item_unit(it["type"], it["width"], it["depth"])
                st.markdown(f"<span style='color:{it['colour']}'>●</span> **{it['ref']} · {it['description']}** — "
                            f"{rows_it['Quantity'].dropna().sum():,.3f} {unit} ({len(rows_it)} measurements)", unsafe_allow_html=True)
                st.dataframe(rows_it[["Level", "Drawing", "Page", "Location", "Timesing", "Deduct", "Measured", "Quantity"]],
                             hide_index=True, column_config={"Quantity": st.column_config.NumberColumn(format=qfmt()),
                                                             "Measured": st.column_config.NumberColumn(format="%.3f")})


def render_openings(item: dict) -> None:
    """Door/window schedule for a blockwork wall type: each row assigns openings to a wall reference."""
    mt = ss.mt
    refs = sorted({s.get("location", "") for s in mt["shapes"] if s["item_id"] == item["id"] and s.get("location")})
    st.markdown("**Openings (from the door/window schedule)**")
    st.caption("Wall references measured so far: " + (", ".join(refs) if refs else "none — type a wall ref in Location before measuring"))
    table = pd.DataFrame(item.get("openings") or [], columns=["wall_ref", "mark", "width", "height", "qty"])
    table = table.astype({"wall_ref": object, "mark": object, "width": float, "height": float, "qty": float})
    edited = st.data_editor(
        table, key=f"op_{item['id']}_{ss.mt_ver}", num_rows="dynamic", hide_index=True,
        column_config={
            "wall_ref": st.column_config.SelectboxColumn("Wall ref", options=refs or [""], required=True),
            "mark": st.column_config.TextColumn("Mark (D1, W2…)"),
            "width": st.column_config.NumberColumn("Width (m)", min_value=0.0, step=0.05, format="%.3f"),
            "height": st.column_config.NumberColumn("Height (m)", min_value=0.0, step=0.05, format="%.3f"),
            "qty": st.column_config.NumberColumn("Qty", min_value=0, step=1),
        },
    )
    new = [{k: (None if pd.isna(v) else v) for k, v in row.items()} for row in edited.to_dict("records")]
    if new != [{k: (None if pd.isna(v) else v) for k, v in row.items()} for row in table.to_dict("records")]:
        item["openings"] = new
        ss.mt_ver += 1
        st.rerun()
    doors = st.file_uploader("Or import a door/window schedule (columns: wall ref, mark, width, height, qty)", type=["xlsx", "csv"],
                             key=f"op_file_{item['id']}")
    if doors is not None and st.button("Import openings", key=f"op_imp_{item['id']}"):
        sheets = cached_schedule(doors.getvalue(), doors.name)
        frame = next(iter(sheets.values()))
        lower = {str(c).strip().lower(): c for c in frame.columns}
        pick = lambda *names: next((lower[n] for n in names if n in lower), None)  # noqa: E731
        cols = {"wall_ref": pick("wall ref", "wall", "wall reference", "location"), "mark": pick("mark", "type", "ref"),
                "width": pick("width", "w"), "height": pick("height", "h"), "qty": pick("qty", "quantity", "nos", "no")}
        if None in cols.values():
            st.error(f"Columns not found: {', '.join(k for k, v in cols.items() if v is None)}")
        else:
            item["openings"] = [{k: frame.at[i, c] for k, c in cols.items()} for i in frame.index]
            ss.mt_ver += 1
            st.rerun()


def view_workbook() -> None:
    mt = ss.mt
    currency = ss[project.CURRENCY_KEY]
    lines = measure.boq_lines(mt)
    st.markdown("#### 📒 Workbook")
    st.caption("Plain items bill their measured total; ⚙ assembly items bill every derived item. Enter rates here, then Workbook tab → 📤 Send to BOQ.")
    if lines.empty:
        st.caption("No measured quantities yet.")
    else:
        keys = dict(zip(lines["Ref"], lines["Key"]))  # refs are unique; one key can cover several buildings
        view = lines[["Ref", "Description", "Unit", "Quantity", "Rate"]].assign(Amount=(lines["Quantity"] * lines["Rate"]).round(2))
        edited = st.data_editor(
            view, key=f"mt_workbook_{ss.mt_ver}", hide_index=True, disabled=["Ref", "Description", "Unit", "Quantity", "Amount"],
            column_config={
                "Description": st.column_config.TextColumn(width="large"),
                "Quantity": st.column_config.NumberColumn(format=qfmt()),
                "Rate": st.column_config.NumberColumn(f"Rate ({currency})", min_value=0.0, format="%.2f"),
                "Amount": st.column_config.NumberColumn(f"Amount ({currency})", format="%.2f"),
            },
        )
        changed = False
        for ref, old, rate in zip(edited["Ref"], view["Rate"], edited["Rate"]):
            new = float(rate or 0.0)
            if new != float(old or 0.0):
                measure.set_rate(mt, keys[ref], new)  # same item/derived code shares one rate across buildings
                changed = True
        if changed:
            ss.mt_ver += 1
            st.rerun()
        st.metric(f"Workbook total ({currency})", f"{float((lines['Quantity'] * lines['Rate']).sum()):,.2f}")

    derived, _ = measure.derived_items(mt)
    if not derived.empty:
        st.markdown("#### ⚙️ Derived items — formula trace")
        st.dataframe(derived[["Ref", "Building", "Description", "Unit", "Quantity", "Formula"]], hide_index=True,
                     column_config={"Quantity": st.column_config.NumberColumn(format=qfmt()),
                                    "Formula": st.column_config.TextColumn(width="large")})
    walls = measure.wall_schedules(mt)
    if not walls.empty:
        st.markdown("#### 🧱 Wall schedule")
        st.dataframe(walls, hide_index=True)

    st.markdown("#### 📋 QTO dimension sheet")
    st.caption("Every measurement as on a QS dimension sheet. Edit building, level, timesing, deduction or location (wall ref); "
               "delete a row to remove the measurement.")
    sheet = measure.qto_sheet(mt)
    if sheet.empty:
        st.caption("Nothing measured yet.")
        return
    edited_sheet = st.data_editor(
        sheet.set_index("Shape"), key=f"mt_sheet_{ss.mt_ver}", hide_index=True, num_rows="dynamic",
        disabled=[c for c in sheet.columns if c not in ("Building", "Level", "Timesing", "Deduct", "Location", "Shape")],
        column_config={
            "_index": None,
            "Building": st.column_config.SelectboxColumn(options=[b["name"] for b in mt["buildings"]], required=True),
            "Timesing": st.column_config.NumberColumn(min_value=0.01, step=1.0, format="%g"),
            "Deduct": st.column_config.CheckboxColumn(),
            "Measured": st.column_config.NumberColumn(format="%.3f"),
            "Quantity": st.column_config.NumberColumn(format=qfmt()),
        },
    )
    if measure.update_from_sheet(mt, edited_sheet.rename_axis("Shape").reset_index()):
        ss.mt_ver += 1
        st.rerun()


def view_check(issues: pd.DataFrame) -> None:
    st.markdown("#### ✅ Project check")
    errors = int((issues["Severity"] == "Error").sum()) if not issues.empty else 0
    warnings = int((issues["Severity"] == "Warning").sum()) if not issues.empty else 0
    a, b = st.columns(2)
    a.metric("Errors (must fix)", errors)
    b.metric("Warnings (review)", warnings)
    if issues.empty:
        st.success("No problems found.")
    else:
        st.dataframe(issues.sort_values("Severity"), hide_index=True,
                     column_config={"Message": st.column_config.TextColumn(width="large")})
    st.markdown("#### 🧪 Calculation self-test")
    st.caption("The acceptance tests from the specification, run on this server. Every expected value was worked out by hand.")
    results = cached_selftest()
    passed = int(results["Pass"].sum())
    (st.success if passed == len(results) else st.error)(f"{passed} of {len(results)} checks passed")
    st.dataframe(results, hide_index=True, column_config={"Pass": st.column_config.CheckboxColumn()})


# ------------------------------------------------------------------ views: other

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
    edited = measured_editor(objects, f"mesh_{name}_{unit}", ["Object", "Faces", "Watertight"])
    if st.button("➕ Add ticked objects to BOQ", type="primary", key=f"addmesh_{name}"):
        add_to_boq(boq.from_measured(edited, name), name, objects)


def view_auto2d() -> None:
    st.caption("Automatic take-off from CAD layers (DXF) or PDF linework. Add drawings in the Drawings tab → 📂 Drawings.")
    drawings = [n for n in ss.files if n.lower().endswith((".dxf", ".pdf"))]
    if not drawings:
        st.info("No DXF or PDF drawings yet. Drawings tab → 📂 Drawings → add files or ✨ Load sample plan.")
        return
    name = st.selectbox("Drawing", drawings, key="drawing_pick")
    (render_dxf if name.lower().endswith(".dxf") else render_pdf)(name, ss.files[name])


def view_3d() -> None:
    models = st.file_uploader("Upload 3D models (IFC, OBJ, STL, PLY, GLB, OFF)", type=["ifc", *mesh_takeoff.MESH_TYPES],
                              accept_multiple_files=True, key="up_3d")
    if not models:
        st.info("Upload an IFC model exported from Revit, ArchiCAD, Tekla, Civil 3D or Allplan for an element-by-element take-off.")
        return
    name = st.selectbox("Model", [m.name for m in models], key="model_pick")
    payload = next(m for m in models if m.name == name).getvalue()
    (render_ifc if name.lower().endswith(".ifc") else render_mesh)(name, payload)


def view_schedules() -> None:
    st.caption("Upload the quantity schedules for each discipline. Columns are matched automatically.")
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


def view_rates() -> None:
    currency = ss[project.CURRENCY_KEY]
    library = ss.rates
    c1, c2, c3 = st.columns(3)
    c1.metric("Library items", f"{len(library):,}")
    c2.metric("Items with a rate", f"{int((library['Rate'] > 0).sum()):,}")
    c3.metric("Disciplines", library.loc[library["Discipline"] != "", "Discipline"].nunique())
    st.caption("The library is kept only for this browser session — download it to keep it. Matching uses the item code first, "
               "then the closest description with the same unit.")
    up_col, dl_col = st.columns([3, 2])
    rate_file = up_col.file_uploader("Upload a rate library (Excel or CSV)", type=["xlsx", "xls", "csv"], key="up_rates")
    dl_col.write("")
    d1, d2, d3 = dl_col.columns(3)
    d1.download_button("⬇️ Template", rates.to_excel(rates.empty(), currency), file_name="rate_library_template.xlsx",
                       mime=XLSX_MIME, key="rate_tpl")
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
                    if m1.button("➕ Merge into library", type="primary", key="rate_merge"):
                        ss.rates = rates.merge(ss.rates, incoming)
                        ss.rates_ver += 1
                        st.rerun()
                    if m2.button("♻️ Replace library", key="rate_replace"):
                        ss.rates = rates.merge(rates.empty(), incoming)
                        ss.rates_ver += 1
                        st.rerun()
    a1, a2, _ = st.columns([1, 1, 2])
    if a1.button("📥 Save BOQ rates to library", disabled=not (ss.boq["Rate"] > 0).any()):
        ss.rates = rates.merge(ss.rates, rates.from_boq(ss.boq))
        ss.rates_ver += 1
        st.rerun()
    if a2.button("🗑️ Clear library", disabled=library.empty):
        ss.rates = rates.empty()
        ss.rates_ver += 1
        st.rerun()
    edited_library = st.data_editor(
        ss.rates, key=f"rates_editor_{ss.rates_ver}", num_rows="dynamic", hide_index=True, height=420,
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


def view_boq() -> None:
    currency = ss[project.CURRENCY_KEY]
    if ss.boq.empty:
        st.info("The BOQ is empty. Measure in 🖼️ Drawing View and press Workbook → 📤 Send to BOQ, or add from schedules and auto take-off.")
        return
    summ = boq.summary(ss.boq)
    cols = st.columns(len(summ) + 1)
    for col, (_, r) in zip(cols, summ.iterrows()):
        col.metric(f"{dz.DISCIPLINE_ICONS.get(r['Discipline'], '•')} {r['Discipline']}", f"{r['Amount']:,.2f}", f"{r['Items']} items", delta_color="off")
    cols[-1].metric(f"Grand total ({currency})", f"{ss.boq['Amount'].sum():,.2f}")
    with st.expander("💰 Price from rate library", expanded=ss.rate_report is not None):
        if (ss.rates["Rate"] > 0).sum() == 0:
            st.info("Your rate library has no rates yet. Upload one in 💰 Rate Library.")
        else:
            p1, p2, p3 = st.columns([2, 1, 1])
            min_score = p1.slider("Minimum description match", 50, 100, 80, step=5, format="%d%%")
            overwrite = p2.checkbox("Replace rates already entered", False)
            p3.write("")
            if p3.button("💰 Apply rates", type="primary"):
                ss.boq, ss.rate_report = rates.apply(ss.boq, ss.rates, min_score / 100, overwrite)
                ss.boq_ver += 1
                st.rerun()
        if ss.rate_report is not None:
            st.success(f"Last run priced {len(ss.rate_report)} of {len(ss.boq)} lines.")
            st.dataframe(ss.rate_report.drop(columns="Line"), hide_index=True, height=240)
    edited = st.data_editor(
        ss.boq, key=f"boq_editor_{ss.boq_ver}", num_rows="dynamic", hide_index=True, height=520,
        column_config={
            "Ref": st.column_config.TextColumn(width="small"),
            "Discipline": st.column_config.SelectboxColumn(options=dz.DISCIPLINES, required=True),
            "Work Section": st.column_config.SelectboxColumn(options=dz.NRM2_SECTIONS, width="medium"),
            "Description": st.column_config.TextColumn(width="large"),
            "Unit": st.column_config.SelectboxColumn(options=sorted(set(dz.UNITS) | set(ss.boq["Unit"])), width="small"),
            "Quantity": st.column_config.NumberColumn(format=qfmt(), min_value=0.0),
            "Rate": st.column_config.NumberColumn(f"Rate ({currency})", format="%.2f", min_value=0.0),
            "Amount": st.column_config.NumberColumn(f"Amount ({currency})", format="%.2f", disabled=True),
            "Source": st.column_config.TextColumn(disabled=True),
        },
    )
    updated = boq.finalise(edited, sort=False)
    if not updated.equals(ss.boq):
        ss.boq = updated
        ss.boq_ver += 1
        st.rerun()
    b1, b2, b3, b4, _ = st.columns(5)
    if b1.button("↕️ Sort by discipline & section"):
        ss.boq = boq.finalise(ss.boq, sort=True)
        ss.boq_ver += 1
        st.rerun()
    if b2.button("🧹 Clear all rates", disabled=not (ss.boq["Rate"] > 0).any()):
        ss.boq = boq.finalise(ss.boq.assign(Rate=0.0), sort=False)
        ss.boq_ver += 1
        ss.rate_report = None
        st.rerun()
    safe = "".join(ch if ch.isalnum() else "_" for ch in ss.p_name).strip("_") or "project"
    b3.download_button("⬇️ Excel BOQ + reports", full_export(ss.boq), file_name=f"{safe}_BOQ.xlsx", mime=XLSX_MIME, type="primary")
    b4.download_button("⬇️ CSV", ss.boq.to_csv(index=False).encode("utf-8-sig"), file_name=f"{safe}_BOQ.csv", mime="text/csv")


def view_dashboard() -> None:
    currency = ss[project.CURRENCY_KEY]
    data = ss.boq
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("BOQ items", f"{len(data):,}")
    c2.metric("Take-off items", len(ss.mt["items"]))
    c3.metric("Measurements", len(ss.mt["shapes"]))
    c4.metric(f"Total ({currency})", f"{float(data['Amount'].sum()):,.2f}")
    if data.empty:
        steps = [
            ("1 · Drawings", "Drawings tab → 📂 add PDF, DXF or scans (or the sample plan) and set the scale."),
            ("2 · Items", "Dimension tab → ➕ New item: pick an assembly such as Isolated footing or Blockwork wall."),
            ("3 · Measure", "Click on the drawing. Excavation, blinding, concrete, formwork, backfill… are generated automatically."),
            ("4 · Check & bill", "✅ Project Check, then Workbook → 📤 Send to BOQ, price it and export to Excel."),
        ]
        for col, (title, text) in zip(st.columns(4), steps):
            col.markdown(f'<div class="card"><h4>{title}</h4><p>{text}</p></div>', unsafe_allow_html=True)
        return
    left, right = st.columns(2)
    items = data.groupby(["Discipline", "Work Section"]).size().reset_index(name="Items")
    left.plotly_chart(px.sunburst(items, path=["Discipline", "Work Section"], values="Items", title="Items by discipline and work section",
                                  color_discrete_sequence=BOLD).update_layout(margin=CHART_MARGIN, height=420), key="sunburst")
    summ = boq.summary(data)
    fig = (px.bar(summ, x="Discipline", y="Amount", text_auto=",.0f", title=f"Cost by discipline ({currency})", color="Discipline",
                  color_discrete_sequence=BOLD) if summ["Amount"].sum() > 0 else
           px.bar(summ, x="Discipline", y="Items", text_auto=True, title="Items by discipline", color="Discipline", color_discrete_sequence=BOLD))
    right.plotly_chart(fig.update_layout(showlegend=False, margin=CHART_MARGIN, height=420), key="disc_bar")


# ------------------------------------------------------------------ layout: left rail, title bar, ribbon, working area

issues = measure.check_project(ss.mt)
issue_count = int((issues["Severity"] == "Error").sum()) if not issues.empty else 0

with st.sidebar:
    st.markdown("## 📐 QTO Studio")
    st.caption(f"v{__version__} · {ss.p_standard}" + (f" · 👤 {ss.account['name']}" if ss.account.get("name") else ""))
    if "project_msg" in ss:
        st.toast(ss.pop("project_msg"), icon="📁")
    st.radio("View", NAV, key="nav", label_visibility="collapsed")
    st.divider()
    st.markdown(f"**📁 {ss.p_name}**")
    for b in ss.mt["buildings"]:
        lv = b["levels"]
        st.caption(f"🏢 {b['name']} · NGL {lv['NGL']:+.3f}")
    st.caption(f"{len(ss.mt['items'])} items · {len(ss.mt['shapes'])} measurements · {len(ss.boq)} BOQ lines")
    if issue_count:
        st.error(f"{issue_count} error(s) — see ✅ Project Check")
    st.caption("The free server keeps nothing: File → 💾 Save before closing.")

doc_name, page_no = current_drawing()
st.markdown(f"<div class='titlebar'><b>📐 QTO Studio</b><span>{ss.p_name}</span><span>·</span><span>{ss.nav}</span>"
            f"<span>·</span><span>{doc_name or 'no drawing'}{f' p{page_no + 1}' if doc_name else ''}</span></div>", unsafe_allow_html=True)

r_file, r_home, r_draw, r_dim, r_wb = st.tabs(["File", "Home", "Drawings", "Dimension", "Workbook"])
with r_file:
    ribbon_file()
with r_home:
    ribbon_home(issue_count)
with r_draw:
    ribbon_drawings()
with r_dim:
    ribbon_dimension()
with r_wb:
    ribbon_workbook()

view = ss.nav
if view == NAV[0]:
    view_drawing()
elif view == NAV[1]:
    view_workbook()
elif view == NAV[2]:
    view_groups()
elif view == NAV[3]:
    view_check(issues)
elif view == NAV[4]:
    view_auto2d()
elif view == NAV[5]:
    view_3d()
elif view == NAV[6]:
    view_schedules()
elif view == NAV[7]:
    view_rates()
elif view == NAV[8]:
    view_boq()
else:
    view_dashboard()
