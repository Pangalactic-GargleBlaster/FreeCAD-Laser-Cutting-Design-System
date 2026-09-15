"""Parametric finger-joint geometry for rectangular sheet bodies."""

from dataclasses import dataclass

import FreeCAD as App
import Part

if App.GuiUp:
    import FreeCADGui as Gui


LINEAR_TOLERANCE = 1e-7
ANGULAR_TOLERANCE = 1e-7


class JointValidationError(ValueError):
    """Raised when the selected geometry cannot define a finger joint."""


@dataclass(frozen=True)
class JointGeometry:
    source_base: object
    source_body: object
    source_face_name: str
    selected_edge_name: str
    receiver_base: object
    receiver_body: object
    receiver_bases: tuple
    receiver_bodies: tuple
    selected_face: object
    selected_edge: object
    contact_face: object
    far_face: object
    edge_start: App.Vector
    edge_end: App.Vector
    across_direction: App.Vector
    extrusion_direction: App.Vector
    edge_length: float
    distribution_length: float
    receiver_thickness: float


def _unit(vector):
    if vector.Length <= LINEAR_TOLERANCE:
        raise JointValidationError("A required direction has zero length.")
    return vector / vector.Length


def _parallel(first, second):
    return abs(abs(_unit(first).dot(_unit(second))) - 1.0) <= ANGULAR_TOLERANCE


def _is_planar(face):
    return getattr(face.Surface, "TypeId", "") == "Part::GeomPlane"


def _edge_direction(edge):
    if len(edge.Vertexes) != 2 or getattr(edge.Curve, "TypeId", "") != "Part::GeomLine":
        raise JointValidationError("The selected edge must be straight.")
    return _unit(edge.Vertexes[1].Point - edge.Vertexes[0].Point)


def _is_rectangle(face):
    if not _is_planar(face) or len(face.Edges) != 4 or len(face.Vertexes) != 4:
        return False
    try:
        directions = [_edge_direction(edge) for edge in face.Edges]
    except JointValidationError:
        return False
    # FreeCAD does not guarantee that Face.Edges follows wire order. Classify
    # the four edges into two perpendicular direction pairs instead.
    first_direction = directions[0]
    parallel = [
        edge
        for edge, direction in zip(face.Edges, directions)
        if _parallel(first_direction, direction)
    ]
    perpendicular = [
        edge
        for edge, direction in zip(face.Edges, directions)
        if abs(first_direction.dot(direction)) <= ANGULAR_TOLERANCE
    ]
    if len(parallel) != 2 or len(perpendicular) != 2:
        return False
    if not close(parallel[0].Length, parallel[1].Length):
        return False
    if not close(perpendicular[0].Length, perpendicular[1].Length):
        return False
    expected_area = parallel[0].Length * perpendicular[0].Length
    return abs(face.Area - expected_area) <= max(
        LINEAR_TOLERANCE, expected_area * 1e-9
    )


def close(actual, expected, tolerance=LINEAR_TOLERANCE):
    return abs(actual - expected) <= tolerance


def _body_and_base(obj, role):
    if obj is None:
        raise JointValidationError(f"The {role} object is missing.")
    if obj.TypeId == "PartDesign::Body":
        body = obj
        base = body.Tip
    else:
        body = obj.getParentGeoFeatureGroup()
        base = obj
    if body is None or body.TypeId != "PartDesign::Body":
        raise JointValidationError(f"The {role} selection must belong to a Part Design body.")
    if base is None or base.Shape.isNull():
        raise JointValidationError(f"The {role} body has no solid tip feature.")
    return body, base


def _subshape(base, name, prefix):
    if not name.startswith(prefix):
        raise JointValidationError(f"Expected a {prefix.lower()} selection, got {name!r}.")
    try:
        index = int(name[len(prefix) :]) - 1
        collection = base.Shape.Faces if prefix == "Face" else base.Shape.Edges
        return collection[index]
    except (ValueError, IndexError):
        raise JointValidationError(f"The selected sub-element {name!r} does not exist.")


