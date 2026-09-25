"""Parametric axis-aligned panel solids with document-space geometry."""

import re

import FreeCAD as App
import Part


HOLE_PREFIXES = ("Hole",) + tuple(f"Hole{index}" for index in range(2, 13))


def cut_holes(shape, obj):
    """Cut every enabled cylindrical hole property from a shape."""
    directions = {
        "X": App.Vector(1, 0, 0),
        "Y": App.Vector(0, 1, 0),
        "Z": App.Vector(0, 0, 1),
    }
    for prefix in HOLE_PREFIXES:
        if not getattr(obj, "Has" + prefix, False):
            continue
        hole_origin = App.Vector(
            getattr(obj, prefix + "X").Value,
            getattr(obj, prefix + "Y").Value,
            getattr(obj, prefix + "Z").Value,
        )
        hole = Part.makeCylinder(
            getattr(obj, prefix + "Diameter").Value / 2,
            getattr(obj, prefix + "Length").Value,
            hole_origin,
            directions[getattr(obj, prefix + "Axis")],
        )
        shape = shape.cut(hole)
    return shape


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
        shape = Part.makeBox(*dimensions, origin)

        if getattr(obj, "HasTab", False):
            tab = self._connector_shape(obj, "Tab")
            inset_property = getattr(obj, "TabInset", None)
            inset = inset_property.Value if inset_property is not None else 0
            if inset > 0:
                if obj.TabAxis == "X":
                    bridge = Part.makeBox(
                        inset,
                        obj.TabWidth.Value,
                        obj.TabHeight.Value,
                        App.Vector(
                            obj.TabX.Value - inset, obj.TabY.Value, obj.TabZ.Value
                        ),
                    )
                else:
                    bridge = Part.makeBox(
                        obj.TabLength.Value,
                        inset,
                        obj.TabHeight.Value,
                        App.Vector(
                            obj.TabX.Value, obj.TabY.Value - inset, obj.TabZ.Value
                        ),
                    )
                tab = tab.fuse(bridge)
            shape = shape.fuse(tab)

        for prefix in ("Recess", "Recess2", "Recess3"):
            if getattr(obj, "Has" + prefix, False):
                shape = shape.cut(self._connector_shape(obj, prefix))

        shape = cut_holes(shape, obj)

        obj.Shape = shape

    @staticmethod
    def _connector_shape(obj, prefix):
        length = getattr(obj, prefix + "Length").Value
        width = getattr(obj, prefix + "Width").Value
        height = getattr(obj, prefix + "Height").Value
        x = getattr(obj, prefix + "X").Value
        y = getattr(obj, prefix + "Y").Value
        z = getattr(obj, prefix + "Z").Value
        if not getattr(obj, prefix + "Rounded", False):
            return Part.makeBox(length, width, height, App.Vector(x, y, z))
        radius = height / 2
        if getattr(obj, prefix + "Axis") == "X":
            result = Part.makeBox(length / 2, width, height, App.Vector(x, y, z))
            cap = Part.makeCylinder(
                radius,
                width,
                App.Vector(x + length / 2, y, z + radius),
                App.Vector(0, 1, 0),
            )
        else:
            result = Part.makeBox(length, width / 2, height, App.Vector(x, y, z))
            cap = Part.makeCylinder(
                radius,
                length,
                App.Vector(x, y + width / 2, z + radius),
                App.Vector(1, 0, 0),
            )
        return result.fuse(cap)

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


class ParametricHoleCutProxy:
    """Cut one expression-driven hole after a panel's joint features."""

    def __init__(self, obj=None):
        if obj is not None:
            obj.Proxy = self

    def execute(self, obj):
        if obj.InputFeature is None:
            return
        directions = {
            "X": App.Vector(1, 0, 0),
            "Y": App.Vector(0, 1, 0),
            "Z": App.Vector(0, 0, 1),
        }
        hole = Part.makeCylinder(
            obj.Diameter.Value / 2,
            obj.Length.Value,
            App.Vector(obj.X.Value, obj.Y.Value, obj.Z.Value),
            directions[obj.Axis],
        )
        obj.Shape = obj.InputFeature.Shape.cut(hole)

    def dumps(self):
        return None

    def loads(self, state):
        return None


class AlignmentBoundsProxy:
    """Expose live bounds of the features used to place alignment holes."""

    def __init__(self, obj=None):
        if obj is not None:
            obj.Proxy = self

    def execute(self, obj):
        features = [
            feature
            for feature in (obj.InputFeature1, obj.InputFeature2)
            if feature is not None and not feature.Shape.isNull()
        ]
        if not features:
            return
        for axis in "XYZ":
            setattr(
                obj, axis + "Min",
                min(getattr(feature.Shape.BoundBox, axis + "Min") for feature in features),
            )
            setattr(
                obj, axis + "Max",
                max(getattr(feature.Shape.BoundBox, axis + "Max") for feature in features),
            )

    def dumps(self):
        return None

    def loads(self, state):
        return None


