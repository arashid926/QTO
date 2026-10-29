# 📐 QTO Studio

**Quantity take-off from 2D drawings, 3D BIM models and schedules, exported as a priced Bill of Quantities.**
It covers Architectural, Structural, Civil, MEP and Infrastructure works, and classifies items by RICS NRM2 work section.

Built in Python with [Streamlit](https://streamlit.io). It runs in the browser, so you can host it for free from GitHub.

---

## Features

| Input | What you get |
|---|---|
| **DXF drawings** (2D CAD) | Length, closed area and object count **per layer**, block (symbol) counts, text-tag counts (D1, W1…), and an interactive plan preview. Units come from the drawing header and can be overridden. |
| **On-screen take-off** (PDF, PNG/JPG scans) | Measure directly on the drawing, as in CostX or Bluebeam: set the scale from the drawing ratio or calibrate on a known dimension, then use **count** (points), **length** (runs) and **area** (outlines) tools, with snapping to CAD line ends, Shift for straight lines, zoom and pan. Each take-off item can carry a width/height and a depth/thickness, so a wall run becomes m² and a slab outline becomes m³. Timesing and deductions are supported. Every measurement goes onto a **QTO dimension sheet**, and the exported workbook links each BOQ quantity to that sheet with live formulas. Take-offs can be saved and reopened. |
| **Professional workspace** | Full-width layout with a slim title row and a menu of ribbon tabs: **File · Home · Drawings · Dimension · Workbook · Views** (Drawing, Workbook, Dimension View, Project Check, 2D auto take-off, 3D, Schedules, Rate Library, BOQ & Reports, Dashboard). Tools are icons with their name on hover; quick drawing tools sit at the right of the menu row, and the ribbon can be minimised or the drawing maximised. The **Home** ribbon groups its tools as **Drawing** (open, property, compare revisions), **View** (all / invert / file layers, reset, rotate 90°, zoom extent, zoom area), **Measure** (add group, property, export, +ve / −ve / both, line, manual dimension, accept-all auto count), **Workbooks** (add line from the code library, properties, reports, spelling, recalc, functions: location factor, markup, rounding, subcontractor rates, custom quantities), **Format** and **Administration** (location constants, custom quantities, standard dimensions, code library, rate library, standard zones, standard variables usable in item formulas, units, subcontractor values; saved with the project). |
| **Dimension View** | Left panel with **Drawings · Layers · Model · View** tabs (click a drawing to open it, switch DXF layers on/off) and **Dimensions · Auto Count** tabs: click a dimension group to highlight its measurements on the drawing, or create count groups from every DXF block / PDF mark (D1, W2…) in one click. |
| **Parametric assemblies** | Measure an element once and every related item is generated with a formula trace: isolated, strip and combined footings and rafts (blinding with thickness and per-side offsets; excavation from **NGL to BOF + blinding + extra depth**; working space; earthwork support; dewatering below the water table; compaction; anti-termite treatment; waterproofing; concrete; formwork; rebar; neck columns; backfill; disposal), grade beams, grade slabs (polythene, granular fill, mesh), columns, beams, suspended slabs, bulk excavation, and **blockwork walls with wall references and schedule-driven door/window deductions** (lintels, plaster, paint, wall schedule). Levels are set per building. |
| **Project check and self-test** | Errors and warnings (levels, missing scale, unassigned openings, unusual ratios) plus the specification's acceptance tests, run inside the app. |
| **Projects and buildings** | **➕ New Project** and **📂 Previous** projects, with save and open of a whole project (details, BOQ, rate library, take-off, libraries, drawings and 3D models) as one file. Projects never mix: opening one closes the other, and each keeps its own buildings, drawings and calculations. Every drawing belongs to one building, and the Drawings tab lists only the selected building's drawings. Each take-off is organised by **building** and **level**, with separate or combined BOQ lines per building, and three views: **🖼️ Drawing**, **📒 Workbook** (priced lines and dimension sheet) and **🗂️ Dimension View** (groups and their measurements, highlighted on the drawing). |
| **PDF drawings** (vector) | Scaled linework lengths and areas grouped by **pen colour and line weight** (a proxy for CAD layers), a crop box to leave out title blocks, tag counting across all pages, and **table extraction** for door, window and rebar schedules. |
| **IFC models** (3D BIM: Revit, ArchiCAD, Tekla, Civil 3D…) | Element-by-element take-off from IFC base quantities (volume, area, length, weight), measured from the 3D geometry when quantities are missing. Shows storey, type and material, with filters and charts. |
| **Mesh models** (OBJ, STL, PLY, GLB, OFF) | Volume, surface area and size of each object. |
| **Schedules** (Excel / CSV) | One upload area per discipline. Header rows and columns are detected automatically (Ref, Description, Unit, Qty, Rate, Section), and unit spellings are normalised (sqm → m², nos → nr…). Downloadable templates included, with no preset rates. |
| **Rate library** (Excel / CSV) | Upload your own unit rates, edit them in the app, and download them again as Excel or CSV. Rates are applied to the BOQ by item code, exact description, or closest similar description with the same unit, and a match report shows what was priced. Rates you priced in a BOQ can be saved back to the library for the next project. |
| **BOQ** | An editable, priced bill with automatic references (`S.11.003`) that sorts by discipline and section. It exports to **Excel** with a summary sheet, one bill per discipline with live formulas and section totals, and the raw take-off sheets. CSV export too. |

Every take-off row can be ticked or unticked, reassigned to a discipline or NRM2 section, and switched between **Count / Length / Area / Volume / Weight** before it goes into the BOQ.

## Quick start (Windows, macOS, Linux)

You need Python 3.10–3.12.

```bash
git clone https://github.com/<your-user>/qto-studio.git
cd qto-studio
python -m venv .venv
.venv\Scripts\activate          # Windows   (macOS/Linux: source .venv/bin/activate)
pip install -r requirements.txt
streamlit run app.py
```

The app opens at <http://localhost:8501>. Click **Load sample plan** in the *2D Drawings* tab, or **Try sample** in *Schedules*, to see it work without your own files.

## Publish it online

### Option A: GitHub + Streamlit Community Cloud (free)
1. Push this folder to a new GitHub repository.
2. Go to <https://share.streamlit.io>, sign in with GitHub, click **New app**, pick the repository, and set the main file to `app.py`.
3. You get a public URL like `https://qto-studio.streamlit.app`. Every `git push` redeploys it.

### Option B: your own domain (Docker)
The included `Dockerfile` runs on any container host: Render, Railway, Fly.io, Google Cloud Run, Azure, or a VPS.

```bash
docker build -t qto-studio .
docker run -p 8501:8501 qto-studio
```

Then point your domain at the host.

### Option C: Hugging Face Spaces (free)
Create a Space with the **Docker** SDK and push this repository to it.

## File preparation tips

- **DWG:** save as DXF from AutoCAD, BricsCAD or DraftSight, or convert batches with the free [ODA File Converter](https://www.opendesign.com/guestfiles/oda_file_converter).
- **Layers matter:** well-named layers (`A-WALL`, `S-COLUMN`, `E-LIGHT`, `C-ROAD-KERB`) are classified automatically. Edit the rules in `qto/disciplines.py` to match your office standard.
- **PDF:** use vector PDFs plotted from CAD, not scans, and enter the scale at the PDF's own paper size (1:100 on A1, for example).
- **IFC:** tick *Export base quantities* in Revit or ArchiCAD for exact quantities. Without them, quantities are measured from the geometry and marked "approx."

## Project structure

```
qto-studio/
├── app.py                 # Streamlit interface
├── qto/
│   ├── disciplines.py     # disciplines, NRM2 sections, classification rules
│   ├── dxf_takeoff.py     # DXF lengths / areas / counts
│   ├── pdf_takeoff.py     # PDF vector measurement, legend reading, tags, tables
│   ├── measure.py         # on-screen take-off items + QTO dimension sheet
│   ├── canvas/            # interactive measuring canvas (HTML/JS component)
│   ├── ifc_takeoff.py     # IFC BIM take-off
│   ├── mesh_takeoff.py    # OBJ/STL/GLB take-off
│   ├── schedules.py       # Excel/CSV schedule import + templates
│   ├── rates.py           # rate library import, matching, export
│   ├── boq.py             # BOQ building + Excel export
│   └── samples.py         # demo drawing
├── tests/                 # pytest suite
├── .streamlit/config.toml # theme
├── Dockerfile
└── requirements.txt
```

Run the tests with `pip install pytest` and then `pytest`.

## Roadmap ideas

- Native DWG reading through the ODA converter, when it's installed
- On-screen measuring (click to measure) on PDF pages
- Shared rate libraries per region, saved online
- Multi-storey DXF sets and revision comparison
- Saving and loading projects

## Disclaimer

QTO Studio is a measurement aid. Always check quantities against the drawings and specifications before tendering.

## License

MIT. See [LICENSE](LICENSE).
