"""Report positive-volume intersections between final Part Design body tips."""

import os
import sys

import FreeCAD as App


SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(SCRIPT_DIR)
MODULE_DIR = os.path.join(ROOT, "freecad", "DesignSystem")
if MODULE_DIR not in sys.path:
    sys.path.insert(0, MODULE_DIR)


TOLERANCE = 1e-6


def _boxes_overlap(first, second):
    return all(
        min(getattr(first, axis + "Max"), getattr(second, axis + "Max"))
        - max(getattr(first, axis + "Min"), getattr(second, axis + "Min"))
        > TOLERANCE
        for axis in "XYZ"
    )


def check(path):
    doc = App.openDocument(path)
    try:
        doc.recompute()
        bodies = [
            obj
            for obj in doc.Objects
            if obj.TypeId == "PartDesign::Body"
            and obj.Tip is not None
            and not obj.Tip.Shape.isNull()
        ]
        overlaps = []
        for index, first in enumerate(bodies):
            first_shape = first.Tip.Shape
            for second in bodies[index + 1 :]:
                second_shape = second.Tip.Shape
                if not _boxes_overlap(first_shape.BoundBox, second_shape.BoundBox):
                    continue
                volume = first_shape.common(second_shape).Volume
                if volume > TOLERANCE:
                    overlaps.append((first.Label, second.Label, volume))

        print(f"Checked {len(bodies)} final body shapes.")
        if overlaps:
            for first, second, volume in overlaps:
                print(f"OVERLAP {volume:g} mm^3: {first} <> {second}")
            raise RuntimeError(f"Found {len(overlaps)} overlapping body pairs.")
        print("No positive-volume body overlaps found.")
    finally:
        App.closeDocument(doc.Name)


if __name__ in ("__main__", "check_bed_overlaps"):
    requested_path = next(
        (argument for argument in sys.argv[1:] if argument.lower().endswith(".fcstd")),
        os.path.join(ROOT, "Bed.FCStd"),
    )
    check(requested_path)
