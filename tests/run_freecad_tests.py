"""Integration tests executed by FreeCADCmd."""

import shutil
import sys
import tempfile
from math import cos, radians, sin
from pathlib import Path

import FreeCAD as App
import Part


PROJECT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_DIR / "freecad" / "DesignSystem"))

from finger_joint import (  # noqa: E402
    JointValidationError,
    _is_rectangle,
    analyze_joint,
    create_joint,
    keep_dominant_solid,
    receiver_fingers_applicable,
    validate_source_face_set,
)
from joint_group import create_joint_group, solve_joint  # noqa: E402


def find_face(feature, axis, coordinate, area):
    for index, face in enumerate(feature.Shape.Faces, start=1):
        normal = face.normalAt(0, 0)
        if abs(abs(normal.dot(axis)) - 1.0) > 1e-7:
            continue
        if abs(face.CenterOfMass.dot(axis) - coordinate) <= 1e-7 and abs(face.Area - area) <= 1e-7:
            return f"Face{index}", face
    raise AssertionError("Expected face not found")


def copied_fixture(name, temp_dir):
    source = PROJECT_DIR / "fixtures" / name
    target = Path(temp_dir) / name
    shutil.copy2(source, target)
    return target


def face_with_normal(feature, direction):
    for index, face in enumerate(feature.Shape.Faces, start=1):
        if face.normalAt(0, 0).dot(direction) >= 1 - 1e-7:
            return f"Face{index}"
    raise AssertionError("Expected face normal not found")


def contacting_rectangular_face(source, receiver):
    faces = []
    for index, face in enumerate(source.Shape.Faces, start=1):
        if not _is_rectangle(face):
            continue
        name = f"Face{index}"
        try:
            validate_source_face_set(((source, name),), (receiver,))
        except JointValidationError:
            continue
        faces.append(name)
    assert len(faces) == 1, (source.Label, receiver.Label, faces)
    return faces[0]


def test_laminated_source_face_set(temp_dir):
    path = copied_fixture("Acute2.FCStd", temp_dir)
    doc = App.openDocument(str(path))
    try:
        inner = doc.getObject("AngledInnerSolid")
        outer = doc.getObject("AngledOuterSolid")
        receivers = (doc.getObject("BaseLower"), doc.getObject("BaseUpper"))
        end_normal = App.Vector(0, -0.5, -(3 ** 0.5) / 2)
        inner_face = face_with_normal(inner, end_normal)
        outer_face = face_with_normal(outer, end_normal)
        contacts = validate_source_face_set(
            ((inner, inner_face), (outer, outer_face)), receivers
        )
        assert any(source is inner for source, _, _ in contacts)
        assert not any(source is outer for source, _, _ in contacts)
        try:
            validate_source_face_set(((outer, outer_face),), receivers)
        except JointValidationError as error:
            assert "At least one edge" in str(error)
        else:
            raise AssertionError("Non-contacting outer ply should fail alone")
    finally:
        App.closeDocument(doc.Name)


