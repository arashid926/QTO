"""Disciplines, RICS NRM2 work sections and the rules used to classify take-off items."""

from __future__ import annotations

import re

DISCIPLINES = ["Architectural", "Structural", "Civil", "MEP", "Infrastructure"]

DISCIPLINE_ICONS = {
    "Architectural": "🏛️",
    "Structural": "🏗️",
    "Civil": "🚜",
    "MEP": "⚡",
    "Infrastructure": "🛣️",
}

DISCIPLINE_CODES = {
    "Architectural": "A",
    "Structural": "S",
    "Civil": "C",
    "MEP": "M",
    "Infrastructure": "I",
}

UNCLASSIFIED = "00 To be classified"

NRM2_SECTIONS = [
    UNCLASSIFIED,
    "01 Preliminaries",
    "02 Off-site manufactured materials, components and buildings",
    "03 Demolitions",
    "04 Alterations, repairs and conservation",
    "05 Excavating and filling",
    "06 Ground remediation and soil stabilisation",
    "07 Piling",
    "08 Underpinning",
    "09 Diaphragm walls and embedded retaining walls",
    "10 Crib walls, gabions and reinforced earth",
    "11 In-situ concrete works",
    "12 Precast/composite concrete",
    "13 Precast concrete",
    "14 Masonry",
    "15 Structural metalwork",
    "16 Carpentry",
    "17 Sheet roof coverings",
    "18 Tile and slate roof and wall coverings",
    "19 Waterproofing",
    "20 Proprietary linings and partitions",
    "21 Cladding and covering",
    "22 General joinery",
    "23 Windows, screens and lights",
    "24 Doors, shutters and hatches",
    "25 Stairs, walkways and balustrades",
    "26 Metalwork",
    "27 Glazing",
    "28 Floor, wall, ceiling and roof finishings",
    "29 Decoration",
    "30 Suspended ceilings",
    "31 Insulation, fire stopping and fire protection",
    "32 Furniture, fittings and equipment",
    "33 Drainage above ground",
    "34 Drainage below ground",
    "35 Site works",
    "36 Fencing",
    "37 Soft landscaping",
    "38 Mechanical services",
    "39 Electrical services",
    "40 Transportation",
    "41 Builder's work in connection with services",
]

# What can be measured for an item, and the column that holds each measure in take-off tables.
MEASURE_COLUMNS = {
    "Count": "Count",
    "Length": "Length (m)",
    "Area": "Area (m²)",
    "Volume": "Volume (m³)",
    "Weight": "Weight (kg)",
}
MEASURE_UNITS = {"Count": "nr", "Length": "m", "Area": "m²", "Volume": "m³", "Weight": "kg"}
# Optional take-off columns: Factor (e.g. 0.5 for walls drawn as two lines) and a second dimension
# that turns a length into an area (wall height) or an area into a volume (slab thickness).
DIM_COLUMN = "× Height/Thk (m)"
NEXT_UNIT = {"m": "m²", "m²": "m³"}
UNITS = ["nr", "m", "m²", "m³", "kg", "t", "item", "sum", "hr", "day", "week"]

