"""Generate the eight-cabinet platform-bed concept model."""

import os
import json
import math
import re
import sys
import xml.etree.ElementTree as ET

import FreeCAD as App
import Materials
import Part


SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(SCRIPT_DIR)
PROJECT_ROOT = os.path.dirname(ROOT)
MODULE_DIR = os.path.join(PROJECT_ROOT, "freecad", "DesignSystem")
if MODULE_DIR not in sys.path:
    sys.path.insert(0, MODULE_DIR)

import panel as panel_tools
import drawer_components
from finger_joint import create_joint

SHARED_TOOLS_DIR = os.path.join(PROJECT_ROOT, "tools")
if SHARED_TOOLS_DIR not in sys.path:
    sys.path.insert(0, SHARED_TOOLS_DIR)
from set_fcstd_visibility import set_visibility


INCH = 25.4
DEPTH = 38 * INCH
WIDTH = 30 * INCH
WALL_DEPTH = 20 * INCH
BEDSIDE_SIZE = 20 * INCH
HEIGHT = 14 * INCH
STRIP = 6 * INCH
FILIGREE_SVG = os.path.join(ROOT, "assets", "filigree.svg")
FILIGREE_IMAGE = os.path.join(ROOT, "assets", "filigree_drawer.png")
FILIGREE_SMALL_LEFT = os.path.join(ROOT, "assets", "filigree_small_left.png")
FILIGREE_SMALL_RIGHT = os.path.join(ROOT, "assets", "filigree_small_right.png")
WOOD_MATERIAL = Materials.MaterialManager().getMaterial(
    "b588224e-e8d6-47ad-ba1f-a058333fd1c6"
)


def load_filigree_trace(doc):
    """Embed the supplied SVG filigree as a hidden reusable source feature."""
    if not os.path.exists(FILIGREE_SVG):
        raise FileNotFoundError(f"Filigree SVG not found: {FILIGREE_SVG}")
    if not os.path.exists(FILIGREE_IMAGE):
        raise FileNotFoundError(f"Filigree preview not found: {FILIGREE_IMAGE}")
    paths = []
    token_pattern = re.compile(
        r"[MmLlHhVvCcZz]|[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?"
    )

    def add_path(path_data):
        tokens = token_pattern.findall(path_data)
        index = 0
        command = None
        x = y = 0.0
        start_x = start_y = 0.0
        points = []

        def number():
            nonlocal index
            value = float(tokens[index])
            index += 1
            return value

        def flush():
            nonlocal points
            if len(points) >= 2:
                paths.append(points)
            points = []

        def line_to(end_x, end_y):
            nonlocal x, y
            if abs(end_x - x) > 1e-9 or abs(end_y - y) > 1e-9:
                points.append((end_x, end_y))
            x, y = end_x, end_y

        while index < len(tokens):
            if tokens[index].isalpha():
                command = tokens[index]
                index += 1
            if command is None:
                raise ValueError("SVG path data begins without a command.")
            relative = command.islower()
            opcode = command.upper()
            if opcode == "Z":
                line_to(start_x, start_y)
                command = None
            elif opcode == "M":
                flush()
                end_x, end_y = number(), number()
                if relative:
                    end_x, end_y = x + end_x, y + end_y
                x, y = end_x, end_y
                start_x, start_y = x, y
                points.append((x, y))
                command = "l" if relative else "L"
            elif opcode == "L":
                end_x, end_y = number(), number()
                if relative:
                    end_x, end_y = x + end_x, y + end_y
                line_to(end_x, end_y)
            elif opcode == "H":
                end_x = number() + (x if relative else 0.0)
                line_to(end_x, y)
            elif opcode == "V":
                end_y = number() + (y if relative else 0.0)
                line_to(x, end_y)
            elif opcode == "C":
                values = [number() for _ in range(6)]
                if relative:
                    values = [
                        values[0] + x,
                        values[1] + y,
                        values[2] + x,
                        values[3] + y,
                        values[4] + x,
                        values[5] + y,
                    ]
                points.append((values[4], values[5]))
                x, y = values[4], values[5]
            else:
                raise ValueError(f"Unsupported SVG path command: {command}")
        flush()

    root = ET.parse(FILIGREE_SVG).getroot()
    for element in root.iter():
        if element.tag.endswith("path") and element.attrib.get("d"):
            add_path(element.attrib["d"])
    if not paths:
        raise ValueError(f"SVG contained no importable shapes: {FILIGREE_SVG}")

    # The source is an Inkscape trace and contains hundreds of microscopic
    # hatch marks and specks. Keep its principal ornamental contours so the
    # embedded FreeCAD shape stays responsive at drawer scale.
    def contour_area(points):
        xs = [point[0] for point in points]
        ys = [point[1] for point in points]
        return (max(xs) - min(xs)) * (max(ys) - min(ys))

    contours = []
    for points in paths:
        if contour_area(points) < 50000.0:
            continue
        closed = (
            abs(points[0][0] - points[-1][0]) <= 1e-7
            and abs(points[0][1] - points[-1][1]) <= 1e-7
        )
        interpolation_points = points[:-1] if closed else points
        # Collapse trace points that are closer than a few source pixels.
        # At the fitted drawer size this is well below DrawerClearance and
        # removes no visually meaningful turn from the ornament.
        simplified = [interpolation_points[0]]
        for point in interpolation_points[1:]:
            dx = point[0] - simplified[-1][0]
            dy = point[1] - simplified[-1][1]
            if dx * dx + dy * dy >= 16.0:
                simplified.append(point)
        if len(simplified) > 12:
            step = (len(simplified) + 11) // 12
            simplified = simplified[::step]
        if len(simplified) < 4:
            continue
        vectors = [App.Vector(point[0], point[1], 0) for point in simplified]
        if closed:
            vectors.append(vectors[0])
        contours.append(Part.makePolygon(vectors))
    source = doc.addObject("Part::Feature", "FiligreeTraceSource")
    source.Label = "Filigree SVG source (embedded, hidden)"
    source.Shape = Part.makeCompound(contours)
    if getattr(source, "ViewObject", None) is not None:
        source.ViewObject.Visibility = False
    return source


def configured_ply():
    with open(os.path.join(ROOT, "design_parameters.json")) as stream:
        value = json.load(stream)["ply_mm"]
    value = float(os.environ.get("BED_PLY_MM", value))
    if not math.isfinite(value) or value <= 0:
        raise ValueError("ply must be a finite, positive number of millimeters")
    return value


def add_parameters(doc):
    params = doc.addObject("App::VarSet", "BedParameters")
    params.Label = "Bed Parameters"
    params.addProperty("App::PropertyInteger", "NumberOfFingers", "Finger joints")
    params.addProperty("App::PropertyInteger", "ShortJointFingers", "Finger joints")
    params.addProperty("App::PropertyLength", "FingerOvershoot", "Finger joints")
    params.addProperty("App::PropertyLength", "FingerFilletRadius", "Finger joints")
    params.addProperty("App::PropertyLength", "WallFrontSupportHeight", "Cabinet supports")
    params.addProperty("App::PropertyLength", "ply", "Material")
    params.addProperty("App::PropertyLength", "BoltHoleDiameter", "Cabinet connectors")
    params.addProperty("App::PropertyLength", "DowelDiameter", "Panel alignment")
    params.addProperty("App::PropertyLength", "DrawerClearance", "Drawers")
    params.addProperty("App::PropertyLength", "DrawerBottomOffset", "Drawers")
    params.addProperty("App::PropertyLength", "DrawerSlideWidth", "Drawers")
    params.addProperty("App::PropertyLength", "DrawerHandleWidth", "Drawers")
    params.addProperty("App::PropertyLength", "DrawerHandleHeight", "Drawers")
    params.addProperty("App::PropertyLength", "DrawerWaveAmplitude", "Drawers")
    params.addProperty("App::PropertyLength", "LargeDrawerBoxHeight", "Drawers")
    params.addProperty("App::PropertyLength", "BedsideDrawerBoxHeight", "Drawers")
    params.addProperty("App::PropertyLength", "LargeDrawerBoxWidth", "Drawers")
    params.addProperty("App::PropertyLength", "BedsideDrawerBoxWidth", "Drawers")
    params.addProperty("App::PropertyLength", "LargeDrawerSideLength", "Drawers")
    params.addProperty("App::PropertyLength", "BedsideDrawerSideLength", "Drawers")
    params.NumberOfFingers = 4
    params.ShortJointFingers = 2
    params.FingerOvershoot = 2
    params.FingerFilletRadius = 2
    params.WallFrontSupportHeight = 100
    params.ply = configured_ply()
    params.BoltHoleDiameter = 7.5
    params.DowelDiameter = 6.0
    params.DrawerClearance = 3
    params.DrawerBottomOffset = 0.5 * INCH
    params.DrawerSlideWidth = 1 * INCH
    params.DrawerHandleWidth = 6 * INCH
    params.DrawerHandleHeight = 2 * INCH
    params.DrawerWaveAmplitude = 12
    params.LargeDrawerBoxHeight = 7 * INCH
    params.BedsideDrawerBoxHeight = 100
    params.setExpression(
        "LargeDrawerBoxWidth", "30 in - 12 * ply - DrawerClearance"
    )
    params.setExpression(
        "BedsideDrawerBoxWidth", "20 in - 12 * ply - DrawerClearance"
    )
    params.setExpression(
        "LargeDrawerSideLength", "38 in - 6 * ply - FingerOvershoot"
    )
    params.setExpression(
        "BedsideDrawerSideLength", "20 in - 6 * ply - FingerOvershoot"
    )
    return params


def make_layer(part, name, label, box, thickness_property, expressions, color):
    body = part.newObject("PartDesign::Body", name + "Body")
    body.Label = label
    feature = panel_tools.create_parametric_panel(body, name, label + " solid")
    feature.Length, feature.Width, feature.Height = box[3:]
    feature.X, feature.Y, feature.Z = box[:3]
    feature.PanelThicknessProperty = thickness_property
    body.ShapeMaterial = WOOD_MATERIAL
    feature.ShapeMaterial = WOOD_MATERIAL
    panel_tools.add_hole_properties(feature)
    for property_name, expression in expressions.items():
        feature.setExpression(property_name, expression)
    if getattr(feature, "ViewObject", None) is not None:
        feature.ViewObject.ShapeColor = color
        feature.ViewObject.LineColor = (0.18, 0.12, 0.06)
    return feature


def _feature_body(feature):
    return feature.getParentGeoFeatureGroup()


def _find_joint_face(feature, axis, coordinate):
    """Find an untouched rectangular panel end face."""
    candidates = []
    for face_index, face in enumerate(feature.Shape.Faces, start=1):
        normal = face.normalAt(0, 0)
        if abs(abs(normal.dot(axis)) - 1.0) > 1e-6:
            continue
        if abs(face.CenterOfMass.dot(axis) - coordinate) > 1e-5:
            continue
        candidates.append((face.Area, face_index))
    if not candidates:
        raise RuntimeError(
            f"No joint face at {coordinate:g} on {feature.Label}"
        )
    _, face_index = max(candidates)
    return f"Face{face_index}"


def _apply_drawer_joint(
    source_body,
    axis,
    coordinate,
    receivers,
    label,
    hidden_front_joint=False,
    finger_count=None,
    zero_receiver_overshoot=False,
):
    source = source_body.Tip
    face_name = _find_joint_face(source, axis, coordinate)
    params = source_body.Document.BedParameters
    kwargs = {
        "finger_count_expression": (
            "BedParameters.NumberOfFingers" if finger_count is None
            else "BedParameters.ShortJointFingers"
        ),
        "fillet_radius": params.FingerFilletRadius.Value,
        "fillet_radius_expression": "BedParameters.FingerFilletRadius",
        "receiver_overshoot": params.FingerOvershoot.Value,
        "receiver_overshoot_expression": "BedParameters.FingerOvershoot",
        "receiver_fillet_radius": params.FingerFilletRadius.Value,
        "receiver_fillet_radius_expression": "BedParameters.FingerFilletRadius",
    }
    if hidden_front_joint:
        kwargs["overshoot"] = 0
    else:
        kwargs["overshoot"] = params.FingerOvershoot.Value
        kwargs["overshoot_expression"] = "BedParameters.FingerOvershoot"
    if zero_receiver_overshoot:
        kwargs["receiver_overshoot"] = 0
        kwargs.pop("receiver_overshoot_expression")
    joint = create_joint(
        source,
        face_name,
        receivers,
        params.NumberOfFingers if finger_count is None else finger_count,
        **kwargs,
    )
    joint.Label = label
    joint.ShapeMaterial = WOOD_MATERIAL
    source_body.ShapeMaterial = WOOD_MATERIAL
    for receiver in receivers:
        receiver.ShapeMaterial = WOOD_MATERIAL
        receiver.Tip.ShapeMaterial = WOOD_MATERIAL
    return joint


