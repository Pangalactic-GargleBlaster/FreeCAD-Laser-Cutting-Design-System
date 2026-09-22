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
    """Fit one centered SVG image inside a drawer face with clearance."""

    def __init__(self, obj=None):
        if obj is not None:
            if "Proxy" not in obj.PropertiesList:
                obj.addProperty("App::PropertyPythonObject", "Proxy", "Python")
            obj.Proxy = self

    def execute(self, obj):
        if obj.DrawerFront is None:
            return
        engraving = obj.Engraving if hasattr(obj, "Engraving") else obj
        front = obj.DrawerFront
        if front.FrameWidth.Value <= 0 or front.FrameHeight.Value <= 0:
            return

        width = front.FrameWidth.Value
        height = front.FrameHeight.Value
        clearance = front.Clearance.Value
        if clearance < 0 or width <= 2 * clearance or height <= 2 * clearance:
            raise ValueError("Drawer face is too small for an engraving with clearance.")

        ply = front.Ply.Value
        box_side = (width - front.DrawerBoxWidth.Value) / 2
        maximum_frame_side = max(0.5, 2 * ply - clearance)
        side_wave = max(
            0.0, box_side - clearance - maximum_frame_side
        )
        side_margin = 2 * ply + side_wave + clearance
        safe_bottom = 2 * ply + front.WaveAmplitude.Value + clearance
        handle_shoulder = height - 2 * ply + 1.0
        handle_bottom = handle_shoulder - front.HandleHeight.Value
        # The handle arch can lower its nominal bottom by no more than the
        # sum of its 20% arch and 7% ripple amplitudes.
        safe_top = min(
            height - 2 * ply - front.WaveAmplitude.Value - clearance,
            handle_bottom - 0.27 * front.HandleHeight.Value - clearance,
        )
        safe_width = width - 2 * side_margin
        safe_height = safe_top - safe_bottom
        if safe_width <= 0 or safe_height <= 0:
            raise ValueError("Drawer clearance leaves no safe engraving area.")
        source_width = obj.SourceWidth.Value
        source_height = obj.SourceHeight.Value
        if source_width <= 0 or source_height <= 0:
            raise ValueError("Filigree SVG dimensions must be positive.")
        scale = min(
            safe_width / source_width,
            safe_height / source_height,
        )
        if scale <= 1e-9:
            raise ValueError("Filigree cannot fit inside the drawer face.")
        engraving.Scale = scale
        motif_center_y = (safe_bottom + safe_top) / 2
        surface = (
            front.Thickness.Value + 0.15
            if obj.SurfaceSign > 0
            else -0.15
        )
        placement = App.Matrix()
        if front.Axis == "X":
            placement.A11, placement.A12, placement.A13 = 0, 0, 1
            placement.A21, placement.A22, placement.A23 = 1, 0, 0
            placement.A31, placement.A32, placement.A33 = 0, 1, 0
            placement.A14 = front.X.Value + surface
            placement.A24 = front.Y.Value + width / 2
            placement.A34 = front.Z.Value + motif_center_y
        else:
            placement.A11, placement.A12, placement.A13 = 1, 0, 0
            placement.A21, placement.A22, placement.A23 = 0, 0, 1
            placement.A31, placement.A32, placement.A33 = 0, 1, 0
            placement.A14 = front.X.Value + width / 2
            placement.A24 = front.Y.Value + surface
            placement.A34 = front.Z.Value + motif_center_y
        engraving.Placement = App.Placement(placement)

    def dumps(self):
        return None

    def loads(self, state):
        return None


