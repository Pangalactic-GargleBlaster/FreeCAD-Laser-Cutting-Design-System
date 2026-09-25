"""Generate the parametric ornamental drawer-front prototype."""

import os
import sys
import contextlib
import io

import FreeCAD as App
import importSVG
import Materials
import Part


SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(SCRIPT_DIR)
PROJECT_ROOT = os.path.dirname(ROOT)
MODULE_DIR = os.path.join(PROJECT_ROOT, "freecad", "DesignSystem")
if MODULE_DIR not in sys.path:
    sys.path.insert(0, MODULE_DIR)

import drawer_relaxation_grid_zero

SHARED_TOOLS_DIR = os.path.join(PROJECT_ROOT, "tools")
if SHARED_TOOLS_DIR not in sys.path:
    sys.path.insert(0, SHARED_TOOLS_DIR)
from set_fcstd_visibility import set_visibility


WOOD_MATERIAL = Materials.MaterialManager().getMaterial(
    "b588224e-e8d6-47ad-ba1f-a058333fd1c6"
)


def add_parameters(doc):
    params = doc.addObject("App::VarSet", "DrawerParameters")
    params.Label = "Drawer Parameters"
    for name, group in (
        ("ply", "Material"),
        ("DrawerClearance", "Clearances"),
        ("SlideStripWidth", "Slides"),
        ("DrawerBoxWidth", "Drawer box"),
        ("DrawerBoxHeight", "Drawer box"),
        ("FaceFrameWidth", "Face frame"),
        ("FaceFrameHeight", "Face frame"),
        ("MaximumFrameSideWidth", "Face frame"),
        ("HandleWidth", "Handle"),
        ("HandleHeight", "Handle"),
        ("MotifHeight", "Engraving"),
    ):
        params.addProperty("App::PropertyLength", name, group)

    params.ply = 5.8
    params.DrawerClearance = 5.0
    params.SlideStripWidth = 25.4
    params.DrawerBoxHeight = 7 * 25.4
    params.HandleWidth = 6 * 25.4
    params.HandleHeight = 2 * 25.4
    params.MotifHeight = 5.5 * 25.4
    params.addProperty("App::PropertyInteger", "TransitionCurveCount", "Engraving")
    params.TransitionCurveCount = 10
    params.addProperty("App::PropertyInteger", "JacobiIterations", "Engraving")
    params.JacobiIterations = 0
    params.setExpression("FaceFrameWidth", "30 in - 4 * ply")
    params.setExpression("FaceFrameHeight", "14 in - 4 * ply")
    params.setExpression("MaximumFrameSideWidth", "2 * ply - DrawerClearance")
    params.setExpression(
        "DrawerBoxWidth", "30 in - 12 * ply - DrawerClearance"
    )
    return params


def import_motif(doc, path, name, label):
    if not os.path.exists(path):
        raise FileNotFoundError(f"Motif SVG not found: {path}")
    before_import = set(obj.Name for obj in doc.Objects)
    with contextlib.redirect_stdout(io.StringIO()):
        importSVG.insert(path, doc.Name)
    imported = [obj for obj in doc.Objects if obj.Name not in before_import and hasattr(obj, "Shape")]
    if not imported:
        raise ValueError(f"SVG contained no importable shapes: {path}")
    source = doc.addObject("Part::Feature", name)
    source.Label = label
    source.ShapeMaterial = WOOD_MATERIAL
    source.Shape = (
        imported[0].Shape
        if len(imported) == 1
        else Part.makeCompound([obj.Shape for obj in imported])
    )
    for obj in imported:
        doc.removeObject(obj.Name)
    return source