def _source_frame(source_obj, face_name, edge_name):
    source_body, source_base = _body_and_base(source_obj, "source")
    selected_face = _subshape(source_base, face_name, "Face")
    selected_edge = _subshape(source_base, edge_name, "Edge")
    if not _is_rectangle(selected_face):
        raise JointValidationError("The selected face must be a planar rectangle.")
    if not any(selected_edge.isSame(edge) for edge in selected_face.Edges):
        raise JointValidationError("The selected edge is not on the selected face.")

    edge_direction = _edge_direction(selected_edge)
    face_normal = _unit(selected_face.normalAt(0, 0))
    edge_start = selected_edge.Vertexes[0].Point
    edge_end = selected_edge.Vertexes[1].Point
    edge_midpoint = (edge_start + edge_end) * 0.5
    toward_face_center = selected_face.CenterOfMass - edge_midpoint
    toward_face_center = toward_face_center - edge_direction * toward_face_center.dot(edge_direction)
    across_direction = _unit(toward_face_center)
    edge_length = selected_edge.Length
    distribution_length = selected_face.Area / edge_length

    opposite_distance = max(
        (vertex.Point - edge_midpoint).dot(across_direction)
        for vertex in selected_face.Vertexes
    )
    if not close(opposite_distance, distribution_length):
        raise JointValidationError("Could not derive the rectangular face dimensions.")
    return (
        source_body,
        source_base,
        selected_face,
        selected_edge,
        face_normal,
        edge_start,
        edge_end,
        across_direction,
        edge_length,
        distribution_length,
    )


def analyze_joint(source_obj, face_name, edge_name, receiver_obj, finger_count):
    """Validate selections and derive a local coordinate system for the joint."""
    if int(finger_count) != finger_count or finger_count < 1:
        raise JointValidationError("Finger count must be a positive integer.")

    (
        source_body,
        source_base,
        selected_face,
        selected_edge,
        face_normal,
        edge_start,
        edge_end,
        across_direction,
        edge_length,
        distribution_length,
    ) = _source_frame(source_obj, face_name, edge_name)
    receiver_objects = (
        list(receiver_obj) if isinstance(receiver_obj, (list, tuple)) else [receiver_obj]
    )
    if not receiver_objects:
        raise JointValidationError("Select at least one receiving body.")

    receiver_pairs = []
    seen_bodies = set()
    parallel_by_body = []
    contact_faces = []
    for receiver_object in receiver_objects:
        receiver_body, receiver_base = _body_and_base(receiver_object, "receiving")
        if receiver_body is source_body:
            raise JointValidationError("Source and receiving bodies must be different.")
        body_key = (receiver_body.Document.Name, receiver_body.Name)
        if body_key in seen_bodies:
            continue
        seen_bodies.add(body_key)
        receiver_pairs.append((receiver_body, receiver_base))

        parallel_faces = []
        for face in receiver_base.Shape.Faces:
            if not _is_planar(face):
                continue
            normal = _unit(face.normalAt(0, 0))
            if _parallel(face_normal, normal):
                parallel_faces.append(face)
        if len(parallel_faces) != 2:
            raise JointValidationError(
                f"Receiving body {receiver_body.Label!r} must have exactly two faces "
                "parallel to the selected face."
            )
        parallel_by_body.append(parallel_faces)
        for face in parallel_faces:
            plane_distance = abs(
                (face.CenterOfMass - selected_face.CenterOfMass).dot(face_normal)
            )
            if plane_distance <= LINEAR_TOLERANCE:
                overlap_area = selected_face.common(face).Area
                if overlap_area > LINEAR_TOLERANCE:
                    contact_faces.append((receiver_body, face, parallel_faces))

    if len(contact_faces) != 1:
        raise JointValidationError(
            "The selected face must have positive-area contact with exactly one face "
            "of the receiving bodies."
        )

    _, contact_face, contact_parallel_faces = contact_faces[0]
    contact_far_face = next(
        face for face in contact_parallel_faces if not face.isSame(contact_face)
    )
    normal_offset = (
        contact_far_face.CenterOfMass - contact_face.CenterOfMass
    ).dot(face_normal)
    extrusion_sign = 1 if normal_offset > 0 else -1
    extrusion_direction = face_normal * extrusion_sign

    far_face = None
    receiver_thickness = 0.0
    for (receiver_body, _), parallel_faces in zip(receiver_pairs, parallel_by_body):
        body_offsets = []
        has_overlap = False
        for face in parallel_faces:
            signed_offset = (
                face.CenterOfMass - selected_face.CenterOfMass
            ).dot(extrusion_direction)
            body_offsets.append(signed_offset)
            projected_face = face.copy()
            projected_face.translate(-extrusion_direction * signed_offset)
            if selected_face.common(projected_face).Area > LINEAR_TOLERANCE:
                has_overlap = True
            if signed_offset > receiver_thickness:
                receiver_thickness = signed_offset
                far_face = face
        if min(body_offsets) < -LINEAR_TOLERANCE:
            raise JointValidationError(
                f"Receiving body {receiver_body.Label!r} lies behind the selected face."
            )
        if not has_overlap:
            raise JointValidationError(
                f"Receiving body {receiver_body.Label!r} does not overlap the selected face."
            )

    if receiver_thickness <= LINEAR_TOLERANCE:
        raise JointValidationError("The receiving bodies have zero thickness at the joint.")

    receiver_bodies = tuple(pair[0] for pair in receiver_pairs)
    receiver_bases = tuple(pair[1] for pair in receiver_pairs)

    return JointGeometry(
        source_base=source_base,
        source_body=source_body,
        source_face_name=face_name,
        selected_edge_name=edge_name,
        receiver_base=receiver_bases[0],
        receiver_body=receiver_bodies[0],
        receiver_bases=receiver_bases,
        receiver_bodies=receiver_bodies,
        selected_face=selected_face,
        selected_edge=selected_edge,
        contact_face=contact_face,
        far_face=far_face,
        edge_start=edge_start,
        edge_end=edge_end,
        across_direction=across_direction,
        extrusion_direction=extrusion_direction,
        edge_length=edge_length,
        distribution_length=distribution_length,
        receiver_thickness=receiver_thickness,
    )


