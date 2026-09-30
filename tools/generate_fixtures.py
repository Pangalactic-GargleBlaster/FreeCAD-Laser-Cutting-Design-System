"""Create the immutable FreeCAD fixture documents.

Run this file with FreeCAD or FreeCADCmd, not a standalone Python interpreter.
Existing fixtures are protected unless DESIGN_SYSTEM_OVERWRITE_FIXTURES=1 is set.
"""

import os
import sys
from pathlib import Path

import FreeCAD as App
import Part

if App.GuiUp:
    import FreeCADGui as Gui


PROJECT_DIR = Path(__file__).resolve().parent.parent
FIXTURE_DIR = PROJECT_DIR / "fixtures"
ALLOW_OVERWRITE = os.environ.get("DESIGN_SYSTEM_OVERWRITE_FIXTURES") == "1"
sys.path.insert(0, str(PROJECT_DIR / "tools"))
from set_fcstd_visibility import set_visibility


def add_panel(doc, name, label, origin, size, plane, color, rotation=None):
    """Add a named PartDesign body containing one rectangular panel."""
    shape = Part.makeBox(*size, App.Vector(*origin))
    if rotation is not None:
        center, angle = rotation
        shape.rotate(App.Vector(*center), App.Vector(1, 0, 0), angle)
    thickness_axis = {"XY": 2, "XZ": 1, "YZ": 0}[plane[:2]]
    dimensions = " x ".join(f"{value:g} mm" for value in size)
    return add_shape_panel(
        doc, name, label, shape, plane, color, size[thickness_axis], dimensions
    )


def add_shape_panel(doc, name, label, shape, plane, color, thickness, dimensions):
    """Add a panel solid and its fixture metadata to a visible body."""
    body = doc.addObject("PartDesign::Body", name)
    body.Label = label
    solid = body.newObject("PartDesign::Feature", f"{name}Solid")
    solid.Label = f"{label} solid"
    solid.Shape = shape
    solid.addProperty("App::PropertyString", "PanelPlane", "Fixture")
    solid.addProperty("App::PropertyLength", "PanelThickness", "Fixture")
    solid.addProperty("App::PropertyString", "FixtureDimensions", "Fixture")
    solid.PanelPlane = plane
    solid.PanelThickness = thickness
    solid.FixtureDimensions = dimensions
    if App.GuiUp:
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
        if App.GuiUp:
            Gui.activeDocument().activeView().viewAxonometric()
            Gui.activeDocument().activeView().fitAll()
        doc.saveAs(str(target))
        if not App.GuiUp:
            # FreeCADCmd omits GuiDocument.xml, making the saved bodies hidden
            # when the fixture is later opened in FreeCAD's GUI.
            set_visibility(target)
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


def build_angled_pair(doc, angle, seam_y=0):
    """Two full-size panels meet along the first panel's top X-directed line."""
    add_panel(
        doc, "BasePanel", "Base panel (XY)", (0, 0, 0),
        (100, 100, 5), "XY", (0.86, 0.67, 0.39),
    )
    add_panel(
        doc, "AngledPanel", f"Angled panel ({angle:g} deg)",
        (0, seam_y, 5), (100, 100, 5), f"XY rotated {angle:g} deg",
        (0.76, 0.55, 0.28), rotation=((0, seam_y, 5), angle),
    )


def build_acute(doc):
    build_angled_pair(doc, 60)


def build_acute2(doc):
    """A thicker version of Acute, with each 10 mm panel split into two plies."""
    for name, label, z, color in (
        ("BaseLower", "Base lower ply", 0, (0.86, 0.67, 0.39)),
        ("BaseUpper", "Base upper ply", 5, (0.95, 0.78, 0.48)),
    ):
        add_panel(doc, name, label, (0, 0, z), (100, 100, 5), "XY", color)
    for name, label, z, color in (
        ("AngledInner", "Angled inner ply", 10, (0.76, 0.55, 0.28)),
        ("AngledOuter", "Angled outer ply", 15, (0.68, 0.47, 0.24)),
    ):
        add_panel(
            doc, name, label, (0, 0, z), (100, 100, 5),
            "XY rotated 60 deg", color, rotation=((0, 0, 10), 60),
        )


