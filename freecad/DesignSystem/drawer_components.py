"""Parametric solid components used by the bed's drawer system."""

import FreeCAD as App
import Part

from drawer_relaxation_grid_zero import _handle_cutout, _ornamental_outline
from panel import add_hole_properties, cut_holes


def _rectangle(width, height):
    points = [
        App.Vector(0, 0, 0),
        App.Vector(width, 0, 0),
        App.Vector(width, height, 0),
        App.Vector(0, height, 0),
        App.Vector(0, 0, 0),
    ]
    return Part.Face(Part.makePolygon(points))


def _drawer_front_face(
    width,
    height,
    clearance,
    ply,
    box_width,
    box_height,
    slide_width,
    handle_width,
    handle_height,
    wave_amplitude,
):
    front_edge = 2 * ply
    box_side = (width - box_width) / 2
    maximum_frame_side = max(0.5, front_edge - clearance)
    side_wave = max(0.0, box_side - clearance - maximum_frame_side)
    # Keep the top and bottom scallops visually consistent when the overall
    # face-frame geometry is scaled for the bedside drawers.
    vertical_wave = wave_amplitude
    wire = _ornamental_outline(
        width,
        height,
        front_edge,
        side_wave,
        vertical_wave,
        slide_width,
    )
    handle = _handle_cutout(
        width, height, front_edge, handle_width, handle_height
    )
    return Part.Face(wire).cut(handle), wire


def _transform(shape, axis, x, y, z):
    matrix = App.Matrix()
    if axis == "X":
        # Local width, height, and extrusion map to world Y, Z, and X.
        matrix.A11, matrix.A12, matrix.A13, matrix.A14 = 0, 0, 1, x
        matrix.A21, matrix.A22, matrix.A23, matrix.A24 = 1, 0, 0, y
        matrix.A31, matrix.A32, matrix.A33, matrix.A34 = 0, 1, 0, z
    else:
        # Local width, height, and extrusion map to world X, Z, and Y.
        matrix.A11, matrix.A12, matrix.A13, matrix.A14 = 1, 0, 0, x
        matrix.A21, matrix.A22, matrix.A23, matrix.A24 = 0, 0, 1, y
        matrix.A31, matrix.A32, matrix.A33, matrix.A34 = 0, 1, 0, z
    transformed = shape.copy()
    transformed.transformShape(matrix, False, False)
    return transformed


class DrawerFrontPanelProxy:
    """Build a prototype-derived drawer front or matching face frame."""

    def __init__(self, obj=None):
        if obj is not None:
            obj.Proxy = self

    def execute(self, obj):
        width = obj.FrameWidth.Value
        height = obj.FrameHeight.Value
        thickness = obj.Thickness.Value
        clearance = obj.Clearance.Value
        ply = obj.Ply.Value
        box_width = obj.DrawerBoxWidth.Value
        box_height = obj.DrawerBoxHeight.Value
        slide_width = obj.SlideWidth.Value
        handle_width = obj.HandleWidth.Value
        handle_height = obj.HandleHeight.Value
        wave_amplitude = obj.WaveAmplitude.Value
        if min(
            width,
            height,
            thickness,
            ply,
            box_width,
            box_height,
            wave_amplitude,
        ) <= 0:
            raise ValueError("Drawer component dimensions must be positive.")

        if obj.Kind == "DrawerFront":
            face, _ = _drawer_front_face(
                width,
                height,
                clearance,
                ply,
                box_width,
                box_height,
                slide_width,
                handle_width,
                handle_height,
                wave_amplitude,
            )
        else:
            face = _rectangle(width, height)
            opening_count = 2 if obj.Kind == "DoubleFaceFrame" else 1
            cell_height = height / opening_count
            for index in range(opening_count):
                _, wire = _drawer_front_face(
                    width,
                    cell_height,
                    clearance,
                    ply,
                    box_width,
                    box_height,
                    slide_width,
                    handle_width,
                    handle_height,
                    wave_amplitude,
                )
                opening = Part.Face(
                    wire.makeOffset2D(clearance, 0, False, False, True)
                )
                opening.translate(App.Vector(0, index * cell_height, 0))
                face = face.cut(opening)

        solid = face.extrude(App.Vector(0, 0, thickness))
        shape = _transform(
            solid,
            obj.Axis,
            obj.X.Value,
            obj.Y.Value,
            obj.Z.Value,
        )
        obj.Shape = cut_holes(shape, obj)

    def dumps(self):
        return None

    def loads(self, state):
        return None


