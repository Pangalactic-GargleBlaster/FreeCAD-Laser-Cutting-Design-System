"""Finger joints across angled and laminated sheet-panel groups."""

from dataclasses import dataclass
import FreeCAD as App
import Part

from finger_joint import (
    ANGULAR_TOLERANCE,
    LINEAR_TOLERANCE,
    JointValidationError,
    JointViewProvider,
    _body_and_base,
    _distal_parallel_edges,
    _is_planar,
    _parallel,
    _source_frame,
    _subshape,
    _unit,
    automatic_edge_name,
    build_finger_shapes,
    keep_dominant_solid,
    show_body_tips,
    validate_source_face_set,
)


@dataclass
class PanelPlanes:
    normal: App.Vector
    low: float
    high: float

    @property
    def thickness(self):
        return self.high - self.low


def broad_planes(shape):
    """Find a panel's two broad boundary planes without using world axes."""
    faces = sorted(
        (face for face in shape.Faces if _is_planar(face)),
        key=lambda face: face.Area,
        reverse=True,
    )
    for first in faces:
        normal = _unit(first.normalAt(0, 0))
        offsets = [
            face.CenterOfMass.dot(normal)
            for face in faces
            if _parallel(face.normalAt(0, 0), normal)
        ]
        if len(offsets) < 2:
            continue
        low, high = min(offsets), max(offsets)
        if high - low > LINEAR_TOLERANCE:
            return PanelPlanes(normal, low, high)
    raise JointValidationError("Could not identify the two broad faces of a panel.")


def _ray_to_outer_planes(points, direction, panels):
    depths = []
    for panel in panels:
        denominator = direction.dot(panel.normal)
        if abs(denominator) <= ANGULAR_TOLERANCE:
            continue
        for point in points:
            coordinate = point.dot(panel.normal)
            for boundary in (panel.low, panel.high):
                distance = (boundary - coordinate) / denominator
                if distance >= -LINEAR_TOLERANCE:
                    depths.append(max(0, distance))
    if not depths or max(depths) <= LINEAR_TOLERANCE:
        raise JointValidationError(
            "The finger direction does not cross the receiving panel thickness."
        )
    return max(depths)


def _complementary_intervals(length, finger_count):
    width = length / (2 * finger_count)
    intervals = [(0, width / 2)]
    intervals.extend(
        ((2 * index + 1.5) * width, (2 * index + 2.5) * width)
        for index in range(finger_count - 1)
    )
    intervals.append((length - width / 2, length))
    return intervals


def _receiver_edge_face(shape, planes, seam_start, seam_end):
    """Find the narrow boundary face containing the shared seam.

    The vector from a panel centroid to a sloping edge need not be normal to
    that edge (as on a triangle), so derive the extension direction from the
    actual edge face instead.
    """
    seam = Part.makeLine(seam_start, seam_end)
    candidates = []
    for face in shape.Faces:
        if not _is_planar(face):
            continue
        normal = _unit(face.normalAt(0, 0))
        if abs(normal.dot(planes.normal)) > ANGULAR_TOLERANCE:
            continue
        if face.common(seam).Length < seam.Length - LINEAR_TOLERANCE:
            continue
        outward = normal - planes.normal * normal.dot(planes.normal)
        outward = _unit(outward)
        if outward.dot(face.CenterOfMass - shape.Solids[0].CenterOfMass) < 0:
            outward = -outward
        candidates.append((face, outward))
    return max(candidates, key=lambda item: item[0].Area) if candidates else (None, None)


def _seam_on_broad_boundary(shape, planes, seam_start, seam_end):
    seam = Part.makeLine(seam_start, seam_end)
    return any(
        sum(edge.common(seam).Length for edge in face.Edges)
        >= seam.Length - LINEAR_TOLERANCE
        for face in shape.Faces
        if _is_planar(face)
        and _parallel(face.normalAt(0, 0), planes.normal)
    )