def build_obtuse(doc):
    build_angled_pair(doc, 120)


def build_edge90(doc):
    build_angled_pair(doc, 90)


def build_angled_t(doc):
    build_angled_pair(doc, 60, seam_y=50)


def build_angled_t2(doc):
    """Laminate each T panel from two 5 mm plies."""
    for name, label, z, color in (
        ("BaseLower", "Base lower ply", 0, (0.86, 0.67, 0.39)),
        ("BaseUpper", "Base upper ply", 5, (0.95, 0.78, 0.48)),
    ):
        add_panel(doc, name, label, (0, 0, z), (100, 100, 5), "XY", color)
    for name, label, z, color in (
        ("AngledInner", "Angled inner ply", 10, (0.76, 0.55, 0.28)),
        ("AngledOuter", "Angled outer ply", 15, (0.68, 0.47, 0.24)),
    ):
        add_panel(
            doc, name, label, (0, 50, z), (100, 100, 5),
            "XY rotated 60 deg", color, rotation=((0, 50, 10), 60),
        )


def build_pyramid(doc):
    """Extrude the square and each sloping triangle away from the pyramid."""
    add_panel(
        doc, "BaseSquare", "Base square", (-50, -50, -5),
        (100, 100, 5), "XY", (0.86, 0.67, 0.39),
    )
    corners = (
        App.Vector(-50, -50, 0), App.Vector(50, -50, 0),
        App.Vector(50, 50, 0), App.Vector(-50, 50, 0),
    )
    apex = App.Vector(0, 0, 100)
    inside = App.Vector(0, 0, 25)
    for index, (name, color) in enumerate((
        ("SouthFace", (0.76, 0.55, 0.28)),
        ("EastFace", (0.95, 0.78, 0.48)),
        ("NorthFace", (0.68, 0.47, 0.24)),
        ("WestFace", (0.80, 0.63, 0.35)),
    )):
        first, second = corners[index], corners[(index + 1) % 4]
        face = Part.Face(Part.makePolygon((first, second, apex, first)))
        normal = face.normalAt(0, 0)
        if normal.dot(inside - face.CenterOfMass) > 0:
            normal = -normal
        shape = face.extrude(normal * 5)
        add_shape_panel(
            doc, name, name.replace("Face", " face"), shape,
            "Pyramid triangle", color, 5, "100 mm base x 100 mm rise",
        )


def build_cycle(doc):
    """Build four vertical panels whose butt-joint directions form a loop."""
    add_panel(
        doc,
        "FrontXZ",
        "Front (XZ)",
        (0, 0, 0),
        (100, 10, 100),
        "XZ",
        (0.86, 0.67, 0.39),
    )
    add_panel(
        doc,
        "RightYZ",
        "Right (YZ)",
        (100, 0, 0),
        (10, 100, 100),
        "YZ",
        (0.76, 0.55, 0.28),
    )
    add_panel(
        doc,
        "BackXZ",
        "Back (XZ)",
        (10, 100, 0),
        (100, 10, 100),
        "XZ",
        (0.95, 0.78, 0.48),
    )
    add_panel(
        doc,
        "LeftYZ",
        "Left (YZ)",
        (0, 10, 0),
        (10, 100, 100),
        "YZ",
        (0.68, 0.47, 0.24),
    )


BUILDERS = {
    "Acute": build_acute,
    "Acute2": build_acute2,
    "AngledT": build_angled_t,
    "AngledT2": build_angled_t2,
    "Corner": build_corner,
    "Cycle": build_cycle,
    "Edge90": build_edge90,
    "Mismatched": build_mismatched,
    "Obtuse": build_obtuse,
    "Pyramid": build_pyramid,
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