def test_angled_joint_groups(temp_dir):
    fixtures = (
        ("Acute", ("AngledPanel",), ("BasePanel",), 60),
        ("Edge90", ("AngledPanel",), ("BasePanel",), 90),
        ("Obtuse", ("AngledPanel",), ("BasePanel",), 120),
        ("AngledT", ("AngledPanel",), ("BasePanel",), 60),
        ("Acute2", ("AngledInner", "AngledOuter"),
         ("BaseLower", "BaseUpper"), 60),
        ("AngledT2", ("AngledInner", "AngledOuter"),
         ("BaseLower", "BaseUpper"), 60),
    )
    for name, source_names, receiver_names, angle in fixtures:
        path = copied_fixture(f"{name}.FCStd", temp_dir)
        doc = App.openDocument(str(path))
        try:
            normal = App.Vector(0, -cos(radians(angle)), -sin(radians(angle)))
            sources = []
            for body_name in source_names:
                feature = doc.getObject(body_name).Tip
                sources.append((feature, face_with_normal(feature, normal)))
            receivers = [doc.getObject(body_name) for body_name in receiver_names]
            # Exercise the task panel's default lengths and radii on every
            # angled fixture, including the laminated source and receiver.
            preview = solve_joint(sources, receivers, 2, 5, 5, 5, 5)
            assert all(shape.isValid() and len(shape.Solids) == 1
                       for shape in preview.values())
            shapes = list(preview.values())
            assert all(shapes[i].common(shapes[j]).Volume <= 1e-7
                       for i in range(len(shapes)) for j in range(i + 1, len(shapes)))
            plan, results = create_joint_group(
                sources, receivers, 2, overshoot=0, fillet_radius=2.5,
                receiver_overshoot=0, receiver_fillet_radius=0,
            )
            assert len(results) == len(source_names) + len(receiver_names)
            assert plan.SourceCount == len(source_names)
            assert all(result.Shape.isValid() and len(result.Shape.Solids) == 1
                       for result in results)
            assert all(
                results[i].Shape.common(results[j].Shape).Volume <= 1e-7
                for i in range(len(results)) for j in range(i + 1, len(results))
            )
            plan.Overshoot = 3
            doc.recompute()
            assert all(result.Shape.isValid() for result in results)
            doc.save()
        finally:
            App.closeDocument(doc.Name)
        reopened = App.openDocument(str(path))
        try:
            reopened.recompute()
            reopened_results = [obj for obj in reopened.Objects
                                if obj.Name.startswith("FingerJointGroupResult")]
            assert len(reopened_results) == len(source_names) + len(receiver_names)
            assert all(result.Shape.isValid() for result in reopened_results)
        finally:
            App.closeDocument(reopened.Name)


def test_pyramid_side_joints_have_matching_receiving_fingers(temp_dir):
    adjacent_pairs = (
        ("SouthFace", "EastFace"),
        ("EastFace", "NorthFace"),
        ("NorthFace", "WestFace"),
        ("WestFace", "SouthFace"),
    )
    pairs = (*adjacent_pairs, *((receiver, source)
                                for source, receiver in adjacent_pairs))
    for source_name, receiver_name in pairs:
        path = copied_fixture("Pyramid.FCStd", temp_dir)
        doc = App.openDocument(str(path))
        try:
            source = doc.getObject(source_name).Tip
            receiver = doc.getObject(receiver_name)
            face_name = contacting_rectangular_face(source, receiver)
            original_receiver_volume = receiver.Tip.Shape.Volume
            _, results = create_joint_group(
                ((source, face_name),), (receiver,), 2,
                overshoot=5, fillet_radius=5,
                receiver_overshoot=5, receiver_fillet_radius=5,
            )
            assert len(results) == 2
            assert all(result.Shape.isValid() and len(result.Shape.Solids) == 1
                       for result in results)
            assert receiver.Tip.Shape.Volume > original_receiver_volume
            assert results[0].Shape.common(results[1].Shape).Volume <= 1e-7
        finally:
            App.closeDocument(doc.Name)


def test_dominant_solid_threshold():
    large = Part.makeBox(3, 1, 1)
    small = Part.makeBox(1, 1, 1, App.Vector(5, 0, 0))
    assert abs(keep_dominant_solid(Part.makeCompound((large, small))).Volume - 3) < 1e-7
    equally_split = Part.makeCompound((Part.makeBox(2, 1, 1), small))
    try:
        keep_dominant_solid(equally_split)
    except JointValidationError:
        pass
    else:
        raise AssertionError("A largest solid below 75% must be rejected")


def test_pyramid_two_joints_sharing_triangle(temp_dir):
    path = copied_fixture("Pyramid.FCStd", temp_dir)
    doc = App.openDocument(str(path))
    try:
        south = doc.getObject("SouthFace")
        for receiver_name in ("EastFace", "WestFace"):
            source = south.Tip
            receiver = doc.getObject(receiver_name)
            face_name = contacting_rectangular_face(source, receiver)
            create_joint_group(
                ((source, face_name),), (receiver,), 2,
                overshoot=5, fillet_radius=5,
                receiver_overshoot=5, receiver_fillet_radius=5,
            )
            doc.recompute()
            assert all(body.Tip.Shape.isValid() and len(body.Tip.Shape.Solids) == 1
                       for body in (south, receiver))
        doc.save()
    finally:
        App.closeDocument(doc.Name)
    reopened = App.openDocument(str(path))
    try:
        reopened.recompute()
        for name in ("SouthFace", "EastFace", "WestFace"):
            shape = reopened.getObject(name).Tip.Shape
            assert shape.isValid() and len(shape.Solids) == 1
    finally:
        App.closeDocument(reopened.Name)