def analyze_stored_joint(source_obj, face_name, edge_name, receiver_thickness, extrusion_sign):
    """Rebuild joint geometry without a dependency back to the receiving body."""
    (
        source_body,
        source_base,
        selected_face,
        selected_edge,
        face_normal,
        edge_start,
        edge_end,
        across_direction,
        edge_length,
        distribution_length,
    ) = _source_frame(source_obj, face_name, edge_name)
    return JointGeometry(
        source_base=source_base,
        source_body=source_body,
        source_face_name=face_name,
        selected_edge_name=edge_name,
        receiver_base=None,
        receiver_body=None,
        receiver_bases=(),
        receiver_bodies=(),
        selected_face=selected_face,
        selected_edge=selected_edge,
        contact_face=None,
        far_face=None,
        edge_start=edge_start,
        edge_end=edge_end,
        across_direction=across_direction,
        extrusion_direction=face_normal * int(extrusion_sign),
        edge_length=edge_length,
        distribution_length=distribution_length,
        receiver_thickness=_length_value(receiver_thickness, 0),
    )


def _distal_parallel_edges(solid, direction, selected_edge_direction, depth):
    edges = []
    for edge in solid.Edges:
        if len(edge.Vertexes) != 2:
            continue
        vector = edge.Vertexes[1].Point - edge.Vertexes[0].Point
        if not _parallel(vector, selected_edge_direction):
            continue
        projections = [vertex.Point.dot(direction) for vertex in edge.Vertexes]
        if all(close(value, depth) for value in projections):
            edges.append(edge)
    return edges


def _length_value(value, default):
    if value is None:
        return default
    return value.Value if hasattr(value, "Value") else float(value)