def _make_receiver_fingers(face, planes, seam_start, seam_end, outward, length,
                           count, radius):
    direction = _unit(seam_end - seam_start)
    span = (seam_end - seam_start).Length
    vertices = [vertex.Point for vertex in face.Vertexes]
    start_coordinate = min(point.dot(direction) for point in vertices)
    low_point = min(vertices, key=lambda point: (
        point.dot(direction), point.dot(planes.normal)
    ))
    start = low_point + direction * (start_coordinate - low_point.dot(direction))
    fingers = []
    cutters = []
    for start_offset, end_offset in _complementary_intervals(span, count):
        if end_offset - start_offset < 2 * radius - LINEAR_TOLERANCE:
            raise JointValidationError(
                "Receiving finger width is too small for the selected fillet radius."
            )
        first = start + direction * start_offset
        second = start + direction * end_offset
        corners = [
            first, second, second + planes.normal * planes.thickness,
            first + planes.normal * planes.thickness,
        ]
        raw = Part.Face(Part.makePolygon(corners + [corners[0]])).extrude(
            outward * length
        )
        cutters.append(raw)
        if radius > LINEAR_TOLERANCE:
            tip_plane = first.dot(outward) + length
            tip_edges = _distal_parallel_edges(
                raw, outward, planes.normal, tip_plane
            )
            if len(tip_edges) != 2:
                raise JointValidationError(
                    "Could not identify the receiving finger tip edges."
                )
            try:
                fingers.append(raw.makeFillet(radius, tip_edges))
            except Part.OCCError as error:
                raise JointValidationError(
                    f"Could not fillet a receiving finger tip: {error}"
                )
        else:
            fingers.append(raw)
    return fingers, cutters


def _convex_hull(points):
    points = sorted(set((round(x, 9), round(y, 9)) for x, y in points))
    if len(points) < 3:
        return []

    def cross(a, b, c):
        return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])

    lower = []
    for point in points:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], point) <= 1e-9:
            lower.pop()
        lower.append(point)
    upper = []
    for point in reversed(points):
        while len(upper) >= 2 and cross(upper[-2], upper[-1], point) <= 1e-9:
            upper.pop()
        upper.append(point)
    return lower[:-1] + upper[:-1]


def _projected_cavity(body_shape, tool, planes):
    intersection = body_shape.common(tool)
    if intersection.Volume <= LINEAR_TOLERANCE:
        return []
    normal = planes.normal
    u = None
    for edge in body_shape.Edges:
        if len(edge.Vertexes) != 2:
            continue
        candidate = edge.Vertexes[1].Point - edge.Vertexes[0].Point
        candidate -= normal * candidate.dot(normal)
        if candidate.Length > LINEAR_TOLERANCE:
            u = _unit(candidate)
            break
    if u is None:
        raise JointValidationError("Could not orient the receiving panel's cut plane.")
    v = normal.cross(u)
    cuts = []
    tolerance = 1e-5
    for solid in intersection.Solids:
        points = [(vertex.Point.dot(u), vertex.Point.dot(v))
                  for vertex in solid.Vertexes]
        hull = _convex_hull(points)
        if len(hull) < 3:
            continue
        corners = [u * x + v * y + normal * (planes.low - tolerance)
                   for x, y in hull]
        cut = Part.Face(Part.makePolygon(corners + [corners[0]])).extrude(
            normal * (planes.thickness + 2 * tolerance)
        )
        cuts.append(cut)
    return cuts