def _apply_cabinet_joint(layers, source_key, axis, coordinate, receiver_keys, label):
    """Join one cabinet ply through every ply of the receiving panel stack."""
    source_body = _feature_body(layers[source_key])
    receiver_bodies = [_feature_body(layers[key]) for key in receiver_keys]
    return _apply_drawer_joint(
        source_body,
        axis,
        coordinate,
        receiver_bodies,
        label,
    )


def add_cabinet_joints(layers, key, x0, y0, kind, front_direction=None):
    """Finger-joint every laminated structural panel in one cabinet."""
    ply = next(iter(layers.values())).Document.BedParameters.ply.Value
    top_receivers = (("Top", "Inner"), ("Top", "Outer"))
    back_receivers = (("Back", "Inner"), ("Back", "Outer"))

    if kind == "main":
        side_names = ("LowerSide", "UpperSide")
        side_receivers = {
            "LowerSide": (("LowerSide", "Inner"), ("LowerSide", "Outer")),
            "UpperSide": (("UpperSide", "Inner"), ("UpperSide", "Outer")),
        }
        side_axis = App.Vector(0, 1, 0)
        side_coordinates = {
            "LowerSide": y0 + 2 * ply,
            "UpperSide": y0 + WIDTH - 2 * ply,
        }
        back_axis = App.Vector(1, 0, 0)
        back_coordinate = (
            x0 + DEPTH - 2 * ply if front_direction == "-X" else x0 + 2 * ply
        )
    else:
        size = WALL_DEPTH if kind == "wall" else BEDSIDE_SIZE
        side_names = ("LeftSide", "RightSide")
        side_receivers = {
            "LeftSide": (("LeftSide", "Inner"), ("LeftSide", "Outer")),
            "RightSide": (("RightSide", "Inner"), ("RightSide", "Outer")),
        }
        side_axis = App.Vector(1, 0, 0)
        side_coordinates = {
            "LeftSide": x0 + 2 * ply,
            "RightSide": x0 + DEPTH - 2 * ply
            if kind == "wall"
            else x0 + BEDSIDE_SIZE - 2 * ply,
        }
        back_axis = App.Vector(0, 1, 0)
        back_coordinate = (
            y0 + 2 * ply if kind == "wall" else y0 + size - 2 * ply
        )

    # The back must use its untouched top face before side and strip cuts reach it.
    for layer_name in ("Outer", "Inner"):
        _apply_cabinet_joint(
            layers,
            ("Back", layer_name),
            App.Vector(0, 0, 1),
            HEIGHT - 2 * ply,
            top_receivers,
            f"{key} back {layer_name.lower()}-to-top joint",
        )

    # Side plies join the top and back before the bottom strips cut their edges.
    for side_name in side_names:
        for layer_name in ("Outer", "Inner"):
            source_key = (side_name, layer_name)
            _apply_cabinet_joint(
                layers,
                source_key,
                App.Vector(0, 0, 1),
                HEIGHT - 2 * ply,
                top_receivers,
                f"{key} {side_name} {layer_name.lower()}-to-top joint",
            )
            _apply_cabinet_joint(
                layers,
                source_key,
                back_axis,
                back_coordinate,
                back_receivers,
                f"{key} {side_name} {layer_name.lower()}-to-back joint",
            )

    # Both bottom strips join both side stacks. The rear strip also joins the back.
    for strip_name in ("FrontBottomStrip", "BackBottomStrip"):
        for layer_name in ("Outer", "Inner"):
            source_key = (strip_name, layer_name)
            for side_name in side_names:
                _apply_cabinet_joint(
                    layers,
                    source_key,
                    side_axis,
                    side_coordinates[side_name],
                    side_receivers[side_name],
                    f"{key} {strip_name} {layer_name.lower()}-to-{side_name} joint",
                )
            if strip_name == "BackBottomStrip":
                _apply_cabinet_joint(
                    layers,
                    source_key,
                    back_axis,
                    back_coordinate,
                    back_receivers,
                    f"{key} {strip_name} {layer_name.lower()}-to-back joint",
                )


def add_face_frame_joints(layers, frames, key, x0, y0, kind):
    """Join both face-frame plies to the cabinet top, sides, and front sill."""
    ply = next(iter(layers.values())).Document.BedParameters.ply.Value
    if kind == "main":
        sides = (
            (App.Vector(0, 1, 0), y0 + 2 * ply, "LowerSide"),
            (App.Vector(0, 1, 0), y0 + WIDTH - 2 * ply, "UpperSide"),
        )
    else:
        sides = (
            (App.Vector(1, 0, 0), x0 + 2 * ply, "LeftSide"),
            (App.Vector(1, 0, 0), x0 + BEDSIDE_SIZE - 2 * ply, "RightSide"),
        )
    for layer_name, frame in frames.items():
        _apply_drawer_joint(
            frame, App.Vector(0, 0, 1), HEIGHT - 2 * ply,
            [_feature_body(layers[("Top", name)]) for name in ("Inner", "Outer")],
            f"{key} frame {layer_name.lower()}-to-top joint",
        )
        for axis, coordinate, side in sides:
            _apply_drawer_joint(
                frame, axis, coordinate,
                [_feature_body(layers[(side, name)]) for name in ("Inner", "Outer")],
                f"{key} frame {layer_name.lower()}-to-{side} joint",
            )
        _apply_drawer_joint(
            frame, App.Vector(0, 0, 1), 2 * ply,
            [_feature_body(layers[("FrontBottomStrip", name)])
             for name in ("Inner", "Outer")],
            f"{key} frame {layer_name.lower()}-to-front-sill joint",
        )


def add_main_center_support(part, layers, frame_inner, key, x0, y0, direction, color):
    """Laminate a shallow longitudinal rib under the main cabinet top."""
    params = part.Document.BedParameters
    ply = params.ply.Value
    height = 2 * ply + params.DrawerWaveAmplitude.Value - params.DrawerClearance.Value
    height_expr = (
        "2 * BedParameters.ply + BedParameters.DrawerWaveAmplitude "
        "- BedParameters.DrawerClearance"
    )
    if height / (2 * params.ShortJointFingers) < 2 * params.FingerFilletRadius.Value:
        raise ValueError("The center support is too shallow for its end fingers")
    x = x0 + 2 * ply
    z = HEIGHT - 2 * ply - height
    front_x = x if direction == "-X" else x0 + DEPTH - 2 * ply
    back_x = x0 + DEPTH - 2 * ply if direction == "-X" else x
    for layer_name, y, y_expr in (
        ("Outer", y0 + WIDTH / 2 - ply,
         f"{y0 + WIDTH / 2} mm - BedParameters.ply"),
        ("Inner", y0 + WIDTH / 2, f"{y0 + WIDTH / 2} mm"),
    ):
        feature = make_layer(
            part, key + "CenterSupport" + layer_name,
            "Center top support — " + layer_name.lower(),
            (x, y, z, DEPTH - 4 * ply, ply, height), "Width",
            {
                "X": f"{x0} mm + 2 * BedParameters.ply",
                "Y": y_expr,
                "Z": f"{HEIGHT} mm - 2 * BedParameters.ply - ({height_expr})",
                "Length": "38 in - 4 * BedParameters.ply",
                "Width": "BedParameters.ply",
                "Height": height_expr,
            },
            color,
        )
        part.Document.recompute()
        body = _feature_body(feature)
        _apply_drawer_joint(
            body, App.Vector(0, 0, 1), HEIGHT - 2 * ply,
            [_feature_body(layers[("Top", name)]) for name in ("Inner", "Outer")],
            f"{key} center support {layer_name.lower()}-to-top joint",
        )
        _apply_drawer_joint(
            body, App.Vector(1, 0, 0), back_x,
            [_feature_body(layers[("Back", name)]) for name in ("Inner", "Outer")],
            f"{key} center support {layer_name.lower()}-to-back joint",
            finger_count=params.ShortJointFingers,
        )
        _apply_drawer_joint(
            body, App.Vector(1, 0, 0), front_x, [frame_inner],
            f"{key} center support {layer_name.lower()}-to-inner-frame joint",
            hidden_front_joint=True, finger_count=params.ShortJointFingers,
            zero_receiver_overshoot=True,
        )


def add_wall_front_support(part, layers, key, x0, y0, color):
    """Add a laminated 100 mm high rail flush with a wall cabinet's front."""
    params = part.Document.BedParameters
    ply = params.ply.Value
    height = params.WallFrontSupportHeight.Value
    for layer_name, y, y_expression in (
        ("Outer", y0 + WALL_DEPTH - ply,
         f"{y0 + WALL_DEPTH} mm - BedParameters.ply"),
        ("Inner", y0 + WALL_DEPTH - 2 * ply,
         f"{y0 + WALL_DEPTH} mm - 2 * BedParameters.ply"),
    ):
        feature = make_layer(
            part, key + "FrontSupport" + layer_name,
            "Front support — " + layer_name.lower(),
            (x0 + 2 * ply, y, HEIGHT - 2 * ply - height,
             DEPTH - 4 * ply, ply, height),
            "Width",
            {
                "X": f"{x0} mm + 2 * BedParameters.ply",
                "Y": y_expression,
                "Z": (f"{HEIGHT} mm - 2 * BedParameters.ply "
                      "- BedParameters.WallFrontSupportHeight"),
                "Length": f"{DEPTH} mm - 4 * BedParameters.ply",
                "Width": "BedParameters.ply",
                "Height": "BedParameters.WallFrontSupportHeight",
            },
            color,
        )
        part.Document.recompute()
        body = _feature_body(feature)
        _apply_drawer_joint(
            body, App.Vector(0, 0, 1), HEIGHT - 2 * ply,
            [_feature_body(layers[("Top", name)]) for name in ("Inner", "Outer")],
            f"{key} front support {layer_name.lower()}-to-top joint",
        )
        for side, coordinate in (
            ("LeftSide", x0 + 2 * ply),
            ("RightSide", x0 + DEPTH - 2 * ply),
        ):
            _apply_drawer_joint(
                body, App.Vector(1, 0, 0), coordinate,
                [_feature_body(layers[(side, name)])
                 for name in ("Inner", "Outer")],
                f"{key} front support {layer_name.lower()}-to-{side} joint",
            )


def _drawer_layer(
    part, name, label, box, thickness_property, expressions, color
):
    feature = make_layer(
        part, name, label, box, thickness_property, expressions, color
    )
    return _feature_body(feature), feature


def _drawer_component_layer(
    part,
    name,
    label,
    kind,
    values,
    expressions,
    axis,
    color,
):
    body = part.newObject("PartDesign::Body", name + "Body")
    body.Label = label
    feature = drawer_components.create_drawer_component(
        body, name, label + " solid", kind
    )
    for property_name, value in values.items():
        setattr(feature, property_name, value)
    feature.Axis = axis
    for property_name, expression in expressions.items():
        feature.setExpression(property_name, expression)
    body.ShapeMaterial = WOOD_MATERIAL
    feature.ShapeMaterial = WOOD_MATERIAL
    if getattr(feature, "ViewObject", None) is not None:
        feature.ViewObject.ShapeColor = color
        feature.ViewObject.LineColor = (0.18, 0.12, 0.06)
    feature.Proxy.execute(feature)
    feature.touch()
    return body, feature


def _rounded_strip(
    part, name, label, values, expressions, axis, color
):
    body = part.newObject("PartDesign::Body", name + "Body")
    body.Label = label
    feature = drawer_components.create_rounded_strip(
        body, name, label + " solid"
    )
    for property_name, value in values.items():
        setattr(feature, property_name, value)
    feature.Axis = axis
    for property_name, expression in expressions.items():
        feature.setExpression(property_name, expression)
    body.ShapeMaterial = WOOD_MATERIAL
    feature.ShapeMaterial = WOOD_MATERIAL
    if getattr(feature, "ViewObject", None) is not None:
        feature.ViewObject.ShapeColor = color
        feature.ViewObject.LineColor = (0.18, 0.12, 0.06)
    feature.Proxy.execute(feature)
    feature.touch()
    return body, feature


def _rounded_strip_stack(
    part,
    name,
    label,
    values,
    expressions,
    axis,
    layer_count,
    color,
    layer_indices=None,
    layer_step=1,
):
    """Create a rounded runner as separately cut, ply-thick laminations."""
    ply = part.Document.BedParameters.ply.Value
    lateral_property = "Y" if axis == "X" else "X"
    base_coordinate = values[lateral_property]
    base_expression = expressions[lateral_property]
    result = []
    indices = range(layer_count) if layer_indices is None else layer_indices
    for index in indices:
        layer_values = {
            **values,
            lateral_property: base_coordinate + layer_step * index * ply,
            "Thickness": ply,
        }
        offset_operator = " + " if layer_step > 0 else " - "
        layer_expressions = {
            **expressions,
            lateral_property: (
                base_expression
                if index == 0
                else base_expression
                + offset_operator
                + f"{index} * BedParameters.ply"
            ),
            "Thickness": "BedParameters.ply",
        }
        result.append(
            _rounded_strip(
                part,
                name + f"Layer{index + 1}",
                label + f" — layer {index + 1}",
                layer_values,
                layer_expressions,
                axis,
                tuple(max(0.0, c - 0.025 * index) for c in color),
            )
        )
    return result


