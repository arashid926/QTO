# 📐 QTO Studio

**Quantity take-off from 2D drawings, 3D BIM models and schedules, exported as a priced Bill of Quantities.**
It covers Architectural, Structural, Civil, MEP and Infrastructure works, and classifies items by RICS NRM2 work section.

Built in Python with [Streamlit](https://streamlit.io). It runs in the browser, so you can host it for free from GitHub.

---

## Features

| Input | What you get |
|---|---|
| **DXF drawings** (2D CAD) | Length, closed area and object count **per layer**, block (symbol) counts, text-tag counts (D1, W1…), and an interactive plan preview. Units come from the drawing header and can be overridden. |
| **PDF drawings** (vector) | Scaled linework lengths and areas grouped by **pen colour and line weight** (a proxy for CAD layers), a crop box to leave out title blocks, tag counting across all pages, and **table extraction** for door, window and rebar schedules. |
| **IFC models** (3D BIM: Revit, ArchiCAD, Tekla, Civil 3D…) | Element-by-element take-off from IFC base quantities (volume, area, length, weight), measured from the 3D geometry when quantities are missing. Shows storey, type and material, with filters and charts. |
| **Mesh models** (OBJ, STL, PLY, GLB, OFF) | Volume, surface area and size of each object. |
| **Schedules** (Excel / CSV) | One upload area per discipline. Header rows and columns are detected automatically (Ref, Description, Unit, Qty, Rate, Section), and unit spellings are normalised (sqm → m², nos → nr…). Downloadable templates included. |
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
│   ├── pdf_takeoff.py     # PDF vector measurement, tags, tables
│   ├── ifc_takeoff.py     # IFC BIM take-off
│   ├── mesh_takeoff.py    # OBJ/STL/GLB take-off
│   ├── schedules.py       # Excel/CSV schedule import + templates
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
- Rate library and cost database per region
- Multi-storey DXF sets and revision comparison
- Saving and loading projects

## Disclaimer

QTO Studio is a measurement aid. Always check quantities against the drawings and specifications before tendering.

## License

MIT. See [LICENSE](LICENSE).