def solve_joint(source_faces, receiver_objs, finger_count, overshoot=0,
                fillet_radius=0, receiver_overshoot=0,
                receiver_fillet_radius=0):
    """Return finished solids keyed by the original source/receiving bodies."""
    if int(finger_count) != finger_count or finger_count < 1:
        raise JointValidationError("Finger count must be a positive integer.")
    contacts = validate_source_face_set(source_faces, receiver_objs)
    receivers = (list(receiver_objs) if isinstance(receiver_objs, (list, tuple))
                 else [receiver_objs])
    receiver_pairs = [_body_and_base(obj, "receiving") for obj in receivers]
    source_pairs = []
    for obj, face_name in source_faces:
        body, base = _body_and_base(obj, "source")
        source_pairs.append((body, base, face_name))
    contact_edges = [(_subshape(base, edge_name, "Edge"), base, face_name)
                     for base, face_name, edge_name in contacts]
    seam_edge, _, _ = max(contact_edges, key=lambda entry: entry[0].Length)
    seam_start = seam_edge.Vertexes[0].Point
    seam_end = seam_edge.Vertexes[1].Point
    seam_direction = _unit(seam_end - seam_start)
    receiver_planes = {body: broad_planes(base.Shape)
                       for body, base in receiver_pairs}
    source_planes = {body: broad_planes(base.Shape)
                     for body, base, _ in source_pairs}
    source_fingers = []
    source_cutters = []
    source_fingers_by_body = {}
    for body, base, face_name in source_pairs:
        edge_name = automatic_edge_name(base, face_name)
        frame = _source_frame(base, face_name, edge_name)
        if not _parallel(frame[7], seam_direction):
            raise JointValidationError("Selected faces must have parallel seam edges.")
        face = frame[2]
        direction = _unit(face.normalAt(0, 0))
        depth = _ray_to_outer_planes(
            [vertex.Point for vertex in face.Vertexes], direction,
            receiver_planes.values()
        )
        geometry = type("FingerFrame", (), {
            "selected_face": face,
            "edge_start": frame[5],
            "edge_end": frame[6],
            "across_direction": frame[7],
            "distribution_length": frame[9],
            "edge_length": frame[8],
            "extrusion_direction": direction,
            "receiver_thickness": depth,
        })()
        finished, raw, _, _, _ = build_finger_shapes(
            geometry, finger_count, overshoot, fillet_radius
        )
        own_fingers = list(finished.Solids)
        source_fingers.extend(own_fingers)
        source_cutters.extend(raw.Solids)
        source_fingers_by_body.setdefault(body, []).extend(own_fingers)
    receiver_fingers = []
    receiver_cutters = []
    receiver_fingers_by_body = {}
    for body, base in receiver_pairs:
        planes = receiver_planes[body]
        edge_face, outward = _receiver_edge_face(
            base.Shape, planes, seam_start, seam_end
        )
        if edge_face is None:
            if _seam_on_broad_boundary(
                base.Shape, planes, seam_start, seam_end
            ):
                raise JointValidationError(
                    f"Could not construct matching edge fingers on {body.Label}."
                )
            continue
        depth = _ray_to_outer_planes(
            [vertex.Point for vertex in edge_face.Vertexes], outward,
            source_planes.values()
        ) + receiver_overshoot
        own_fingers, own_cutters = _make_receiver_fingers(
            edge_face, planes, seam_start, seam_end, outward, depth, finger_count,
            receiver_fillet_radius,
        )
        receiver_fingers.extend(own_fingers)
        receiver_cutters.extend(own_cutters)
        receiver_fingers_by_body.setdefault(body, []).extend(own_fingers)
    finished = {}
    for body, base, _ in source_pairs:
        shape = base.Shape
        for finger in receiver_cutters:
            for cut in _projected_cavity(shape, finger, source_planes[body]):
                shape = shape.cut(cut)
        for finger in source_fingers_by_body.get(body, ()):
            if finger.common(base.Shape).Volume > LINEAR_TOLERANCE or \
                    finger.distToShape(base.Shape)[0] <= LINEAR_TOLERANCE:
                shape = shape.fuse(finger)
        finished[body] = keep_dominant_solid(shape.removeSplitter())
    for body, base in receiver_pairs:
        shape = base.Shape
        for finger in source_cutters:
            for cut in _projected_cavity(shape, finger, receiver_planes[body]):
                shape = shape.cut(cut)
        for finger in receiver_fingers_by_body.get(body, ()):
            if finger.common(base.Shape).Volume > LINEAR_TOLERANCE or \
                    finger.distToShape(base.Shape)[0] <= LINEAR_TOLERANCE:
                shape = shape.fuse(finger)
        finished[body] = keep_dominant_solid(shape.removeSplitter())
    return finished


class GroupInputsProxy:
    """Measure the current ply thicknesses for parameter expressions."""

    def __init__(self, obj=None):
        if obj is not None:
            obj.Proxy = self
            self._hide_internal_object(obj)

    def execute(self, obj):
        self._hide_internal_object(obj)
        if obj.SourceFeature is None or obj.ReceivingFeature is None:
            return
        obj.SourceThickness = broad_planes(obj.SourceFeature.Shape).thickness
        obj.ReceivingThickness = broad_planes(obj.ReceivingFeature.Shape).thickness

    def onDocumentRestored(self, obj):
        self._hide_internal_object(obj)

    @staticmethod
    def _hide_internal_object(obj):
        if not getattr(App, "GuiUp", False) or obj.ViewObject is None:
            return
        obj.ViewObject.Visibility = False
        if hasattr(obj.ViewObject, "ShowInTree"):
            obj.ViewObject.ShowInTree = False

    def dumps(self):
        return None

    def loads(self, state):
        return None


class GroupPlanProxy:
    """Own joint parameters and source/receiver references without a body cycle."""

    def __init__(self, obj=None):
        if obj is not None:
            obj.Proxy = self
            self._hide_geometry(obj)

    def execute(self, obj):
        self._hide_geometry(obj)
        return None

    def onDocumentRestored(self, obj):
        self._hide_geometry(obj)

    @staticmethod
    def _hide_geometry(obj):
        if getattr(App, "GuiUp", False) and obj.ViewObject is not None:
            obj.ViewObject.Visibility = False

    def dumps(self):
        return None

    def loads(self, state):
        return None