def test_corner_success(temp_dir):
    path = copied_fixture("Corner.FCStd", temp_dir)
    doc = App.openDocument(str(path))
    try:
        source = doc.getObject("BackXZSolid")
        receiver = doc.getObject("BaseXYSolid")
        face_name, face = find_face(source, App.Vector(0, 0, 1), 10, 1000)
        source_volume = source.Shape.Volume
        joint = create_joint(source, face_name, receiver, 2,
                             receiver_fillet_radius=0)
        doc.recompute()

        source_result = joint
        receiver_result = doc.getObject("FingerJointCut")
        assert abs(joint.FingerWidth.Value - 25.0) <= 1e-7
        assert abs(joint.FingerDepth.Value - 20.0) <= 1e-7
        assert abs(joint.Overshoot.Value - 10.0) <= 1e-7
        assert abs(joint.FilletRadius.Value - 10.0) <= 1e-7
        expressions = dict(joint.ExpressionEngine)
        assert "FingerJointInputs.EdgeLength" in expressions["Overshoot"]
        assert "FingerJointInputs.EdgeLength" in expressions["FilletRadius"]
        assert "FingerJointInputs.ReceiverThickness" in expressions["ReceiverOvershoot"]
        assert "ReceiverFilletRadius" not in expressions
        assert abs(joint.ReceiverFilletRadius.Value) <= 1e-7
        assert abs(joint.ToolShape.BoundBox.XMin - 12.5) <= 1e-7
        assert abs(joint.ToolShape.BoundBox.XMax - 87.5) <= 1e-7
        assert source_result.Shape.Volume > source_volume
        assert receiver_result.Shape.Volume > 95_000.0
        assert abs(receiver_result.Shape.BoundBox.YMin + 10.0) <= 1e-7
        assert joint.ToolShape.Volume > source_result.Shape.Volume - source_volume
        assert len(source_result.Shape.Solids) == 1
        assert len(receiver_result.Shape.Solids) == 1
        start_side_areas = sorted(
            face.Area
            for face in source_result.Shape.Faces
            if all(abs(vertex.Point.x) <= 1e-7 for vertex in face.Vertexes)
        )
        assert len(start_side_areas) == 1
        assert abs(start_side_areas[0] - 900.0) <= 1e-7
        assert receiver_result.Shape.common(joint.ToolShape).Volume <= 1e-7
        assert joint.getParentGeoFeatureGroup() is doc.getObject("BackXZ")
        assert receiver_result.getParentGeoFeatureGroup() is doc.getObject("BaseXY")
        assert doc.getObject("BackXZ").Tip is joint
        assert doc.getObject("BaseXY").Tip is receiver_result
        assert not any(
            obj.TypeId == "Part::FeaturePython" and obj.getParentGeoFeatureGroup() is None
            for obj in doc.Objects
        )

        two_finger_volume = joint.ToolShape.Volume
        joint.setExpression("ReceiverOvershoot", None)
        joint.setExpression("ReceiverFilletRadius", None)
        joint.ReceiverFilletRadius = 2
        joint.ReceiverOvershoot = 5
        assert abs(receiver_result.Shape.BoundBox.YMin + 5.0) <= 1e-7

        joint.setExpression("Overshoot", None)
        joint.setExpression("FilletRadius", None)
        joint.Overshoot = 5
        assert abs(joint.FingerDepth.Value - 15.0) <= 1e-7
        joint.FilletRadius = 2
        assert abs(joint.FingerDepth.Value - 15.0) <= 1e-7
        assert abs(joint.FilletRadius.Value - 2.0) <= 1e-7

        joint.FingerCount = 1
        assert abs(joint.FingerWidth.Value - 50.0) <= 1e-7
        assert abs(joint.ToolShape.BoundBox.XMin - 25.0) <= 1e-7
        assert abs(joint.ToolShape.BoundBox.XMax - 75.0) <= 1e-7
        assert abs(joint.ToolShape.Volume - two_finger_volume) > 1e-7
        assert receiver_result.Shape.common(joint.ToolShape).Volume <= 1e-7
        doc.save()
    finally:
        App.closeDocument(doc.Name)


