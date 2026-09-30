"""Headless FreeCAD integration tests for the half-lap command's geometry."""

import shutil
import sys
import tempfile
from pathlib import Path

import FreeCAD as App
import Part


PROJECT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_DIR / "freecad" / "DesignSystem"))

from finger_joint import JointValidationError, _body_and_base  # noqa: E402
from half_lap import HalfLapFaceRequired, create_half_lap, solve_half_lap  # noqa: E402


def end_face(body, z=0):
    base = body.Tip
    name = next(
        f"Face{index}"
        for index, face in enumerate(base.Shape.Faces, start=1)
        if abs(face.CenterOfMass.z - z) < 1e-7
        and abs(abs(face.normalAt(0, 0).z) - 1) < 1e-7
    )
    return base, name


def expect_validation_error(callback):
    try:
        callback()
    except JointValidationError:
        return
    raise AssertionError("Expected a joint validation error")


def test_fixture(name, first_names, second_names, anchor_name, temp_dir,
                 expected_radius=10):
    source = PROJECT_DIR / "fixtures" / "half-lap" / f"{name}.FCStd"
    path = Path(temp_dir) / f"{name}.FCStd"
    shutil.copy2(source, path)
    doc = App.openDocument(str(path))
    try:
        first = [doc.getObject(item) for item in first_names]
        second = [doc.getObject(item) for item in second_names]
        face = end_face(doc.getObject(anchor_name)) if anchor_name else None
        if anchor_name:
            try:
                solve_half_lap(first, second, 0)
            except HalfLapFaceRequired:
                pass
            else:
                raise AssertionError("Aligned panels must request an end face")
        zero_radius = solve_half_lap(first, second, 0, face)
        if name in ("X", "AngledX", "PartialX"):
            low_z, high_z = ((60, 90) if name == "PartialX" else (25, 75))
            assert zero_radius[first[0]].isInside(
                App.Vector(0, 0, low_z), 1e-7, False
            )
            assert not zero_radius[first[0]].isInside(
                App.Vector(0, 0, high_z), 1e-7, False
            )
            assert not zero_radius[second[0]].isInside(
                App.Vector(0, 0, low_z), 1e-7, False
            )
            assert zero_radius[second[0]].isInside(
                App.Vector(0, 0, high_z), 1e-7, False
            )
        plan, results = create_half_lap(first, second, intact_face=face)
        assert len(results) == len(first) + len(second)
        assert abs(plan.FilletRadius.Value - expected_radius) < 1e-7
        assert "MinimumThickness" in dict(plan.ExpressionEngine)["FilletRadius"]
        for body, result in zip(first + second, results):
            assert body.Tip is result
            assert result.Shape.isValid() and len(result.Shape.Solids) == 1
            assert result.Shape.Volume < zero_radius[body].Volume
        for index, result in enumerate(results):
            for other in results[index + 1:]:
                assert result.Shape.common(other.Shape).Volume < 1e-7
        plan.setExpression("FilletRadius", None)
        plan.FilletRadius = 0
        doc.recompute()
        for body, result in zip(first + second, results):
            assert abs(result.Shape.Volume - zero_radius[body].Volume) < 1e-5
        doc.save()
    finally:
        App.closeDocument(doc.Name)
    reopened = App.openDocument(str(path))
    try:
        reopened.recompute()
        results = [obj for obj in reopened.Objects
                   if obj.Name.startswith("HalfLapResult")]
        assert len(results) == len(first_names) + len(second_names)
        assert all(result.Shape.isValid() and len(result.Shape.Solids) == 1
                   and "Invalid" not in result.State for result in results)
    finally:
        App.closeDocument(reopened.Name)


def test_rejects_non_panel():
    doc = App.newDocument("HalfLapNonPanel")
    try:
        body = doc.addObject("PartDesign::Body", "Cube")
        solid = body.newObject("PartDesign::Feature", "CubeSolid")
        solid.Shape = Part.makeBox(100, 100, 100)
        body.Tip = solid
        expect_validation_error(lambda: _body_and_base(body, "source"))
    finally:
        App.closeDocument(doc.Name)