def _connected_strip_pair_layer(
    part,
    name,
    label,
    values,
    expressions,
    axis,
    color,
):
    body = part.newObject("PartDesign::Body", name + "Body")
    body.Label = label
    feature = drawer_components.create_connected_strip_pair(
        body, name, label + " solid"
    )
    for property_name, value in values.items():
        setattr(feature, property_name, value)
    feature.Axis = axis
    for property_name, expression in expressions.items():
        feature.setExpression(property_name, expression)
    body.ShapeMaterial = WOOD_MATERIAL
    feature.ShapeMaterial = WOOD_MATERIAL
    if getattr(feature, "ViewObject", None) is not None:
        feature.ViewObject.ShapeColor = color
        feature.ViewObject.LineColor = (0.18, 0.12, 0.06)
    feature.Proxy.execute(feature)
    feature.touch()
    return body, feature


def create_large_drawer(
    doc,
    cabinet_part,
    cabinet_layers,
    key,
    label,
    x0,
    y0,
    front_direction,
    color,
    filigree_source,
):
    """Create one doubled-wall drawer and its paired wooden slides."""
    ply = doc.BedParameters.ply.Value
    params = doc.BedParameters
    clearance = params.DrawerClearance.Value
    slide_width = params.DrawerSlideWidth.Value
    box_width = params.LargeDrawerBoxWidth.Value
    box_height = params.LargeDrawerBoxHeight.Value
    side_length = params.LargeDrawerSideLength.Value
    box_low = y0 + 6 * ply + clearance / 2
    box_high = box_low + box_width
    wave_amplitude = params.DrawerWaveAmplitude.Value
    box_z = 4 * ply + wave_amplitude
    box_z_expression = (
        "4 * BedParameters.ply + BedParameters.DrawerWaveAmplitude"
    )
    bottom_z = box_z + params.DrawerBottomOffset.Value
    slide_z = HEIGHT / 2 - slide_width / 2
    frame_y = y0 + 2 * ply
    frame_width = WIDTH - 4 * ply
    frame_z = 2 * ply
    frame_height = HEIGHT - 4 * ply

    if front_direction == "-X":
        face_outer_x = x0
        face_inner_x = x0 + ply
        side_min = x0 + 2 * ply
        side_max = side_min + side_length
        back_inner_x = side_max
        back_outer_x = side_max + ply
        face_outer_expr = f"{x0} mm"
        face_inner_expr = f"{x0} mm + BedParameters.ply"
        side_min_expr = f"{x0} mm + 2 * BedParameters.ply"
        back_inner_expr = (
            f"{x0} mm + 2 * BedParameters.ply + "
            "BedParameters.LargeDrawerSideLength"
        )
        back_outer_expr = back_inner_expr + " + BedParameters.ply"
        front_coordinate = side_min
        back_coordinate = side_max
    else:
        face_outer_x = x0 + DEPTH - ply
        face_inner_x = x0 + DEPTH - 2 * ply
        side_max = face_inner_x
        side_min = side_max - side_length
        back_inner_x = side_min - ply
        back_outer_x = side_min - 2 * ply
        face_outer_expr = f"{x0 + DEPTH} mm - BedParameters.ply"
        face_inner_expr = f"{x0 + DEPTH} mm - 2 * BedParameters.ply"
        side_min_expr = (
            f"{x0 + DEPTH} mm - 2 * BedParameters.ply - "
            "BedParameters.LargeDrawerSideLength"
        )
        back_inner_expr = side_min_expr + " - BedParameters.ply"
        back_outer_expr = side_min_expr + " - 2 * BedParameters.ply"
        front_coordinate = side_max
        back_coordinate = side_min

    drawer = doc.addObject("App::Part", key)
    drawer.Label = label
    drawer.addProperty("App::PropertyString", "FrontDirection", "Drawer")
    drawer.FrontDirection = front_direction

    component_values = {
        "FrameWidth": frame_width,
        "FrameHeight": frame_height,
        "Clearance": clearance,
        "Ply": ply,
        "DrawerBoxWidth": box_width,
        "DrawerBoxHeight": box_height,
        "SlideWidth": slide_width,
        "HandleWidth": params.DrawerHandleWidth.Value,
        "HandleHeight": params.DrawerHandleHeight.Value,
        "WaveAmplitude": wave_amplitude,
        "Y": frame_y,
        "Z": frame_z,
    }
    component_expressions = {
        "FrameWidth": "30 in - 4 * BedParameters.ply",
        "FrameHeight": "14 in - 4 * BedParameters.ply",
        "Clearance": "BedParameters.DrawerClearance",
        "Ply": "BedParameters.ply",
        "DrawerBoxWidth": "BedParameters.LargeDrawerBoxWidth",
        "DrawerBoxHeight": "BedParameters.LargeDrawerBoxHeight",
        "SlideWidth": "BedParameters.DrawerSlideWidth",
        "HandleWidth": "BedParameters.DrawerHandleWidth",
        "HandleHeight": "BedParameters.DrawerHandleHeight",
        "WaveAmplitude": "BedParameters.DrawerWaveAmplitude",
        "Y": f"{y0} mm + 2 * BedParameters.ply",
        "Z": "2 * BedParameters.ply",
    }
    frame_bodies = {}
    for layer_name, layer_x, layer_x_expression, shade_offset in (
        ("Outer", face_outer_x, face_outer_expr, 0.14),
        ("Inner", face_inner_x, face_inner_expr, 0.20),
    ):
        frame_bodies[layer_name], _ = _drawer_component_layer(
            cabinet_part,
            key + "FaceFrame" + layer_name,
            label + " face frame — " + layer_name.lower(),
            "FaceFrame",
            {**component_values, "Thickness": ply, "X": layer_x},
            {
                **component_expressions,
                "Thickness": "BedParameters.ply",
                "X": layer_x_expression,
            },
            "X",
            tuple(max(0.0, c - shade_offset) for c in color),
        )
    add_face_frame_joints(cabinet_layers, frame_bodies, key, x0, y0, "main")
    add_main_center_support(
        cabinet_part, cabinet_layers, frame_bodies["Inner"],
        key.removesuffix("Drawer"), x0, y0, front_direction, color,
    )
    face_outer, face_outer_feature = _drawer_component_layer(
        drawer,
        key + "FaceOuter",
        "Drawer face — outer",
        "DrawerFront",
        {**component_values, "Thickness": ply, "X": face_outer_x},
        {
            **component_expressions,
            "Thickness": "BedParameters.ply",
            "X": face_outer_expr,
        },
        "X",
        color,
    )
    face_inner, face_inner_feature = _drawer_component_layer(
        drawer,
        key + "FaceInner",
        "Drawer face — inner",
        "DrawerFront",
        {**component_values, "Thickness": ply, "X": face_inner_x},
        {
            **component_expressions,
            "Thickness": "BedParameters.ply",
            "X": face_inner_expr,
        },
        "X",
        tuple(max(0.0, c - 0.08) for c in color),
    )
    drawer_components.create_filigree_engraving(
        drawer,
        key + "Engraving",
        label + " filigree engraving",
        filigree_source[0],
        filigree_source[1],
        filigree_source[2],
        face_outer_feature,
        -1 if front_direction == "-X" else 1,
    )
    add_profile_alignment_holes(
        [face_outer_feature, face_inner_feature], "X"
    )

    low_expr = f"{y0} mm + 6 * BedParameters.ply + BedParameters.DrawerClearance / 2"
    high_outer_expr = (
        low_expr + " + BedParameters.LargeDrawerBoxWidth - BedParameters.ply"
    )
    side_common = {
        "X": side_min_expr,
        "Length": "BedParameters.LargeDrawerSideLength",
        "Width": "BedParameters.ply",
        "Height": "BedParameters.LargeDrawerBoxHeight",
        "Z": box_z_expression,
    }
    side_specs = (
        ("LowOuter", box_low, low_expr),
        ("LowInner", box_low + ply, low_expr + " + BedParameters.ply"),
        (
            "HighInner",
            box_high - 2 * ply,
            low_expr
            + " + BedParameters.LargeDrawerBoxWidth - 2 * BedParameters.ply",
        ),
        ("HighOuter", box_high - ply, high_outer_expr),
    )
    side_bodies = {}
    side_features = {}
    for index, (side_name, side_y, side_y_expr) in enumerate(side_specs):
        side_bodies[side_name], side_features[side_name] = _drawer_layer(
            drawer,
            key + "Side" + side_name,
            "Drawer side — " + side_name.lower(),
            (side_min, side_y, box_z, side_length, ply, box_height),
            "Width",
            {**side_common, "Y": side_y_expr},
            tuple(max(0.0, c - 0.03 * index) for c in color),
        )

    back_common = {
        "Y": low_expr,
        "Width": "BedParameters.LargeDrawerBoxWidth",
        "Height": "BedParameters.LargeDrawerBoxHeight",
        "Z": box_z_expression,
        "Length": "BedParameters.ply",
    }
    back_inner, back_inner_feature = _drawer_layer(
        drawer,
        key + "BackInner",
        "Drawer back — inner",
        (back_inner_x, box_low, box_z, ply, box_width, box_height),
        "Length",
        {**back_common, "X": back_inner_expr},
        color,
    )
    back_outer, back_outer_feature = _drawer_layer(
        drawer,
        key + "BackOuter",
        "Drawer back — outer",
        (back_outer_x, box_low, box_z, ply, box_width, box_height),
        "Length",
        {**back_common, "X": back_outer_expr},
        tuple(max(0.0, c - 0.08) for c in color),
    )
    add_rectangular_alignment_holes(
        [back_inner_feature, back_outer_feature]
    )

    bottom, _ = _drawer_layer(
        drawer,
        key + "Bottom",
        "Drawer bottom — single ply",
        (
            side_min,
            box_low + 2 * ply,
            bottom_z,
            side_length,
            box_width - 4 * ply,
            ply,
        ),
        "Height",
        {
            "X": side_min_expr,
            "Y": low_expr + " + 2 * BedParameters.ply",
            "Z": box_z_expression + " + BedParameters.DrawerBottomOffset",
            "Length": "BedParameters.LargeDrawerSideLength",
            "Width": "BedParameters.LargeDrawerBoxWidth - 4 * BedParameters.ply",
            "Height": "BedParameters.ply",
        },
        tuple(max(0.0, c - 0.12) for c in color),
    )

    slide_z_expression = (
        "2 * BedParameters.ply + "
        "(14 in - 4 * BedParameters.ply - BedParameters.DrawerSlideWidth) / 2"
    )
    slide_common = {
        "X": side_min_expr,
        "Length": "BedParameters.LargeDrawerSideLength",
        "Thickness": "2 * BedParameters.ply",
        "Height": "BedParameters.DrawerSlideWidth",
        "Z": slide_z_expression,
    }
    low_slide_layers = _rounded_strip_stack(
        drawer,
        key + "LowSlide",
        "Drawer slide — low side",
        {
            "X": side_min,
            "Y": box_low - 2 * ply,
            "Z": slide_z,
            "Length": side_length,
            "Thickness": ply,
            "Height": slide_width,
        },
        {**slide_common, "Y": low_expr + " - 2 * BedParameters.ply"},
        "X",
        2,
        color,
    )
    high_slide_layers = _rounded_strip_stack(
        drawer,
        key + "HighSlide",
        "Drawer slide — high side",
        {
            "X": side_min,
            "Y": box_high,
            "Z": slide_z,
            "Length": side_length,
            "Thickness": 2 * ply,
            "Height": slide_width,
        },
        {**slide_common, "Y": low_expr + " + BedParameters.LargeDrawerBoxWidth"},
        "X",
        2,
        color,
    )
    for strip_layers in (low_slide_layers, high_slide_layers):
        add_strip_alignment_holes(
            [feature for _, feature in strip_layers],
            slide_width / 2,
            "Height / 2",
        )
    drawer_hole_z = slide_z + slide_width / 2
    drawer_hole_z_expression = (
        slide_z_expression + " + BedParameters.DrawerSlideWidth / 2"
    )
    for side_names in (
        ("LowOuter", "LowInner"),
        ("HighInner", "HighOuter"),
    ):
        add_strip_aligned_side_holes(
            [side_features[name] for name in side_names],
            "Y",
            "X",
            side_min,
            side_length,
            side_min_expr,
            "BedParameters.LargeDrawerSideLength",
            drawer_hole_z,
            drawer_hole_z_expression,
        )

    cabinet_strip_min = x0 + 4 * ply + params.FingerOvershoot.Value
    cabinet_strip_min_expr = (
        f"{x0} mm + 4 * BedParameters.ply + BedParameters.FingerOvershoot"
    )
    cabinet_strip_length = (
        side_length - 2 * ply - params.FingerOvershoot.Value
    )
    cabinet_strip_length_expr = (
        "BedParameters.LargeDrawerSideLength - 2 * BedParameters.ply "
        "- BedParameters.FingerOvershoot"
    )
    cabinet_hole_z = slide_z - slide_width / 2
    cabinet_hole_z_expression = (
        slide_z_expression + " - BedParameters.DrawerSlideWidth / 2"
    )
    for panel_name in ("LowerSide", "UpperSide"):
        side_layers = [
            cabinet_layers[(panel_name, "Outer")],
            cabinet_layers[(panel_name, "Inner")],
        ]
        for hole_z, hole_z_expression in (
            (cabinet_hole_z, cabinet_hole_z_expression),
            (
                slide_z + 1.5 * slide_width + clearance,
                slide_z_expression
                + " + 3 * BedParameters.DrawerSlideWidth / 2"
                + " + BedParameters.DrawerClearance",
            ),
        ):
            add_strip_aligned_side_holes(
                side_layers,
                "Y",
                "X",
                cabinet_strip_min,
                cabinet_strip_length,
                cabinet_strip_min_expr,
                cabinet_strip_length_expr,
                hole_z,
                hole_z_expression,
            )
    cabinet_slide_common = {
        "X": cabinet_strip_min_expr,
        "Length": cabinet_strip_length_expr,
        "Thickness": "4 * BedParameters.ply",
        "Height": "BedParameters.DrawerSlideWidth",
    }
    cabinet_strip_specs = (
        (
            "LowSupport",
            y0 + 2 * ply,
            f"{y0} mm + 2 * BedParameters.ply",
            slide_z - slide_width,
            slide_z_expression + " - BedParameters.DrawerSlideWidth",
            1,
        ),
        (
            "LowAntiTip",
            y0 + 2 * ply,
            f"{y0} mm + 2 * BedParameters.ply",
            slide_z + slide_width + clearance,
            slide_z_expression
            + " + BedParameters.DrawerSlideWidth + BedParameters.DrawerClearance",
            1,
        ),
        (
            "HighSupport",
            y0 + WIDTH - 3 * ply,
            f"{y0 + WIDTH} mm - 3 * BedParameters.ply",
            slide_z - slide_width,
            slide_z_expression + " - BedParameters.DrawerSlideWidth",
            -1,
        ),
        (
            "HighAntiTip",
            y0 + WIDTH - 3 * ply,
            f"{y0 + WIDTH} mm - 3 * BedParameters.ply",
            slide_z + slide_width + clearance,
            slide_z_expression
            + " + BedParameters.DrawerSlideWidth + BedParameters.DrawerClearance",
            -1,
        ),
    )
    for strip_name, strip_y, strip_y_expression, strip_z, strip_z_expression, layer_step in cabinet_strip_specs:
        strip_layers = _rounded_strip_stack(
            cabinet_part,
            key + "Cabinet" + strip_name,
            label + " cabinet " + strip_name.lower() + " strip",
            {
                "X": cabinet_strip_min,
                "Y": strip_y,
                "Z": strip_z,
                "Length": cabinet_strip_length,
                "Thickness": 4 * ply,
                "Height": slide_width,
            },
            {
                **cabinet_slide_common,
                "Y": strip_y_expression,
                "Z": strip_z_expression,
            },
            "X",
            4,
            color,
            (2, 3),
            layer_step,
        )
        add_strip_alignment_holes(
            [feature for _, feature in strip_layers],
            slide_width / 2,
            "Height / 2",
        )
    for side_name, layer_one_y, layer_one_y_expression, layer_step in (
        ("Low", y0 + 2 * ply, f"{y0} mm + 2 * BedParameters.ply", 1),
        (
            "High",
            y0 + WIDTH - 3 * ply,
            f"{y0 + WIDTH} mm - 3 * BedParameters.ply",
            -1,
        ),
    ):
        operator = " + " if layer_step > 0 else " - "
        for layer_index in (0, 1):
            layer_suffix = "" if layer_index == 0 else operator + "BedParameters.ply"
            _, channel_back = _connected_strip_pair_layer(
                cabinet_part,
                key + "Cabinet" + side_name + f"ChannelBackLayer{layer_index + 1}",
                label
                + " cabinet "
                + side_name.lower()
                + f" channel back — layer {layer_index + 1}",
                {
                    "X": cabinet_strip_min,
                    "Y": layer_one_y + layer_step * layer_index * ply,
                    "Z": slide_z - slide_width,
                    "Length": cabinet_strip_length,
                    "Thickness": ply,
                    "Height": slide_width,
                    "Separation": 2 * slide_width + clearance,
                    "HasHoles": True,
                    "AccessHoleDiameter": slide_width,
                    "AccessHole1Position": x0 + DEPTH / 3 - cabinet_strip_min,
                    "AccessHole2Position": x0 + 2 * DEPTH / 3 - cabinet_strip_min,
                    "AccessHoleCenterHeight": 1.5 * slide_width,
                },
                {
                    "X": cabinet_strip_min_expr,
                    "Y": layer_one_y_expression + layer_suffix,
                    "Z": slide_z_expression + " - BedParameters.DrawerSlideWidth",
                    "Length": cabinet_strip_length_expr,
                    "Thickness": "BedParameters.ply",
                    "Height": "BedParameters.DrawerSlideWidth",
                    "Separation": (
                        "2 * BedParameters.DrawerSlideWidth + "
                        "BedParameters.DrawerClearance"
                    ),
                    "AccessHoleDiameter": "BedParameters.DrawerSlideWidth",
                    "AccessHole1Position": (
                        f"{x0 + DEPTH / 3} mm - ({cabinet_strip_min_expr})"
                    ),
                    "AccessHole2Position": (
                        f"{x0 + 2 * DEPTH / 3} mm - ({cabinet_strip_min_expr})"
                    ),
                    "AccessHoleCenterHeight": (
                        "3 * BedParameters.DrawerSlideWidth / 2"
                    ),
                },
                "X",
                tuple(max(0.0, c - 0.025 * layer_index) for c in color),
            )
            add_strip_alignment_holes(
                [channel_back], slide_width / 2, "Height / 2"
            )
            add_strip_alignment_holes(
                [channel_back],
                2.5 * slide_width + clearance,
                "Separation + Height / 2",
            )

    doc.recompute()
    full_back = [back_inner, back_outer]
    for side_name in ("LowOuter", "LowInner", "HighInner", "HighOuter"):
        side = side_bodies[side_name]
        _apply_drawer_joint(
            side,
            App.Vector(1, 0, 0),
            front_coordinate,
            [face_inner],
            label + " hidden side-to-face joint (zero overshoot)",
            hidden_front_joint=True,
        )
        _apply_drawer_joint(
            side,
            App.Vector(1, 0, 0),
            back_coordinate,
            full_back,
            label + " side-to-back joint",
        )

    _apply_drawer_joint(
        bottom,
        App.Vector(0, 1, 0),
        box_low + 2 * ply,
        [side_bodies["LowOuter"], side_bodies["LowInner"]],
        label + " bottom-to-low-side joint",
    )
    _apply_drawer_joint(
        bottom,
        App.Vector(0, 1, 0),
        box_high - 2 * ply,
        [side_bodies["HighInner"], side_bodies["HighOuter"]],
        label + " bottom-to-high-side joint",
    )
    _apply_drawer_joint(
        bottom,
        App.Vector(1, 0, 0),
        back_coordinate,
        full_back,
        label + " bottom-to-back joint",
    )
    _apply_drawer_joint(
        bottom,
        App.Vector(1, 0, 0),
        front_coordinate,
        [face_inner],
        label + " hidden bottom-to-face joint (zero overshoot)",
        hidden_front_joint=True,
    )
    return drawer


