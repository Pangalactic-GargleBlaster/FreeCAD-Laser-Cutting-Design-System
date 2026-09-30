"""Read-only geometry checks for the immutable fixture documents."""

import math
from pathlib import Path
import xml.etree.ElementTree as ET
import zipfile

import FreeCAD as App
import Part


FIXTURE_DIR = Path(__file__).resolve().parent.parent / "fixtures"
FINGER_JOINT_DIR = FIXTURE_DIR / "finger joint"
HALF_LAP_DIR = FIXTURE_DIR / "half-lap"
TOLERANCE = 1e-7


def close(actual, expected):
    return abs(actual - expected) <= TOLERANCE


def check_panel(doc, name, bounds, volume):
    body = doc.getObject(name)
    assert body is not None, f"{doc.Name}: missing {name}"
    shape = body.Shape
    assert not shape.isNull(), f"{doc.Name}/{name}: null shape"
    assert len(shape.Solids) == 1, f"{doc.Name}/{name}: expected one solid"
    bb = shape.BoundBox
    actual_bounds = (bb.XMin, bb.YMin, bb.ZMin, bb.XMax, bb.YMax, bb.ZMax)
    assert all(close(a, e) for a, e in zip(actual_bounds, bounds)), (
        f"{doc.Name}/{name}: bounds {actual_bounds}, expected {bounds}"
    )
    assert close(shape.Volume, volume), (
        f"{doc.Name}/{name}: volume {shape.Volume}, expected {volume}"
    )
    return shape


def check_contact(doc, first, second):
    distance = first.distToShape(second)[0]
    assert close(distance, 0), f"{doc.Name}: panels do not touch; distance={distance}"
    overlap = first.common(second).Volume
    assert close(overlap, 0), f"{doc.Name}: panels overlap; volume={overlap}"


def _point_matches(point, coordinates):
    return all(close(actual, expected) for actual, expected in zip(
        (point.x, point.y, point.z), coordinates
    ))


def _has_edge(shape, start, end):
    return any(
        len(edge.Vertexes) == 2 and (
            (_point_matches(edge.Vertexes[0].Point, start) and
             _point_matches(edge.Vertexes[1].Point, end)) or
            (_point_matches(edge.Vertexes[1].Point, start) and
             _point_matches(edge.Vertexes[0].Point, end))
        )
        for edge in shape.Edges
    )


def check_saved_visibility(path, body_names):
    with zipfile.ZipFile(path) as archive:
        assert "GuiDocument.xml" in archive.namelist(), (
            f"{path.name}: missing saved GUI visibility"
        )
        gui = ET.fromstring(archive.read("GuiDocument.xml"))
    for body_name in body_names:
        for name in (body_name, body_name + "Solid"):
            visibility = gui.find(
                f"./ViewProviderData/ViewProvider[@name='{name}']"
                "/Properties/Property[@name='Visibility']/Bool"
            )
            assert visibility is not None and visibility.get("value") == "true", (
                f"{path.name}: {name} is hidden by default"
            )


def validate_angled(name, angle, seam_y):
    path = FINGER_JOINT_DIR / f"{name}.FCStd"
    check_saved_visibility(path, ("BasePanel", "AngledPanel"))
    doc = App.openDocument(str(path))
    try:
        base = doc.getObject("BasePanel")
        angled = doc.getObject("AngledPanel")
        assert base is not None and angled is not None
        assert len(doc.findObjects("PartDesign::Body")) == 2
        for body in (base, angled):
            shape = body.Shape
            assert shape.isValid() and len(shape.Solids) == 1
            assert close(shape.Volume, 50_000)
            assert sorted(round(edge.Length, 7) for edge in shape.Edges) == (
                [5.0] * 4 + [100.0] * 8
            )

        check_panel(doc, "BasePanel", (0, 0, 0, 100, 100, 5), 50_000)
        check_contact(doc, base.Shape, angled.Shape)
        start, end = (0, seam_y, 5), (100, seam_y, 5)
        assert _has_edge(angled.Shape, start, end), f"{name}: missing seam edge"
        if seam_y == 0:
            assert _has_edge(base.Shape, start, end), f"{name}: seam is not a shared edge"
        else:
            assert 0 < seam_y < 100, f"{name}: seam is not inside the base face"
            top = next(face for face in base.Shape.Faces if close(face.CenterOfMass.z, 5)
                       and close(face.Area, 10_000))
            seam = next(edge for edge in angled.Shape.Edges if _has_edge(
                edge, start, end
            ))
            assert close(top.distToShape(seam)[0], 0), f"{name}: seam misses top face"

        radians = math.radians(angle)
        far_corner = (0, seam_y + 100 * math.cos(radians),
                      5 + 100 * math.sin(radians))
        assert any(_point_matches(vertex.Point, far_corner)
                   for vertex in angled.Shape.Vertexes), f"{name}: wrong panel angle"
    finally:
        App.closeDocument(doc.Name)