def test_default_radius_tracks_thinnest_panel(temp_dir):
    source = PROJECT_DIR / "fixtures" / "half-lap" / "X.FCStd"
    path = Path(temp_dir) / "ThinX.FCStd"
    shutil.copy2(source, path)
    doc = App.openDocument(str(path))
    try:
        first = doc.getObject("FirstPanel")
        second = doc.getObject("SecondPanel")
        original = second.Tip.Shape.copy()
        thinner = Part.makeBox(100, 5, 100, App.Vector(-50, -2.5, 0))
        thinner.rotate(App.Vector(0, 0, 0), App.Vector(0, 0, 1), 90)
        second.Tip.Shape = thinner
        doc.recompute()
        plan, results = create_half_lap(
            (first,), (second,), intact_face=end_face(first)
        )
        assert abs(plan.FilletRadius.Value - 5) < 1e-7
        assert all(result.Shape.isValid() for result in results)
        second.Tip.InputFeature.Shape = original
        doc.recompute()
        assert abs(plan.FilletRadius.Value - 10) < 1e-7
        assert all(result.Shape.isValid() for result in results)
    finally:
        App.closeDocument(doc.Name)


def test_set_overlap_rules(temp_dir):
    source = PROJECT_DIR / "fixtures" / "half-lap" / "X.FCStd"
    path = Path(temp_dir) / "SetRules.FCStd"
    shutil.copy2(source, path)
    doc = App.openDocument(str(path))
    try:
        first = doc.getObject("FirstPanel")
        second = doc.getObject("SecondPanel")
        far = doc.addObject("PartDesign::Body", "FarPanel")
        feature = far.newObject("PartDesign::Feature", "FarPanelSolid")
        feature.Shape = Part.makeBox(100, 10, 100, App.Vector(1000, 0, 0))
        far.Tip = feature
        expect_validation_error(
            lambda: solve_half_lap((first, second), (far,), 0)
        )
        expect_validation_error(
            lambda: solve_half_lap((first, far), (second,), 0)
        )
    finally:
        App.closeDocument(doc.Name)


def test_mixed_seam_directions():
    doc = App.newDocument("HalfLapMixedSeams")
    try:
        def panel(name, shape):
            body = doc.addObject("PartDesign::Body", name)
            feature = body.newObject("PartDesign::Feature", name + "Solid")
            feature.Shape = shape
            body.Tip = feature
            return body

        first = panel("First", Part.makeBox(100, 10, 100, App.Vector(-50, -5, 0)))
        vertical = panel(
            "Vertical", Part.makeBox(10, 50, 100, App.Vector(-35, -50, 0))
        )
        horizontal = panel(
            "Horizontal", Part.makeBox(100, 50, 10, App.Vector(0, 0, 45))
        )
        results = solve_half_lap(
            (first,), (vertical, horizontal), 10, end_face(first)
        )
        assert len(results) == 3
        assert all(shape.isValid() and len(shape.Solids) == 1
                   for shape in results.values())
        assert all(results[first].common(results[other]).Volume < 1e-7
                   for other in (vertical, horizontal))
    finally:
        App.closeDocument(doc.Name)


with tempfile.TemporaryDirectory(prefix="half-lap-tests-") as temp_dir:
    test_fixture("X", ("FirstPanel",), ("SecondPanel",), "FirstPanel", temp_dir)
    test_fixture("X2", ("FirstNegative", "FirstPositive"),
                 ("SecondNegative", "SecondPositive"), "FirstNegative",
                 temp_dir, expected_radius=5)
    test_fixture("AngledX", ("FirstPanel",), ("SecondPanel",), "FirstPanel", temp_dir)
    test_fixture("AngledX2", ("FirstNegative", "FirstPositive"),
                 ("SecondNegative", "SecondPositive"), "FirstNegative",
                 temp_dir, expected_radius=5)
    test_fixture("PartialX", ("FirstPanel",), ("SecondPanel",), None, temp_dir)
    test_fixture("#", ("XZNegativeY", "XZPositiveY"),
                 ("YZNegativeX", "YZPositiveX"), "XZNegativeY", temp_dir)
    test_rejects_non_panel()
    test_default_radius_tracks_thinnest_panel(temp_dir)
    test_set_overlap_rules(temp_dir)
    test_mixed_seam_directions()

print("Half-lap integration tests passed.")