def create_bedside_drawer(
    doc,
    cabinet_part,
    cabinet_layers,
    key,
    label,
    x0,
    y0,
    drawer_index,
    color,
    filigree_source,
):
    """Create one of the two doubled-wall drawers in a bedside cabinet."""
    ply = doc.BedParameters.ply.Value
    params = doc.BedParameters
    clearance = params.DrawerClearance.Value
    slide_width = params.DrawerSlideWidth.Value
    box_width = params.BedsideDrawerBoxWidth.Value
    box_height = params.BedsideDrawerBoxHeight.Value
    side_length = params.BedsideDrawerSideLength.Value
    box_low = x0 + 6 * ply + clearance / 2
    box_high = box_low + box_width
    side_min = y0 + 2 * ply
    side_max = side_min + side_length
    frame_width = BEDSIDE_SIZE - 4 * ply
    frame_height = HEIGHT - 4 * ply
    face_height = frame_height / 2
    face_z = 2 * ply + drawer_index * face_height
    vertical_wave = params.DrawerWaveAmplitude.Value
    box_z = face_z + 2 * ply + vertical_wave
    bottom_z = box_z + params.DrawerBottomOffset.Value
    slide_z = face_z + face_height / 2 - slide_width / 2
    face_x = x0 + 2 * ply

    drawer = doc.addObject("App::Part", key)
    drawer.Label = label
    drawer.addProperty("App::PropertyString", "FrontDirection", "Drawer")
    drawer.FrontDirection = "-Y"

    face_height_expr = "(14 in - 4 * BedParameters.ply) / 2"
    face_z_expr = "2 * BedParameters.ply"
    if drawer_index:
        face_z_expr += " + " + face_height_expr
    box_z_expr = (
        face_z_expr
        + " + 2 * BedParameters.ply + BedParameters.DrawerWaveAmplitude"
    )
    low_expr = (
        f"{x0} mm + 6 * BedParameters.ply + "
        "BedParameters.DrawerClearance / 2"
    )
    side_min_expr = f"{y0} mm + 2 * BedParameters.ply"
    side_max_expr = (
        side_min_expr + " + BedParameters.BedsideDrawerSideLength"
    )

    component_values = {
        "FrameWidth": frame_width,
        "FrameHeight": face_height,
        "Clearance": clearance,
        "Ply": ply,
        "DrawerBoxWidth": box_width,
        "DrawerBoxHeight": box_height,
        "SlideWidth": slide_width,
        "HandleWidth": 2 * params.DrawerHandleWidth.Value / 3,
        "HandleHeight": params.DrawerHandleHeight.Value / 2,
        "WaveAmplitude": vertical_wave,
        "X": face_x,
        "Z": face_z,
    }
    component_expressions = {
        "FrameWidth": "20 in - 4 * BedParameters.ply",
        "FrameHeight": face_height_expr,
        "Clearance": "BedParameters.DrawerClearance",
        "Ply": "BedParameters.ply",
        "DrawerBoxWidth": "BedParameters.BedsideDrawerBoxWidth",
        "DrawerBoxHeight": "BedParameters.BedsideDrawerBoxHeight",
        "SlideWidth": "BedParameters.DrawerSlideWidth",
        "HandleWidth": "2 * BedParameters.DrawerHandleWidth / 3",
        "HandleHeight": "BedParameters.DrawerHandleHeight / 2",
        "WaveAmplitude": "BedParameters.DrawerWaveAmplitude",
        "X": f"{x0} mm + 2 * BedParameters.ply",
        "Z": face_z_expr,
    }
    if drawer_index == 0:
        frame_values = {
            **component_values,
            "FrameHeight": frame_height,
            "Thickness": ply,
            "Y": y0,
            "Z": 2 * ply,
        }
        frame_expressions = {
            **component_expressions,
            "FrameHeight": "14 in - 4 * BedParameters.ply",
            "Thickness": "BedParameters.ply",
            "Y": f"{y0} mm",
            "Z": "2 * BedParameters.ply",
        }
        frame_bodies = {}
        for layer_name, layer_y, layer_y_expression, shade_offset in (
            ("Outer", y0, f"{y0} mm", 0.14),
            (
                "Inner",
                y0 + ply,
                f"{y0} mm + BedParameters.ply",
                0.20,
            ),
        ):
            frame_bodies[layer_name], _ = _drawer_component_layer(
                cabinet_part,
                key + "CombinedFaceFrame" + layer_name,
                label.replace(" lower", "")
                + " combined face frame — "
                + layer_name.lower(),
                "DoubleFaceFrame",
                {**frame_values, "Y": layer_y},
                {**frame_expressions, "Y": layer_y_expression},
                "Y",
                tuple(max(0.0, c - shade_offset) for c in color),
            )
        add_face_frame_joints(
            cabinet_layers, frame_bodies, key, x0, y0, "bedside"
        )
    face_outer, face_outer_feature = _drawer_component_layer(
        drawer,
        key + "FaceOuter",
        "Drawer face — outer",
        "DrawerFront",
        {**component_values, "Thickness": ply, "Y": y0},
        {
            **component_expressions,
            "Thickness": "BedParameters.ply",
            "Y": f"{y0} mm",
        },
        "Y",
        color,
    )
    face_inner, face_inner_feature = _drawer_component_layer(
        drawer,
        key + "FaceInner",
        "Drawer face — inner",
        "DrawerFront",
        {**component_values, "Thickness": ply, "Y": y0 + ply},
        {
            **component_expressions,
            "Thickness": "BedParameters.ply",
            "Y": f"{y0} mm + BedParameters.ply",
        },
        "Y",
        tuple(max(0.0, c - 0.08) for c in color),
    )
    drawer_components.create_filigree_engraving_pair(
        drawer,
        key + "Engraving",
        label + " filigree engraving",
        filigree_source[0],
        filigree_source[1],
        filigree_source[2],
        filigree_source[3],
        face_outer_feature,
        -1,
    )
    add_profile_alignment_holes(
        [face_outer_feature, face_inner_feature], "Y"
    )

    side_common = {
        "Y": side_min_expr,
        "Width": "BedParameters.BedsideDrawerSideLength",
        "Length": "BedParameters.ply",
        "Height": "BedParameters.BedsideDrawerBoxHeight",
        "Z": box_z_expr,
    }
    side_specs = (
        ("LowOuter", box_low, low_expr),
        ("LowInner", box_low + ply, low_expr + " + BedParameters.ply"),
        (
            "HighInner",
            box_high - 2 * ply,
            low_expr
            + " + BedParameters.BedsideDrawerBoxWidth - 2 * BedParameters.ply",
        ),
        (
            "HighOuter",
            box_high - ply,
            low_expr
            + " + BedParameters.BedsideDrawerBoxWidth - BedParameters.ply",
        ),
    )
    side_bodies = {}
    side_features = {}
    for index, (side_name, side_x, side_x_expr) in enumerate(side_specs):
        side_bodies[side_name], side_features[side_name] = _drawer_layer(
            drawer,
            key + "Side" + side_name,
            "Drawer side — " + side_name.lower(),
            (side_x, side_min, box_z, ply, side_length, box_height),
            "Length",
            {**side_common, "X": side_x_expr},
            tuple(max(0.0, c - 0.03 * index) for c in color),
        )

    back_common = {
        "X": low_expr,
        "Length": "BedParameters.BedsideDrawerBoxWidth",
        "Width": "BedParameters.ply",
        "Height": "BedParameters.BedsideDrawerBoxHeight",
        "Z": box_z_expr,
    }
    back_inner, back_inner_feature = _drawer_layer(
        drawer,
        key + "BackInner",
        "Drawer back — inner",
        (box_low, side_max, box_z, box_width, ply, box_height),
        "Width",
        {**back_common, "Y": side_max_expr},
        color,
    )
    back_outer, back_outer_feature = _drawer_layer(
        drawer,
        key + "BackOuter",
        "Drawer back — outer",
        (box_low, side_max + ply, box_z, box_width, ply, box_height),
        "Width",
        {**back_common, "Y": side_max_expr + " + BedParameters.ply"},
        tuple(max(0.0, c - 0.08) for c in color),
    )
    add_rectangular_alignment_holes(
        [back_inner_feature, back_outer_feature]
    )

    bottom, _ = _drawer_layer(
        drawer,
        key + "Bottom",
        "Drawer bottom — single ply",
        (
            box_low + 2 * ply,
            side_min,
            bottom_z,
            box_width - 4 * ply,
            side_length,
            ply,
        ),
        "Height",
        {
            "X": low_expr + " + 2 * BedParameters.ply",
            "Y": side_min_expr,
            "Z": box_z_expr + " + BedParameters.DrawerBottomOffset",
            "Length": "BedParameters.BedsideDrawerBoxWidth - 4 * BedParameters.ply",
            "Width": "BedParameters.BedsideDrawerSideLength",
            "Height": "BedParameters.ply",
        },
        tuple(max(0.0, c - 0.12) for c in color),
    )

    slide_z_expression = (
        face_z_expr
        + " + ("
        + face_height_expr
        + " - BedParameters.DrawerSlideWidth) / 2"
    )
    slide_common = {
        "Y": side_min_expr,
        "Length": "BedParameters.BedsideDrawerSideLength",
        "Thickness": "2 * BedParameters.ply",
        "Height": "BedParameters.DrawerSlideWidth",
        "Z": slide_z_expression,
    }
    low_slide_layers = _rounded_strip_stack(
        drawer,
        key + "LowSlide",
        "Drawer slide — low side",
        {
            "X": box_low - 2 * ply,
            "Y": side_min,
            "Z": slide_z,
            "Length": side_length,
            "Thickness": 2 * ply,
            "Height": slide_width,
        },
        {**slide_common, "X": low_expr + " - 2 * BedParameters.ply"},
        "Y",
        2,
        color,
    )
    high_slide_layers = _rounded_strip_stack(
        drawer,
        key + "HighSlide",
        "Drawer slide — high side",
        {
            "X": box_high,
            "Y": side_min,
            "Z": slide_z,
            "Length": side_length,
            "Thickness": 2 * ply,
            "Height": slide_width,
        },
        {
            **slide_common,
            "X": low_expr + " + BedParameters.BedsideDrawerBoxWidth",
        },
        "Y",
        2,
        color,
    )
    for strip_layers in (low_slide_layers, high_slide_layers):
        add_strip_alignment_holes(
            [feature for _, feature in strip_layers],
            slide_width / 2,
            "Height / 2",
        )
    drawer_hole_z = slide_z + slide_width / 2
    drawer_hole_z_expression = (
        slide_z_expression + " + BedParameters.DrawerSlideWidth / 2"
    )
    for side_names in (
        ("LowOuter", "LowInner"),
        ("HighInner", "HighOuter"),
    ):
        add_strip_aligned_side_holes(
            [side_features[name] for name in side_names],
            "X",
            "Y",
            side_min,
            side_length,
            side_min_expr,
            "BedParameters.BedsideDrawerSideLength",
            drawer_hole_z,
            drawer_hole_z_expression,
        )

    cabinet_strip_min = y0 + 4 * ply + params.FingerOvershoot.Value
    cabinet_strip_min_expr = (
        f"{y0} mm + 4 * BedParameters.ply + BedParameters.FingerOvershoot"
    )
    cabinet_strip_length = (
        side_length - 2 * ply - params.FingerOvershoot.Value
    )
    cabinet_strip_length_expr = (
        "BedParameters.BedsideDrawerSideLength - 2 * BedParameters.ply "
        "- BedParameters.FingerOvershoot"
    )
    cabinet_hole_z = slide_z - slide_width / 2
    cabinet_hole_z_expression = (
        slide_z_expression + " - BedParameters.DrawerSlideWidth / 2"
    )
    for panel_name in ("LeftSide", "RightSide"):
        side_layers = [
            cabinet_layers[(panel_name, "Outer")],
            cabinet_layers[(panel_name, "Inner")],
        ]
        for hole_z, hole_z_expression in (
            (cabinet_hole_z, cabinet_hole_z_expression),
            (
                slide_z + 1.5 * slide_width + clearance,
                slide_z_expression
                + " + 3 * BedParameters.DrawerSlideWidth / 2"
                + " + BedParameters.DrawerClearance",
            ),
        ):
            add_strip_aligned_side_holes(
                side_layers,
                "X",
                "Y",
                cabinet_strip_min,
                cabinet_strip_length,
                cabinet_strip_min_expr,
                cabinet_strip_length_expr,
                hole_z,
                hole_z_expression,
            )
    cabinet_slide_common = {
        "Y": cabinet_strip_min_expr,
        "Length": cabinet_strip_length_expr,
        "Thickness": "4 * BedParameters.ply",
        "Height": "BedParameters.DrawerSlideWidth",
    }
    cabinet_strip_specs = (
        (
            "LowSupport",
            x0 + 2 * ply,
            f"{x0} mm + 2 * BedParameters.ply",
            slide_z - slide_width,
            slide_z_expression + " - BedParameters.DrawerSlideWidth",
            1,
        ),
        (
            "LowAntiTip",
            x0 + 2 * ply,
            f"{x0} mm + 2 * BedParameters.ply",
            slide_z + slide_width + clearance,
            slide_z_expression
            + " + BedParameters.DrawerSlideWidth + BedParameters.DrawerClearance",
            1,
        ),
        (
            "HighSupport",
            x0 + BEDSIDE_SIZE - 3 * ply,
            f"{x0 + BEDSIDE_SIZE} mm - 3 * BedParameters.ply",
            slide_z - slide_width,
            slide_z_expression + " - BedParameters.DrawerSlideWidth",
            -1,
        ),
        (
            "HighAntiTip",
            x0 + BEDSIDE_SIZE - 3 * ply,
            f"{x0 + BEDSIDE_SIZE} mm - 3 * BedParameters.ply",
            slide_z + slide_width + clearance,
            slide_z_expression
            + " + BedParameters.DrawerSlideWidth + BedParameters.DrawerClearance",
            -1,
        ),
    )
    for strip_name, strip_x, strip_x_expression, strip_z, strip_z_expression, layer_step in cabinet_strip_specs:
        strip_layers = _rounded_strip_stack(
            cabinet_part,
            key + "Cabinet" + strip_name,
            label + " cabinet " + strip_name.lower() + " strip",
            {
                "X": strip_x,
                "Y": cabinet_strip_min,
                "Z": strip_z,
                "Length": cabinet_strip_length,
                "Thickness": 4 * ply,
                "Height": slide_width,
            },
            {
                **cabinet_slide_common,
                "X": strip_x_expression,
                "Z": strip_z_expression,
            },
            "Y",
            4,
            color,
            (2, 3),
            layer_step,
        )
        add_strip_alignment_holes(
            [feature for _, feature in strip_layers],
            slide_width / 2,
            "Height / 2",
        )
    for side_name, layer_one_x, layer_one_x_expression, layer_step in (
        ("Low", x0 + 2 * ply, f"{x0} mm + 2 * BedParameters.ply", 1),
        (
            "High",
            x0 + BEDSIDE_SIZE - 3 * ply,
            f"{x0 + BEDSIDE_SIZE} mm - 3 * BedParameters.ply",
            -1,
        ),
    ):
        operator = " + " if layer_step > 0 else " - "
        for layer_index in (0, 1):
            layer_suffix = "" if layer_index == 0 else operator + "BedParameters.ply"
            _, channel_back = _connected_strip_pair_layer(
                cabinet_part,
                key + "Cabinet" + side_name + f"ChannelBackLayer{layer_index + 1}",
                label
                + " cabinet "
                + side_name.lower()
                + f" channel back — layer {layer_index + 1}",
                {
                    "X": layer_one_x + layer_step * layer_index * ply,
                    "Y": cabinet_strip_min,
                    "Z": slide_z - slide_width,
                    "Length": cabinet_strip_length,
                    "Thickness": ply,
                    "Height": slide_width,
                    "Separation": 2 * slide_width + clearance,
                    "HasHoles": True,
                    "AccessHoleDiameter": slide_width,
                    "AccessHole1Position": y0 + BEDSIDE_SIZE / 3 - cabinet_strip_min,
                    "AccessHole2Position": y0 + 2 * BEDSIDE_SIZE / 3 - cabinet_strip_min,
                    "AccessHoleCenterHeight": 1.5 * slide_width,
                },
                {
                    "X": layer_one_x_expression + layer_suffix,
                    "Y": cabinet_strip_min_expr,
                    "Z": slide_z_expression + " - BedParameters.DrawerSlideWidth",
                    "Length": cabinet_strip_length_expr,
                    "Thickness": "BedParameters.ply",
                    "Height": "BedParameters.DrawerSlideWidth",
                    "Separation": (
                        "2 * BedParameters.DrawerSlideWidth + "
                        "BedParameters.DrawerClearance"
                    ),
                    "AccessHoleDiameter": "BedParameters.DrawerSlideWidth",
                    "AccessHole1Position": (
                        f"{y0 + BEDSIDE_SIZE / 3} mm - ({cabinet_strip_min_expr})"
                    ),
                    "AccessHole2Position": (
                        f"{y0 + 2 * BEDSIDE_SIZE / 3} mm - ({cabinet_strip_min_expr})"
                    ),
                    "AccessHoleCenterHeight": (
                        "3 * BedParameters.DrawerSlideWidth / 2"
                    ),
                },
                "Y",
                tuple(max(0.0, c - 0.025 * layer_index) for c in color),
            )
            add_strip_alignment_holes(
                [channel_back], slide_width / 2, "Height / 2"
            )
            add_strip_alignment_holes(
                [channel_back],
                2.5 * slide_width + clearance,
                "Separation + Height / 2",
            )

    doc.recompute()
    full_back = [back_inner, back_outer]
    for side_name in ("LowOuter", "LowInner", "HighInner", "HighOuter"):
        side = side_bodies[side_name]
        _apply_drawer_joint(
            side,
            App.Vector(0, 1, 0),
            side_min,
            [face_inner],
            label + " hidden side-to-face joint (zero overshoot)",
            hidden_front_joint=True,
        )
        _apply_drawer_joint(
            side,
            App.Vector(0, 1, 0),
            side_max,
            full_back,
            label + " side-to-back joint",
        )

    _apply_drawer_joint(
        bottom,
        App.Vector(1, 0, 0),
        box_low + 2 * ply,
        [side_bodies["LowOuter"], side_bodies["LowInner"]],
        label + " bottom-to-low-side joint",
    )
    _apply_drawer_joint(
        bottom,
        App.Vector(1, 0, 0),
        box_high - 2 * ply,
        [side_bodies["HighInner"], side_bodies["HighOuter"]],
        label + " bottom-to-high-side joint",
    )
    _apply_drawer_joint(
        bottom,
        App.Vector(0, 1, 0),
        side_max,
        full_back,
        label + " bottom-to-back joint",
    )
    _apply_drawer_joint(
        bottom,
        App.Vector(0, 1, 0),
        side_min,
        [face_inner],
        label + " hidden bottom-to-face joint (zero overshoot)",
        hidden_front_joint=True,
    )
    return drawer