def build_finger_shapes(geometry, finger_count, overshoot=None, fillet_radius=None):
    """Return filleted fingers, the raw cutting tool, and derived dimensions."""
    finger_count = int(finger_count)
    finger_width = geometry.distribution_length / (2.0 * finger_count)
    overshoot = _length_value(overshoot, geometry.edge_length)
    radius = _length_value(fillet_radius, geometry.edge_length)
    if overshoot < 0:
        raise JointValidationError("Overshoot cannot be negative.")
    if radius < 0:
        raise JointValidationError("Fillet radius cannot be negative.")
    if finger_width < 2.0 * radius - LINEAR_TOLERANCE:
        raise JointValidationError(
            f"Finger width is {finger_width:g} mm, but two {radius:g} mm tip "
            f"fillets require at least {2.0 * radius:g} mm. Reduce FingerCount."
        )

    depth = geometry.receiver_thickness + overshoot
    extrusion = geometry.extrusion_direction * depth
    direction_offset = geometry.edge_start.dot(geometry.extrusion_direction)
    raw_fingers = []
    filleted_fingers = []
    for index in range(finger_count):
        offset = geometry.across_direction * (2.0 * index * finger_width)
        next_offset = offset + geometry.across_direction * finger_width
        corners = [
            geometry.edge_start + offset,
            geometry.edge_end + offset,
            geometry.edge_end + next_offset,
            geometry.edge_start + next_offset,
        ]
        wire = Part.makePolygon(corners + [corners[0]])
        raw_finger = Part.Face(wire).extrude(extrusion)
        raw_fingers.append(raw_finger)
        tip_plane = direction_offset + depth
        tip_edges = _distal_parallel_edges(
            raw_finger, geometry.extrusion_direction, geometry.edge_end - geometry.edge_start, tip_plane
        )
        if len(tip_edges) != 2:
            raise JointValidationError("Could not identify both distal finger edges for filleting.")
        if radius <= LINEAR_TOLERANCE:
            filleted_fingers.append(raw_finger)
        else:
            try:
                filleted_fingers.append(raw_finger.makeFillet(radius, tip_edges))
            except Part.OCCError as error:
                raise JointValidationError(f"FreeCAD could not fillet a finger tip: {error}")

    return (
        Part.makeCompound(filleted_fingers),
        Part.makeCompound(raw_fingers),
        finger_width,
        depth,
        radius,
    )


def build_fingers(geometry, finger_count, overshoot=None, fillet_radius=None):
    """Return the filleted finger compound and its derived dimensions."""
    fingers, _, width, depth, radius = build_finger_shapes(
        geometry, finger_count, overshoot, fillet_radius
    )
    return fingers, width, depth, radius


def build_receiver_fingers(
    geometry, receiver_base, finger_count, overshoot=None, fillet_radius=None
):
    """Build rounded extensions for open-ended slots on a receiving panel."""
    finger_count = int(finger_count)
    finger_width = geometry.distribution_length / (2.0 * finger_count)
    overshoot = _length_value(overshoot, geometry.edge_length)
    radius = _length_value(fillet_radius, geometry.edge_length)
    if overshoot < 0:
        raise JointValidationError("Receiving-panel overshoot cannot be negative.")
    if radius < 0:
        raise JointValidationError("Receiving-panel fillet radius cannot be negative.")

    parallel_faces = [
        face
        for face in receiver_base.Shape.Faces
        if _is_planar(face)
        and _parallel(face.normalAt(0, 0), geometry.extrusion_direction)
    ]
    if len(parallel_faces) != 2:
        raise JointValidationError(
            f"Receiving body {receiver_base.Label!r} must have exactly two faces "
            "parallel to the selected face."
        )
    offsets = [
        (face.CenterOfMass - geometry.selected_face.CenterOfMass).dot(
            geometry.extrusion_direction
        )
        for face in parallel_faces
    ]
    near_index = 0 if offsets[0] <= offsets[1] else 1
    near_face = parallel_faces[near_index]
    near_offset = offsets[near_index]
    panel_thickness = abs(offsets[1] - offsets[0])
    edge_direction = _unit(geometry.edge_end - geometry.edge_start)

    extensions = []
    boundary_segments = 0
    for side_point, outward_direction in (
        (geometry.edge_start, -edge_direction),
        (geometry.edge_end, edge_direction),
    ):
        for index in range(finger_count):
            gap_start = side_point + geometry.across_direction * (
                (2.0 * index + 1.0) * finger_width
            )
            gap_end = gap_start + geometry.across_direction * finger_width
            gap_start = gap_start + geometry.extrusion_direction * near_offset
            gap_end = gap_end + geometry.extrusion_direction * near_offset
            boundary_edge = Part.makeLine(gap_start, gap_end)
            overlap_length = sum(
                boundary_edge.common(edge).Length for edge in near_face.Edges
            )
            if not close(overlap_length, finger_width):
                continue
            boundary_segments += 1
            if overshoot <= LINEAR_TOLERANCE:
                continue
            if finger_width < 2.0 * radius - LINEAR_TOLERANCE:
                raise JointValidationError(
                    f"Receiving finger width is {finger_width:g} mm, but two "
                    f"{radius:g} mm tip fillets require at least "
                    f"{2.0 * radius:g} mm. Reduce FingerCount."
                )
            # Extend a hair into the existing panel. Besides making the later
            # fuse robust, this avoids OCC's degenerate exact-radius case when
            # the radius equals the requested overshoot.
            join_overlap = max(LINEAR_TOLERANCE * 100.0, overshoot * 1e-9)
            base_start = gap_start - outward_direction * join_overlap
            base_end = gap_end - outward_direction * join_overlap
            outward = outward_direction * (overshoot + join_overlap)
            corners = [
                base_start,
                base_end,
                base_end + outward,
                base_start + outward,
            ]
            extension = Part.Face(Part.makePolygon(corners + [corners[0]])).extrude(
                geometry.extrusion_direction * panel_thickness
            )
            if radius > LINEAR_TOLERANCE:
                tip_plane = (base_start + outward).dot(outward_direction)
                tip_edges = _distal_parallel_edges(
                    extension,
                    outward_direction,
                    geometry.extrusion_direction,
                    tip_plane,
                )
                if len(tip_edges) != 2:
                    raise JointValidationError(
                        "Could not identify both receiving-finger tip edges for filleting."
                    )
                try:
                    extension = extension.makeFillet(radius, tip_edges)
                except Part.OCCError as error:
                    raise JointValidationError(
                        f"FreeCAD could not fillet a receiving finger tip: {error}"
                    )
            extensions.append(extension)

    shape = Part.makeCompound(extensions) if extensions else Part.Shape()
    return shape, boundary_segments > 0


