"""Audit saved Bed panels for symmetry about either in-plane midline.

Run with FreeCAD's Python, for example:
    FreeCADCmd Bed/tools/audit_bed_symmetry.py
Set BED_AUDIT_CSV to save one result per body, or BED_MODEL_PATH to audit a
candidate model. The FCStd archive is read
directly, so the script checks saved shapes without loading proxies,
recomputing, or changing the document.
"""

import csv
import os
import time
import xml.etree.ElementTree as ET
import zipfile

import FreeCAD as App
import Part


def mirror_difference(shape, bounds, axis):
    middle = (getattr(bounds, axis + "Min") + getattr(bounds, axis + "Max")) / 2
    point = App.Vector(*(middle if name == axis else 0 for name in "XYZ"))
    normal = App.Vector(*(1 if name == axis else 0 for name in "XYZ"))
    reflected = shape.mirror(point, normal)
    overlap = shape.common(reflected).Volume
    return max(0.0, shape.Volume - overlap)


def document_bodies(archive):
    document = ET.fromstring(archive.read("Document.xml"))
    names = [obj.get("name") for obj in document.find("Objects")
             if obj.get("type") == "PartDesign::Body"]
    name_set = set(names)
    labels = {}
    for obj in document.find("ObjectData"):
        if obj.get("name") not in name_set:
            continue
        for prop in obj.find("Properties"):
            if prop.get("name") == "Label":
                labels[obj.get("name")] = prop.find("String").get("value")
                break
    return names, labels


def audit():
    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    model = os.environ.get("BED_MODEL_PATH", os.path.join(root, "Bed", "Bed.FCStd"))
    fieldnames = ["name", "label", "thickness_axis", "in_plane_axes",
                  "symmetric_axes", "volume_mm3", "tolerance_mm3",
                  "x_mismatch_mm3", "y_mismatch_mm3", "z_mismatch_mm3"]
    output = os.environ.get("BED_AUDIT_CSV")
    limit = int(os.environ.get("BED_AUDIT_LIMIT", "0"))
    start = time.time()
    with zipfile.ZipFile(model) as archive:
        names, labels = document_bodies(archive)
        print("BODIES", len(names), flush=True)
        if limit:
            names = names[:limit]
        stream = open(output, "w", newline="", encoding="utf-8") if output else None
        try:
            writer = csv.DictWriter(stream, fieldnames=fieldnames) if stream else None
            if writer:
                writer.writeheader()
            failures = 0
            for index, name in enumerate(names, 1):
                shape = Part.Shape()
                shape.importBrepFromString(archive.read(name + ".Shape.brp").decode("ascii"))
                if shape.isNull() or len(shape.Solids) != 1:
                    raise ValueError("Invalid body shape: " + name)
                bounds = shape.BoundBox
                thickness_axis = min("XYZ", key=lambda axis: getattr(bounds, axis + "Length"))
                plane_axes = [axis for axis in "XYZ" if axis != thickness_axis]
                tolerance = max(0.01, shape.Volume * 1e-8)
                differences = {axis: mirror_difference(shape, bounds, axis)
                               for axis in plane_axes}
                symmetric = [axis for axis in plane_axes if differences[axis] <= tolerance]
                row = {
                    "name": name,
                    "label": labels.get(name, name),
                    "thickness_axis": thickness_axis,
                    "in_plane_axes": "".join(plane_axes),
                    "symmetric_axes": "".join(symmetric),
                    "volume_mm3": shape.Volume,
                    "tolerance_mm3": tolerance,
                    "x_mismatch_mm3": differences.get("X", ""),
                    "y_mismatch_mm3": differences.get("Y", ""),
                    "z_mismatch_mm3": differences.get("Z", ""),
                }
                if writer:
                    writer.writerow(row)
                    stream.flush()
                if not symmetric:
                    failures += 1
                    print("ASYMMETRIC", name, differences, flush=True)
                if index % 20 == 0:
                    print("PROGRESS", index, len(names), round(time.time() - start, 1), flush=True)
            print("DONE", len(names), failures, round(time.time() - start, 1), flush=True)
        finally:
            if stream:
                stream.close()


audit()
