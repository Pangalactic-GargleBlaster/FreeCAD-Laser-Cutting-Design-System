"""Read-only geometry checks for the immutable fixture documents."""

from pathlib import Path

import FreeCAD as App


FIXTURE_DIR = Path(__file__).resolve().parent.parent / "fixtures"
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


def validate_corner():
    doc = App.openDocument(str(FIXTURE_DIR / "Corner.FCStd"))
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
    doc = App.openDocument(str(FIXTURE_DIR / "Mismatched.FCStd"))
    try:
        side = check_panel(doc, "DrawerSideXZ", (0, 0, 0, 100, 10, 30), 30_000)
        front = check_panel(doc, "DrawerFrontYZ", (100, 0, 0, 110, 100, 60), 60_000)
        check_contact(doc, side, front)
    finally:
        App.closeDocument(doc.Name)


def validate_t():
    doc = App.openDocument(str(FIXTURE_DIR / "T.FCStd"))
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
    doc = App.openDocument(str(FIXTURE_DIR / "Cycle.FCStd"))
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


validate_corner()
validate_cycle()
validate_mismatched()
validate_t()
print("Fixture geometry is valid.")