# Keywords matched case-insensitively inside layer, block, object or description names.
# Order matters: the first match wins, so specific words come before general ones.
KEYWORD_RULES = [
    ("CURTAIN", "Architectural", "21 Cladding and covering"),
    ("PILE", "Structural", "07 Piling"),
    ("FOUNDATION", "Structural", "11 In-situ concrete works"),
    ("FOOTING", "Structural", "11 In-situ concrete works"),
    ("RAFT", "Structural", "11 In-situ concrete works"),
    ("COLUMN", "Structural", "11 In-situ concrete works"),
    ("BEAM", "Structural", "11 In-situ concrete works"),
    ("SLAB", "Structural", "11 In-situ concrete works"),
    ("CONCRETE", "Structural", "11 In-situ concrete works"),
    ("REBAR", "Structural", "11 In-situ concrete works"),
    ("REINF", "Structural", "11 In-situ concrete works"),
    ("FORMWORK", "Structural", "11 In-situ concrete works"),
    ("PRECAST", "Structural", "13 Precast concrete"),
    ("STEEL", "Structural", "15 Structural metalwork"),
    ("TRUSS", "Structural", "15 Structural metalwork"),
    ("EXCAV", "Civil", "05 Excavating and filling"),
    ("BACKFILL", "Civil", "05 Excavating and filling"),
    ("EARTH", "Civil", "05 Excavating and filling"),
    ("GRADING", "Civil", "05 Excavating and filling"),
    ("DEMOL", "Civil", "03 Demolitions"),
    ("RETAINING", "Civil", "09 Diaphragm walls and embedded retaining walls"),
    ("GABION", "Civil", "10 Crib walls, gabions and reinforced earth"),
    ("FENCE", "Civil", "36 Fencing"),
    ("LANDSCAP", "Civil", "37 Soft landscaping"),
    ("TREE", "Civil", "37 Soft landscaping"),
    ("TURF", "Civil", "37 Soft landscaping"),
    ("ROAD", "Infrastructure", "35 Site works"),
    ("PAV", "Infrastructure", "35 Site works"),
    ("KERB", "Infrastructure", "35 Site works"),
    ("CURB", "Infrastructure", "35 Site works"),
    ("ASPHALT", "Infrastructure", "35 Site works"),
    ("PARKING", "Infrastructure", "35 Site works"),
    ("SEWER", "Infrastructure", "34 Drainage below ground"),
    ("STORM", "Infrastructure", "34 Drainage below ground"),
    ("MANHOLE", "Infrastructure", "34 Drainage below ground"),
    ("CULVERT", "Infrastructure", "34 Drainage below ground"),
    ("GULLY", "Infrastructure", "34 Drainage below ground"),
    ("WATER MAIN", "Infrastructure", "34 Drainage below ground"),
    ("DUCT", "MEP", "38 Mechanical services"),
    ("HVAC", "MEP", "38 Mechanical services"),
    ("SPRINK", "MEP", "38 Mechanical services"),
    ("FIRE ALARM", "MEP", "39 Electrical services"),
    ("FIRE", "MEP", "38 Mechanical services"),
    ("SANIT", "MEP", "33 Drainage above ground"),
    ("SOIL", "MEP", "33 Drainage above ground"),
    ("PLUMB", "MEP", "38 Mechanical services"),
    ("PIPE", "MEP", "38 Mechanical services"),
    ("CHILLER", "MEP", "38 Mechanical services"),
    ("PUMP", "MEP", "38 Mechanical services"),
    ("ELEC", "MEP", "39 Electrical services"),
    ("LIGHT", "MEP", "39 Electrical services"),
    ("LUMIN", "MEP", "39 Electrical services"),
    ("CABLE", "MEP", "39 Electrical services"),
    ("POWER", "MEP", "39 Electrical services"),
    ("SOCKET", "MEP", "39 Electrical services"),
    ("SWITCH", "MEP", "39 Electrical services"),
    ("LIFT", "MEP", "40 Transportation"),
    ("ELEVATOR", "MEP", "40 Transportation"),
    ("ESCALATOR", "MEP", "40 Transportation"),
    ("DRAIN", "Infrastructure", "34 Drainage below ground"),
    ("PARTITION", "Architectural", "20 Proprietary linings and partitions"),
    ("DRYWALL", "Architectural", "20 Proprietary linings and partitions"),
    ("GYPSUM", "Architectural", "20 Proprietary linings and partitions"),
    ("WALL", "Architectural", "14 Masonry"),
    ("BLOCK", "Architectural", "14 Masonry"),
    ("BRICK", "Architectural", "14 Masonry"),
    ("MASONRY", "Architectural", "14 Masonry"),
    ("DOOR", "Architectural", "24 Doors, shutters and hatches"),
    ("SHUTTER", "Architectural", "24 Doors, shutters and hatches"),
    ("WINDOW", "Architectural", "23 Windows, screens and lights"),
    ("WIN", "Architectural", "23 Windows, screens and lights"),
    ("GLAZ", "Architectural", "27 Glazing"),
    ("STAIR", "Architectural", "25 Stairs, walkways and balustrades"),
    ("RAIL", "Architectural", "25 Stairs, walkways and balustrades"),
    ("BALUST", "Architectural", "25 Stairs, walkways and balustrades"),
    ("CEIL", "Architectural", "30 Suspended ceilings"),
    ("ROOF", "Architectural", "17 Sheet roof coverings"),
    ("WATERPROOF", "Architectural", "19 Waterproofing"),
    ("INSUL", "Architectural", "31 Insulation, fire stopping and fire protection"),
    ("CLAD", "Architectural", "21 Cladding and covering"),
    ("PAINT", "Architectural", "29 Decoration"),
    ("FLOOR", "Architectural", "28 Floor, wall, ceiling and roof finishings"),
    ("FINISH", "Architectural", "28 Floor, wall, ceiling and roof finishings"),
    ("TILE", "Architectural", "28 Floor, wall, ceiling and roof finishings"),
    ("SKIRT", "Architectural", "28 Floor, wall, ceiling and roof finishings"),
    ("PLASTER", "Architectural", "28 Floor, wall, ceiling and roof finishings"),
    ("SCREED", "Architectural", "28 Floor, wall, ceiling and roof finishings"),
    ("JOINERY", "Architectural", "22 General joinery"),
    ("FURN", "Architectural", "32 Furniture, fittings and equipment"),
    ("FIXTURE", "Architectural", "32 Furniture, fittings and equipment"),
]