def validate_acute2():
    path = FINGER_JOINT_DIR / "Acute2.FCStd"
    names = ("BaseLower", "BaseUpper", "AngledInner", "AngledOuter")
    check_saved_visibility(path, names)
    doc = App.openDocument(str(path))
    try:
        assert len(doc.findObjects("PartDesign::Body")) == 4
        shapes = {}
        for name in names:
            body = doc.getObject(name)
            assert body is not None and body.Tip is not None
            shape = body.Shape
            assert shape.isValid() and len(shape.Solids) == 1
            assert close(shape.Volume, 50_000)
            assert close(body.Tip.PanelThickness.Value, 5)
            shapes[name] = shape

        check_panel(doc, "BaseLower", (0, 0, 0, 100, 100, 5), 50_000)
        check_panel(doc, "BaseUpper", (0, 0, 5, 100, 100, 10), 50_000)
        check_contact(doc, shapes["BaseLower"], shapes["BaseUpper"])
        check_contact(doc, shapes["AngledInner"], shapes["AngledOuter"])
        check_contact(doc, shapes["BaseUpper"], shapes["AngledInner"])
        seam = ((0, 0, 10), (100, 0, 10))
        assert _has_edge(shapes["BaseUpper"], *seam)
        assert _has_edge(shapes["AngledInner"], *seam)

        for index, first in enumerate(names):
            for second in names[index + 1:]:
                assert close(shapes[first].common(shapes[second]).Volume, 0), (
                    f"Acute2: {first} overlaps {second}"
                )
        for first, second in (
            ("BaseLower", "BaseUpper"),
            ("AngledInner", "AngledOuter"),
        ):
            laminated = shapes[first].fuse(shapes[second])
            assert close(laminated.Volume, 100_000)
            assert laminated.isValid() and len(laminated.Solids) == 1
    finally:
        App.closeDocument(doc.Name)


def validate_angled_t2():
    path = FINGER_JOINT_DIR / "AngledT2.FCStd"
    names = ("BaseLower", "BaseUpper", "AngledInner", "AngledOuter")
    check_saved_visibility(path, names)
    doc = App.openDocument(str(path))
    try:
        assert len(doc.findObjects("PartDesign::Body")) == 4
        shapes = {}
        for name in names:
            body = doc.getObject(name)
            assert body is not None and body.Tip is not None
            shape = body.Shape
            assert shape.isValid() and len(shape.Solids) == 1
            assert close(shape.Volume, 50_000)
            assert close(body.Tip.PanelThickness.Value, 5)
            shapes[name] = shape

        check_panel(doc, "BaseLower", (0, 0, 0, 100, 100, 5), 50_000)
        check_panel(doc, "BaseUpper", (0, 0, 5, 100, 100, 10), 50_000)
        check_contact(doc, shapes["BaseLower"], shapes["BaseUpper"])
        check_contact(doc, shapes["AngledInner"], shapes["AngledOuter"])
        check_contact(doc, shapes["BaseUpper"], shapes["AngledInner"])
        seam = ((0, 50, 10), (100, 50, 10))
        assert _has_edge(shapes["AngledInner"], *seam)
        top = next(face for face in shapes["BaseUpper"].Faces
                   if close(face.CenterOfMass.z, 10) and close(face.Area, 10_000))
        seam_edge = next(edge for edge in shapes["AngledInner"].Edges
                         if _has_edge(edge, *seam))
        assert close(top.distToShape(seam_edge)[0], 0)
        for index, first in enumerate(names):
            for second in names[index + 1:]:
                assert close(shapes[first].common(shapes[second]).Volume, 0)

        base = shapes["BaseLower"].fuse(shapes["BaseUpper"])
        angled = shapes["AngledInner"].fuse(shapes["AngledOuter"])
        expected_base = Part.makeBox(100, 100, 10)
        expected_angled = Part.makeBox(100, 100, 10, App.Vector(0, 50, 10))
        expected_angled.rotate(App.Vector(0, 50, 10), App.Vector(1, 0, 0), 60)
        for actual, expected in ((base, expected_base), (angled, expected_angled)):
            assert actual.isValid() and len(actual.Solids) == 1
            assert close(actual.Volume, expected.Volume)
            assert close(actual.cut(expected).Volume, 0)
            assert close(expected.cut(actual).Volume, 0)
    finally:
        App.closeDocument(doc.Name)