def set_profile(feature, prefix, box, expressions, axis, rounded):
    for suffix, value in zip(("X", "Y", "Z", "Length", "Width", "Height"), box):
        setattr(feature, prefix + suffix, value)
    for suffix, expression in expressions.items():
        feature.setExpression(prefix + suffix, expression)
    setattr(feature, prefix + "Axis", axis)
    setattr(feature, prefix + "Rounded", rounded)
    setattr(feature, "Has" + prefix, True)


def next_recess_prefix(feature):
    for prefix in ("Recess", "Recess2", "Recess3"):
        if not getattr(feature, "Has" + prefix):
            return prefix
    raise ValueError(f"No free recess slot on {feature.Name}")


def add_recess(feature, box, expressions, axis="X", rounded=False):
    set_profile(
        feature,
        next_recess_prefix(feature),
        box,
        expressions,
        axis,
        rounded,
    )


def next_hole_prefix(feature):
    for prefix in panel_tools.HOLE_PREFIXES:
        if not getattr(feature, "Has" + prefix):
            return prefix
    raise ValueError(f"No free hole slot on {feature.Name}")


def add_hole(
    feature,
    origin,
    axis,
    expressions=None,
    diameter=None,
    diameter_expression="BedParameters.BoltHoleDiameter",
):
    ply = feature.Document.BedParameters.ply.Value
    if diameter is None:
        diameter = feature.Document.BedParameters.BoltHoleDiameter.Value
    body = _feature_body(feature)
    if body.Tip is not feature:
        cut_expressions = {
            "Length": "BedParameters.ply",
            "Diameter": diameter_expression,
        }
        for suffix, expression in (expressions or {}).items():
            cut_expressions[suffix] = expression
        cut = panel_tools.create_parametric_hole_cut(
            body,
            feature,
            feature.Label + " — hole",
            origin,
            axis,
            ply,
            diameter,
            cut_expressions,
        )
        cut.ShapeMaterial = WOOD_MATERIAL
        return cut

    prefix = next_hole_prefix(feature)
    for suffix, value in zip(("X", "Y", "Z"), origin):
        setattr(feature, prefix + suffix, value)
    setattr(feature, prefix + "Length", ply)
    setattr(feature, prefix + "Diameter", diameter)
    setattr(feature, prefix + "Axis", axis)
    feature.setExpression(prefix + "Length", "BedParameters.ply")
    feature.setExpression(prefix + "Diameter", diameter_expression)
    for suffix, expression in (expressions or {}).items():
        feature.setExpression(prefix + suffix, expression)
    setattr(feature, "Has" + prefix, True)
    feature.touch()
    if getattr(feature, "Proxy", None) is not None:
        feature.Proxy.execute(feature)