class FiligreePairEngravingProxy:
    """Fit one half of a mirrored motif pair inside a drawer face."""

    def __init__(self, obj=None):
        if obj is not None:
            if "Proxy" not in obj.PropertiesList:
                obj.addProperty("App::PropertyPythonObject", "Proxy", "Python")
            obj.Proxy = self

    def execute(self, obj):
        if obj.DrawerFront is None:
            return
        engraving = obj.Engraving if hasattr(obj, "Engraving") else obj
        front = obj.DrawerFront
        width = front.FrameWidth.Value
        height = front.FrameHeight.Value
        clearance = front.Clearance.Value
        if clearance < 0 or width <= 2 * clearance or height <= 2 * clearance:
            raise ValueError("Drawer face is too small for an engraving with clearance.")

        ply = front.Ply.Value
        box_side = (width - front.DrawerBoxWidth.Value) / 2
        maximum_frame_side = max(0.5, 2 * ply - clearance)
        side_wave = max(0.0, box_side - clearance - maximum_frame_side)
        side_margin = 2 * ply + side_wave + clearance
        safe_bottom = 2 * ply + front.WaveAmplitude.Value + clearance
        handle_shoulder = height - 2 * ply + 1.0
        handle_bottom = handle_shoulder - front.HandleHeight.Value
        safe_top = min(
            height - 2 * ply - front.WaveAmplitude.Value - clearance,
            handle_bottom - 0.27 * front.HandleHeight.Value - clearance,
        )
        safe_width = width - 2 * side_margin
        safe_height = safe_top - safe_bottom
        source_width = obj.SourceWidth.Value
        source_height = obj.SourceHeight.Value
        if safe_width <= clearance or safe_height <= 0:
            raise ValueError("Drawer clearance leaves no safe paired engraving area.")
        if source_width <= 0 or source_height <= 0:
            raise ValueError("Filigree subpattern dimensions must be positive.")

        scale = min(
            (safe_width - clearance) / (2 * source_width),
            safe_height / source_height,
        )
        if scale <= 1e-9:
            raise ValueError("Filigree pair cannot fit inside the drawer face.")
        engraving.Scale = scale
        motif_width = source_width * scale
        pair_width = 2 * motif_width + clearance
        pair_left = side_margin + (safe_width - pair_width) / 2
        motif_center_x = pair_left + motif_width / 2
        if obj.PairIndex == 1:
            motif_center_x += motif_width + clearance
        motif_center_y = (safe_bottom + safe_top) / 2
        surface = (
            front.Thickness.Value + 0.15
            if obj.SurfaceSign > 0
            else -0.15
        )
        placement = App.Matrix()
        if front.Axis == "X":
            placement.A11, placement.A12, placement.A13 = 0, 0, 1
            placement.A21, placement.A22, placement.A23 = 1, 0, 0
            placement.A31, placement.A32, placement.A33 = 0, 1, 0
            placement.A14 = front.X.Value + surface
            placement.A24 = front.Y.Value + motif_center_x
            placement.A34 = front.Z.Value + motif_center_y
        else:
            placement.A11, placement.A12, placement.A13 = 1, 0, 0
            placement.A21, placement.A22, placement.A23 = 0, 0, 1
            placement.A31, placement.A32, placement.A33 = 0, 1, 0
            placement.A14 = front.X.Value + motif_center_x
            placement.A24 = front.Y.Value + surface
            placement.A34 = front.Z.Value + motif_center_y
        engraving.Placement = App.Placement(placement)

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
    part,
    name,
    label,
    image_path,
    source_width,
    source_height,
    drawer_front,
    surface_sign,
):
    doc = part.Document
    source = doc.getObject("FiligreeImageSource")
    if source is None:
        source = doc.addObject("Image::ImagePlane", "FiligreeImageSource")
        source.Label = "Filigree SVG preview source (embedded, hidden)"
        source.ImageFile = image_path
        source.XSize = source_width
        source.YSize = source_height
        source.Visibility = False

    engraving = part.newObject("App::Link", name)
    engraving.Label = label
    engraving.LinkedObject = source
    engraving.LinkTransform = True
    engraving.addProperty("App::PropertyLinkGlobal", "DrawerFront", "Engraving")
    engraving.addProperty("App::PropertyInteger", "SurfaceSign", "Engraving")
    engraving.addProperty("App::PropertyLength", "SourceWidth", "Engraving")
    engraving.addProperty("App::PropertyLength", "SourceHeight", "Engraving")
    engraving.SourceWidth = source_width
    engraving.SourceHeight = source_height
    engraving.DrawerFront = drawer_front
    engraving.SurfaceSign = surface_sign
    controller = part.newObject("App::FeaturePython", name + "Controller")
    controller.Label = label + " controller"
    controller.addProperty("App::PropertyLinkGlobal", "Engraving", "Engraving")
    controller.addProperty("App::PropertyLinkGlobal", "DrawerFront", "Engraving")
    controller.addProperty("App::PropertyInteger", "SurfaceSign", "Engraving")
    controller.addProperty("App::PropertyLength", "SourceWidth", "Engraving")
    controller.addProperty("App::PropertyLength", "SourceHeight", "Engraving")
    controller.Engraving = engraving
    controller.DrawerFront = drawer_front
    controller.SurfaceSign = surface_sign
    controller.SourceWidth = source_width
    controller.SourceHeight = source_height
    proxy = FiligreeEngravingProxy(controller)
    proxy.execute(controller)
    return engraving