def receiver_fingers_applicable(geometry):
    """Return whether any receiving panel has edge-open finger slots."""
    return any(
        build_receiver_fingers(geometry, base, 1, 0, 0)[1]
        for base in geometry.receiver_bases
    )


def _link_sub_value(value):
    linked, subnames = value
    if isinstance(subnames, str):
        subnames = [subnames]
    if len(subnames) != 1:
        raise JointValidationError("A joint reference must contain exactly one sub-element.")
    return linked, subnames[0]


class FingerJointProxy:
    """Legacy standalone controller retained for older saved documents."""

    def __init__(self, obj=None):
        if obj is not None:
            obj.Proxy = self

    def execute(self, obj):
        source, face_name = _link_sub_value(obj.SourceFace)
        edge_source, edge_name = _link_sub_value(obj.FirstFingerEdge)
        if source is not edge_source:
            raise JointValidationError("The face and first-finger edge must share a source.")
        geometry = analyze_joint(source, face_name, edge_name, obj.ReceiverBase, obj.FingerCount)
        fingers, width, depth, radius = build_fingers(geometry, obj.FingerCount)
        obj.Shape = fingers
        obj.FingerWidth = width
        obj.FingerDepth = depth
        obj.FilletRadius = radius


class SourceJointProxy:
    """Parametric source-body feature that also owns the joint parameters."""

    def __init__(self, obj=None):
        self._executing = False
        if obj is not None:
            obj.Proxy = self

    def onChanged(self, obj, property_name):
        if property_name not in (
            "FingerCount",
            "Overshoot",
            "FilletRadius",
            "ReceiverOvershoot",
            "ReceiverFilletRadius",
        ):
            return
        if getattr(self, "_executing", False) or obj.Document.Recomputing:
            return
        obj.Document.recompute()

    def execute(self, obj):
        self._executing = True
        try:
            source, face_name = _link_sub_value(obj.SourceFace)
            edge_source, edge_name = _link_sub_value(obj.FirstFingerEdge)
            if source is not edge_source or source is not obj.InputFeature:
                raise JointValidationError("The joint inputs must share the same source feature.")
            if hasattr(obj.InputFeature, "ReceiverThickness") and hasattr(
                obj.InputFeature, "ExtrusionSign"
            ):
                geometry = analyze_stored_joint(
                    source,
                    face_name,
                    edge_name,
                    obj.InputFeature.ReceiverThickness,
                    obj.InputFeature.ExtrusionSign,
                )
            elif hasattr(obj, "ReceiverThickness") and hasattr(obj, "ExtrusionSign"):
                # Compatibility with joints created before the upstream input
                # feature was introduced.
                geometry = analyze_stored_joint(
                    source, face_name, edge_name, obj.ReceiverThickness, obj.ExtrusionSign
                )
            else:
                geometry = analyze_joint(
                    source, face_name, edge_name, obj.ReceiverBase, obj.FingerCount
                )
            overshoot = obj.Overshoot if hasattr(obj, "Overshoot") else None
            fillet_radius = obj.FilletRadius if hasattr(obj, "FilletRadius") else None
            fingers, cutting_tool, width, depth, radius = build_finger_shapes(
                geometry, obj.FingerCount, overshoot, fillet_radius
            )
            obj.ToolShape = cutting_tool
            obj.Shape = source.Shape.fuse(fingers).removeSplitter()
            obj.FingerWidth = width
            obj.FingerDepth = depth
            obj.FilletRadius = radius
        finally:
            self._executing = False