# AIA / ISO 13567 style layer prefixes such as "A-WALL", "S-COLS", "E-LITE".
PREFIX_RULES = {
    "A": ("Architectural", UNCLASSIFIED),
    "I": ("Infrastructure", UNCLASSIFIED),
    "S": ("Structural", "11 In-situ concrete works"),
    "C": ("Civil", UNCLASSIFIED),
    "L": ("Civil", "37 Soft landscaping"),
    "M": ("MEP", "38 Mechanical services"),
    "P": ("MEP", "38 Mechanical services"),
    "F": ("MEP", "38 Mechanical services"),
    "E": ("MEP", "39 Electrical services"),
}

# Items usually measured as a number of units rather than length or area.
COUNT_KEYWORDS = (
    "DOOR", "WIN", "COLUMN", "LIGHT", "LUMIN", "SOCKET", "SWITCH", "MANHOLE", "GULLY",
    "FIXTURE", "FURN", "TREE", "PUMP", "PILE", "SANIT", "WC", "BASIN", "DIFFUSER",
)

# Layers that hold annotation, not things to build; unticked by default.
NON_BILL_KEYWORDS = (
    "DIM", "TEXT", "ANNO", "GRID", "TAG", "TITLE", "BORDER", "VPORT", "VIEWPORT",
    "DEFPOINTS", "NOTE", "SYMB", "LEGEND", "XREF", "CENTER", "AXIS",
)

DEFAULT_CLASS = ("Architectural", UNCLASSIFIED)

IFC_CLASS_RULES = {
    "IfcWall": ("Architectural", "14 Masonry"),
    "IfcWallStandardCase": ("Architectural", "14 Masonry"),
    "IfcCurtainWall": ("Architectural", "21 Cladding and covering"),
    "IfcPlate": ("Architectural", "21 Cladding and covering"),
    "IfcDoor": ("Architectural", "24 Doors, shutters and hatches"),
    "IfcWindow": ("Architectural", "23 Windows, screens and lights"),
    "IfcStair": ("Architectural", "25 Stairs, walkways and balustrades"),
    "IfcStairFlight": ("Architectural", "25 Stairs, walkways and balustrades"),
    "IfcRamp": ("Architectural", "25 Stairs, walkways and balustrades"),
    "IfcRampFlight": ("Architectural", "25 Stairs, walkways and balustrades"),
    "IfcRailing": ("Architectural", "25 Stairs, walkways and balustrades"),
    "IfcCovering": ("Architectural", "28 Floor, wall, ceiling and roof finishings"),
    "IfcRoof": ("Architectural", "17 Sheet roof coverings"),
    "IfcSpace": ("Architectural", "28 Floor, wall, ceiling and roof finishings"),
    "IfcFurnishingElement": ("Architectural", "32 Furniture, fittings and equipment"),
    "IfcFurniture": ("Architectural", "32 Furniture, fittings and equipment"),
    "IfcSystemFurnitureElement": ("Architectural", "32 Furniture, fittings and equipment"),
    "IfcSlab": ("Structural", "11 In-situ concrete works"),
    "IfcColumn": ("Structural", "11 In-situ concrete works"),
    "IfcBeam": ("Structural", "11 In-situ concrete works"),
    "IfcFooting": ("Structural", "11 In-situ concrete works"),
    "IfcPile": ("Structural", "07 Piling"),
    "IfcMember": ("Structural", "15 Structural metalwork"),
    "IfcReinforcingBar": ("Structural", "11 In-situ concrete works"),
    "IfcReinforcingMesh": ("Structural", "11 In-situ concrete works"),
    "IfcTendon": ("Structural", "11 In-situ concrete works"),
    "IfcPipeSegment": ("MEP", "38 Mechanical services"),
    "IfcPipeFitting": ("MEP", "38 Mechanical services"),
    "IfcDuctSegment": ("MEP", "38 Mechanical services"),
    "IfcDuctFitting": ("MEP", "38 Mechanical services"),
    "IfcAirTerminal": ("MEP", "38 Mechanical services"),
    "IfcFlowSegment": ("MEP", "38 Mechanical services"),
    "IfcFlowFitting": ("MEP", "38 Mechanical services"),
    "IfcFlowTerminal": ("MEP", "38 Mechanical services"),
    "IfcFlowController": ("MEP", "38 Mechanical services"),
    "IfcFlowMovingDevice": ("MEP", "38 Mechanical services"),
    "IfcEnergyConversionDevice": ("MEP", "38 Mechanical services"),
    "IfcPump": ("MEP", "38 Mechanical services"),
    "IfcValve": ("MEP", "38 Mechanical services"),
    "IfcUnitaryEquipment": ("MEP", "38 Mechanical services"),
    "IfcFireSuppressionTerminal": ("MEP", "38 Mechanical services"),
    "IfcSanitaryTerminal": ("MEP", "33 Drainage above ground"),
    "IfcCableSegment": ("MEP", "39 Electrical services"),
    "IfcCableCarrierSegment": ("MEP", "39 Electrical services"),
    "IfcCableFitting": ("MEP", "39 Electrical services"),
    "IfcLightFixture": ("MEP", "39 Electrical services"),
    "IfcLamp": ("MEP", "39 Electrical services"),
    "IfcOutlet": ("MEP", "39 Electrical services"),
    "IfcSwitchingDevice": ("MEP", "39 Electrical services"),
    "IfcElectricDistributionBoard": ("MEP", "39 Electrical services"),
    "IfcTransportElement": ("MEP", "40 Transportation"),
    "IfcEarthworksCut": ("Civil", "05 Excavating and filling"),
    "IfcEarthworksFill": ("Civil", "05 Excavating and filling"),
    "IfcGeographicElement": ("Civil", "37 Soft landscaping"),
    "IfcCivilElement": ("Civil", "35 Site works"),
    "IfcCourse": ("Infrastructure", "35 Site works"),
    "IfcPavement": ("Infrastructure", "35 Site works"),
    "IfcKerb": ("Infrastructure", "35 Site works"),
    "IfcTrackElement": ("Infrastructure", "35 Site works"),
    "IfcRail": ("Infrastructure", "35 Site works"),
    "IfcBuildingElementProxy": DEFAULT_CLASS,
}

