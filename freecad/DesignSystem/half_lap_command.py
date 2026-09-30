"""Guided FreeCAD task panel for creating a half-lap joint."""

import FreeCAD as App
import FreeCADGui as Gui
from PySide import QtCore, QtGui, QtWidgets

from finger_joint import JointValidationError, _body_and_base, show_body_tips
from half_lap import HalfLapFaceRequired, create_half_lap, solve_half_lap
from joint_group import broad_planes


_active_panel = None


def _body(obj):
    if obj.TypeId == "PartDesign::Body":
        return obj
    parent = obj.getParentGeoFeatureGroup()
    return parent if parent is not None and parent.TypeId == "PartDesign::Body" else None


class HalfLapSelectionGate:
    def __init__(self, mode):
        self.mode = mode

    def allow(self, doc, obj, sub_name):
        if self.mode == "face":
            body = _body(obj)
            return (body is not None and obj in (body, body.Tip)
                    and sub_name.startswith("Face"))
        return _body(obj) is not None


class HalfLapTaskPanel:
    def __init__(self):
        self.doc = App.ActiveDocument
        self.doc.openTransaction("Configure half-lap")
        self._transaction_open = True
        self.parameters = self.doc.addObject(
            "App::FeaturePython", "HalfLapDialogParameters"
        )
        self.parameters.Label = "Half Lap parameters"
        self.parameters.addProperty("App::PropertyLength", "MinimumThickness", "Internal")
        self.parameters.addProperty("App::PropertyLength", "FilletRadius", "Parameters")
        self.parameters.MinimumThickness = 0
        self.parameters.FilletRadius = 0
        self.parameters.setExpression("FilletRadius", "MinimumThickness")
        self.parameters.setEditorMode("MinimumThickness", 2)
        self.parameters.ViewObject.Visibility = False
        if hasattr(self.parameters.ViewObject, "ShowInTree"):
            self.parameters.ViewObject.ShowInTree = False

        self.first = []
        self.second = []
        self.intact_face = None
        self.pick_mode = None
        self.selection_gate = None
        self.hidden = {}
        self._syncing = False
        self._expression_changed = False
        self.form = QtWidgets.QWidget()
        self.form.setWindowTitle("Half Lap")
        self._timer = QtCore.QTimer(self.form)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._update_state)
        self._build_form()
        self.shortcuts = []
        for key in ("Return", "Enter"):
            shortcut = QtGui.QShortcut(QtGui.QKeySequence(key), self.form)
            shortcut.setContext(QtCore.Qt.ApplicationShortcut)
            shortcut.activated.connect(self._finish_pick)
            self.shortcuts.append(shortcut)
        Gui.Selection.addObserver(self)
        App.addDocumentObserver(self)
        Gui.Selection.clearSelection()
        self._update_state()

    def _build_form(self):
        layout = QtWidgets.QVBoxLayout(self.form)
        intro = QtWidgets.QLabel(
            "Select the two panel sets. For aligned panels, select an overlap "
            "end face to leave intact, then set the slot-mouth fillet radius."
        )
        intro.setWordWrap(True)
        layout.addWidget(intro)
        self.first_value = self._add_picker(
            layout, "1. First set of bodies", "first", "Select bodies…"
        )
        self.second_value = self._add_picker(
            layout, "2. Second set of bodies", "second", "Select bodies…"
        )
        self.face_value = self._add_picker(
            layout, "3. Face to leave intact when aligned", "face", "Select face…"
        )
        radius_row = QtWidgets.QHBoxLayout()
        radius_row.addWidget(QtWidgets.QLabel("4. Fillet radius"))
        self.radius = Gui.UiLoader().createWidget("Gui::QuantitySpinBox")
        self.radius.setProperty("minimum", 0.0)
        self.radius.setProperty("maximum", 1_000_000.0)
        self.radius_binding = Gui.ExpressionBinding(self.radius)
        self.radius_binding.bind(self.parameters, "FilletRadius")
        self.radius.valueChanged.connect(self._schedule_update)
        self.radius.editingFinished.connect(self._update_state)
        radius_row.addWidget(self.radius)
        layout.addLayout(radius_row)
        self.prompt = QtWidgets.QLabel("")
        self.prompt.setWordWrap(True)
        layout.addWidget(self.prompt)
        self.status = QtWidgets.QLabel("")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        buttons = QtWidgets.QHBoxLayout()
        self.create_button = QtWidgets.QPushButton("Create Half Lap")
        self.create_button.clicked.connect(self._create)
        cancel = QtWidgets.QPushButton("Cancel")
        cancel.clicked.connect(self.reject)
        buttons.addWidget(self.create_button)
        buttons.addWidget(cancel)
        layout.addLayout(buttons)
        layout.addStretch()

    def _add_picker(self, layout, label, mode, text):
        layout.addWidget(QtWidgets.QLabel(label))
        row = QtWidgets.QHBoxLayout()
        value = QtWidgets.QLineEdit("Not selected")
        value.setReadOnly(True)
        button = QtWidgets.QPushButton(text)
        button.clicked.connect(lambda checked=False: self._picker_clicked(mode))
        setattr(self, f"{mode}_button", button)
        row.addWidget(value, 1)
        row.addWidget(button)
        layout.addLayout(row)
        return value

    def _picker_clicked(self, mode):
        if self.pick_mode == mode:
            self._finish_pick()
        else:
            self._begin_pick(mode)

    def _begin_pick(self, mode):
        self._remove_gate()
        self.pick_mode = mode
        if mode == "first":
            self._restore_visibility()
            self.first = []
            self.first_value.setText("Not selected")
        elif mode == "second":
            self.second = []
            self.second_value.setText("Not selected")
            for body in self.first:
                if body not in self.hidden:
                    self.hidden[body] = body.ViewObject.Visibility
                body.ViewObject.Visibility = False
        if mode in ("first", "second"):
            self.intact_face = None
            self.face_value.setText("Not selected")
        else:
            self._restore_visibility()
            self.intact_face = None
            self.face_value.setText("Not selected")
        buttons = (self.first_button, self.second_button, self.face_button)
        for button in buttons:
            button.setText("Picking…" if button is getattr(self, f"{mode}_button")
                           else ("Select face…" if button is self.face_button
                                 else "Select bodies…"))
        prompt = {
            "first": "Select each body in the first set, then press Enter.",
            "second": "Select each body in the second set, then press Enter.",
            "face": "Select one end face of an overlap to leave intact.",
        }
        self.prompt.setText(prompt[mode])
        self.prompt.setStyleSheet("color: #2060a0;")
        Gui.Selection.clearSelection()
        self.selection_gate = HalfLapSelectionGate(mode)
        Gui.Selection.addSelectionGate(self.selection_gate)
        Gui.activeDocument().activeView().redraw()

    def _finish_pick(self):
        mode = self.pick_mode
        if mode is None:
            return
        if mode == "first" and not self.first:
            self._error("Select at least one body in the first set.")
            return
        if mode == "second" and not self.second:
            self._error("Select at least one body in the second set.")
            return
        if mode == "face" and self.intact_face is None:
            self._error("Select one overlap end face.")
            return
        self.pick_mode = None
        self._remove_gate()
        getattr(self, f"{mode}_button").setText(
            "Change face…" if mode == "face" else "Change bodies…"
        )
        self.prompt.setText("")
        Gui.Selection.clearSelection()
        if mode == "first":
            self._begin_pick("second")
        elif mode == "second":
            self._restore_visibility()
            self.parameters.MinimumThickness = min(
                broad_planes(body.Tip.Shape).thickness
                for body in self.first + self.second
            )
            self.doc.recompute()
            self.radius.setProperty("value", self.parameters.FilletRadius)
            try:
                solve_half_lap(self.first, self.second, 0)
            except HalfLapFaceRequired:
                self._begin_pick("face")
            except JointValidationError:
                self.radius.setFocus()
                self._update_state()
            else:
                self.radius.setFocus()
                self._update_state()
        else:
            self.radius.setFocus()
            self._update_state()

    def addSelection(self, document_name, object_name, sub_name, *args):
        mode = self.pick_mode
        if mode is None:
            return
        doc = App.getDocument(document_name)
        obj = doc.getObject(object_name)
        body = _body(obj)
        if body is None:
            self._error("Select a Part Design body or one of its faces.")
            return
        try:
            _body_and_base(body, "half-lap")
        except JointValidationError as error:
            self._error(str(error))
            return
        if mode == "face":
            if (body not in self.first + self.second or obj not in (body, body.Tip)
                    or not sub_name.startswith("Face")):
                self._error("Select a face on one of the chosen panels.")
                return
            base = body.Tip
            try:
                solve_half_lap(
                    self.first, self.second, 0, (base, sub_name)
                )
            except JointValidationError as error:
                self._error(str(error))
                return
            self.intact_face = (base, sub_name)
            self.face_value.setText(f"{body.Label} · {sub_name}")
            self._finish_pick()
            return
        group = self.first if mode == "first" else self.second
        if body in group:
            self._error("That body is already selected.")
            return
        if mode == "second" and body in self.first:
            self._error("A body cannot belong to both sets.")
            return
        group.append(body)
        if mode in ("first", "second"):
            self.hidden[body] = body.ViewObject.Visibility
            body.ViewObject.Visibility = False
        value = self.first_value if mode == "first" else self.second_value
        value.setText(", ".join(item.Label for item in group))
        getattr(self, f"{mode}_button").setText(f"Done ({len(group)})")
        self.prompt.setText("Select another body, or press Enter.")
        Gui.Selection.clearSelection()
        Gui.activeDocument().activeView().redraw()
        self._update_state()

    def _sync_radius(self):
        if self._syncing:
            return
        self._syncing = True
        try:
            expressions = dict(self.parameters.ExpressionEngine)
            if "FilletRadius" not in expressions:
                self.parameters.FilletRadius = self.radius.property("value")
            if self._expression_changed:
                self.doc.recompute()
                self._expression_changed = False
        finally:
            self._syncing = False

    def slotChangedObject(self, obj, property_name):
        if (obj is self.parameters and property_name == "ExpressionEngine"
                and not self._syncing):
            self._expression_changed = True
            self._schedule_update()

    def _schedule_update(self, *args):
        self._timer.start(150)

    def _update_state(self, *args):
        self._timer.stop()
        self._sync_radius()
        if self.pick_mode is not None:
            self.create_button.setEnabled(False)
            return
        if not self.first or not self.second:
            missing = "first set" if not self.first else "second set"
            self.status.setText(f"Still needed: {missing}.")
            self.status.setStyleSheet("color: #606060;")
            self.create_button.setEnabled(False)
            return
        try:
            solve_half_lap(
                self.first, self.second, self.parameters.FilletRadius.Value,
                self.intact_face,
            )
            self.status.setText(
                f"Ready — {len(self.first)} + {len(self.second)} panels; "
                f"fillet radius {self.parameters.FilletRadius.Value:g} mm."
            )
            self.status.setStyleSheet("color: #207020;")
            self.create_button.setEnabled(True)
        except JointValidationError as error:
            self.status.setText(str(error))
            self.status.setStyleSheet("color: #b03030;")
            self.create_button.setEnabled(False)

    def _create(self):
        self._timer.stop()
        self._sync_radius()
        if not self.create_button.isEnabled():
            return
        try:
            expressions = dict(self.parameters.ExpressionEngine)
            create_half_lap(
                self.first, self.second, self.parameters.FilletRadius,
                self.intact_face,
                fillet_radius_expression=expressions.get("FilletRadius"),
            )
            self._finish()
            Gui.Control.closeDialog()
            self.doc.removeObject(self.parameters.Name)
            self.doc.recompute()
            self.doc.commitTransaction()
            self._transaction_open = False
            show_body_tips(*(self.first + self.second))
            Gui.activeDocument().activeView().fitAll()
        except JointValidationError as error:
            self._error(str(error))
        except Exception as error:
            if self._transaction_open:
                self.doc.abortTransaction()
                self._transaction_open = False
            self._finish()
            Gui.Control.closeDialog()
            App.Console.PrintError(f"Half Lap failed: {error}\n")

    def _error(self, message):
        self.prompt.setText(message)
        self.prompt.setStyleSheet("color: #b03030;")
        Gui.Selection.clearSelection()

    def _restore_visibility(self):
        for body, visible in self.hidden.items():
            if body.Document is not None:
                body.ViewObject.Visibility = visible
        self.hidden.clear()
        if Gui.ActiveDocument is not None:
            Gui.activeDocument().activeView().redraw()

    def _remove_gate(self):
        if self.selection_gate is not None:
            Gui.Selection.removeSelectionGate()
            self.selection_gate = None

    def _finish(self):
        global _active_panel
        self._timer.stop()
        self._remove_gate()
        self._restore_visibility()
        Gui.Selection.removeObserver(self)
        App.removeDocumentObserver(self)
        Gui.Selection.clearSelection()
        _active_panel = None

    def getStandardButtons(self):
        return 0

    def reject(self):
        self._finish()
        Gui.Control.closeDialog()
        if self._transaction_open:
            self.doc.abortTransaction()
            self._transaction_open = False


class HalfLapCommand:
    def GetResources(self):
        return {
            "MenuText": "Half Lap",
            "ToolTip": "Create a rounded half-lap joint between two panel sets",
        }

    def IsActive(self):
        return App.ActiveDocument is not None and not Gui.Control.activeDialog()

    def Activated(self):
        global _active_panel
        _active_panel = HalfLapTaskPanel()
        Gui.Control.showDialog(_active_panel)
        _active_panel._begin_pick("first")


Gui.addCommand("DesignSystem_HalfLap", HalfLapCommand())
