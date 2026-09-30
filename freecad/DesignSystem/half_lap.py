"""Parametric half-lap cuts between two sets of sheet panels."""

import FreeCAD as App
import Part

from finger_joint import (
    ANGULAR_TOLERANCE,
    LINEAR_TOLERANCE,
    JointValidationError,
    JointViewProvider,
    _body_and_base,
    _is_planar,
    _parallel,
    _subshape,
    _unit,
    show_body_tips,
)
from joint_group import _projected_cavity, broad_planes


class HalfLapFaceRequired(JointValidationError):
    """An aligned overlap needs a face to choose its opening sides."""


def _panels(objects, role):
    if not objects:
        raise JointValidationError(f"Select at least one body for {role}.")
    pairs = [_body_and_base(obj, role) for obj in objects]
    if len({body for body, _ in pairs}) != len(pairs):
        raise JointValidationError(f"A body was selected twice in {role}.")
    return pairs


def _extent(shape, direction):
    values = [vertex.Point.dot(direction) for vertex in shape.Vertexes]
    return min(values), max(values)


def _clip_between(shape, axis, low, high):
    """Intersect a solid with a generous slab normal to the seam axis."""
    if high - low <= LINEAR_TOLERANCE:
        raise JointValidationError("The panels have no usable overlap length.")
    reference = App.Vector(1, 0, 0)
    if abs(reference.dot(axis)) > 0.9:
        reference = App.Vector(0, 1, 0)
    u = _unit(reference - axis * reference.dot(axis))
    v = axis.cross(u)
    points = [vertex.Point for vertex in shape.Vertexes]
    u0, u1 = min(point.dot(u) for point in points), max(point.dot(u) for point in points)
    v0, v1 = min(point.dot(v) for point in points), max(point.dot(v) for point in points)
    margin = 10
    corners = [
        u * (u0 - margin) + v * (v0 - margin) + axis * low,
        u * (u1 + margin) + v * (v0 - margin) + axis * low,
        u * (u1 + margin) + v * (v1 + margin) + axis * low,
        u * (u0 - margin) + v * (v1 + margin) + axis * low,
    ]
    slab = Part.Face(Part.makePolygon(corners + [corners[0]])).extrude(
        axis * (high - low)
    )
    return shape.common(slab)


def _intact_end(face_ref, axis, overlaps):
    if face_ref is None:
        return None
    feature, face_name = face_ref
    if isinstance(face_name, (list, tuple)):
        if len(face_name) != 1:
            raise JointValidationError("Select exactly one overlap end face.")
        face_name = face_name[0]
    face = _subshape(feature, face_name, "Face")
    if not _is_planar(face) or not _parallel(face.normalAt(0, 0), axis):
        raise JointValidationError("Select an end face perpendicular to the overlap.")
    coordinate = face.CenterOfMass.dot(axis)
    contacts = [
        (overlap, low, high) for overlap, low, high in overlaps
        if face.common(overlap).Area > LINEAR_TOLERANCE
    ]
    if any(abs(coordinate - low) <= LINEAR_TOLERANCE
           for _, low, _ in contacts):
        return "low"
    if any(abs(coordinate - high) <= LINEAR_TOLERANCE
           for _, _, high in contacts):
        return "high"
    raise JointValidationError("The selected face must be where an overlap ends.")


def _mouth_edges(shape, plane, axis, mouth, transverse_bounds):
    transverse = _unit(plane.normal.cross(axis))
    candidates = []
    for edge in shape.Edges:
        if len(edge.Vertexes) != 2:
            continue
        start, end = (vertex.Point for vertex in edge.Vertexes)
        direction = end - start
        if direction.Length < plane.thickness - 1e-5 or not _parallel(direction, plane.normal):
            continue
        middle = (start + end) * 0.5
        if abs(middle.dot(axis) - mouth) > 1e-5:
            continue
        coordinate = middle.dot(transverse)
        if any(abs(coordinate - bound) <= 1e-5 for bound in transverse_bounds):
            candidates.append(edge)
    if not 1 <= len(candidates) <= 2:
        raise JointValidationError(
            "Could not identify the slot-mouth edges to fillet."
        )
    return candidates


