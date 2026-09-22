"""Set default Part, Body, and active Body-tip visibility in an FCStd archive."""

import argparse
import os
from pathlib import Path
import tempfile
import xml.etree.ElementTree as ET
import zipfile


VISIBLE_TYPES = {
    "App::Link",
    "App::Part",
    "PartDesign::Body",
    "Part::FeaturePython",
}


def property_element(parent, name, property_type, value_tag, value):
    prop = ET.SubElement(
        parent,
        "Property",
        {"name": name, "type": property_type, "status": "1"},
    )
    ET.SubElement(prop, value_tag, {"value": value})


def build_gui_document(document_xml, hidden_names=None):
    hidden_names = set(hidden_names or ())
    document = ET.fromstring(document_xml)
    object_records = {}
    for obj in document.findall("./Objects/Object"):
        object_records[obj.get("name")] = (
            obj.get("type"),
            obj.get("id", "-1"),
        )

    # A visible PartDesign Body still displays nothing when its Tip feature's
    # view provider is hidden. Preserve the normal Body history behavior by
    # exposing each body's current Tip, while leaving earlier features absent.
    body_tips = set()
    for obj in document.findall("./ObjectData/Object"):
        record = object_records.get(obj.get("name"))
        if record is None or record[0] != "PartDesign::Body":
            continue
        tip = obj.find("./Properties/Property[@name='Tip']/Link")
        if tip is not None and tip.get("value"):
            body_tips.add(tip.get("value"))

    target_names = {
        name
        for name, (object_type, _) in object_records.items()
        if object_type in VISIBLE_TYPES
    }
    target_names.update(body_tips)
    target_names.update(hidden_names)
    targets = [
        (name, object_records[name][1])
        for name in target_names
        if name in object_records
    ]

    root = ET.Element("Document", {"SchemaVersion": "1", "HasExpansion": "1"})
    ET.SubElement(root, "Expand")
    providers = ET.SubElement(root, "ViewProviderData", {"Count": str(len(targets))})
    for name, object_id in targets:
        provider = ET.SubElement(
            providers,
            "ViewProvider",
            {"name": name, "expanded": "0", "treeRank": object_id},
        )
        properties = ET.SubElement(
            provider, "Properties", {"Count": "2", "TransientCount": "0"}
        )
        property_element(
            properties, "ShowInTree", "App::PropertyBool", "Bool", "true"
        )
        property_element(
            properties,
            "Visibility",
            "App::PropertyBool",
            "Bool",
            "false" if name in hidden_names else "true",
        )

    ET.SubElement(
        root,
        "Camera",
        {
            "settings": (
                "OrthographicCamera {\n"
                "  viewportMapping ADJUST_CAMERA\n"
                "  position 0 0 2500\n"
                "  orientation 0 0 1  0\n"
                "  nearDistance 0\n"
                "  farDistance 5000\n"
                "  aspectRatio 1\n"
                "  focalDistance 2500\n"
                "  height 2500\n\n}\n"
            )
        },
    )
    ET.indent(root, space="    ")
    return ET.tostring(root, encoding="utf-8", xml_declaration=True), targets


def set_visibility(path, hidden_names=None):
    path = Path(path).resolve()
    with zipfile.ZipFile(path, "r") as source:
        gui_xml, targets = build_gui_document(
            source.read("Document.xml"), hidden_names=hidden_names
        )
        with tempfile.NamedTemporaryFile(
            dir=path.parent, prefix=path.name + ".", suffix=".tmp", delete=False
        ) as temporary:
            temporary_path = Path(temporary.name)
        try:
            with zipfile.ZipFile(temporary_path, "w") as destination:
                for info in source.infolist():
                    if info.filename != "GuiDocument.xml":
                        destination.writestr(info, source.read(info.filename))
                destination.writestr("GuiDocument.xml", gui_xml)
            os.replace(temporary_path, path)
        finally:
            if temporary_path.exists():
                temporary_path.unlink()
    return targets


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("document")
    args = parser.parse_args()
    changed = set_visibility(args.document)
    print(
        f"Set {len(changed)} Parts, Bodies, and active Body tips visible "
        f"in {args.document}"
    )