def test_mismatched_rejects_impossible_fillet(temp_dir):
    path = copied_fixture("Mismatched.FCStd", temp_dir)
    doc = App.openDocument(str(path))
    try:
        source = doc.getObject("DrawerSideXZSolid")
        receiver = doc.getObject("DrawerFrontYZSolid")
        face_name, face = find_face(source, App.Vector(1, 0, 0), 100, 300)
        geometry = analyze_joint(source, face_name, receiver, 1)
        assert receiver_fingers_applicable(geometry)
        try:
            create_joint(source, face_name, receiver, 1)
        except JointValidationError as error:
            assert "require at least 20" in str(error)
        else:
            raise AssertionError("Expected the exact-radius fillet constraint to reject the joint")
    finally:
        App.closeDocument(doc.Name)


def test_default_receiver_fillet_tracks_thickness(temp_dir):
    corner_path = copied_fixture("Corner.FCStd", temp_dir)
    doc = App.openDocument(str(corner_path))
    try:
        source = doc.getObject("BackXZSolid")
        receiver = doc.getObject("BaseXYSolid")
        face_name, _ = find_face(source, App.Vector(0, 0, 1), 10, 1000)
        joint = create_joint(source, face_name, receiver, 1)
        assert abs(joint.ReceiverFilletRadius.Value - 10) <= 1e-7
        assert "FingerJointInputs.ReceiverThickness" in dict(
            joint.ExpressionEngine
        )["ReceiverFilletRadius"]
    finally:
        App.closeDocument(doc.Name)

    obtuse_path = copied_fixture("Obtuse.FCStd", temp_dir)
    doc = App.openDocument(str(obtuse_path))
    try:
        source = doc.getObject("AngledPanel").Tip
        receiver = doc.getObject("BasePanel")
        normal = App.Vector(0, -cos(radians(120)), -sin(radians(120)))
        face_name = face_with_normal(source, normal)
        plan, results = create_joint_group(
            ((source, face_name),), (receiver,), 1
        )
        assert abs(plan.ReceiverFilletRadius.Value - 5) <= 1e-7
        assert "FingerJointGroupInputs.ReceivingThickness" in dict(
            plan.ExpressionEngine
        )["ReceiverFilletRadius"]
        assert all(result.Shape.isValid() for result in results)
    finally:
        App.closeDocument(doc.Name)


def test_t_joint_has_no_receiving_panel_finger_extensions(temp_dir):
    path = copied_fixture("T.FCStd", temp_dir)
    doc = App.openDocument(str(path))
    try:
        source = doc.getObject("StemPanelYZSolid")
        receiver = doc.getObject("CrossPanelXZSolid")
        face_name, face = find_face(source, App.Vector(0, 1, 0), 10, 1000)
        joint = create_joint(source, face_name, receiver, 2)
        doc.recompute()
        result = doc.getObject("CrossPanelXZ").Tip
        original = result.Shape.copy()

        assert abs(result.Shape.Volume - 95_000.0) <= 1e-7
        joint.setExpression("ReceiverOvershoot", None)
        joint.ReceiverOvershoot = 20
        assert original.cut(result.Shape).Volume <= 1e-7
        assert result.Shape.cut(original).Volume <= 1e-7
    finally:
        App.closeDocument(doc.Name)


def test_tilted_trapezoid_edge_faces_are_rectangles():
    points = [
        App.Vector(0, 0, 0),
        App.Vector(100, 0, 0),
        App.Vector(80, 0, 100),
        App.Vector(20, 0, 100),
        App.Vector(0, 0, 0),
    ]
    solid = Part.Face(Part.makePolygon(points)).extrude(App.Vector(0, 10, 0))
    side_faces = [face for face in solid.Faces if abs(face.normalAt(0, 0).y) < 1e-7]
    assert len(side_faces) == 4
    assert all(_is_rectangle(face) for face in side_faces)
    broad_faces = [face for face in solid.Faces if abs(face.normalAt(0, 0).y) > 1 - 1e-7]
    assert len(broad_faces) == 2
    assert not any(_is_rectangle(face) for face in broad_faces)


