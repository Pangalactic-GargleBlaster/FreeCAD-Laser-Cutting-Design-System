"""Guided FreeCAD task panel for creating a finger joint."""

import FreeCAD as App
import FreeCADGui as Gui
from PySide import QtCore, QtGui, QtWidgets

from finger_joint import (
    JointValidationError,
    analyze_joint,
    automatic_edge_name,
    build_fingers,
    build_receiver_fingers,
    create_joint,
    receiver_fingers_applicable,
    show_body_tips,
)


_active_panel = None


def _base_feature(obj):
    if obj.TypeId == "PartDesign::Body":
        return obj.Tip
    return obj


def _body(obj):
    if obj.TypeId == "PartDesign::Body":
        return obj
    parent = obj.getParentGeoFeatureGroup()
    return parent if parent is not None and parent.TypeId == "PartDesign::Body" else None


class FingerJointSelectionGate:
    def __init__(self, panel, mode):
        self.panel = panel
        self.mode = mode

    def allow(self, doc, obj, sub_name):
        if self.mode == "face":
            return bool(sub_name and sub_name.startswith("Face") and hasattr(obj, "Shape"))
        if self.mode == "receiver":
            return _body(obj) is not None
        return False


class FingerJointTaskPanel:
    def __init__(self):
        self.doc = App.ActiveDocument
        self.doc.openTransaction("Configure finger joint")
        self._transaction_open = True
        self.parameters = self.doc.addObject(
            "App::FeaturePython", "FingerJointDialogParameters"
        )
        self.parameters.Label = "Finger Joint parameters"
        self.parameters.addProperty(
            "App::PropertyIntegerConstraint", "FingerCount", "Parameters"
        )
        self.parameters.addProperty(
            "App::PropertyLength", "SelectedEdgeLength", "Internal"
        )
        self.parameters.addProperty(
            "App::PropertyLength", "ReceiverThickness", "Internal"
        )
        self.parameters.addProperty("App::PropertyLength", "Overshoot", "Parameters")
        self.parameters.addProperty(
            "App::PropertyLength", "FilletRadius", "Parameters"
        )
        self.parameters.addProperty(
            "App::PropertyLength", "ReceiverOvershoot", "Parameters"
        )
        self.parameters.addProperty(
            "App::PropertyLength", "ReceiverFilletRadius", "Parameters"
        )
        self.parameters.FingerCount = (2, 1, 1000, 1)
        self.parameters.SelectedEdgeLength = 0
        self.parameters.ReceiverThickness = 0
        self.parameters.Overshoot = 0
        self.parameters.FilletRadius = 0
        self.parameters.ReceiverOvershoot = 0
        self.parameters.ReceiverFilletRadius = 0
        self.parameters.setExpression("Overshoot", "SelectedEdgeLength")
        self.parameters.setExpression("FilletRadius", "SelectedEdgeLength")
        self.parameters.setExpression("ReceiverOvershoot", "ReceiverThickness")
        self.parameters.setExpression("ReceiverFilletRadius", "0 mm")
        self.parameters.setEditorMode("SelectedEdgeLength", 2)
        self.parameters.setEditorMode("ReceiverThickness", 2)
        if hasattr(self.parameters.ViewObject, "ShowInTree"):
            self.parameters.ViewObject.ShowInTree = False
        self.parameters.ViewObject.Visibility = False
        self.doc.recompute()

        self.source_face = None
        self.first_edge = None
        self.receivers = []
        self.pick_mode = None
        self.selection_gate = None
        self._hidden_receiver_visibility = {}
        self._syncing_parameters = False
        self._receiver_parameters_applicable = False
        self._expression_bindings = []
        self.pick_buttons = {}
        self.form = QtWidgets.QWidget()
        self.form.setWindowTitle("Finger Joint")
        self._validation_timer = QtCore.QTimer(self.form)
        self._validation_timer.setSingleShot(True)
        self._validation_pending = False
        self._expression_update_pending = False
        self._validation_timer.timeout.connect(self._run_scheduled_update)
        self._build_form()
        self._install_receiver_shortcuts()
        Gui.Selection.addObserver(self)
        App.addDocumentObserver(self)
        Gui.Selection.clearSelection()
        self._update_state()

    def _build_form(self):
        layout = QtWidgets.QVBoxLayout(self.form)
        intro = QtWidgets.QLabel(
            "Choose each input separately. Click a Select button, then click "
            "the requested geometry in the model or tree."
        )
        intro.setWordWrap(True)
        layout.addWidget(intro)

        self.receiver_value = self._add_picker(
            layout, "1. Receiving bodies", "Select bodies…", "receiver"
        )
        self.face_value = self._add_picker(
            layout, "2. Source face", "Select face…", "face"
        )

        count_row = QtWidgets.QHBoxLayout()
        count_row.addWidget(QtWidgets.QLabel("3. Number of fingers"))
        self.count = Gui.UiLoader().createWidget("Gui::IntSpinBox")
        self.count.setRange(1, 1000)
        self.count.setValue(int(self.parameters.FingerCount))
        self._bind_expression(self.count, "FingerCount")
        self.count.valueChanged.connect(self._schedule_update_state)
        self.count.editingFinished.connect(self._update_state_now)
        count_row.addWidget(self.count)
        layout.addLayout(count_row)

        self.overshoot = self._add_length_input(layout, "4. Overshoot", "Overshoot")
        self.radius = self._add_length_input(
            layout, "5. Fillet radius", "FilletRadius"
        )
        self.receiver_overshoot = self._add_length_input(
            layout, "6. Receiving-panel overshoot", "ReceiverOvershoot"
        )
        self.receiver_radius = self._add_length_input(
            layout, "7. Receiving-panel fillet radius", "ReceiverFilletRadius"
        )

        self.prompt = QtWidgets.QLabel("")
        self.prompt.setWordWrap(True)
        layout.addWidget(self.prompt)

        self.status = QtWidgets.QLabel("")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)

        buttons = QtWidgets.QHBoxLayout()
        self.create_button = QtWidgets.QPushButton("Create Joint")
        self.create_button.clicked.connect(self._create)
        cancel_button = QtWidgets.QPushButton("Cancel")
        cancel_button.clicked.connect(self.reject)
        buttons.addWidget(self.create_button)
        buttons.addWidget(cancel_button)
        layout.addLayout(buttons)
        layout.addStretch()

    def _install_receiver_shortcuts(self):
        self._receiver_shortcuts = []
        for key in ("Return", "Enter"):
            shortcut = QtGui.QShortcut(QtGui.QKeySequence(key), self.form)
            shortcut.setContext(QtCore.Qt.ApplicationShortcut)
            shortcut.activated.connect(self._finish_receiver_if_picking)
            self._receiver_shortcuts.append(shortcut)

    def _finish_receiver_if_picking(self):
        if self.pick_mode == "receiver":
            self._finish_receiver_pick()

    def _add_picker(self, parent_layout, label, button_text, mode):
        parent_layout.addWidget(QtWidgets.QLabel(label))
        row = QtWidgets.QHBoxLayout()
        value = QtWidgets.QLineEdit("Not selected")
        value.setReadOnly(True)
        button = QtWidgets.QPushButton(button_text)
        button.clicked.connect(
            lambda checked=False, selected_mode=mode: self._picker_clicked(selected_mode)
        )
        self.pick_buttons[mode] = button
        row.addWidget(value, 1)
        row.addWidget(button)
        parent_layout.addLayout(row)
        return value

    def _picker_clicked(self, mode):
        if mode == "receiver" and self.pick_mode == "receiver":
            self._finish_receiver_pick()
        else:
            self._begin_pick(mode)

    def _bind_expression(self, widget, property_name):
        binding = Gui.ExpressionBinding(widget)
        binding.bind(self.parameters, property_name)
        self._expression_bindings.append(binding)

    def _add_length_input(self, parent_layout, label, property_name):
        row = QtWidgets.QHBoxLayout()
        row.addWidget(QtWidgets.QLabel(label))
        value = Gui.UiLoader().createWidget("Gui::QuantitySpinBox")
        value.setProperty("minimum", 0.0)
        value.setProperty("maximum", 1_000_000.0)
        value.setProperty("value", getattr(self.parameters, property_name))
        self._bind_expression(value, property_name)
        value.valueChanged.connect(self._schedule_update_state)
        value.editingFinished.connect(self._update_state_now)
        row.addWidget(value)
        parent_layout.addLayout(row)
        return value

    def _begin_pick(self, mode):
        self._remove_selection_gate()
        self.pick_mode = mode
        if mode == "receiver":
            self._restore_receiver_visibility()
            self.receivers = []
            self.receiver_value.setText("Not selected")
        prompts = {
            "face": "Click the rectangular face from which the fingers should protrude.",
            "receiver": "Click each receiving body in the scene or model tree, then click Done.",
        }
        labels = {
            "face": "Select face…",
            "receiver": "Select bodies…",
        }
        for key, button in self.pick_buttons.items():
            button.setText("Picking…" if key == mode else labels[key])
        self.prompt.setText(prompts[mode])
        self.prompt.setStyleSheet("color: #2060a0;")
        Gui.Selection.clearSelection()
        self.selection_gate = FingerJointSelectionGate(self, mode)
        Gui.Selection.addSelectionGate(self.selection_gate)

    def _finish_receiver_pick(self):
        if not self.receivers:
            self._selection_error("Select at least one receiving body.")
            return
        self.pick_mode = None
        self._remove_selection_gate()
        self.pick_buttons["receiver"].setText("Change bodies…")
        self.prompt.setText("")
        Gui.Selection.clearSelection()
        self._update_state()
        self._begin_pick("face")

    def addSelection(self, document_name, object_name, sub_name, *args):
        if self.pick_mode is None:
            return
        doc = App.getDocument(document_name)
        obj = doc.getObject(object_name)
        mode = self.pick_mode
        next_mode = None

        if mode == "face":
            if not sub_name.startswith("Face"):
                self._selection_error("Please click a face, not an edge or tree item.")
                return
            base = _base_feature(obj)
            self.source_face = (base, sub_name)
            self.face_value.setText(f"{base.Label} · {sub_name}")
            try:
                edge_name = automatic_edge_name(base, sub_name)
            except JointValidationError as error:
                self.source_face = None
                self.face_value.setText("Not selected")
                self._selection_error(str(error))
                return
            self.first_edge = (base, edge_name)
            edge_index = int(edge_name[4:]) - 1
            default_length = base.Shape.Edges[edge_index].Length
            self.parameters.SelectedEdgeLength = default_length
            self.doc.recompute()
            widgets = (
                (self.overshoot, self.parameters.Overshoot),
                (self.radius, self.parameters.FilletRadius),
                (self.receiver_overshoot, self.parameters.ReceiverOvershoot),
                (self.receiver_radius, self.parameters.ReceiverFilletRadius),
            )
            for widget, value in widgets:
                widget.blockSignals(True)
                widget.setProperty("value", value)
                widget.blockSignals(False)
        else:
            body = _body(obj)
            if body is None:
                self._selection_error("The receiving selection must be a Part Design body.")
                return
            if body not in self.receivers:
                self.receivers.append(body)
                self._hidden_receiver_visibility[body] = body.ViewObject.Visibility
                body.ViewObject.Visibility = False
            self.receiver_value.setText(", ".join(item.Label for item in self.receivers))
            self.pick_buttons["receiver"].setText(f"Done ({len(self.receivers)})")
            self.prompt.setText("Select another receiving body, or click Done / press Enter.")
            Gui.Selection.clearSelection()
            Gui.activeDocument().activeView().redraw()
            self._update_state()
            return

        self.pick_mode = None
        self._remove_selection_gate()
        labels = {
            "face": "Change face…",
            "receiver": "Change bodies…",
        }
        for key, button in self.pick_buttons.items():
            button.setText(labels[key])
        self.prompt.setText("")
        Gui.Selection.clearSelection()
        self._show_saved_selection()
        self._update_state()
        if next_mode is not None:
            self._begin_pick(next_mode)

    def _selection_error(self, message):
        self.prompt.setText(message)
        self.prompt.setStyleSheet("color: #b03030;")
        Gui.Selection.clearSelection()

    def _show_saved_selection(self):
        if self.source_face is not None:
            Gui.Selection.addSelection(
                self.source_face[0].Document.Name,
                self.source_face[0].Name,
                self.source_face[1],
            )
        for receiver in self.receivers:
            Gui.Selection.addSelection(receiver.Document.Name, receiver.Name)

    def _validated_geometry(self):
        self._sync_parameters_from_widgets()
        self._receiver_parameters_applicable = False
        if self.source_face is None or not self.receivers:
            return None
        geometry = analyze_joint(
            self.source_face[0],
            self.source_face[1],
            self.receivers,
            int(self.parameters.FingerCount),
        )
        # Determine this before validating radii so the receiving controls stay
        # available when an invalid default needs to be corrected.
        applicable = receiver_fingers_applicable(geometry)
        self._receiver_parameters_applicable = applicable
        self.receiver_overshoot.blockSignals(True)
        self.receiver_radius.blockSignals(True)
        try:
            receiver_thickness_changed = (
                abs(
                    self.parameters.ReceiverThickness.Value
                    - geometry.receiver_thickness
                )
                > 1e-7
            )
            if receiver_thickness_changed:
                self.parameters.ReceiverThickness = geometry.receiver_thickness
                self.doc.recompute()
            self.receiver_overshoot.setProperty(
                "value", self.parameters.ReceiverOvershoot
            )
            self.receiver_radius.setProperty(
                "value", self.parameters.ReceiverFilletRadius
            )
        finally:
            self.receiver_overshoot.blockSignals(False)
            self.receiver_radius.blockSignals(False)
        _, width, depth, radius = build_fingers(
            geometry,
            int(self.parameters.FingerCount),
            self.parameters.Overshoot,
            self.parameters.FilletRadius,
        )
        for receiver_base in geometry.receiver_bases:
            build_receiver_fingers(
                geometry,
                receiver_base,
                int(self.parameters.FingerCount),
                self.parameters.ReceiverOvershoot,
                self.parameters.ReceiverFilletRadius,
            )
        return geometry, width, depth, radius, applicable

    def _sync_parameters_from_widgets(self):
        if self._syncing_parameters:
            return
        self._syncing_parameters = True
        try:
            expressions_changed = self._expression_update_pending
            self._expression_update_pending = False
            expressions = dict(self.parameters.ExpressionEngine)
            if "FingerCount" not in expressions:
                self.parameters.FingerCount = int(self.count.value())
            if "Overshoot" not in expressions:
                self.parameters.Overshoot = self.overshoot.property("value")
            if "FilletRadius" not in expressions:
                self.parameters.FilletRadius = self.radius.property("value")
            if "ReceiverOvershoot" not in expressions:
                self.parameters.ReceiverOvershoot = self.receiver_overshoot.property(
                    "value"
                )
            if "ReceiverFilletRadius" not in expressions:
                self.parameters.ReceiverFilletRadius = self.receiver_radius.property(
                    "value"
                )
            if expressions_changed:
                self.doc.recompute()
        finally:
            self._syncing_parameters = False

    def slotChangedObject(self, obj, property_name):
        if (
            obj is self.parameters
            and property_name == "ExpressionEngine"
            and not self._syncing_parameters
        ):
            self._expression_update_pending = True
            self._schedule_update_state()

    def _schedule_update_state(self, *args):
        self._validation_pending = True
        self._validation_timer.start(150)

    def _update_state_now(self, *args):
        self._validation_timer.stop()
        self._validation_pending = False
        self._update_state()

    def _run_scheduled_update(self):
        if not self._validation_pending:
            return
        self._validation_pending = False
        self._update_state()

    def _update_state(self, *args):
        self._validation_timer.stop()
        self._validation_pending = False
        try:
            result = self._validated_geometry()
            if result is None:
                self._set_receiver_parameters_enabled(False)
                missing = []
                if self.source_face is None:
                    missing.append("source face")
                if not self.receivers:
                    missing.append("receiving bodies")
                self.status.setText("Still needed: " + ", ".join(missing) + ".")
                self.status.setStyleSheet("color: #606060;")
                self.create_button.setEnabled(False)
                return
            geometry, width, depth, radius, applicable = result
            self._set_receiver_parameters_enabled(applicable)
            receiver_labels = ", ".join(body.Label for body in geometry.receiver_bodies)
            self.status.setText(
                f"Ready — {geometry.source_body.Label} → {receiver_labels}; "
                f"width {width:g} mm, depth {depth:g} mm, tip radius {radius:g} mm."
            )
            self.status.setStyleSheet("color: #207020;")
            self.create_button.setEnabled(True)
        except JointValidationError as error:
            self._set_receiver_parameters_enabled(
                self._receiver_parameters_applicable
            )
            self.status.setText(str(error))
            self.status.setStyleSheet("color: #b03030;")
            self.create_button.setEnabled(False)

    def _create(self):
        self._validation_timer.stop()
        self._validation_pending = False
        try:
            self._validated_geometry()
            expressions = dict(self.parameters.ExpressionEngine)
            doc = self.doc
            try:
                joint = create_joint(
                    self.source_face[0],
                    self.source_face[1],
                    self.receivers,
                    int(self.parameters.FingerCount),
                    self.parameters.Overshoot,
                    self.parameters.FilletRadius,
                    expressions.get("FingerCount"),
                    expressions.get("Overshoot"),
                    expressions.get("FilletRadius"),
                    receiver_overshoot=self.parameters.ReceiverOvershoot,
                    receiver_fillet_radius=self.parameters.ReceiverFilletRadius,
                    receiver_overshoot_expression=expressions.get(
                        "ReceiverOvershoot"
                    ),
                    receiver_fillet_radius_expression=expressions.get(
                        "ReceiverFilletRadius"
                    ),
                )
            except Exception:
                raise
            self._finish()
            Gui.Control.closeDialog()
            doc.removeObject(self.parameters.Name)
            doc.recompute()
            doc.commitTransaction()
            self._transaction_open = False
            # Committing the transaction can reapply Part Design's automatic
            # child visibility. Restore both current tips after the dialog and
            # transaction have finished.
            show_body_tips(_body(joint), *self.receivers)
            Gui.activeDocument().activeView().fitAll()
        except JointValidationError as error:
            self.status.setText(str(error))
            self.status.setStyleSheet("color: #b03030;")
        except Exception as error:
            if self._transaction_open:
                self.doc.abortTransaction()
                self._transaction_open = False
                self._finish()
                Gui.Control.closeDialog()
            App.Console.PrintError(f"Finger Joint failed: {error}\n")

    def _set_receiver_parameters_enabled(self, enabled):
        self.receiver_overshoot.setEnabled(enabled)
        self.receiver_radius.setEnabled(enabled)

    def getStandardButtons(self):
        return 0

    def reject(self):
        self._finish()
        Gui.Control.closeDialog()
        if self._transaction_open:
            self.doc.abortTransaction()
            self._transaction_open = False

    def _finish(self):
        global _active_panel
        self._validation_timer.stop()
        self._validation_pending = False
        self._remove_selection_gate()
        self._restore_receiver_visibility()
        Gui.Selection.removeObserver(self)
        App.removeDocumentObserver(self)
        Gui.Selection.clearSelection()
        _active_panel = None

    def _restore_receiver_visibility(self):
        for body, was_visible in self._hidden_receiver_visibility.items():
            if body.Document is not None:
                body.ViewObject.Visibility = was_visible
        self._hidden_receiver_visibility.clear()
        if Gui.ActiveDocument is not None:
            Gui.activeDocument().activeView().redraw()

    def _remove_selection_gate(self):
        if self.selection_gate is not None:
            Gui.Selection.removeSelectionGate()
            self.selection_gate = None


class FingerJointCommand:
    def GetResources(self):
        return {
            "MenuText": "Finger Joint",
            "ToolTip": "Interactively select inputs and create a rounded finger joint",
        }

    def IsActive(self):
        return App.ActiveDocument is not None and not Gui.Control.activeDialog()

    def Activated(self):
        global _active_panel
        _active_panel = FingerJointTaskPanel()
        Gui.Control.showDialog(_active_panel)
        _active_panel._begin_pick("receiver")


Gui.addCommand("DesignSystem_FingerJoint", FingerJointCommand())