class JointInputProxy:
    """Upstream edge measurement used by the joint's default expressions."""

    def __init__(self, obj=None):
        if obj is not None:
            obj.Proxy = self

    def execute(self, obj):
        source, edge_name = _link_sub_value(obj.SelectedEdge)
        obj.Shape = source.Shape
        obj.EdgeLength = _subshape(source, edge_name, "Edge").Length
        obj.ReceiverThickness = obj.EdgeLength * obj.ReceiverThicknessRatio


class JointResultProxy:
    def __init__(self, obj=None, operation="Add"):
        self.operation = operation
        if obj is not None:
            obj.Proxy = self

    def execute(self, obj):
        if obj.InputFeature is None or obj.Joint is None or obj.Joint.Shape.isNull():
            return
        if self.operation == "Add":
            obj.Shape = obj.InputFeature.Shape.fuse(obj.Joint.Shape).removeSplitter()
        else:
            tool = obj.Joint.ToolShape if hasattr(obj.Joint, "ToolShape") else obj.Joint.Shape
            result = obj.InputFeature.Shape.cut(tool)
            if hasattr(obj.Joint, "ReceiverOvershoot") and hasattr(
                obj.Joint, "ReceiverFilletRadius"
            ):
                source, face_name = _link_sub_value(obj.Joint.SourceFace)
                _, edge_name = _link_sub_value(obj.Joint.FirstFingerEdge)
                geometry = analyze_stored_joint(
                    source,
                    face_name,
                    edge_name,
                    obj.Joint.InputFeature.ReceiverThickness,
                    obj.Joint.InputFeature.ExtrusionSign,
                )
                receiver_fingers, _ = build_receiver_fingers(
                    geometry,
                    obj.InputFeature,
                    obj.Joint.FingerCount,
                    obj.Joint.ReceiverOvershoot,
                    obj.Joint.ReceiverFilletRadius,
                )
                if not receiver_fingers.isNull():
                    result = result.fuse(receiver_fingers)
            obj.Shape = result.removeSplitter()

    def dumps(self):
        return {"operation": self.operation}

    def loads(self, state):
        self.operation = state["operation"]


class JointViewProvider:
    """Initialize the standard Part Design shape display for scripted features."""

    def __init__(self, view_object=None):
        if view_object is not None:
            view_object.Proxy = self

    def attach(self, view_object):
        self.ViewObject = view_object

    def updateData(self, obj, prop):
        return None

    def getDisplayModes(self, view_object):
        return []

    def getDefaultDisplayMode(self):
        return "Flat Lines"

    def setDisplayMode(self, mode):
        return mode

    def onChanged(self, view_object, prop):
        return None

    def dumps(self):
        return None

    def loads(self, state):
        return None


def _add_result(body, name, label, base, joint, operation):
    result = body.newObject("PartDesign::FeaturePython", name)
    result.Label = label
    result.addProperty("App::PropertyLink", "InputFeature", "Joint", "Unmodified input feature")
    result.addProperty("App::PropertyLinkGlobal", "Joint", "Joint", "Finger-joint controller")
    result.InputFeature = base
    result.Joint = joint
    JointResultProxy(result, operation)
    if App.GuiUp:
        JointViewProvider(result.ViewObject)
    return result