def test_angled_binder_fixture_has_no_cycle_and_tracks_thickness(temp_dir):
    path = copied_fixture("Angled.FCStd", temp_dir)
    doc = App.openDocument(str(path))
    try:
        joint = create_joint(doc.Pad, "Face3", doc.Body001, 2,
                             receiver_fillet_radius=0)
        doc.recompute()
        cut = doc.getObject("FingerJointCut")
        assert not joint.Shape.isNull()
        assert not joint.ToolShape.isNull()
        assert not cut.Shape.isNull()
        assert "ReceiverBase" not in joint.PropertiesList
        expressions = dict(joint.ExpressionEngine)
        assert "FingerJointInputs.EdgeLength" in expressions["Overshoot"]
        assert "FingerJointInputs.EdgeLength" in expressions["FilletRadius"]

        doc.Pad.Length = 12
        doc.recompute()
        assert abs(joint.SelectedEdgeLength.Value - 12.0) <= 1e-7
        assert abs(joint.Overshoot.Value - 12.0) <= 1e-7
        assert abs(joint.FilletRadius.Value - 12.0) <= 1e-7
        assert not joint.Shape.isNull()
        assert not cut.Shape.isNull()
    finally:
        App.closeDocument(doc.Name)


def test_params_fixture_tracks_both_panel_thicknesses(temp_dir):
    path = copied_fixture("Params.FCStd", temp_dir)
    doc = App.openDocument(str(path))
    try:
        joint = create_joint(doc.Pad, "Face4", doc.Body001, 2,
                             receiver_fillet_radius=0)
        doc.recompute()
        assert abs(joint.FingerDepth.Value - 20.0) <= 1e-7

        params = next(obj for obj in doc.Objects if obj.Label == "Params")
        params.Thickness = 12
        doc.recompute()
        assert abs(joint.SelectedEdgeLength.Value - 12.0) <= 1e-7
        assert abs(joint.Overshoot.Value - 12.0) <= 1e-7
        assert abs(joint.FilletRadius.Value - 12.0) <= 1e-7
        assert abs(joint.InputFeature.ReceiverThickness.Value - 12.0) <= 1e-7
        assert abs(joint.FingerDepth.Value - 24.0) <= 1e-7
        assert not joint.Shape.isNull()
        assert not doc.FingerJointCut.Shape.isNull()
    finally:
        App.closeDocument(doc.Name)


def test_joint_cuts_through_multiple_receiving_bodies():
    doc = App.newDocument("MultiBodyFingerJointTest")
    try:
        source_body = doc.addObject("PartDesign::Body", "SourceBody")
        source = source_body.newObject("PartDesign::Feature", "Source")
        source.Shape = Part.makeBox(100, 10, 90)

        first_body = doc.addObject("PartDesign::Body", "FirstReceiver")
        first = first_body.newObject("PartDesign::Feature", "FirstPanel")
        first.Shape = Part.makeBox(100, 100, 5, App.Vector(0, 0, 90))

        second_body = doc.addObject("PartDesign::Body", "SecondReceiver")
        second = second_body.newObject("PartDesign::Feature", "SecondPanel")
        second.Shape = Part.makeBox(100, 100, 7, App.Vector(0, 0, 95))
        doc.recompute()

        face_name, face = find_face(source, App.Vector(0, 0, 1), 90, 1000)
        joint = create_joint(
            source, face_name, [first_body, second_body], 2,
            receiver_fillet_radius=0,
        )
        doc.recompute()

        assert abs(joint.InputFeature.ReceiverThickness.Value - 12.0) <= 1e-7
        assert abs(joint.ReceiverOvershoot.Value - 12.0) <= 1e-7
        assert abs(joint.ReceiverFilletRadius.Value) <= 1e-7
        assert abs(joint.FingerDepth.Value - 22.0) <= 1e-7
        assert first_body.Tip.Shape.Volume > 47_500.0
        assert second_body.Tip.Shape.Volume > 66_500.0
        assert abs(first_body.Tip.Shape.BoundBox.YMin + 12.0) <= 1e-7
        assert abs(second_body.Tip.Shape.BoundBox.YMin + 12.0) <= 1e-7
        assert first_body.Tip.Joint is joint
        assert second_body.Tip.Joint is joint

        joint.setExpression("Overshoot", None)
        joint.Overshoot = 3
        assert abs(joint.FingerDepth.Value - 15.0) <= 1e-7
        assert first_body.Tip.Shape.common(joint.ToolShape).Volume <= 1e-7
        assert second_body.Tip.Shape.common(joint.ToolShape).Volume <= 1e-7
    finally:
        App.closeDocument(doc.Name)