def solve_half_lap(first_objects, second_objects, fillet_radius=0, intact_face=None):
    """Return one cut solid per body, without changing the document."""
    first = _panels(first_objects, "the first set")
    second = _panels(second_objects, "the second set")
    all_pairs = first + second
    doc = all_pairs[0][0].Document
    if any(body.Document is not doc for body, _ in all_pairs):
        raise JointValidationError("All half-lap bodies must share a document.")
    if len({body for body, _ in all_pairs}) != len(all_pairs):
        raise JointValidationError("A body cannot belong to both sets.")
    for pairs in (first, second):
        for index, (_, base) in enumerate(pairs):
            for _, other in pairs[index + 1:]:
                if base.Shape.common(other.Shape).Volume > LINEAR_TOLERANCE:
                    raise JointValidationError("Bodies within a set must not overlap.")

    planes = {body: broad_planes(base.Shape) for body, base in all_pairs}
    radius = fillet_radius.Value if hasattr(fillet_radius, "Value") else float(fillet_radius)
    if radius < 0:
        raise JointValidationError("Fillet radius cannot be negative.")

    intersections = []
    first_hits = set()
    second_hits = set()
    for first_body, first_base in first:
        for second_body, second_base in second:
            overlap = first_base.Shape.common(second_base.Shape)
            if overlap.Volume <= LINEAR_TOLERANCE:
                continue
            first_hits.add(first_body)
            second_hits.add(second_body)
            direction = planes[first_body].normal.cross(planes[second_body].normal)
            if direction.Length <= ANGULAR_TOLERANCE:
                raise JointValidationError("Overlapping half-lap panels must cross at an angle.")
            direction.normalize()
            first_low, first_high = _extent(first_base.Shape, direction)
            second_low, second_high = _extent(second_base.Shape, direction)
            low, high = max(first_low, second_low), min(first_high, second_high)
            if high - low <= LINEAR_TOLERANCE:
                raise JointValidationError("The overlapping panels have no shared seam length.")
            intersections.append((
                first_body, second_body, overlap, direction, low, high,
                (first_low, first_high), (second_low, second_high),
            ))
    if len(first_hits) != len(first) or len(second_hits) != len(second):
        raise JointValidationError(
            "Every body must overlap at least one body from the other set."
        )

    anchor_group = None
    anchor_normal = None
    if intact_face is not None:
        anchor_body, _ = _body_and_base(intact_face[0], "selected face")
        if anchor_body in first_hits:
            anchor_group = "first"
        elif anchor_body in second_hits:
            anchor_group = "second"
        else:
            raise JointValidationError("The selected face must belong to a joint body.")
        face_name = intact_face[1]
        if isinstance(face_name, (list, tuple)):
            face_name = face_name[0]
        anchor_face = _subshape(intact_face[0], face_name, "Face")
        if not _is_planar(anchor_face):
            raise JointValidationError("Select a planar overlap end face.")
        anchor_normal = _unit(anchor_face.normalAt(0, 0))
        valid_end = False
        for a, b, overlap, direction, low, high, _, _ in intersections:
            if anchor_body not in (a, b):
                continue
            try:
                _intact_end(intact_face, direction, ((overlap, low, high),))
                valid_end = True
                break
            except JointValidationError:
                continue
        if not valid_end:
            raise JointValidationError("The selected face must be where an overlap ends.")

    cutters = {body: [] for body, _ in all_pairs}
    mouths = {body: [] for body, _ in all_pairs}
    for a, b, overlap, direction, low, high, a_bounds, b_bounds in intersections:
        a_low = abs(a_bounds[0] - low) <= LINEAR_TOLERANCE
        a_high = abs(a_bounds[1] - high) <= LINEAR_TOLERANCE
        b_low = abs(b_bounds[0] - low) <= LINEAR_TOLERANCE
        b_high = abs(b_bounds[1] - high) <= LINEAR_TOLERANCE
        options = []
        if a_low and b_high:
            options.append("low")
        if a_high and b_low:
            options.append("high")
        if len(options) == 1:
            a_side = options[0]
        elif anchor_group is not None:
            alignment = anchor_normal.dot(direction)
            if abs(alignment) <= ANGULAR_TOLERANCE:
                raise JointValidationError(
                    "The selected face cannot orient this overlap's cut direction."
                )
            selected_side = "high" if alignment > 0 else "low"
            a_side = ("low" if selected_side == "high" else "high") \
                if anchor_group == "first" else selected_side
            if a_side not in options:
                raise JointValidationError(
                    "The selected face does not define open cuts for every overlap."
                )
        elif options:
            raise HalfLapFaceRequired(
                "Select an overlap end face to choose which side remains intact."
            )
        else:
            raise JointValidationError(
                "This overlap has no complementary open ends for a half-lap."
            )
        midpoint = (low + high) / 2
        for body, side in ((a, a_side), (b, "high" if a_side == "low" else "low")):
            cut_low, cut_high = (low, midpoint) if side == "low" else (midpoint, high)
            portion = _clip_between(overlap, direction, cut_low, cut_high)
            if portion.Volume <= LINEAR_TOLERANCE:
                raise JointValidationError("Could not construct the half-lap cavity.")
            panel_cuts = _projected_cavity(
                next(base.Shape for candidate, base in all_pairs if candidate is body),
                portion, planes[body],
            )
            if not panel_cuts:
                raise JointValidationError("Could not project the half-lap cavity.")
            cutters[body].extend(panel_cuts)
            transverse = _unit(planes[body].normal.cross(direction))
            points = [vertex.Point.dot(transverse)
                      for cut in panel_cuts for vertex in cut.Vertexes]
            mouth = low if side == "low" else high
            mouths[body].append((direction, mouth, (min(points), max(points))))

    results = {}
    for body, base in all_pairs:
        shape = base.Shape
        for cut in cutters[body]:
            shape = shape.cut(cut)
        shape = shape.removeSplitter()
        if not shape.isValid() or len(shape.Solids) != 1:
            raise JointValidationError("A half-lap cut split a panel into multiple solids.")
        if radius > LINEAR_TOLERANCE:
            edges = []
            for direction, mouth, bounds in mouths[body]:
                edges.extend(_mouth_edges(shape, planes[body], direction, mouth, bounds))
            try:
                shape = shape.makeFillet(radius, edges).removeSplitter()
            except Part.OCCError as error:
                raise JointValidationError(f"Could not fillet a half-lap opening: {error}")
            if not shape.isValid() or len(shape.Solids) != 1:
                raise JointValidationError("The half-lap fillet produced an invalid panel.")
        results[body] = shape
    for index, (body, _) in enumerate(all_pairs):
        for other, _ in all_pairs[index + 1:]:
            if results[body].common(results[other]).Volume > LINEAR_TOLERANCE:
                raise JointValidationError("Half-lap results still overlap.")
    return results