def create_filigree_engraving_pair(
    part,
    name,
    label,
    left_image_path,
    right_image_path,
    source_width,
    source_height,
    drawer_front,
    surface_sign,
):
    """Create an inward-facing mirrored pair with DrawerClearance spacing."""
    doc = part.Document
    sources = []
    for source_name, source_label, image_path in (
        (
            "FiligreeSmallLeftSource",
            "Top-left filigree subpattern source (embedded, hidden)",
            left_image_path,
        ),
        (
            "FiligreeSmallRightSource",
            "Mirrored top-left filigree subpattern source (embedded, hidden)",
            right_image_path,
        ),
    ):
        source = doc.getObject(source_name)
        if source is None:
            source = doc.addObject("Image::ImagePlane", source_name)
            source.Label = source_label
            source.ImageFile = image_path
            source.XSize = source_width
            source.YSize = source_height
            source.Visibility = False
        sources.append(source)

    engravings = []
    for pair_index, (suffix, source) in enumerate(
        (("Left", sources[0]), ("Right", sources[1]))
    ):
        engraving = part.newObject("App::Link", name + suffix)
        engraving.Label = label + " — " + suffix.lower()
        engraving.LinkedObject = source
        engraving.LinkTransform = True
        engraving.addProperty("App::PropertyLinkGlobal", "DrawerFront", "Engraving")
        engraving.addProperty("App::PropertyInteger", "SurfaceSign", "Engraving")
        engraving.addProperty("App::PropertyInteger", "PairIndex", "Engraving")
        engraving.addProperty("App::PropertyLength", "SourceWidth", "Engraving")
        engraving.addProperty("App::PropertyLength", "SourceHeight", "Engraving")
        engraving.SourceWidth = source_width
        engraving.SourceHeight = source_height
        engraving.DrawerFront = drawer_front
        engraving.SurfaceSign = surface_sign
        engraving.PairIndex = pair_index
        controller = part.newObject(
            "App::FeaturePython", name + suffix + "Controller"
        )
        controller.Label = engraving.Label + " controller"
        controller.addProperty("App::PropertyLinkGlobal", "Engraving", "Engraving")
        controller.addProperty("App::PropertyLinkGlobal", "DrawerFront", "Engraving")
        controller.addProperty("App::PropertyInteger", "SurfaceSign", "Engraving")
        controller.addProperty("App::PropertyInteger", "PairIndex", "Engraving")
        controller.addProperty("App::PropertyLength", "SourceWidth", "Engraving")
        controller.addProperty("App::PropertyLength", "SourceHeight", "Engraving")
        controller.Engraving = engraving
        controller.DrawerFront = drawer_front
        controller.SurfaceSign = surface_sign
        controller.PairIndex = pair_index
        controller.SourceWidth = source_width
        controller.SourceHeight = source_height
        proxy = FiligreePairEngravingProxy(controller)
        proxy.execute(controller)
        engravings.append(engraving)
    return tuple(engravings)