class RoundedStripProxy:
    """Build a runner with semicircular noses in its length/height plane."""

    def __init__(self, obj=None):
        if obj is not None:
            obj.Proxy = self

    def execute(self, obj):
        length = obj.Length.Value
        thickness = obj.Thickness.Value
        height = obj.Height.Value
        if min(length, thickness, height) <= 0 or length <= height:
            raise ValueError("Rounded strip dimensions are invalid.")
        solid = _rounded_strip_solid(length, thickness, height)
        shape = _place_strip(
            solid,
            obj.Axis,
            obj.X.Value,
            obj.Y.Value,
            obj.Z.Value,
        )
        obj.Shape = cut_holes(shape, obj)

    def dumps(self):
        return None

    def loads(self, state):
        return None


def _rounded_strip_solid(length, thickness, height, z=0.0):
    radius = height / 2
    center = Part.makeBox(
        length - height,
        thickness,
        height,
        App.Vector(radius, 0, z),
    )
    first = Part.makeCylinder(
        radius,
        thickness,
        App.Vector(radius, 0, z + radius),
        App.Vector(0, 1, 0),
    )
    second = Part.makeCylinder(
        radius,
        thickness,
        App.Vector(length - radius, 0, z + radius),
        App.Vector(0, 1, 0),
    )
    return center.fuse(first).fuse(second)


def _place_strip(solid, axis, x, y, z):
    if axis == "X":
        solid.translate(App.Vector(x, y, z))
        return solid
    matrix = App.Matrix()
    matrix.A11, matrix.A12, matrix.A13, matrix.A14 = 0, 1, 0, x
    matrix.A21, matrix.A22, matrix.A23, matrix.A24 = 1, 0, 0, y
    matrix.A31, matrix.A32, matrix.A33, matrix.A34 = 0, 0, 1, z
    solid.transformShape(matrix, False, False)
    return solid


class ConnectedStripPairProxy:
    """Join the second lamination of two rails with tangent end walls."""

    def __init__(self, obj=None):
        if obj is not None:
            obj.Proxy = self

    def execute(self, obj):
        length = obj.Length.Value
        thickness = obj.Thickness.Value
        height = obj.Height.Value
        separation = obj.Separation.Value
        if min(length, thickness, height, separation) <= 0:
            raise ValueError("Connected strip dimensions must be positive.")
        if length <= height or separation < height:
            raise ValueError("Connected strip proportions are invalid.")
        radius = height / 2
        lower = _rounded_strip_solid(length, thickness, height)
        upper = _rounded_strip_solid(
            length, thickness, height, separation
        )
        # The bridge runs between the two circular centerlines. Its end faces
        # are therefore tangent to both semicircular noses.
        bridge = Part.makeBox(
            length,
            thickness,
            separation,
            App.Vector(0, 0, radius),
        )
        solid = lower.fuse(bridge).fuse(upper)
        if obj.HasHoles:
            for position in (
                obj.AccessHole1Position.Value,
                obj.AccessHole2Position.Value,
            ):
                hole = Part.makeCylinder(
                    obj.AccessHoleDiameter.Value / 2,
                    thickness + 2.0,
                    App.Vector(
                        position,
                        -1.0,
                        obj.AccessHoleCenterHeight.Value,
                    ),
                    App.Vector(0, 1, 0),
                )
                solid = solid.cut(hole)
        shape = _place_strip(
            solid,
            obj.Axis,
            obj.X.Value,
            obj.Y.Value,
            obj.Z.Value,
        )
        obj.Shape = cut_holes(shape, obj)

    def dumps(self):
        return None

    def loads(self, state):
        return None