def add_dowel_hole(feature, origin, axis, expressions=None):
    add_hole(
        feature,
        origin,
        axis,
        expressions,
        feature.Document.BedParameters.DowelDiameter.Value,
        "BedParameters.DowelDiameter",
    )


_PANEL_AXES = {
    "X": ("X", "Length"),
    "Y": ("Y", "Width"),
    "Z": ("Z", "Height"),
}
_THICKNESS_AXES = {"Length": "X", "Width": "Y", "Height": "Z"}


def add_rectangular_alignment_holes(features, use_final_shape=False, use_short_axis=False):
    """Add two aligned holes using the stack's in-plane bounding rectangle."""
    first = features[0]
    thickness_axis = _THICKNESS_AXES[first.PanelThicknessProperty]
    plane_axes = [axis for axis in "XYZ" if axis != thickness_axis]
    if use_final_shape:
        inputs = [_feature_body(feature).Tip for feature in features]
        live_bounds = panel_tools.create_alignment_bounds(
            _feature_body(first).getParentGeoFeatureGroup(),
            first.Name + "AlignmentBounds",
            inputs,
        )
        bounds = {
            axis: (
                getattr(live_bounds, axis + "Min").Value,
                getattr(live_bounds, axis + "Max").Value,
            )
            for axis in plane_axes
        }
    else:
        bounds = {
            axis: (
                min(getattr(feature, _PANEL_AXES[axis][0]).Value for feature in features),
                max(
                    getattr(feature, _PANEL_AXES[axis][0]).Value
                    + getattr(feature, _PANEL_AXES[axis][1]).Value
                    for feature in features
                ),
            )
            for axis in plane_axes
        }
    long_axis = max(
        plane_axes,
        key=lambda axis: bounds[axis][1] - bounds[axis][0],
    )
    short_axis = next(axis for axis in plane_axes if axis != long_axis)
    if use_short_axis:
        long_axis, short_axis = short_axis, long_axis
    thickness_origin, _ = _PANEL_AXES[thickness_axis]

    for fraction in (1, 5):
        divisor = 6
        long_coordinate = (
            bounds[long_axis][0]
            + fraction * (bounds[long_axis][1] - bounds[long_axis][0]) / divisor
        )
        short_coordinate = (bounds[short_axis][0] + bounds[short_axis][1]) / 2
        for feature in features:
            values = {
                long_axis: long_coordinate,
                short_axis: short_coordinate,
                thickness_axis: getattr(feature, thickness_origin).Value,
            }
            if use_final_shape:
                expressions = {
                    long_axis: (
                        f"{live_bounds.Name}.{long_axis}Min + {fraction} * "
                        f"({live_bounds.Name}.{long_axis}Max - "
                        f"{live_bounds.Name}.{long_axis}Min) / {divisor}"
                    ),
                    short_axis: (
                        f"({live_bounds.Name}.{short_axis}Min + "
                        f"{live_bounds.Name}.{short_axis}Max) / 2"
                    ),
                }
            else:
                long_origin, long_size = _PANEL_AXES[long_axis]
                short_origin, short_size = _PANEL_AXES[short_axis]
                expressions = {
                    long_axis: (
                        f"{long_origin} + {fraction} * {long_size} / {divisor}"
                    ),
                    short_axis: f"{short_origin} + {short_size} / 2",
                }
            expressions[thickness_axis] = thickness_origin
            add_dowel_hole(
                feature,
                tuple(values[axis] for axis in "XYZ"),
                thickness_axis,
                expressions,
            )


def add_panel_stack_alignment(layers, excluded=()):
    """Add alignment holes to every outer/inner panel pair in a cabinet."""
    panel_names = sorted({panel_name for panel_name, _ in layers})
    for panel_name in panel_names:
        if panel_name in excluded:
            continue
        add_rectangular_alignment_holes(
            [layers[(panel_name, "Outer")], layers[(panel_name, "Inner")]],
            use_final_shape=True,
            use_short_axis=panel_name == "Top" and ("LowerSide", "Outer") in layers,
        )


def add_profile_alignment_holes(features, axis):
    """Add 1/6 and 5/6 holes to an ornamental drawer-front stack."""
    for fraction in (1, 5):
        for feature in features:
            if axis == "X":
                origin = (
                    feature.X.Value,
                    feature.Y.Value + fraction * feature.FrameWidth.Value / 6,
                    feature.Z.Value + feature.FrameHeight.Value / 2,
                )
                expressions = {
                    "X": "X",
                    "Y": f"Y + {fraction} * FrameWidth / 6",
                    "Z": "Z + FrameHeight / 2",
                }
            else:
                origin = (
                    feature.X.Value + fraction * feature.FrameWidth.Value / 6,
                    feature.Y.Value,
                    feature.Z.Value + feature.FrameHeight.Value / 2,
                )
                expressions = {
                    "X": f"X + {fraction} * FrameWidth / 6",
                    "Y": "Y",
                    "Z": "Z + FrameHeight / 2",
                }
            add_dowel_hole(feature, origin, axis, expressions)


def add_strip_alignment_holes(
    features, z_offset, z_offset_expression
):
    """Add two dowel holes through each ply of an aligned strip stack."""
    for fraction in (1, 5):
        for feature in features:
            if feature.Axis == "X":
                origin = (
                    feature.X.Value + fraction * feature.Length.Value / 6,
                    feature.Y.Value,
                    feature.Z.Value + z_offset,
                )
                axis = "Y"
                expressions = {
                    "X": f"X + {fraction} * Length / 6",
                    "Y": "Y",
                    "Z": f"Z + ({z_offset_expression})",
                }
            else:
                origin = (
                    feature.X.Value,
                    feature.Y.Value + fraction * feature.Length.Value / 6,
                    feature.Z.Value + z_offset,
                )
                axis = "X"
                expressions = {
                    "X": "X",
                    "Y": f"Y + {fraction} * Length / 6",
                    "Z": f"Z + ({z_offset_expression})",
                }
            add_dowel_hole(feature, origin, axis, expressions)


def add_strip_aligned_side_holes(
    features,
    axis,
    long_axis,
    long_origin,
    long_length,
    long_origin_expression,
    long_length_expression,
    z_center,
    z_expression,
):
    """Put a side-wall stack's two holes on its attached runner centerline."""
    for fraction in (1, 5):
        long_coordinate = long_origin + fraction * long_length / 6
        for feature in features:
            origin = {
                "X": feature.X.Value,
                "Y": feature.Y.Value,
                "Z": z_center,
            }
            origin[long_axis] = long_coordinate
            expressions = {
                axis: axis,
                long_axis: (
                    f"({long_origin_expression}) + {fraction} * "
                    f"({long_length_expression}) / 6"
                ),
                "Z": z_expression,
            }
            add_dowel_hole(
                feature,
                tuple(origin[coordinate] for coordinate in "XYZ"),
                axis,
                expressions,
            )


def create_cabinet(doc, key, label, x0, y0, front_direction, color):
    ply = doc.BedParameters.ply.Value
    part = doc.addObject("App::Part", key)
    part.Label = label
    part.addProperty("App::PropertyString", "FrontDirection", "Cabinet")
    part.FrontDirection = front_direction
    layers = {}

    def layer(panel_name, layer_name, box, thickness_property, expressions):
        name = key + panel_name + layer_name
        display = panel_name.replace("_", " ").strip() + " — " + layer_name.lower()
        shade = color if layer_name == "Outer" else tuple(max(0.0, c - 0.12) for c in color)
        item = make_layer(part, name, display, box, thickness_property, expressions, shade)
        layers[(panel_name, layer_name)] = item

    if front_direction == "-X":
        side_x = x0
        side_x_expr = f"{x0} mm"
        back_outer_x = x0 + DEPTH - ply
        back_inner_x = x0 + DEPTH - 2 * ply
        front_strip_x = x0
        back_strip_x = x0 + DEPTH - 2 * ply - STRIP
        back_strip_x_expr = f"{x0 + DEPTH - STRIP} mm - 2 * BedParameters.ply"
        outer_x_expr = f"{x0 + DEPTH} mm - BedParameters.ply"
        inner_x_expr = f"{x0 + DEPTH} mm - 2 * BedParameters.ply"
    else:
        side_x = x0 + 2 * ply
        side_x_expr = f"{x0} mm + 2 * BedParameters.ply"
        back_outer_x = x0
        back_inner_x = x0 + ply
        front_strip_x = x0 + DEPTH - STRIP
        back_strip_x = x0 + 2 * ply
        back_strip_x_expr = f"{x0} mm + 2 * BedParameters.ply"
        outer_x_expr = f"{x0} mm"
        inner_x_expr = f"{x0} mm + BedParameters.ply"

    # The top covers the cabinet; every vertical panel stops at its underside.
    layer("Top", "Outer", (x0, y0, HEIGHT - ply, DEPTH, WIDTH, ply), "Height", {
        "Height": "BedParameters.ply",
        "Z": f"{HEIGHT} mm - BedParameters.ply",
    })
    layer("Top", "Inner", (x0, y0, HEIGHT - 2 * ply, DEPTH, WIDTH, ply), "Height", {
        "Height": "BedParameters.ply",
        "Z": f"{HEIGHT} mm - 2 * BedParameters.ply",
    })

    side_length = DEPTH - 2 * ply
    side_height = HEIGHT - 2 * ply
    side_expressions = {
        "Length": f"{DEPTH} mm - 2 * BedParameters.ply",
        "Height": f"{HEIGHT} mm - 2 * BedParameters.ply",
        "X": side_x_expr,
    }

    # Sides butt against the back and the underside of the top.
    layer("LowerSide", "Outer", (side_x, y0, 0, side_length, ply, side_height), "Width", {
        **side_expressions,
        "Width": "BedParameters.ply",
    })
    layer("LowerSide", "Inner", (side_x, y0 + ply, 0, side_length, ply, side_height), "Width", {
        **side_expressions,
        "Width": "BedParameters.ply",
        "Y": f"{y0} mm + BedParameters.ply",
    })
    layer("UpperSide", "Outer", (side_x, y0 + WIDTH - ply, 0, side_length, ply, side_height), "Width", {
        **side_expressions,
        "Width": "BedParameters.ply",
        "Y": f"{y0 + WIDTH} mm - BedParameters.ply",
    })
    layer("UpperSide", "Inner", (side_x, y0 + WIDTH - 2 * ply, 0, side_length, ply, side_height), "Width", {
        **side_expressions,
        "Width": "BedParameters.ply",
        "Y": f"{y0 + WIDTH} mm - 2 * BedParameters.ply",
    })

    layer("Back", "Outer", (back_outer_x, y0, 0, ply, WIDTH, side_height), "Length", {
        "Length": "BedParameters.ply",
        "Height": f"{HEIGHT} mm - 2 * BedParameters.ply",
        "X": outer_x_expr,
    })
    layer("Back", "Inner", (back_inner_x, y0, 0, ply, WIDTH, side_height), "Length", {
        "Length": "BedParameters.ply",
        "Height": f"{HEIGHT} mm - 2 * BedParameters.ply",
        "X": inner_x_expr,
    })

    strip_y = y0 + 2 * ply
    strip_width = WIDTH - 4 * ply
    for panel_name, strip_x in (("FrontBottomStrip", front_strip_x), ("BackBottomStrip", back_strip_x)):
        position_expression = {"X": back_strip_x_expr} if panel_name == "BackBottomStrip" else {}
        layer(panel_name, "Outer", (strip_x, strip_y, 0, STRIP, strip_width, ply), "Height", {
            **position_expression,
            "Height": "BedParameters.ply",
            "Width": f"{WIDTH} mm - 4 * BedParameters.ply",
            "Y": f"{y0} mm + 2 * BedParameters.ply",
        })
        layer(panel_name, "Inner", (strip_x, strip_y, ply, STRIP, strip_width, ply), "Height", {
            **position_expression,
            "Height": "BedParameters.ply",
            "Width": f"{WIDTH} mm - 4 * BedParameters.ply",
            "Y": f"{y0} mm + 2 * BedParameters.ply",
            "Z": "BedParameters.ply",
        })
    return part, layers


