"""QTO Studio — quantity take-off from 2D drawings, 3D models and schedules.

Run with:  streamlit run app.py
"""

from __future__ import annotations

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from qto import __version__, boq, dxf_takeoff, ifc_takeoff, mesh_takeoff, pdf_takeoff, samples, schedules
from qto import disciplines as dz

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

ss = st.session_state
ss.setdefault("boq", boq.empty())
ss.setdefault("boq_ver", 0)
ss.setdefault("details", {})


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
def cached_pdf_image(data: bytes, page: int, crop: tuple):
    return pdf_takeoff.render_page(data, page, crop)


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
    }
    for column in measures:
        config[column] = st.column_config.NumberColumn(format="%.0f" if column == M["Count"] else "%.2f")
    view = table[["Bill", "Discipline", "Work Section", "Measure", "Description", *info_columns, *measures]]
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

    view_col, table_col = st.columns([3, 2])
    view_col.image(cached_pdf_image(data, page, crop), caption=f"{name} — page {page + 1}")
    vectors = cached_pdf_vectors(data, page, scale, crop)
    with table_col:
        st.markdown("#### Linework by colour and weight")
        if vectors.empty:
            st.warning("No vector linework found. This page is probably a scanned image — use a vector PDF or DXF.")
        else:
            st.caption("CAD layers usually plot in distinct colours/weights. Tick the groups to bill.")
            edited = measured_editor(vectors, f"pdfv_{name}_{page}_{scale}_{crop}", ["Colour", "Line width"])
            if st.button("➕ Add ticked linework to BOQ", type="primary", key=f"addpdf_{name}"):
                add_to_boq(boq.from_measured(edited, f"{name} · p{page + 1}"), f"{name} · p{page + 1}", vectors)

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
        ss.boq, ss.details = boq.empty(), {}
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

tab_home, tab_2d, tab_3d, tab_sched, tab_boq = st.tabs(
    ["🏠 Dashboard", "📏 2D Drawings", "🧊 3D Models", "📋 Schedules", "📑 BOQ & Export"]
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
            ("3 · Price", "Enter rates in the BOQ tab. Amounts and totals update instantly."),
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

        b1, b2, b3, _ = st.columns([1, 1, 1, 2])
        if b1.button("↕️ Sort by discipline & section"):
            ss.boq = boq.finalise(ss.boq, sort=True)
            ss.boq_ver += 1
            st.rerun()
        safe_name = "".join(ch if ch.isalnum() else "_" for ch in project["Project"]).strip("_") or "project"
        b2.download_button(
            "⬇️ Excel BOQ",
            boq.to_excel(ss.boq, {k: v for k, v in project.items() if v}, currency, ss.details),
            file_name=f"{safe_name}_BOQ.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            type="primary",
        )
        b3.download_button("⬇️ CSV", ss.boq.to_csv(index=False).encode("utf-8-sig"), file_name=f"{safe_name}_BOQ.csv", mime="text/csv")

st.markdown(
    "<div style='text-align:center;color:#94a3b8;font-size:.85rem;margin-top:2rem'>"
    "QTO Studio · open source · quantities are a measurement aid — always check them against the drawings.</div>",
    unsafe_allow_html=True,
)