def show_body_tips(*bodies):
    """Show each body and only its current tip feature."""
    if not App.GuiUp:
        return
    for body in bodies:
        tip = body.Tip
        body.ViewObject.Visibility = True
        for feature in body.Group:
            if feature.ViewObject is not None:
                feature.ViewObject.Visibility = feature == tip
    Gui.activeDocument().activeView().redraw()
    Gui.updateGui()


def create_joint(
    source_obj,
    face_name,
    edge_name,
    receiver_obj,
    finger_count,
    overshoot=None,
    fillet_radius=None,
    finger_count_expression=None,
    overshoot_expression=None,
    fillet_radius_expression=None,
    receiver_overshoot=None,
    receiver_fillet_radius=None,
    receiver_overshoot_expression=None,
    receiver_fillet_radius_expression=None,
):
    """Create one parametric joint feature in each affected body."""
    geometry = analyze_joint(source_obj, face_name, edge_name, receiver_obj, finger_count)
    # Validate the exact requested fillet before changing the document.
    default_overshoot = overshoot is None or overshoot_expression is not None
    default_fillet_radius = fillet_radius is None or fillet_radius_expression is not None
    default_receiver_overshoot = (
        receiver_overshoot is None or receiver_overshoot_expression is not None
    )
    default_receiver_fillet_radius = (
        receiver_fillet_radius is None
        or receiver_fillet_radius_expression is not None
    )
    overshoot = _length_value(overshoot, geometry.edge_length)
    fillet_radius = _length_value(fillet_radius, geometry.edge_length)
    receiver_overshoot = _length_value(
        receiver_overshoot, geometry.receiver_thickness
    )
    receiver_fillet_radius = _length_value(
        receiver_fillet_radius, geometry.receiver_thickness
    )
    build_fingers(geometry, finger_count, overshoot, fillet_radius)
    for receiver_base in geometry.receiver_bases:
        build_receiver_fingers(
            geometry,
            receiver_base,
            finger_count,
            receiver_overshoot,
            receiver_fillet_radius,
        )

    doc = geometry.source_body.Document
    if any(body.Document is not doc for body in geometry.receiver_bodies):
        raise JointValidationError("Both bodies must be in the same document.")

    inputs = geometry.source_body.newObject(
        "PartDesign::FeaturePython", "FingerJointInputs"
    )
    inputs.Label = "Finger Joint (inputs)"
    inputs.addProperty(
        "App::PropertyLink", "InputFeature", "Inputs", "Unmodified source feature"
    )
    inputs.addProperty(
        "App::PropertyLinkSub", "SelectedEdge", "Inputs", "Selected thickness edge"
    )
    inputs.addProperty(
        "App::PropertyFloat", "ReceiverThicknessRatio", "Internal", "Receiver/source thickness ratio"
    )
    inputs.addProperty(
        "App::PropertyLength", "EdgeLength", "Results", "Current selected-edge length"
    )
    inputs.addProperty(
        "App::PropertyLength", "ReceiverThickness", "Internal", "Receiving thickness at creation"
    )
    inputs.addProperty(
        "App::PropertyInteger", "ExtrusionSign", "Internal", "Direction relative to face normal"
    )
    inputs.InputFeature = geometry.source_base
    inputs.SelectedEdge = (geometry.source_base, [edge_name])
    inputs.EdgeLength = geometry.edge_length
    inputs.ReceiverThickness = geometry.receiver_thickness
    inputs.ReceiverThicknessRatio = geometry.receiver_thickness / geometry.edge_length
    face_normal = _unit(geometry.selected_face.normalAt(0, 0))
    inputs.ExtrusionSign = 1 if geometry.extrusion_direction.dot(face_normal) > 0 else -1
    JointInputProxy(inputs)
    if App.GuiUp:
        JointViewProvider(inputs.ViewObject)
    for property_name in (
        "ReceiverThicknessRatio",
        "EdgeLength",
        "ReceiverThickness",
        "ExtrusionSign",
    ):
        inputs.setEditorMode(property_name, 2)
    doc.recompute()

    joint = geometry.source_body.newObject("PartDesign::FeaturePython", "FingerJoint")
    joint.Label = "Finger Joint (added)"
    joint.addProperty("App::PropertyLink", "InputFeature", "Inputs", "Unmodified source feature")
    joint.addProperty("App::PropertyLinkSub", "SourceFace", "Inputs", "Rectangular source face")
    joint.addProperty("App::PropertyLinkSub", "FirstFingerEdge", "Inputs", "Edge where the pattern begins")
    joint.addProperty(
        "App::PropertyIntegerConstraint", "FingerCount", "Parameters", "Number of fingers"
    )
    joint.addProperty(
        "App::PropertyLength", "Overshoot", "Parameters", "Distance past the receiving panel"
    )
    joint.addProperty(
        "App::PropertyLength", "FilletRadius", "Parameters", "Finger-tip fillet radius"
    )
    joint.addProperty(
        "App::PropertyLength",
        "ReceiverOvershoot",
        "Parameters",
        "Receiving-panel finger extension past its edge",
    )
    joint.addProperty(
        "App::PropertyLength",
        "ReceiverFilletRadius",
        "Parameters",
        "Receiving-panel finger-tip fillet radius",
    )
    joint.addProperty("App::PropertyLength", "FingerWidth", "Results", "Calculated finger width")
    joint.addProperty("App::PropertyLength", "FingerDepth", "Results", "Calculated extrusion depth")
    joint.addProperty(
        "App::PropertyLength", "SelectedEdgeLength", "Results", "Current selected-edge length"
    )
    joint.addProperty("Part::PropertyPartShape", "ToolShape", "Internal", "Finger cutting tool")
    joint.InputFeature = inputs
    joint.SourceFace = (inputs, [face_name])
    joint.FirstFingerEdge = (inputs, [edge_name])
    joint.FingerCount = (int(finger_count), 1, 1000, 1)
    joint.Overshoot = overshoot
    joint.FilletRadius = fillet_radius
    joint.ReceiverOvershoot = receiver_overshoot
    joint.ReceiverFilletRadius = receiver_fillet_radius
    edge_length_expression = f"{inputs.Name}.EdgeLength"
    receiver_thickness_expression = f"{inputs.Name}.ReceiverThickness"
    def transferred_expression(expression):
        return expression.replace(
            "SelectedEdgeLength", edge_length_expression
        ).replace("ReceiverThickness", receiver_thickness_expression)

    joint.setExpression("SelectedEdgeLength", edge_length_expression)
    if finger_count_expression:
        joint.setExpression(
            "FingerCount", transferred_expression(finger_count_expression)
        )
    if default_overshoot:
        expression = overshoot_expression or "SelectedEdgeLength"
        joint.setExpression("Overshoot", transferred_expression(expression))
    if default_fillet_radius:
        expression = fillet_radius_expression or "SelectedEdgeLength"
        joint.setExpression("FilletRadius", transferred_expression(expression))
    if default_receiver_overshoot:
        expression = receiver_overshoot_expression or "ReceiverThickness"
        joint.setExpression("ReceiverOvershoot", transferred_expression(expression))
    if default_receiver_fillet_radius:
        expression = receiver_fillet_radius_expression or "ReceiverThickness"
        joint.setExpression(
            "ReceiverFilletRadius", transferred_expression(expression)
        )
    SourceJointProxy(joint)
    if App.GuiUp:
        JointViewProvider(joint.ViewObject)
    for property_name in ("FingerWidth", "FingerDepth", "SelectedEdgeLength"):
        joint.setEditorMode(property_name, 1)
    joint.setEditorMode("ToolShape", 2)

    geometry.source_body.Tip = joint
    for receiver_body, receiver_base in zip(
        geometry.receiver_bodies, geometry.receiver_bases
    ):
        receiver_result = _add_result(
            receiver_body,
            "FingerJointCut",
            "Finger Joint (cut)",
            receiver_base,
            joint,
            "Cut",
        )
        receiver_body.Tip = receiver_result
    doc.recompute()

    show_body_tips(geometry.source_body, *geometry.receiver_bodies)

    doc.recompute()
    return joint