def validate_pyramid():
    path = FINGER_JOINT_DIR / "Pyramid.FCStd"
    side_names = ("SouthFace", "EastFace", "NorthFace", "WestFace")
    names = ("BaseSquare", *side_names)
    check_saved_visibility(path, names)
    doc = App.openDocument(str(path))
    try:
        assert len(doc.findObjects("PartDesign::Body")) == 5
        base = check_panel(
            doc, "BaseSquare", (-50, -50, -5, 50, 50, 0), 50_000
        )
        corners = (
            (-50, -50, 0), (50, -50, 0),
            (50, 50, 0), (-50, 50, 0),
        )
        apex = (0, 0, 100)
        shapes = [base]
        triangle_area = 50 * math.hypot(100, 50)
        for index, name in enumerate(side_names):
            body = doc.getObject(name)
            assert body is not None and body.Tip is not None
            assert close(body.Tip.PanelThickness.Value, 5)
            shape = body.Shape
            assert shape.isValid() and len(shape.Solids) == 1
            assert close(shape.Volume, triangle_area * 5)
            vertices = (corners[index], corners[(index + 1) % 4], apex)
            inner_face = next(
                face for face in shape.Faces
                if len(face.Vertexes) == 3 and all(
                    any(_point_matches(vertex.Point, point) for vertex in face.Vertexes)
                    for point in vertices
                )
            )
            outer_face = next(face for face in shape.Faces
                              if len(face.Vertexes) == 3 and not face.isSame(inner_face))
            assert close(inner_face.distToShape(outer_face)[0], 5)
            first, second, tip = (App.Vector(*point) for point in vertices)
            outward = (second - first).cross(tip - first)
            outward.normalize()
            if outward.dot(App.Vector(0, 0, 25) - inner_face.CenterOfMass) > 0:
                outward = -outward
            assert close(
                (outer_face.CenterOfMass - inner_face.CenterOfMass).dot(outward), 5
            )
            shapes.append(shape)
        for index, first in enumerate(shapes):
            for second in shapes[index + 1:]:
                check_contact(doc, first, second)
    finally:
        App.closeDocument(doc.Name)


def validate_corner():
    doc = App.openDocument(str(FINGER_JOINT_DIR / "Corner.FCStd"))
    try:
        base = check_panel(doc, "BaseXY", (0, 0, 0, 100, 100, 10), 100_000)
        back = check_panel(doc, "BackXZ", (0, 0, 10, 100, 10, 100), 90_000)
        side = check_panel(doc, "SideYZ", (0, 10, 10, 10, 100, 100), 81_000)
        check_contact(doc, base, back)
        check_contact(doc, base, side)
        check_contact(doc, back, side)
    finally:
        App.closeDocument(doc.Name)


def validate_mismatched():
    doc = App.openDocument(str(FINGER_JOINT_DIR / "Mismatched.FCStd"))
    try:
        side = check_panel(doc, "DrawerSideXZ", (0, 0, 0, 100, 10, 30), 30_000)
        front = check_panel(doc, "DrawerFrontYZ", (100, 0, 0, 110, 100, 60), 60_000)
        check_contact(doc, side, front)
    finally:
        App.closeDocument(doc.Name)


def validate_t():
    doc = App.openDocument(str(FINGER_JOINT_DIR / "T.FCStd"))
    try:
        cross = check_panel(
            doc, "CrossPanelXZ", (0, 0, 0, 100, 10, 100), 100_000
        )
        stem = check_panel(
            doc, "StemPanelYZ", (45, 10, 0, 55, 100, 100), 90_000
        )
        check_contact(doc, cross, stem)
    finally:
        App.closeDocument(doc.Name)


def validate_cycle():
    doc = App.openDocument(str(FINGER_JOINT_DIR / "Cycle.FCStd"))
    try:
        front = check_panel(doc, "FrontXZ", (0, 0, 0, 100, 10, 100), 100_000)
        right = check_panel(doc, "RightYZ", (100, 0, 0, 110, 100, 100), 100_000)
        back = check_panel(doc, "BackXZ", (10, 100, 0, 110, 110, 100), 100_000)
        left = check_panel(doc, "LeftYZ", (0, 10, 0, 10, 110, 100), 100_000)
        check_contact(doc, front, right)
        check_contact(doc, right, back)
        check_contact(doc, back, left)
        check_contact(doc, left, front)
        assert front.distToShape(back)[0] > 0
        assert right.distToShape(left)[0] > 0
    finally:
        App.closeDocument(doc.Name)