class FiligreeEngravingProxy:
    """Place two horizontally mirrored trace copies on a drawer face."""

    def __init__(self, obj=None):
        if obj is not None:
            obj.Proxy = self

    def execute(self, obj):
        if obj.TraceSource is None or obj.DrawerFront is None:
            return
        source = obj.TraceSource.Shape
        front = obj.DrawerFront
        if source.isNull() or front.FrameWidth.Value <= 0 or front.FrameHeight.Value <= 0:
            return

        width = front.FrameWidth.Value
        height = front.FrameHeight.Value
        source_box = source.BoundBox
        # Pack two rotated copies exactly across the drawer face: one
        # DrawerClearance at each side and one between the motifs.
        clearance = front.Clearance.Value
        motif_width = (width - 3 * clearance) / 2
        if motif_width <= 0:
            raise ValueError("Drawer face is too narrow for two engravings.")
        scale = motif_width / source_box.YLength
        motif_height = scale * source_box.XLength
        left_x = clearance
        bottom = (height - motif_height) / 2

        placement = App.Matrix()
        # This is the previous landscape orientation turned through another
        # 180 degrees around the motif's own bounding-box center.
        placement.A11 = 0.0
        placement.A12 = scale
        placement.A21 = scale
        placement.A22 = 0.0
        placement.A33 = 1.0
        placement.A14 = left_x - scale * source_box.YMin
        placement.A24 = bottom - scale * source_box.XMin
        left = source.transformGeometry(placement)

        mirror = App.Matrix()
        mirror.A11 = -1.0
        mirror.A22 = 1.0
        mirror.A33 = 1.0
        mirror.A14 = width
        right = left.transformGeometry(mirror)
        pattern = Part.makeCompound((left, right))
        surface = (
            front.Thickness.Value + 0.15
            if obj.SurfaceSign > 0
            else -0.15
        )
        pattern.translate(App.Vector(0, 0, surface))
        obj.Shape = _transform(
            pattern,
            front.Axis,
            front.X.Value,
            front.Y.Value,
            front.Z.Value,
        )

    def dumps(self):
        return None

    def loads(self, state):
        return None


def create_drawer_component(body, name, label, kind):
    feature = body.newObject("PartDesign::FeaturePython", name)
    feature.Label = label
    feature.addProperty("App::PropertyEnumeration", "Kind", "Drawer")
    feature.Kind = ["DrawerFront", "FaceFrame", "DoubleFaceFrame"]
    feature.Kind = kind
    for property_name in (
        "FrameWidth",
        "FrameHeight",
        "Thickness",
        "Clearance",
        "Ply",
        "DrawerBoxWidth",
        "DrawerBoxHeight",
        "SlideWidth",
        "HandleWidth",
        "HandleHeight",
        "WaveAmplitude",
        "X",
        "Y",
        "Z",
    ):
        feature.addProperty("App::PropertyLength", property_name, "Drawer")
    feature.addProperty("App::PropertyEnumeration", "Axis", "Drawer")
    feature.Axis = ["X", "Y"]
    add_hole_properties(feature)
    DrawerFrontPanelProxy(feature)
    body.Tip = feature
    return feature


def create_rounded_strip(body, name, label):
    feature = body.newObject("PartDesign::FeaturePython", name)
    feature.Label = label
    for property_name in (
        "Length",
        "Thickness",
        "Height",
        "X",
        "Y",
        "Z",
    ):
        feature.addProperty("App::PropertyLength", property_name, "Strip")
    feature.addProperty("App::PropertyEnumeration", "Axis", "Strip")
    feature.Axis = ["X", "Y"]
    add_hole_properties(feature)
    RoundedStripProxy(feature)
    body.Tip = feature
    return feature


def create_connected_strip_pair(body, name, label):
    feature = body.newObject("PartDesign::FeaturePython", name)
    feature.Label = label
    for property_name in (
        "Length",
        "Thickness",
        "Height",
        "Separation",
        "AccessHoleDiameter",
        "AccessHole1Position",
        "AccessHole2Position",
        "AccessHoleCenterHeight",
        "X",
        "Y",
        "Z",
    ):
        feature.addProperty("App::PropertyLength", property_name, "Strip")
    feature.addProperty("App::PropertyBool", "HasHoles", "Strip")
    feature.addProperty("App::PropertyEnumeration", "Axis", "Strip")
    feature.Axis = ["X", "Y"]
    add_hole_properties(feature)
    ConnectedStripPairProxy(feature)
    body.Tip = feature
    return feature


def create_filigree_engraving(
    part, name, label, trace_source, drawer_front, surface_sign
):
    engraving = part.newObject("Part::FeaturePython", name)
    engraving.Label = label
    engraving.addProperty("App::PropertyLinkGlobal", "TraceSource", "Engraving")
    engraving.addProperty("App::PropertyLinkGlobal", "DrawerFront", "Engraving")
    engraving.addProperty("App::PropertyInteger", "SurfaceSign", "Engraving")
    engraving.TraceSource = trace_source
    engraving.DrawerFront = drawer_front
    engraving.SurfaceSign = surface_sign
    FiligreeEngravingProxy(engraving)
    if getattr(engraving, "ViewObject", None) is not None:
        engraving.ViewObject.LineColor = (0.22, 0.08, 0.03)
        engraving.ViewObject.LineWidth = 1.5
    engraving.Proxy.execute(engraving)
    return engraving