class HalfLapInputsProxy:
    def __init__(self, obj=None):
        if obj is not None:
            obj.Proxy = self
            self._hide(obj)

    def execute(self, obj):
        features = [getattr(obj, f"Panel{index}")
                    for index in range(1, obj.PanelCount + 1)]
        if all(features):
            obj.MinimumThickness = min(broad_planes(feature.Shape).thickness
                                       for feature in features)
        self._hide(obj)

    def onDocumentRestored(self, obj):
        self._hide(obj)

    @staticmethod
    def _hide(obj):
        if getattr(App, "GuiUp", False) and obj.ViewObject is not None:
            obj.ViewObject.Visibility = False
            if hasattr(obj.ViewObject, "ShowInTree"):
                obj.ViewObject.ShowInTree = False

    def dumps(self):
        return None

    def loads(self, state):
        return None


class HalfLapPlanProxy:
    def __init__(self, obj=None):
        if obj is not None:
            obj.Proxy = self
            self._hide(obj)

    def execute(self, obj):
        self._hide(obj)

    def onDocumentRestored(self, obj):
        self._hide(obj)

    @staticmethod
    def _hide(obj):
        if getattr(App, "GuiUp", False) and obj.ViewObject is not None:
            obj.ViewObject.Visibility = False

    def dumps(self):
        return None

    def loads(self, state):
        return None