def add_drawer_prototype(
    doc, name, label, motif_source, row
):
    part = doc.addObject("App::Part", name)
    part.Label = label

    frame = drawer_relaxation_grid_zero.create_drawer_plane_feature(
        part,
        f"{name}FaceFrame",
        "Face frame",
        "FaceFrame",
        "DrawerParameters.JacobiIterations",
    )
    front = drawer_relaxation_grid_zero.create_drawer_plane_feature(
        part,
        f"{name}DrawerFront",
        "Curved drawer front",
        "DrawerFront",
        "DrawerParameters.JacobiIterations",
    )
    engraving = drawer_relaxation_grid_zero.create_drawer_plane_feature(
        part,
        f"{name}Engraving",
        "Engraving paths",
        "Engraving",
        "DrawerParameters.JacobiIterations",
    )
    engraving.MotifSource = motif_source
    box = drawer_relaxation_grid_zero.create_drawer_plane_feature(
        part,
        f"{name}DrawerBoxEnvelope",
        "Drawer box outer profile",
        "DrawerBoxEnvelope",
        "DrawerParameters.JacobiIterations",
    )
    for feature in (frame, front, engraving, box):
        feature.ShapeMaterial = WOOD_MATERIAL

    if row:
        part.setExpression(
            "Placement.Base.y",
            f"-{row} * (DrawerParameters.FaceFrameHeight + 1 in)",
        )

    if App.GuiUp:
        frame.ViewObject.ShapeColor = (0.76, 0.55, 0.30)
        front.ViewObject.ShapeColor = (0.91, 0.72, 0.43)
        engraving.ViewObject.LineColor = (0.28, 0.12, 0.04)
        engraving.ViewObject.LineWidth = 3.0
        box.ViewObject.LineColor = (0.12, 0.38, 0.78)
        box.ViewObject.LineWidth = 3.0
    return part


def generate(output_path):
    doc = App.newDocument("DrawerPrototype")
    add_parameters(doc)

    shared_folder = os.path.expanduser("~/Desktop/Shared with Agents/Bed")
    motifs = (
        (
            "Rose",
            "Rose",
            import_motif(
                doc,
                os.path.join(shared_folder, "rose.svg"),
                "RoseSource",
                "Rose SVG source (embedded, hidden)",
            ),
        ),
        (
            "Butterfly1",
            "Butterfly 1",
            import_motif(
                doc,
                os.path.join(shared_folder, "Butterfly.svg"),
                "Butterfly1Source",
                "Butterfly 1 SVG source (embedded, hidden)",
            ),
        ),
        (
            "Butterfly2",
            "Butterfly 2",
            import_motif(
                doc,
                os.path.join(shared_folder, "Butterfly2.svg"),
                "Butterfly2Source",
                "Butterfly 2 SVG source (embedded, hidden)",
            ),
        ),
    )
    for row, (motif_name, motif_label, motif_source) in enumerate(motifs):
        add_drawer_prototype(
            doc,
            f"{motif_name}DrawerPrototype",
            f"Large Drawer — {motif_label} Prototype",
            motif_source,
            row,
        )

    notes = doc.addObject("App::FeaturePython", "DesignNotes")
    notes.Label = "Design constraints"
    notes.addProperty("App::PropertyString", "FrameSizing", "Notes")
    notes.addProperty("App::PropertyString", "DrawerSizing", "Notes")
    notes.addProperty("App::PropertyString", "ClearanceRule", "Notes")
    notes.addProperty("App::PropertyString", "HandleRule", "Notes")
    notes.FrameSizing = "30 in - 4*ply by 14 in - 4*ply"
    notes.DrawerSizing = "Width = 30 in - 12*ply - clearance; height is parametric"
    notes.ClearanceRule = "Face opening follows the drawer perimeter at DrawerClearance"
    notes.HandleRule = "Handle cuts only the drawer front; the face frame does not follow it"

    doc.recompute()
    doc.saveAs(output_path)
    App.closeDocument(doc.Name)


if __name__ == "__main__":
    output = os.path.join(ROOT, "prototypes", "DrawerPrototype.FCStd")
    generate(output)
    set_visibility(
        output,
        hidden_names={"RoseSource", "Butterfly1Source", "Butterfly2Source"},
    )