class GroupResultProxy:
    """Recompute one panel solid from a shared angled-joint plan."""

    def __init__(self, obj=None, role="source", index=0):
        self.role = role
        self.index = index
        if obj is not None:
            obj.Proxy = self

    def execute(self, obj):
        self._ensure_view_provider(obj)
        if obj.InputFeature is None or obj.JointGroup is None:
            return
        plan = obj.JointGroup
        source_features = [getattr(plan, f"SourceFeature{index}")
                           for index in range(1, plan.SourceCount + 1)]
        receiver_features = [getattr(plan, f"ReceivingFeature{index}")
                             for index in range(1, plan.ReceivingCount + 1)]
        source_faces = tuple(zip(source_features, plan.SourceFaceNames))
        finished = solve_joint(
            source_faces,
            receiver_features,
            plan.FingerCount,
            plan.Overshoot.Value,
            plan.FilletRadius.Value,
            plan.ReceiverOvershoot.Value,
            plan.ReceiverFilletRadius.Value,
        )
        body, _ = _body_and_base(obj.InputFeature, self.role)
        obj.Shape = finished[body]

    def onDocumentRestored(self, obj):
        self._ensure_view_provider(obj)

    @staticmethod
    def _ensure_view_provider(obj):
        if (getattr(App, "GuiUp", False) and obj.ViewObject is not None
                and obj.ViewObject.Proxy is None):
            JointViewProvider(obj.ViewObject)

    def dumps(self):
        return {"role": self.role, "index": self.index}

    def loads(self, state):
        self.role = state["role"]
        self.index = state["index"]