def validate_half_lap(name, angle, second_z):
    path = HALF_LAP_DIR / f"{name}.FCStd"
    check_saved_visibility(path, ("FirstPanel", "SecondPanel"))
    doc = App.openDocument(str(path))
    try:
        assert len(doc.findObjects("PartDesign::Body")) == 2
        first = doc.getObject("FirstPanel")
        second = doc.getObject("SecondPanel")
        expected_first = Part.makeBox(100, 10, 100, App.Vector(-50, -5, 0))
        expected_second = Part.makeBox(
            100, 10, 100, App.Vector(-50, -5, second_z)
        )
        expected_second.rotate(App.Vector(0, 0, 0), App.Vector(0, 0, 1), angle)
        for body, expected in ((first, expected_first), (second, expected_second)):
            assert body is not None and body.Tip is not None
            shape = body.Shape
            assert shape.isValid() and len(shape.Solids) == 1
            assert close(shape.Volume, 100_000)
            assert close(body.Tip.PanelThickness.Value, 10)
            assert close(shape.cut(expected).Volume, 0)
            assert close(expected.cut(shape).Volume, 0)
        overlap = first.Shape.common(second.Shape)
        assert overlap.isValid() and len(overlap.Solids) == 1
        assert overlap.Volume > 0
        expected_overlap = 100 * (100 - second_z) / math.sin(math.radians(angle))
        assert close(overlap.Volume, expected_overlap), (
            f"{name}: overlap {overlap.Volume}, expected {expected_overlap}"
        )
        assert close(overlap.BoundBox.ZMin, second_z)
        assert close(overlap.BoundBox.ZMax, 100)
    finally:
        App.closeDocument(doc.Name)


def validate_laminated_half_lap(name, angle):
    path = HALF_LAP_DIR / f"{name}.FCStd"
    first_names = ("FirstNegative", "FirstPositive")
    second_names = ("SecondNegative", "SecondPositive")
    check_saved_visibility(path, first_names + second_names)
    doc = App.openDocument(str(path))
    try:
        assert len(doc.findObjects("PartDesign::Body")) == 4
        shapes = {}
        for prefix, names in (("First", first_names), ("Second", second_names)):
            for name, local_y in zip(names, (-5, 0)):
                body = doc.getObject(name)
                assert body is not None and body.Tip is not None
                shape = body.Shape
                expected = Part.makeBox(
                    100, 5, 100, App.Vector(-50, local_y, 0)
                )
                if prefix == "Second":
                    expected.rotate(
                        App.Vector(0, 0, 0), App.Vector(0, 0, 1), angle
                    )
                assert shape.isValid() and len(shape.Solids) == 1
                assert close(shape.Volume, 50_000)
                assert close(body.Tip.PanelThickness.Value, 5)
                assert close(shape.cut(expected).Volume, 0)
                assert close(expected.cut(shape).Volume, 0)
                shapes[name] = shape
        for names in (first_names, second_names):
            assert close(shapes[names[0]].common(shapes[names[1]]).Volume, 0)
            laminated = shapes[names[0]].fuse(shapes[names[1]])
            assert laminated.isValid() and len(laminated.Solids) == 1
            assert close(laminated.Volume, 100_000)
        for first_name in first_names:
            for second_name in second_names:
                assert shapes[first_name].common(shapes[second_name]).Volume > 0
    finally:
        App.closeDocument(doc.Name)


def validate_hash():
    path = HALF_LAP_DIR / "#.FCStd"
    xz_names = ("XZNegativeY", "XZPositiveY")
    yz_names = ("YZNegativeX", "YZPositiveX")
    check_saved_visibility(path, xz_names + yz_names)
    doc = App.openDocument(str(path))
    try:
        assert len(doc.findObjects("PartDesign::Body")) == 4
        shapes = {
            "XZNegativeY": check_panel(
                doc, "XZNegativeY", (-50, -35, 0, 50, -25, 100), 100_000
            ),
            "XZPositiveY": check_panel(
                doc, "XZPositiveY", (-50, 25, 0, 50, 35, 100), 100_000
            ),
            "YZNegativeX": check_panel(
                doc, "YZNegativeX", (-35, -50, 0, -25, 50, 100), 100_000
            ),
            "YZPositiveX": check_panel(
                doc, "YZPositiveX", (25, -50, 0, 35, 50, 100), 100_000
            ),
        }
        for names in (xz_names, yz_names):
            assert shapes[names[0]].common(shapes[names[1]]).Volume <= TOLERANCE
        for xz_name in xz_names:
            for yz_name in yz_names:
                overlap = shapes[xz_name].common(shapes[yz_name])
                assert overlap.isValid() and len(overlap.Solids) == 1
                assert close(overlap.Volume, 10_000)
    finally:
        App.closeDocument(doc.Name)


validate_angled("Acute", 60, 0)
validate_acute2()
validate_angled("Obtuse", 120, 0)
validate_angled("Edge90", 90, 0)
validate_angled("AngledT", 60, 50)
validate_angled_t2()
validate_pyramid()
validate_corner()
validate_cycle()
validate_mismatched()
validate_t()
validate_half_lap("X", 90, 0)
validate_laminated_half_lap("X2", 90)
validate_half_lap("AngledX", 60, 0)
validate_laminated_half_lap("AngledX2", 60)
validate_half_lap("PartialX", 90, 50)
validate_hash()
print("Fixture geometry is valid.")
