"""Exercise multi-face selection and joint creation in the FreeCAD task panel."""

import sys
from math import cos, radians, sin
from pathlib import Path

import FreeCAD as App
import FreeCADGui as Gui


PROJECT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_DIR / "freecad" / "DesignSystem"))

from finger_joint_command import FingerJointTaskPanel  # noqa: E402


doc = App.openDocument(str(PROJECT_DIR / "fixtures" / "finger joint" / "Acute2.FCStd"))
panel = FingerJointTaskPanel()
Gui.Control.showDialog(panel)
panel._begin_pick("receiver")
for name in ("BaseLower", "BaseUpper"):
    body = doc.getObject(name)
    panel.addSelection(doc.Name, body.Name, "")
panel._finish_receiver_pick()
assert panel.pick_mode == "face"

normal = App.Vector(0, -cos(radians(60)), -sin(radians(60)))
for index, name in enumerate(("AngledInner", "AngledOuter"), start=1):
    body = doc.getObject(name)
    feature = body.Tip
    face_name = next(
        f"Face{number}"
        for number, face in enumerate(feature.Shape.Faces, start=1)
        if face.normalAt(0, 0).dot(normal) > 1 - 1e-7
    )
    panel.addSelection(doc.Name, feature.Name, face_name)
    assert panel.pick_mode == "face"
    assert len(panel.source_faces) == index
    assert body.ViewObject.Visibility

panel._receiver_shortcuts[0].activated.emit()
assert panel.pick_mode is None
assert panel.create_button.isEnabled(), panel.status.text()
panel._create()
plan = doc.getObject("FingerJointGroup")
assert plan is not None
assert plan.SourceCount == 2 and plan.ReceivingCount == 2
inputs = doc.getObject("FingerJointGroupInputs")
assert inputs is not None
assert not inputs.ViewObject.Visibility
if hasattr(inputs.ViewObject, "ShowInTree"):
    assert not inputs.ViewObject.ShowInTree
results = [obj for obj in doc.Objects if obj.Name.startswith("FingerJointGroupResult")]
assert len(results) == 4
assert all(result.Shape.isValid() and len(result.Shape.Solids) == 1
           for result in results)
assert all(result.ViewObject.Proxy is not None for result in results)
assert all(result.getParentGeoFeatureGroup().ViewObject.Visibility
           and result.ViewObject.Visibility for result in results)
for result in results:
    result.ViewObject.Visibility = False
    result.ViewObject.Visibility = True
    assert result.ViewObject.Visibility
assert all(results[i].Shape.common(results[j].Shape).Volume <= 1e-7
           for i in range(len(results)) for j in range(i + 1, len(results)))
App.Console.PrintMessage("Finger Joint group GUI smoke passed\n")
App.closeDocument(doc.Name)
