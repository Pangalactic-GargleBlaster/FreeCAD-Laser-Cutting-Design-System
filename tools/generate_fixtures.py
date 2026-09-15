"""Create the immutable FreeCAD fixture documents.

Run this file with FreeCADCmd, not a standalone Python interpreter. Existing
fixtures are protected unless DESIGN_SYSTEM_OVERWRITE_FIXTURES=1 is set.
"""

import os
import sys
from pathlib import Path

import FreeCAD as App
import Part

if not App.GuiUp:
    raise RuntimeError(
        "Fixture generation requires FreeCAD's GUI so visibility state is saved."
    )

import FreeCADGui as Gui


PROJECT_DIR = Path(__file__).resolve().parent.parent
FIXTURE_DIR = PROJECT_DIR / "fixtures"
ALLOW_OVERWRITE = os.environ.get("DESIGN_SYSTEM_OVERWRITE_FIXTURES") == "1"


def add_panel(doc, name, label, origin, size, plane, color):
    """Add a named PartDesign body containing one rectangular panel."""
    body = doc.addObject("PartDesign::Body", name)
    body.Label = label
    solid = body.newObject("PartDesign::Feature", f"{name}Solid")
    solid.Label = f"{label} solid"
    solid.Shape = Part.makeBox(*size, App.Vector(*origin))
    solid.addProperty("App::PropertyString", "PanelPlane", "Fixture")
    solid.addProperty("App::PropertyLength", "PanelThickness", "Fixture")
    solid.addProperty("App::PropertyString", "FixtureDimensions", "Fixture")
    solid.PanelPlane = plane
    solid.PanelThickness = 10.0
    solid.FixtureDimensions = " x ".join(f"{value:g} mm" for value in size)
    body.ViewObject.Visibility = True
    solid.ViewObject.Visibility = True
    solid.ViewObject.ShapeColor = color
    body.Tip = solid
    return body


def save_fixture(name, build):
    target = FIXTURE_DIR / f"{name}.FCStd"
    if target.exists() and not ALLOW_OVERWRITE:
        raise RuntimeError(
            f"Refusing to overwrite immutable fixture: {target}. "
            "Set DESIGN_SYSTEM_OVERWRITE_FIXTURES=1 only for an intentional rebuild."
        )

    doc = App.newDocument(name)
    try:
        build(doc)
        doc.recompute()
        Gui.activeDocument().activeView().viewAxonometric()
        Gui.activeDocument().activeView().fitAll()
        doc.saveAs(str(target))
    finally:
        App.closeDocument(doc.Name)


def build_corner(doc):
    add_panel(
        doc, "BaseXY", "Base (XY)", (0, 0, 0), (100, 100, 10), "XY", (0.86, 0.67, 0.39)
    )
    add_panel(
        doc, "BackXZ", "Back (XZ)", (0, 0, 10), (100, 10, 90), "XZ", (0.76, 0.55, 0.28)
    )
    add_panel(
        doc, "SideYZ", "Side (YZ)", (0, 10, 10), (10, 90, 90), "YZ", (0.95, 0.78, 0.48)
    )


def build_mismatched(doc):
    add_panel(
        doc,
        "DrawerSideXZ",
        "Drawer side (XZ)",
        (0, 0, 0),
        (100, 10, 30),
        "XZ",
        (0.86, 0.67, 0.39),
    )
    add_panel(
        doc,
        "DrawerFrontYZ",
        "Drawer front (YZ)",
        (100, 0, 0),
        (10, 100, 60),
        "YZ",
        (0.76, 0.55, 0.28),
    )


def build_t(doc):
    add_panel(
        doc,
        "CrossPanelXZ",
        "Cross panel (XZ)",
        (0, 0, 0),
        (100, 10, 100),
        "XZ",
        (0.86, 0.67, 0.39),
    )
    add_panel(
        doc,
        "StemPanelYZ",
        "Stem panel (YZ)",
        (45, 10, 0),
        (10, 90, 100),
        "YZ",
        (0.76, 0.55, 0.28),
    )


BUILDERS = {
    "Corner": build_corner,
    "Mismatched": build_mismatched,
    "T": build_t,
}


FIXTURE_DIR.mkdir(parents=True, exist_ok=True)
requested = [argument for argument in sys.argv[1:] if not argument.endswith(".py")]
requested = requested or list(BUILDERS)
unknown = [name for name in requested if name not in BUILDERS]
if unknown:
    raise RuntimeError(f"Unknown fixture(s): {', '.join(unknown)}")
for fixture_name in requested:
    save_fixture(fixture_name, BUILDERS[fixture_name])
