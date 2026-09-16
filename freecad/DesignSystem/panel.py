"""Parametric axis-aligned panel solids with document-space geometry."""

import FreeCAD as App
import Part


class ParametricPanelProxy:
    """Build a box directly in document coordinates for cross-body tools."""

    def __init__(self, obj=None):
        if obj is not None:
            obj.Proxy = self

    def execute(self, obj):
        required = ("Length", "Width", "Height", "X", "Y", "Z")
        if not all(hasattr(obj, name) for name in required):
            return
        dimensions = (obj.Length.Value, obj.Width.Value, obj.Height.Value)
        if any(value <= 0 for value in dimensions):
            raise ValueError("Panel dimensions must be positive.")
        origin = App.Vector(obj.X.Value, obj.Y.Value, obj.Z.Value)
        obj.Shape = Part.makeBox(*dimensions, origin)

    def dumps(self):
        return None

    def loads(self, state):
        return None


class ParametricPanelViewProvider:
    """Use FreeCAD's standard shape display for a parametric panel."""

    def __init__(self, view_object=None):
        if view_object is not None:
            view_object.Proxy = self

    def attach(self, view_object):
        self.ViewObject = view_object

    def updateData(self, obj, prop):
        return None

    def getDisplayModes(self, view_object):
        return []

    def getDefaultDisplayMode(self):
        return "Flat Lines"

    def setDisplayMode(self, mode):
        return mode

    def onChanged(self, view_object, prop):
        return None

    def dumps(self):
        return None

    def loads(self, state):
        return None


def create_parametric_panel(body, name, label):
    """Create an expression-ready panel feature inside a Part Design body."""
    panel = body.newObject("PartDesign::FeaturePython", name)
    panel.Label = label
    for property_name in ("Length", "Width", "Height"):
        panel.addProperty("App::PropertyLength", property_name, "Dimensions")
    for property_name in ("X", "Y", "Z"):
        panel.addProperty("App::PropertyLength", property_name, "Position")
    panel.addProperty(
        "App::PropertyString",
        "PanelThicknessProperty",
        "Panel",
        "Dimension property controlled by the material thickness",
    )
    ParametricPanelProxy(panel)
    if App.GuiUp:
        ParametricPanelViewProvider(panel.ViewObject)
    body.Tip = panel
    return panel
