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

panel.reject()
assert receiver.ViewObject.Visibility
App.closeDocument(doc.Name)

# An invalid default radius must not disable controls needed to correct it,
# and changing a formula must trigger validation even though FreeCAD's
# ExpressionBinding does not emit the spinbox editing signals.
mismatched = App.openDocument(str(PROJECT_DIR / "fixtures" / "Mismatched.FCStd"))
mismatched_panel = FingerJointTaskPanel()
Gui.Control.showDialog(mismatched_panel)
mismatched_panel._begin_pick("receiver")
mismatched_panel.addSelection(mismatched.Name, mismatched.Body.Name, "")
mismatched_panel.addSelection(mismatched.Name, mismatched.DrawerFrontYZ.Name, "")
mismatched_panel._finish_receiver_pick()
mismatched_panel.addSelection(
    mismatched.Name, mismatched.DrawerSideXZSolid.Name, "Face2"
)
assert mismatched_panel.pick_mode is None
assert mismatched_panel.first_edge is not None
assert not mismatched_panel.create_button.isEnabled()
assert mismatched_panel.receiver_overshoot.isEnabled()
assert mismatched_panel.receiver_radius.isEnabled()

mismatched_panel.parameters.setExpression(
    "FilletRadius", "SelectedEdgeLength / 5"
)
mismatched_panel.parameters.setExpression(
    "ReceiverFilletRadius", "ReceiverThickness / 10"
)
assert mismatched_panel._expression_update_pending
mismatched_panel._run_scheduled_update()
assert mismatched_panel.create_button.isEnabled()
assert mismatched_panel.status.text().startswith("Ready")


def finish():
    mismatched_panel.reject()
    App.closeDocument(mismatched.Name)
    App.Console.PrintMessage("Finger Joint GUI smoke panel closed\n")
    Gui.getMainWindow().close()


def capture():
    mismatched_panel.form.grab().save("/tmp/design-system-finger-joint-panel.png")


QtCore.QTimer.singleShot(250, capture)
QtCore.QTimer.singleShot(1000, finish)
