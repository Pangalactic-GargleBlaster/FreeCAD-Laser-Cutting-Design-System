"""Exercise finger joints followed by half-laps on the Combination fixture."""

import shutil
import sys
import tempfile
from pathlib import Path

import FreeCAD as App


PROJECT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_DIR / "freecad" / "DesignSystem"))

from finger_joint import create_joint  # noqa: E402
from half_lap import create_half_lap  # noqa: E402


def test_combination():
    source = PROJECT_DIR / "fixtures" / "Combination.FCStd"
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / source.name
        shutil.copy2(source, path)
        doc = App.openDocument(str(path))
        try:
            base = doc.getObject("Body")
            binders = [doc.getObject(name) for name in
                       ("Binder", "Binder001", "Binder002", "Binder003")]
            original_shapes = [binder.Shape.copy() for binder in binders]
            for name in ("Body002", "Body001", "Body003", "Body004"):
                panel = doc.getObject(name)
                create_joint(panel.Tip, "Face5", base, 1)
                doc.recompute()
                assert base.Shape.isValid() and len(base.Shape.Solids) == 1
                assert panel.Shape.isValid() and len(panel.Shape.Solids) == 1
            for binder, original in zip(binders, original_shapes):
                assert binder.Support[0][0] is doc.getObject("Pad")
                assert binder.Shape.distToShape(original)[0] < 1e-7

            first = [doc.getObject(name) for name in ("Body001", "Body002")]
            second = [doc.getObject(name) for name in ("Body003", "Body004")]
            face_name = next(
                f"Face{index}" for index, face in enumerate(first[0].Tip.Shape.Faces, 1)
                if abs(face.CenterOfMass.z - 55) < 1e-7
                and face.normalAt(0, 0).z > 0.99
            )
            create_half_lap(first, second, intact_face=(first[0].Tip, face_name))
            doc.recompute()
            for body in (base, *first, *second):
                assert body.Shape.isValid() and len(body.Shape.Solids) == 1
                assert "Invalid" not in body.Tip.State
            doc.save()
        finally:
            App.closeDocument(doc.Name)

        reopened = App.openDocument(str(path))
        try:
            reopened.recompute()
            for name in ("Body", "Body001", "Body002", "Body003", "Body004"):
                body = reopened.getObject(name)
                assert body.Shape.isValid() and len(body.Shape.Solids) == 1
                assert "Invalid" not in body.Tip.State
        finally:
            App.closeDocument(reopened.Name)


test_combination()
print("Combination integration test passed.")
