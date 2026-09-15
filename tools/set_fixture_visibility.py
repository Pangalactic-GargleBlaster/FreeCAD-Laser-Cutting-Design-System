"""Persist visible bodies and tip features in existing fixture files.

Run from FreeCAD's GUI Python console so GuiDocument.xml is written.
"""

from pathlib import Path

import FreeCAD as App
import FreeCADGui as Gui


FIXTURE_DIR = Path("/Users/paolo/Desktop/Design System/fixtures")
FIXTURES = {
    "Corner.FCStd": ("BaseXY", "BackXZ", "SideYZ"),
    "Mismatched.FCStd": ("DrawerSideXZ", "DrawerFrontYZ"),
}


for filename, body_names in FIXTURES.items():
    path = FIXTURE_DIR / filename
    existing = next(
        (doc for doc in App.listDocuments().values() if Path(doc.FileName) == path),
        None,
    )
    doc = existing or App.openDocument(str(path))
    try:
        Gui.activeDocument().activeView().viewAxonometric()
        for body_name in body_names:
            body = doc.getObject(body_name)
            if body is None or body.Tip is None:
                raise RuntimeError(f"{filename}: missing body or tip {body_name}")
            body.ViewObject.Visibility = True
            body.Tip.ViewObject.Visibility = True
        Gui.activeDocument().activeView().fitAll()
        doc.recompute()
        doc.save()
    finally:
        if existing is None:
            App.closeDocument(doc.Name)

print("Fixture visibility is saved.")
