"""Exercise FreeCAD's application import before its GUI is available."""

import importlib.util
import sys
import types
from pathlib import Path


app = types.ModuleType("FreeCAD")
app.GuiUp = False
app.Vector = type("Vector", (), {})
sys.modules["FreeCAD"] = app
sys.modules["Part"] = types.ModuleType("Part")

path = Path(__file__).resolve().parent.parent / "freecad" / "DesignSystem" / "finger_joint.py"
spec = importlib.util.spec_from_file_location("finger_joint_delayed_gui", path)
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)

calls = []
gui = types.ModuleType("FreeCADGui")
gui.activeDocument = lambda: types.SimpleNamespace(
    activeView=lambda: types.SimpleNamespace(redraw=lambda: calls.append("redraw"))
)
gui.updateGui = lambda: calls.append("updateGui")
sys.modules["FreeCADGui"] = gui
app.GuiUp = True

tip = types.SimpleNamespace(ViewObject=types.SimpleNamespace(Visibility=False))
other = types.SimpleNamespace(ViewObject=types.SimpleNamespace(Visibility=True))
body = types.SimpleNamespace(
    Tip=tip, Group=[other, tip], ViewObject=types.SimpleNamespace(Visibility=False)
)
module.show_body_tips(body)
assert body.ViewObject.Visibility
assert tip.ViewObject.Visibility
assert not other.ViewObject.Visibility
assert calls == ["redraw", "updateGui"]
print("Delayed GUI import passed")