def create_joint_group(source_faces, receiver_objs, finger_count,
                       overshoot=None, fillet_radius=None,
                       receiver_overshoot=None, receiver_fillet_radius=None,
                       finger_count_expression=None,
                       overshoot_expression=None,
                       fillet_radius_expression=None,
                       receiver_overshoot_expression=None,
                       receiver_fillet_radius_expression=None):
    """Create a recomputable joint across source and receiving panel bodies."""
    source_faces = tuple(source_faces)
    receivers = (list(receiver_objs) if isinstance(receiver_objs, (list, tuple))
                 else [receiver_objs])
    source_pairs = [_body_and_base(obj, "source") for obj, _ in source_faces]
    receiver_pairs = [_body_and_base(obj, "receiving") for obj in receivers]
    source_features = [base for _, base in source_pairs]
    receiver_features = [base for _, base in receiver_pairs]
    doc = source_features[0].Document
    if any(feature.Document is not doc for feature in source_features + receiver_features):
        raise JointValidationError("All joint bodies must be in the same document.")
    source_thickness = broad_planes(source_features[0].Shape).thickness
    receiver_thickness = broad_planes(receiver_features[0].Shape).thickness
    default_overshoot = overshoot is None or overshoot_expression is not None
    default_radius = fillet_radius is None or fillet_radius_expression is not None
    default_receiver_overshoot = (
        receiver_overshoot is None or receiver_overshoot_expression is not None
    )
    default_receiver_radius = (
        receiver_fillet_radius is None or
        receiver_fillet_radius_expression is not None
    )
    overshoot = source_thickness if overshoot is None else (
        overshoot.Value if hasattr(overshoot, "Value") else float(overshoot)
    )
    fillet_radius = source_thickness / 2 if fillet_radius is None else (
        fillet_radius.Value if hasattr(fillet_radius, "Value") else float(fillet_radius)
    )
    receiver_overshoot = receiver_thickness if receiver_overshoot is None else (
        receiver_overshoot.Value if hasattr(receiver_overshoot, "Value")
        else float(receiver_overshoot)
    )
    receiver_fillet_radius = receiver_thickness if receiver_fillet_radius is None else (
        receiver_fillet_radius.Value if hasattr(receiver_fillet_radius, "Value")
        else float(receiver_fillet_radius)
    )
    preview = solve_joint(
        source_faces, receivers, finger_count, overshoot, fillet_radius,
        receiver_overshoot, receiver_fillet_radius,
    )
    if any(not shape.isValid() or len(shape.Solids) != 1
           for shape in preview.values()):
        raise JointValidationError("The joint did not produce one valid solid per body.")
    bodies = list(preview)
    if any(preview[bodies[i]].common(preview[bodies[j]]).Volume > LINEAR_TOLERANCE
           for i in range(len(bodies)) for j in range(i + 1, len(bodies))):
        raise JointValidationError("The joint would leave overlapping bodies.")

    inputs = doc.addObject("App::FeaturePython", "FingerJointGroupInputs")
    inputs.Label = "Finger Joint group (inputs)"
    inputs.addProperty("App::PropertyLinkGlobal", "SourceFeature", "Inputs")
    inputs.addProperty("App::PropertyLinkGlobal", "ReceivingFeature", "Inputs")
    inputs.addProperty("App::PropertyLength", "SourceThickness", "Results")
    inputs.addProperty("App::PropertyLength", "ReceivingThickness", "Results")
    inputs.SourceFeature = source_features[0]
    inputs.ReceivingFeature = receiver_features[0]
    GroupInputsProxy(inputs)

    plan = doc.addObject("App::FeaturePython", "FingerJointGroup")
    plan.Label = "Finger Joint group"
    plan.addProperty("App::PropertyLink", "InputFeature", "Inputs")
    plan.addProperty("App::PropertyStringList", "SourceFaceNames", "Inputs")
    plan.addProperty("App::PropertyIntegerConstraint", "FingerCount", "Parameters")
    for name in ("Overshoot", "FilletRadius", "ReceiverOvershoot",
                 "ReceiverFilletRadius"):
        plan.addProperty("App::PropertyLength", name, "Parameters")
    plan.addProperty("App::PropertyInteger", "SourceCount", "Results")
    plan.addProperty("App::PropertyInteger", "ReceivingCount", "Results")
    plan.InputFeature = inputs
    plan.SourceFaceNames = [name for _, name in source_faces]
    plan.SourceCount = len(source_features)
    plan.ReceivingCount = len(receiver_features)
    for index, feature in enumerate(source_features, start=1):
        property_name = f"SourceFeature{index}"
        plan.addProperty("App::PropertyLinkGlobal", property_name, "Inputs")
        setattr(plan, property_name, feature)
    for index, feature in enumerate(receiver_features, start=1):
        property_name = f"ReceivingFeature{index}"
        plan.addProperty("App::PropertyLinkGlobal", property_name, "Inputs")
        setattr(plan, property_name, feature)
    plan.FingerCount = (int(finger_count), 1, 1000, 1)
    plan.Overshoot = overshoot
    plan.FilletRadius = fillet_radius
    plan.ReceiverOvershoot = receiver_overshoot
    plan.ReceiverFilletRadius = receiver_fillet_radius
    GroupPlanProxy(plan)
    def transferred_expression(expression):
        return expression.replace(
            "SelectedEdgeLength", f"{inputs.Name}.SourceThickness"
        ).replace("ReceiverThickness", f"{inputs.Name}.ReceivingThickness")

    if finger_count_expression:
        plan.setExpression("FingerCount", transferred_expression(finger_count_expression))
    if default_overshoot:
        plan.setExpression(
            "Overshoot", transferred_expression(overshoot_expression)
            if overshoot_expression else f"{inputs.Name}.SourceThickness"
        )
    if default_radius:
        plan.setExpression(
            "FilletRadius", transferred_expression(fillet_radius_expression)
            if fillet_radius_expression else f"{inputs.Name}.SourceThickness / 2"
        )
    if default_receiver_overshoot:
        plan.setExpression(
            "ReceiverOvershoot", transferred_expression(receiver_overshoot_expression)
            if receiver_overshoot_expression else
            f"{inputs.Name}.ReceivingThickness"
        )
    if default_receiver_radius:
        plan.setExpression(
            "ReceiverFilletRadius", transferred_expression(receiver_fillet_radius_expression)
            if receiver_fillet_radius_expression else
            f"{inputs.Name}.ReceivingThickness"
        )

    results = []
    for role, pairs in (("source", source_pairs), ("receiving", receiver_pairs)):
        for index, (body, base) in enumerate(pairs):
            result = body.newObject("PartDesign::FeaturePython", "FingerJointGroupResult")
            result.Label = "Finger Joint (" + ("added" if role == "source" else "cut") + ")"
            result.addProperty("App::PropertyLink", "InputFeature", "Joint")
            result.addProperty("App::PropertyLinkGlobal", "JointGroup", "Joint")
            result.InputFeature = base
            result.JointGroup = plan
            GroupResultProxy(result, role, index)
            GroupResultProxy._ensure_view_provider(result)
            body.Tip = result
            results.append(result)
    doc.recompute()
    show_body_tips(*(body for body, _ in source_pairs + receiver_pairs))
    return plan, tuple(results)
