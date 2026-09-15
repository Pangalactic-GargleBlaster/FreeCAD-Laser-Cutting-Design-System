"""Open and close the Finger Joint task panel in a real FreeCAD GUI process."""

import sys
from pathlib import Path

import FreeCAD as App
import FreeCADGui as Gui
import Part
from PySide import QtCore


PROJECT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_DIR / "freecad" / "DesignSystem"))

from finger_joint_command import FingerJointTaskPanel  # noqa: E402


if Gui.Control.activeDialog():
    Gui.Control.closeDialog()
doc = App.newDocument("FingerJointGuiSmoke")
receiver = doc.addObject("PartDesign::Body", "Receiver")
receiver_feature = receiver.newObject("PartDesign::Feature", "ReceiverFeature")
receiver_feature.Shape = Part.makeBox(10, 10, 10)
panel = FingerJointTaskPanel()
Gui.Control.showDialog(panel)
App.Console.PrintMessage("Finger Joint GUI smoke panel opened\n")
panel._begin_pick("receiver")
assert panel.selection_gate.allow(doc.Name, receiver_feature, "Face1")
panel.addSelection(doc.Name, receiver_feature.Name, "Face1")
assert not receiver.ViewObject.Visibility
panel._receiver_shortcuts[0].activated.emit()
assert panel.pick_mode == "face"
assert not receiver.ViewObject.Visibility
assert not panel.receiver_overshoot.isEnabled()
assert not panel.receiver_radius.isEnabled()
panel.count.setValue(3)
panel._validated_geometry()
assert int(panel.parameters.FingerCount) == 3
for name, widget in (
    ("FingerCount", panel.count),
    ("Overshoot", panel.overshoot),
    ("FilletRadius", panel.radius),
    ("ReceiverOvershoot", panel.receiver_overshoot),
    ("ReceiverFilletRadius", panel.receiver_radius),
):
    App.Console.PrintMessage(
        f"{name}: {widget.metaObject().className()}, "
        f"{len(widget.actions())} expression action(s)\n"
    )


def finish():
    panel.reject()
    assert receiver.ViewObject.Visibility
    App.closeDocument(doc.Name)
    App.Console.PrintMessage("Finger Joint GUI smoke panel closed\n")
    Gui.getMainWindow().close()


def capture():
    panel.form.grab().save("/tmp/design-system-finger-joint-panel.png")


QtCore.QTimer.singleShot(250, capture)
QtCore.QTimer.singleShot(1000, finish)