def create_wall_cabinet(doc, key, label, x0, y0, color):
    """Create a 38-inch-wide, 20-inch-deep cabinet opening toward +Y."""
    ply = doc.BedParameters.ply.Value
    part = doc.addObject("App::Part", key)
    part.Label = label
    part.addProperty("App::PropertyString", "FrontDirection", "Cabinet")
    part.FrontDirection = "+Y (against wall)"
    layers = {}

    def layer(panel_name, layer_name, box, thickness_property, expressions):
        name = key + panel_name + layer_name
        display = panel_name.replace("_", " ").strip() + " — " + layer_name.lower()
        shade = color if layer_name == "Outer" else tuple(max(0.0, c - 0.12) for c in color)
        item = make_layer(part, name, display, box, thickness_property, expressions, shade)
        layers[(panel_name, layer_name)] = item

    layer("Top", "Outer", (x0, y0, HEIGHT - ply, DEPTH, WALL_DEPTH, ply), "Height", {
        "Height": "BedParameters.ply",
        "Z": f"{HEIGHT} mm - BedParameters.ply",
    })
    layer("Top", "Inner", (x0, y0, HEIGHT - 2 * ply, DEPTH, WALL_DEPTH, ply), "Height", {
        "Height": "BedParameters.ply",
        "Z": f"{HEIGHT} mm - 2 * BedParameters.ply",
    })

    side_y = y0 + 2 * ply
    side_depth = WALL_DEPTH - 2 * ply
    side_height = HEIGHT - 2 * ply
    common_side = {
        "Width": f"{WALL_DEPTH} mm - 2 * BedParameters.ply",
        "Height": f"{HEIGHT} mm - 2 * BedParameters.ply",
        "Y": f"{y0} mm + 2 * BedParameters.ply",
    }
    layer("LeftSide", "Outer", (x0, side_y, 0, ply, side_depth, side_height), "Length", {
        **common_side,
        "Length": "BedParameters.ply",
    })
    layer("LeftSide", "Inner", (x0 + ply, side_y, 0, ply, side_depth, side_height), "Length", {
        **common_side,
        "Length": "BedParameters.ply",
        "X": f"{x0} mm + BedParameters.ply",
    })
    layer("RightSide", "Outer", (x0 + DEPTH - ply, side_y, 0, ply, side_depth, side_height), "Length", {
        **common_side,
        "Length": "BedParameters.ply",
        "X": f"{x0 + DEPTH} mm - BedParameters.ply",
    })
    layer("RightSide", "Inner", (x0 + DEPTH - 2 * ply, side_y, 0, ply, side_depth, side_height), "Length", {
        **common_side,
        "Length": "BedParameters.ply",
        "X": f"{x0 + DEPTH} mm - 2 * BedParameters.ply",
    })

    layer("Back", "Outer", (x0, y0, 0, DEPTH, ply, side_height), "Width", {
        "Width": "BedParameters.ply",
        "Height": f"{HEIGHT} mm - 2 * BedParameters.ply",
    })
    layer("Back", "Inner", (x0, y0 + ply, 0, DEPTH, ply, side_height), "Width", {
        "Width": "BedParameters.ply",
        "Height": f"{HEIGHT} mm - 2 * BedParameters.ply",
        "Y": f"{y0} mm + BedParameters.ply",
    })

    strip_x = x0 + 2 * ply
    strip_length = DEPTH - 4 * ply
    for panel_name, strip_y, y_expression in (
        ("BackBottomStrip", y0 + 2 * ply, f"{y0} mm + 2 * BedParameters.ply"),
        ("FrontBottomStrip", y0 + WALL_DEPTH - STRIP, f"{y0 + WALL_DEPTH - STRIP} mm"),
    ):
        common_strip = {
            "Length": f"{DEPTH} mm - 4 * BedParameters.ply",
            "X": f"{x0} mm + 2 * BedParameters.ply",
            "Y": y_expression,
        }
        layer(panel_name, "Outer", (strip_x, strip_y, 0, strip_length, STRIP, ply), "Height", {
            **common_strip,
            "Height": "BedParameters.ply",
        })
        layer(panel_name, "Inner", (strip_x, strip_y, ply, strip_length, STRIP, ply), "Height", {
            **common_strip,
            "Height": "BedParameters.ply",
            "Z": "BedParameters.ply",
        })
    return part, layers


def create_bedside_cabinet(doc, key, label, x0, y0, color):
    """Create a 20-inch-square bedside cabinet opening away from the +Y wall."""
    ply = doc.BedParameters.ply.Value
    part = doc.addObject("App::Part", key)
    part.Label = label
    part.addProperty("App::PropertyString", "FrontDirection", "Cabinet")
    part.FrontDirection = "-Y (away from wall)"
    layers = {}

    def layer(panel_name, layer_name, box, thickness_property, expressions):
        name = key + panel_name + layer_name
        display = panel_name.replace("_", " ").strip() + " — " + layer_name.lower()
        shade = color if layer_name == "Outer" else tuple(max(0.0, c - 0.12) for c in color)
        item = make_layer(part, name, display, box, thickness_property, expressions, shade)
        layers[(panel_name, layer_name)] = item

    layer("Top", "Outer", (x0, y0, HEIGHT - ply, BEDSIDE_SIZE, BEDSIDE_SIZE, ply), "Height", {
        "Height": "BedParameters.ply",
        "Z": f"{HEIGHT} mm - BedParameters.ply",
    })
    layer("Top", "Inner", (x0, y0, HEIGHT - 2 * ply, BEDSIDE_SIZE, BEDSIDE_SIZE, ply), "Height", {
        "Height": "BedParameters.ply",
        "Z": f"{HEIGHT} mm - 2 * BedParameters.ply",
    })

    side_y = y0
    side_depth = BEDSIDE_SIZE - 2 * ply
    side_height = HEIGHT - 2 * ply
    common_side = {
        "Width": f"{BEDSIDE_SIZE} mm - 2 * BedParameters.ply",
        "Height": f"{HEIGHT} mm - 2 * BedParameters.ply",
        "Y": f"{y0} mm",
    }
    layer("LeftSide", "Outer", (x0, side_y, 0, ply, side_depth, side_height), "Length", {
        **common_side,
        "Length": "BedParameters.ply",
    })
    layer("LeftSide", "Inner", (x0 + ply, side_y, 0, ply, side_depth, side_height), "Length", {
        **common_side,
        "Length": "BedParameters.ply",
        "X": f"{x0} mm + BedParameters.ply",
    })
    layer("RightSide", "Outer", (x0 + BEDSIDE_SIZE - ply, side_y, 0, ply, side_depth, side_height), "Length", {
        **common_side,
        "Length": "BedParameters.ply",
        "X": f"{x0 + BEDSIDE_SIZE} mm - BedParameters.ply",
    })
    layer("RightSide", "Inner", (x0 + BEDSIDE_SIZE - 2 * ply, side_y, 0, ply, side_depth, side_height), "Length", {
        **common_side,
        "Length": "BedParameters.ply",
        "X": f"{x0 + BEDSIDE_SIZE} mm - 2 * BedParameters.ply",
    })

    # The back occupies the wall-side edge; the opposite edge remains open.
    layer("Back", "Outer", (x0, y0 + BEDSIDE_SIZE - ply, 0, BEDSIDE_SIZE, ply, side_height), "Width", {
        "Width": "BedParameters.ply",
        "Height": f"{HEIGHT} mm - 2 * BedParameters.ply",
        "Y": f"{y0 + BEDSIDE_SIZE} mm - BedParameters.ply",
    })
    layer("Back", "Inner", (x0, y0 + BEDSIDE_SIZE - 2 * ply, 0, BEDSIDE_SIZE, ply, side_height), "Width", {
        "Width": "BedParameters.ply",
        "Height": f"{HEIGHT} mm - 2 * BedParameters.ply",
        "Y": f"{y0 + BEDSIDE_SIZE} mm - 2 * BedParameters.ply",
    })

    strip_x = x0 + 2 * ply
    strip_length = BEDSIDE_SIZE - 4 * ply
    for panel_name, strip_y, y_expression in (
        ("FrontBottomStrip", y0, f"{y0} mm"),
        (
            "BackBottomStrip",
            y0 + BEDSIDE_SIZE - 2 * ply - STRIP,
            f"{y0 + BEDSIDE_SIZE - STRIP} mm - 2 * BedParameters.ply",
        ),
    ):
        common_strip = {
            "Length": f"{BEDSIDE_SIZE} mm - 4 * BedParameters.ply",
            "X": f"{x0} mm + 2 * BedParameters.ply",
            "Y": y_expression,
        }
        layer(panel_name, "Outer", (strip_x, strip_y, 0, strip_length, STRIP, ply), "Height", {
            **common_strip,
            "Height": "BedParameters.ply",
        })
        layer(panel_name, "Inner", (strip_x, strip_y, ply, strip_length, STRIP, ply), "Height", {
            **common_strip,
            "Height": "BedParameters.ply",
            "Z": "BedParameters.ply",
        })
    return part, layers


def x_joint_bolt_holes(source, receiver, y_centers, z_center):
    """Drill aligned holes through the four back-panel laminations."""
    layers = (
        source[("Back", "Inner")],
        source[("Back", "Outer")],
        receiver[("Back", "Outer")],
        receiver[("Back", "Inner")],
    )
    for y_center in y_centers:
        for layer in layers:
            add_hole(
                layer,
                (layer.X.Value, y_center, z_center),
                "X",
                {"X": "X"},
            )


def y_joint_bolt_holes(source, receiver, x_centers, z_center):
    """Drill aligned holes through the four adjoining side laminations."""
    layers = (
        source[("UpperSide", "Inner")],
        source[("UpperSide", "Outer")],
        receiver[("LowerSide", "Outer")],
        receiver[("LowerSide", "Inner")],
    )
    for x_center in x_centers:
        for layer in layers:
            add_hole(
                layer,
                (x_center, layer.Y.Value, z_center),
                "Y",
                {"Y": "Y"},
            )


def wall_row_bolt_holes(existing, wall_cabinet, x_centers, z_center):
    """Join an existing cabinet's upper side to a wall cabinet's back."""
    layers = (
        existing[("UpperSide", "Inner")],
        existing[("UpperSide", "Outer")],
        wall_cabinet[("Back", "Outer")],
        wall_cabinet[("Back", "Inner")],
    )
    for x_center in x_centers:
        for layer in layers:
            add_hole(
                layer,
                (x_center, layer.Y.Value, z_center),
                "Y",
                {"Y": "Y"},
            )