def test_receiver_coplanar_face_fragments_share_two_boundary_planes():
    doc = App.newDocument("FragmentedReceiverTest")
    try:
        source_body = doc.addObject("PartDesign::Body", "SourceBody")
        source = source_body.newObject("PartDesign::Feature", "Source")
        source.Shape = Part.makeBox(100, 10, 90)

        receiver_body = doc.addObject("PartDesign::Body", "ReceiverBody")
        receiver = receiver_body.newObject("PartDesign::Feature", "Receiver")
        receiver.Shape = Part.makeBox(
            100, 100, 10, App.Vector(0, 0, 90)
        ).fuse(Part.makeBox(20, 50, 10, App.Vector(100, 0, 90)))
        doc.recompute()

        parallel_faces = [
            face
            for face in receiver.Shape.Faces
            if abs(abs(face.normalAt(0, 0).z) - 1.0) <= 1e-7
        ]
        assert len(parallel_faces) > 2
        face_name, face = find_face(
            source, App.Vector(0, 0, 1), 90, 1000
        )
        joint = create_joint(source, face_name, receiver, 2,
                             receiver_fillet_radius=0)
        doc.recompute()
        assert not joint.Shape.isNull()
        assert not receiver_body.Tip.Shape.isNull()
    finally:
        App.closeDocument(doc.Name)


def test_saved_joint_reopens(temp_dir):
    path = copied_fixture("Corner.FCStd", temp_dir)
    doc = App.openDocument(str(path))
    try:
        source = doc.getObject("BackXZSolid")
        receiver = doc.getObject("BaseXYSolid")
        face_name, face = find_face(source, App.Vector(0, 0, 1), 10, 1000)
        create_joint(source, face_name, receiver, 2,
                     receiver_fillet_radius=0)
        doc.recompute()
        doc.save()
    finally:
        App.closeDocument(doc.Name)

    reopened = App.openDocument(str(path))
    try:
        reopened.recompute()
        joint = reopened.getObject("FingerJoint")
        cut = reopened.getObject("FingerJointCut")
        assert "Invalid" not in joint.State
        assert "Invalid" not in cut.State
        assert not joint.Shape.isNull()
        assert not cut.Shape.isNull()
    finally:
        App.closeDocument(reopened.Name)


with tempfile.TemporaryDirectory(prefix="design-system-tests-") as temp_dir:
    test_laminated_source_face_set(temp_dir)
    test_angled_joint_groups(temp_dir)
    test_pyramid_side_joints_have_matching_receiving_fingers(temp_dir)
    test_dominant_solid_threshold()
    test_pyramid_two_joints_sharing_triangle(temp_dir)
    test_corner_success(temp_dir)
    test_default_receiver_fillet_tracks_thickness(temp_dir)
    test_mismatched_rejects_impossible_fillet(temp_dir)
    test_t_joint_has_no_receiving_panel_finger_extensions(temp_dir)
    test_tilted_trapezoid_edge_faces_are_rectangles()
    test_angled_binder_fixture_has_no_cycle_and_tracks_thickness(temp_dir)
    test_params_fixture_tracks_both_panel_thicknesses(temp_dir)
    test_joint_cuts_through_multiple_receiving_bodies()
    test_receiver_coplanar_face_fragments_share_two_boundary_planes()
    test_saved_joint_reopens(temp_dir)

print("Finger-joint integration tests passed.")