def create_alignment_bounds(container, name, features):
    """Create an expression source tied to panel shapes before their hole cuts."""
    if len(features) != 2:
        raise ValueError("Alignment bounds require two panel layers.")
    bounds = container.newObject("App::FeaturePython", name)
    bounds.Label = "Alignment hole bounds"
    bounds.addProperty("App::PropertyLinkGlobal", "InputFeature1", "Inputs")
    bounds.addProperty("App::PropertyLinkGlobal", "InputFeature2", "Inputs")
    for axis in "XYZ":
        for suffix in ("Min", "Max"):
            bounds.addProperty("App::PropertyDistance", axis + suffix, "Bounds")
    bounds.InputFeature1, bounds.InputFeature2 = features
    AlignmentBoundsProxy(bounds)
    bounds.Proxy.execute(bounds)
    if getattr(bounds, "ViewObject", None) is not None:
        bounds.ViewObject.Visibility = False
    return bounds


def _panel_link_expression(expression, panel):
    """Qualify bare panel properties for use on a downstream feature."""
    result = expression
    for property_name in sorted(panel.PropertiesList, key=len, reverse=True):
        result = re.sub(
            rf"(?<![\w.]){re.escape(property_name)}(?![\w])",
            f"PanelFeature.{property_name}",
            result,
        )
    return result


def create_parametric_hole_cut(
    body,
    panel,
    label,
    origin,
    axis,
    length,
    diameter,
    expressions=None,
):
    """Append one parametric cylindrical cut to a body's current tip."""
    input_feature = body.Tip
    cut = body.newObject("PartDesign::FeaturePython", panel.Name + "HoleCut")
    cut.Label = label
    cut.addProperty("App::PropertyLink", "InputFeature", "Inputs")
    cut.addProperty("App::PropertyLink", "PanelFeature", "Inputs")
    cut.InputFeature = input_feature
    cut.PanelFeature = panel
    for name in ("X", "Y", "Z", "Length", "Diameter"):
        cut.addProperty("App::PropertyLength", name, "Hole")
    cut.addProperty("App::PropertyEnumeration", "Axis", "Hole")
    cut.Axis = ["X", "Y", "Z"]
    cut.X, cut.Y, cut.Z = origin
    cut.Length = length
    cut.Diameter = diameter
    cut.Axis = axis
    for property_name, expression in (expressions or {}).items():
        cut.setExpression(
            property_name, _panel_link_expression(expression, panel)
        )
    ParametricHoleCutProxy(cut)
    if getattr(App, "GuiUp", False):
        ParametricPanelViewProvider(cut.ViewObject)
        input_feature.ViewObject.Visibility = False
        cut.ViewObject.Visibility = True
    body.Tip = cut
    return cut


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


def add_connector_properties(panel):
    """Add optional tab, recess, and dowel-hole inputs to a panel feature."""
    panel.addProperty("App::PropertyBool", "HasTab", "Connector")
    for property_name in (
        "TabLength",
        "TabWidth",
        "TabHeight",
        "TabX",
        "TabY",
        "TabZ",
    ):
        panel.addProperty("App::PropertyLength", property_name, "Connector - Tab")
    panel.addProperty("App::PropertyLength", "TabInset", "Connector - Tab")
    panel.addProperty("App::PropertyBool", "TabRounded", "Connector - Tab")
    panel.addProperty("App::PropertyEnumeration", "TabAxis", "Connector - Tab")
    panel.TabAxis = ["X", "Y"]

    for prefix, label in (
        ("Recess", "Connector - Recess 1"),
        ("Recess2", "Connector - Recess 2"),
        ("Recess3", "Connector - Recess 3"),
    ):
        panel.addProperty("App::PropertyBool", "Has" + prefix, "Connector")
        for suffix in ("Length", "Width", "Height", "X", "Y", "Z"):
            panel.addProperty("App::PropertyLength", prefix + suffix, label)
        panel.addProperty("App::PropertyBool", prefix + "Rounded", label)
        panel.addProperty("App::PropertyEnumeration", prefix + "Axis", label)
        setattr(panel, prefix + "Axis", ["X", "Y"])

    add_hole_properties(panel)
    return panel


def add_hole_properties(panel):
    """Add independently positioned parametric holes."""
    for index, prefix in enumerate(HOLE_PREFIXES, start=1):
        label = f"Connector - Hole {index}"
        panel.addProperty("App::PropertyBool", "Has" + prefix, "Connector")
        panel.addProperty("App::PropertyLength", prefix + "Diameter", label)
        panel.addProperty("App::PropertyLength", prefix + "Length", label)
        for suffix in ("X", "Y", "Z"):
            panel.addProperty("App::PropertyLength", prefix + suffix, label)
        panel.addProperty("App::PropertyEnumeration", prefix + "Axis", label)
        setattr(panel, prefix + "Axis", ["X", "Y", "Z"])
    return panel