IFC_PRIMARY_MEASURE = {
    "IfcWall": "Area",
    "IfcWallStandardCase": "Area",
    "IfcCurtainWall": "Area",
    "IfcPlate": "Area",
    "IfcCovering": "Area",
    "IfcRoof": "Area",
    "IfcSpace": "Area",
    "IfcSlab": "Volume",
    "IfcColumn": "Volume",
    "IfcBeam": "Volume",
    "IfcFooting": "Volume",
    "IfcEarthworksCut": "Volume",
    "IfcEarthworksFill": "Volume",
    "IfcCourse": "Area",
    "IfcPavement": "Area",
    "IfcPile": "Length",
    "IfcMember": "Length",
    "IfcRailing": "Length",
    "IfcKerb": "Length",
    "IfcPipeSegment": "Length",
    "IfcDuctSegment": "Length",
    "IfcFlowSegment": "Length",
    "IfcCableSegment": "Length",
    "IfcCableCarrierSegment": "Length",
    "IfcReinforcingBar": "Weight",
    "IfcReinforcingMesh": "Weight",
}


def classify(name: str, default: tuple[str, str] = DEFAULT_CLASS) -> tuple[str, str]:
    """Guess (discipline, NRM2 work section) from a layer, block or item name."""
    upper = str(name or "").upper().replace("_", " ")
    for keyword, discipline, section in KEYWORD_RULES:
        if keyword in upper:
            return discipline, section
    match = re.match(r"^([A-Z])[- ]", upper)
    if match and match.group(1) in PREFIX_RULES:
        return PREFIX_RULES[match.group(1)]
    return default


def classify_ifc(ifc_class: str, name: str = "") -> tuple[str, str]:
    """Classify an IFC element by its entity class, falling back to its name."""
    if ifc_class in IFC_CLASS_RULES and IFC_CLASS_RULES[ifc_class] != DEFAULT_CLASS:
        return IFC_CLASS_RULES[ifc_class]
    return classify(name, IFC_CLASS_RULES.get(ifc_class, DEFAULT_CLASS))


def suggest_count(name: str) -> bool:
    upper = str(name or "").upper()
    return any(k in upper for k in COUNT_KEYWORDS)


def is_annotation(name: str) -> bool:
    upper = str(name or "").upper()
    return upper in ("0", "DEFPOINTS") or any(k in upper for k in NON_BILL_KEYWORDS)


def pretty_name(name: str) -> str:
    """'A-FLOOR-FINISH' -> 'Floor Finish', 'DOOR_900' -> 'Door 900'."""
    text = re.sub(r"^[A-Z]{1,2}[-_](?=[A-Za-z])", "", str(name or "").strip())
    text = re.sub(r"[-_|$]+", " ", text).strip()
    return text.title() if text.isupper() or text.islower() else text or str(name)


def section_number(section: str) -> str:
    match = re.match(r"^(\d{2})", str(section or ""))
    return match.group(1) if match else "00"