def wall_cabinet_pair_bolt_holes(left, right, y_centers, z_center):
    """Join the two wall cabinets through their touching side panels."""
    layers = (
        left[("RightSide", "Inner")],
        left[("RightSide", "Outer")],
        right[("LeftSide", "Outer")],
        right[("LeftSide", "Inner")],
    )
    for y_center in y_centers:
        for layer in layers:
            add_hole(
                layer,
                (layer.X.Value, y_center, z_center),
                "X",
                {"X": "X"},
            )


def bedside_bolt_holes(left, right, y_centers, z_center):
    """Join neighboring wall-row and bedside cabinets through their sides."""
    layers = (
        left[("RightSide", "Inner")],
        left[("RightSide", "Outer")],
        right[("LeftSide", "Outer")],
        right[("LeftSide", "Inner")],
    )
    for y_center in y_centers:
        for layer in layers:
            add_hole(
                layer,
                (layer.X.Value, y_center, z_center),
                "X",
                {"X": "X"},
            )


def generate(output_path):
    doc = App.newDocument("Bed")
    add_parameters(doc)
    if not os.path.exists(FILIGREE_SVG):
        raise FileNotFoundError(f"Filigree SVG not found: {FILIGREE_SVG}")
    if not os.path.exists(FILIGREE_IMAGE):
        raise FileNotFoundError(f"Filigree preview not found: {FILIGREE_IMAGE}")
    for filigree_small in (FILIGREE_SMALL_LEFT, FILIGREE_SMALL_RIGHT):
        if not os.path.exists(filigree_small):
            raise FileNotFoundError(
                f"Filigree subpattern preview not found: {filigree_small}"
            )
    svg_root = ET.parse(FILIGREE_SVG).getroot()
    view_box = [float(value) for value in svg_root.attrib["viewBox"].split()]
    filigree_source = (FILIGREE_IMAGE, view_box[2], view_box[3])
    small_filigree_source = (
        FILIGREE_SMALL_LEFT,
        FILIGREE_SMALL_RIGHT,
        454.0,
        323.0,
    )
    # Build cabinet-local geometry on a gapless grid. Part placements below
    # supply the parameter-driven gap without changing panel cut dimensions.
    bed_x = BEDSIDE_SIZE
    right_x = bed_x + DEPTH
    second_row_y = WIDTH
    wall_y = second_row_y + WIDTH
    right_bedside_x = right_x + DEPTH
    colors = (
        (0.88, 0.68, 0.38),
        (0.84, 0.58, 0.32),
        (0.73, 0.57, 0.35),
        (0.76, 0.48, 0.28),
        (0.65, 0.50, 0.30),
        (0.69, 0.43, 0.25),
        (0.58, 0.44, 0.27),
        (0.62, 0.39, 0.23),
    )
    cabinet1, c1 = create_cabinet(doc, "Cabinet1", "Cabinet 1 — front left", bed_x, 0, "-X", colors[0])
    cabinet2, c2 = create_cabinet(doc, "Cabinet2", "Cabinet 2 — front right", right_x, 0, "+X", colors[1])
    cabinet3, c3 = create_cabinet(doc, "Cabinet3", "Cabinet 3 — front left", bed_x, second_row_y, "-X", colors[2])
    cabinet4, c4 = create_cabinet(doc, "Cabinet4", "Cabinet 4 — front right", right_x, second_row_y, "+X", colors[3])
    cabinet5, c5 = create_wall_cabinet(
        doc, "Cabinet5", "Cabinet 5 — front against wall", bed_x, wall_y, colors[4]
    )
    cabinet6, c6 = create_wall_cabinet(
        doc, "Cabinet6", "Cabinet 6 — front against wall", right_x, wall_y, colors[5]
    )
    cabinet7, c7 = create_bedside_cabinet(
        doc,
        "Cabinet7",
        "Cabinet 7 — left bedside table, front away from wall",
        0,
        wall_y,
        colors[6],
    )
    cabinet8, c8 = create_bedside_cabinet(
        doc,
        "Cabinet8",
        "Cabinet 8 — right bedside table, front away from wall",
        right_bedside_x,
        wall_y,
        colors[7],
    )

    # Build the final cabinet outlines before placing their alignment holes.
    doc.recompute()
    for layers, key, x0, y0, kind, direction in (
        (c1, "Cabinet1", bed_x, 0, "main", "-X"),
        (c2, "Cabinet2", right_x, 0, "main", "+X"),
        (c3, "Cabinet3", bed_x, second_row_y, "main", "-X"),
        (c4, "Cabinet4", right_x, second_row_y, "main", "+X"),
        (c5, "Cabinet5", bed_x, wall_y, "wall", None),
        (c6, "Cabinet6", right_x, wall_y, "wall", None),
        (c7, "Cabinet7", 0, wall_y, "bedside", None),
        (c8, "Cabinet8", right_bedside_x, wall_y, "bedside", None),
    ):
        add_cabinet_joints(layers, key, x0, y0, kind, direction)
    doc.recompute()

    add_wall_front_support(cabinet5, c5, "Cabinet5", bed_x, wall_y, colors[4])
    add_wall_front_support(cabinet6, c6, "Cabinet6", right_x, wall_y, colors[5])

    # The four 30-inch openings receive one drawer each. The wall-row
    # support cabinets remain open and drawerless.
    create_large_drawer(
        doc,
        cabinet1,
        c1,
        "Cabinet1Drawer",
        "Cabinet 1 drawer",
        bed_x,
        0,
        "-X",
        colors[0],
        filigree_source,
    )
    create_large_drawer(
        doc,
        cabinet2,
        c2,
        "Cabinet2Drawer",
        "Cabinet 2 drawer",
        right_x,
        0,
        "+X",
        colors[1],
        filigree_source,
    )
    create_large_drawer(
        doc,
        cabinet3,
        c3,
        "Cabinet3Drawer",
        "Cabinet 3 drawer",
        bed_x,
        second_row_y,
        "-X",
        colors[2],
        filigree_source,
    )
    create_large_drawer(
        doc,
        cabinet4,
        c4,
        "Cabinet4Drawer",
        "Cabinet 4 drawer",
        right_x,
        second_row_y,
        "+X",
        colors[3],
        filigree_source,
    )

    # Each bedside table receives a lower and an upper drawer.
    for drawer_index, position in enumerate(("lower", "upper")):
        create_bedside_drawer(
            doc,
            cabinet7,
            c7,
            f"Cabinet7{position.title()}Drawer",
            f"Cabinet 7 {position} drawer",
            0,
            wall_y,
            drawer_index,
            colors[6],
            small_filigree_source,
        )
        create_bedside_drawer(
            doc,
            cabinet8,
            c8,
            f"Cabinet8{position.title()}Drawer",
            f"Cabinet 8 {position} drawer",
            right_bedside_x,
            wall_y,
            drawer_index,
            colors[7],
            small_filigree_source,
        )

    for layers, excluded in (
        (c1, ("LowerSide", "UpperSide")),
        (c2, ("LowerSide", "UpperSide")),
        (c3, ("LowerSide", "UpperSide")),
        (c4, ("LowerSide", "UpperSide")),
        (c5, ()),
        (c6, ()),
        (c7, ("LeftSide", "RightSide")),
        (c8, ("LeftSide", "RightSide")),
    ):
        add_panel_stack_alignment(layers, excluded)
    doc.recompute()

    # X joints: two bolts through each pair of back-panel stacks.
    x_center_z = HEIGHT / 2
    x_joint_bolt_holes(c1, c2, (WIDTH / 3, 2 * WIDTH / 3), x_center_z)
    x_joint_bolt_holes(
        c3,
        c4,
        (second_row_y + WIDTH / 3, second_row_y + 2 * WIDTH / 3),
        x_center_z,
    )

    # Y joints: two bolts through each pair of adjoining side-panel stacks.
    y_center_z = HEIGHT / 2
    y_joint_bolt_holes(c1, c3, (bed_x + DEPTH / 3, bed_x + 2 * DEPTH / 3), y_center_z)
    y_joint_bolt_holes(
        c2,
        c4,
        (right_x + DEPTH / 3, right_x + 2 * DEPTH / 3),
        y_center_z,
    )

    # Join the 20-inch wall row to the existing bed and join its two halves.
    wall_row_bolt_holes(c3, c5, (bed_x + DEPTH / 3, bed_x + 2 * DEPTH / 3), HEIGHT / 2)
    wall_row_bolt_holes(
        c4,
        c6,
        (right_x + DEPTH / 3, right_x + 2 * DEPTH / 3),
        HEIGHT / 2,
    )
    wall_cabinet_pair_bolt_holes(
        c5,
        c6,
        (wall_y + WALL_DEPTH / 3, wall_y + 2 * WALL_DEPTH / 3),
        HEIGHT / 2,
    )
    bedside_bolt_holes(
        c7,
        c5,
        (wall_y + WALL_DEPTH / 3, wall_y + 2 * WALL_DEPTH / 3),
        HEIGHT / 2,
    )
    bedside_bolt_holes(
        c6,
        c8,
        (wall_y + WALL_DEPTH / 3, wall_y + 2 * WALL_DEPTH / 3),
        HEIGHT / 2,
    )

    # Every cabinet and its independent drawer part move by the same number
    # of 2 * FingerOvershoot gaps from the gapless layout above.
    for part_name, x_gaps, y_gaps in (
        ("Cabinet1", 1, 0),
        ("Cabinet2", 2, 0),
        ("Cabinet3", 1, 1),
        ("Cabinet4", 2, 1),
        ("Cabinet5", 1, 2),
        ("Cabinet6", 2, 2),
        ("Cabinet7", 0, 2),
        ("Cabinet8", 3, 2),
        ("Cabinet1Drawer", 1, 0),
        ("Cabinet2Drawer", 2, 0),
        ("Cabinet3Drawer", 1, 1),
        ("Cabinet4Drawer", 2, 1),
        ("Cabinet7LowerDrawer", 0, 2),
        ("Cabinet7UpperDrawer", 0, 2),
        ("Cabinet8LowerDrawer", 3, 2),
        ("Cabinet8UpperDrawer", 3, 2),
    ):
        part = doc.getObject(part_name)
        if x_gaps:
            part.setExpression(
                "Placement.Base.x",
                f"{2 * x_gaps} * BedParameters.FingerOvershoot",
            )
        if y_gaps:
            part.setExpression(
                "Placement.Base.y",
                f"{2 * y_gaps} * BedParameters.FingerOvershoot",
            )

    layout = doc.addObject("App::FeaturePython", "ConnectorLayout")
    layout.Label = "Connector Layout"
    layout.addProperty("App::PropertyString", "XAxisRule", "Layout")
    layout.addProperty("App::PropertyString", "YAxisRule", "Layout")
    layout.addProperty("App::PropertyString", "Fastener", "Layout")
    layout.addProperty("App::PropertyString", "Footprint", "Layout")
    layout.addProperty("App::PropertyString", "WallRow", "Layout")
    layout.addProperty("App::PropertyString", "BedsideTables", "Layout")
    layout.XAxisRule = "Two bolt holes through each back-panel joint at half height"
    layout.YAxisRule = "Two bolt holes through each side-panel joint at half height"
    layout.Fastener = "Bolts with threaded inserts; hardware not modeled"
    layout.Footprint = "76 in x 80 in"
    layout.WallRow = "Two 38 in wide x 20 in deep cabinets, fronts toward +Y wall"
    layout.BedsideTables = "Two 20 in square cabinets beside wall row, fronts toward -Y"

    drawer_layout = doc.addObject("App::FeaturePython", "DrawerLayout")
    drawer_layout.Label = "Drawer Construction"
    drawer_layout.addProperty("App::PropertyString", "LargeDrawers", "Layout")
    drawer_layout.addProperty("App::PropertyString", "BedsideDrawers", "Layout")
    drawer_layout.addProperty("App::PropertyString", "Walls", "Construction")
    drawer_layout.addProperty("App::PropertyString", "Bottom", "Construction")
    drawer_layout.addProperty("App::PropertyString", "Slides", "Construction")
    drawer_layout.LargeDrawers = "One drawer in each 30 in cabinet opening"
    drawer_layout.BedsideDrawers = "Two drawers in each 20 in bedside table"
    drawer_layout.Walls = (
        "Faces, face frames, sides, and backs are two-ply laminations"
    )
    drawer_layout.Bottom = (
        "Single ply, 1/2 in above side bottoms; hidden zero-overshoot joint at face"
    )
    drawer_layout.Slides = (
        "Rounded two-ply drawer runners between rounded four-ply support and anti-tip strips"
    )

    doc.recompute()
    doc.recompute()
    doc.saveAs(output_path)
    App.closeDocument(doc.Name)


if __name__ in ("__main__", "generate_bed"):
    output = os.environ.get("BED_OUTPUT_PATH", os.path.join(ROOT, "Bed.FCStd"))
    generate(output)
    set_visibility(
        output,
        hidden_names={
            "FiligreeImageSource",
            "FiligreeSmallLeftSource",
            "FiligreeSmallRightSource",
        },
    )