class HalfLapResultProxy:
    def __init__(self, obj=None):
        if obj is not None:
            obj.Proxy = self

    def execute(self, obj):
        if obj.InputFeature is None or obj.HalfLap is None:
            return
        plan = obj.HalfLap
        first = [getattr(plan, f"First{index}")
                 for index in range(1, plan.FirstCount + 1)]
        second = [getattr(plan, f"Second{index}")
                  for index in range(1, plan.SecondCount + 1)]
        face = plan.IntactFace if plan.IntactFace else None
        result = solve_half_lap(first, second, plan.FilletRadius.Value, face)
        body, _ = _body_and_base(obj.InputFeature, "half-lap")
        obj.Shape = result[body]
        self._ensure_view(obj)

    def onDocumentRestored(self, obj):
        self._ensure_view(obj)

    @staticmethod
    def _ensure_view(obj):
        if (getattr(App, "GuiUp", False) and obj.ViewObject is not None
                and obj.ViewObject.Proxy is None):
            JointViewProvider(obj.ViewObject)

    def dumps(self):
        return None

    def loads(self, state):
        return None


def create_half_lap(first_objects, second_objects, fillet_radius=None,
                    intact_face=None, fillet_radius_expression=None):
    """Create one recomputable half-lap result feature in each selected body."""
    first = _panels(first_objects, "the first set")
    second = _panels(second_objects, "the second set")
    all_pairs = first + second
    minimum = min(broad_planes(base.Shape).thickness for _, base in all_pairs)
    radius = minimum if fillet_radius is None else (
        fillet_radius.Value if hasattr(fillet_radius, "Value") else float(fillet_radius)
    )
    solve_half_lap([base for _, base in first], [base for _, base in second],
                   radius, intact_face)
    doc = all_pairs[0][0].Document
    inputs = doc.addObject("App::FeaturePython", "HalfLapInputs")
    inputs.Label = "Half Lap (inputs)"
    inputs.addProperty("App::PropertyInteger", "PanelCount", "Internal")
    inputs.addProperty("App::PropertyLength", "MinimumThickness", "Results")
    inputs.PanelCount = len(all_pairs)
    for index, (_, base) in enumerate(all_pairs, start=1):
        name = f"Panel{index}"
        inputs.addProperty("App::PropertyLinkGlobal", name, "Inputs")
        setattr(inputs, name, base)
    HalfLapInputsProxy(inputs)

    plan = doc.addObject("App::FeaturePython", "HalfLap")
    plan.Label = "Half Lap"
    plan.addProperty("App::PropertyLink", "InputFeature", "Inputs")
    plan.addProperty("App::PropertyInteger", "FirstCount", "Inputs")
    plan.addProperty("App::PropertyInteger", "SecondCount", "Inputs")
    plan.addProperty("App::PropertyLinkSubGlobal", "IntactFace", "Inputs")
    plan.addProperty("App::PropertyLength", "FilletRadius", "Parameters")
    plan.InputFeature = inputs
    plan.FirstCount = len(first)
    plan.SecondCount = len(second)
    for role, pairs in (("First", first), ("Second", second)):
        for index, (_, base) in enumerate(pairs, start=1):
            name = f"{role}{index}"
            plan.addProperty("App::PropertyLinkGlobal", name, "Inputs")
            setattr(plan, name, base)
    if intact_face is not None:
        plan.IntactFace = (intact_face[0], [intact_face[1]])
    plan.FilletRadius = radius
    HalfLapPlanProxy(plan)
    if fillet_radius_expression:
        plan.setExpression(
            "FilletRadius", fillet_radius_expression.replace(
                "MinimumThickness", f"{inputs.Name}.MinimumThickness"
            )
        )
    elif fillet_radius is None:
        plan.setExpression("FilletRadius", f"{inputs.Name}.MinimumThickness")
    results = []
    for body, base in all_pairs:
        result = body.newObject("PartDesign::FeaturePython", "HalfLapResult")
        result.Label = "Half Lap (cut)"
        result.addProperty("App::PropertyLink", "InputFeature", "Joint")
        result.addProperty("App::PropertyLinkGlobal", "HalfLap", "Joint")
        result.InputFeature = base
        result.HalfLap = plan
        HalfLapResultProxy(result)
        HalfLapResultProxy._ensure_view(result)
        body.Tip = result
        results.append(result)
    doc.recompute()
    show_body_tips(*(body for body, _ in all_pairs))
    return plan, tuple(results)
