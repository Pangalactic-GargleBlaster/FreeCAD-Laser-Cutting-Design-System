"""Build face-up laser files from the current saved Bed.FCStd model."""

import argparse
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import zipfile


BED = Path(__file__).resolve().parent.parent
TOOLS = BED / "tools"
FREECAD = Path("/Applications/FreeCAD.app/Contents/Resources/bin/FreeCADCmd")
ARCHIVE = "bed_laser_layout_face_up_nested_vector_engraving.zip"


def run(label, command, environment, log_dir):
    print(label, flush=True)
    log = log_dir / (label.lower().replace(" ", "_") + ".log")
    with log.open("w") as stream:
        result = subprocess.run(command, cwd=BED.parent, env=environment,
                                stdout=stream, stderr=subprocess.STDOUT)
    output = log.read_text(errors="replace")
    if result.returncode or "Traceback (most recent call last)" in output:
        raise RuntimeError(f"{label} failed (exit {result.returncode}):\n{output[-5000:]}")
    for line in output.splitlines():
        if line.startswith(("DONE ", "NESTED_LAYOUT ", "GROUP_LAYOUT ", "ENGRAVING_LINKS ",
                            "SVG_VECTORS ", "ENGRAVED ", "SHEETS_EXPORTED ")):
            print("  " + line, flush=True)


def readme(parameters, sheet_count, bodies, layout):
    stock_count = math.ceil(sheet_count / 3)
    return f"""BED LASER LAYOUT — FACE UP, NESTED DRAWER FACES

Source: the saved Bed.FCStd with DrawerClearance = {parameters['drawer_clearance_mm']:g} mm
and ply = {parameters['ply_mm']:g} mm.
There is one DXF profile per final FreeCAD body ({bodies} total).

FACE ORIENTATION
Put the better-finished plywood face UP under the laser. Do not mirror the
profiles or sheet layouts. Profiles use the selected visible face away from
each laminated mate; this puts the rougher faces together for gluing.
The eight single-ply drawer bottoms use their upward interior faces.
The manifest records the selected face normal for each body.

SHEET LAYOUT
Usable panel: 47 x 31 in = 1193.8 x 787.4 mm.
On a 48 x 32 in blank, the nominal job origin is 12.7 mm from each physical
edge. Check the actual blank and align manually.
The layout uses {sheet_count} panels, requiring {stock_count} full 4 x 8 ft sheets cut in thirds;
{3 * stock_count - sheet_count} of the available panels are unused.
Independent part bounding boxes have at least 5 mm of spacing. Drawer faces
are nested in their matching face-frame openings with at least
{layout['nested_face_frame_gap_mm']:g} mm of profile clearance. Ninety-degree rotations within the sheet are allowed;
there are no flips or mirrors.
The layout search minimizes the widest assembly span, then balances panel
count against total span across laminate and cabinet/drawer side groups.
The widest assembly spans {layout['group_span_max']} sheet positions.

COLORS
Black/white (ACI 7): cut paths.
Red (ACI 1), ENGRAVE_RED layer: filigree engraving paths on eight visible
outer drawer faces. Twelve motif placements in total: one on each of four
main drawer faces and two on each of four bedside drawer faces. The paths
come from the original filigree.svg Bézier contours, registered to the saved
engraving positions and scales. The smaller bedside patterns use the SVG's
top-left motif and its horizontal mirror. Curves are sampled to under 0.031 mm
maximum deviation at the current engraving scale; no raster pixels are traced.
Set the red closed contours to a fill engraving operation in the laser
software, and inspect nested holes in its preview before production.
No kerf compensation is included.

FILES
profiles/*.dxf             One face-up cut profile per body; affected outer
                           drawer faces also include red engraving paths.
profiles/manifest.csv      Body names, selected faces, and dimensions.
sheets/sheet-XX-cut.dxf    Combined cut and engraving paths for each panel.
sheets/sheet-XX-map.svg    Visual placement map with part IDs; do not cut it.
sheets/sheet-index.csv     Part ID, body name, sheet, position, rotation.
layout.json                Machine-readable placements and assumptions.

REBUILD
From the Design System folder, run:
python3 Bed/tools/build_manufacturing.py
This reads the current saved Bed.FCStd and rebuilds manufacturing/ only.
"""


def validate(publication, model, parameters):
    if not model.is_file() or model.stat().st_size < 1_000_000:
        raise ValueError("Bed.FCStd is missing or unexpectedly small")
    records = json.loads((publication / "profiles/manifest.json").read_text())
    layout = json.loads((publication / "layout.json").read_text())
    expected = {r["body_name"] for r in records}
    placed = [p["body_name"] for s in layout["sheets"] for p in s["parts"]]
    if len(records) != 320 or len(expected) != 320 or sorted(placed) != sorted(expected):
        raise ValueError("Body, profile, or sheet placement count mismatch")
    sheet_for = {p["body_name"]: sheet["number"]
                 for sheet in layout["sheets"] for p in sheet["parts"]}
    stacks = layout.get("cabinet_side_stacks", {})
    if len(stacks) != 12 or any(name not in sheet_for for names in stacks.values() for name in names):
        raise ValueError("Cabinet side stack metadata is incomplete")
    if any(abs(r["thickness_mm"] - parameters["ply_mm"]) > 1e-4 for r in records):
        raise ValueError("Exported profile thickness differs from Bed.FCStd ply")
    groups = layout.get("packing_groups", {})
    nested = {name for faces in layout.get("nested_groups", {}).values()
              for name in faces}
    packing_names = expected - nested
    grouped_names = [name for names in groups.values() for name in names]
    if len(groups) != 92 or sorted(grouped_names) != sorted(packing_names):
        raise ValueError("Packing groups do not cover every independent body exactly once")
    spans = [max(sheet_for[name] for name in names) - min(sheet_for[name] for name in names)
             for names in groups.values()]
    if max(spans) != layout.get("group_span_max") or sum(spans) != layout.get("group_span_total"):
        raise ValueError("Group proximity metrics do not match placements")
    profiles = list((publication / "profiles").glob("*.dxf"))
    sheets = list((publication / "sheets").glob("sheet-*-cut.dxf"))
    maps = list((publication / "sheets").glob("sheet-*-map.svg"))
    if len(profiles) != 320 or len(sheets) != len(layout["sheets"]) or len(maps) != len(sheets):
        raise ValueError("Missing profile or sheet export")
    if sum("ENGRAVE_RED" in p.read_text(errors="replace") for p in profiles) != 8:
        raise ValueError("Expected red engraving on eight face profiles")
    for path in profiles + sheets:
        if path.stat().st_size < 300:
            raise ValueError(f"Empty DXF: {path}")
    return len(records), len(sheets)


def publish(items):
    backups = []
    installed = []
    try:
        for _, destination in items:
            backup = destination.with_name(destination.name + ".previous-build")
            if backup.exists():
                raise FileExistsError(f"Remove stale backup before publishing: {backup}")
            if destination.exists():
                destination.rename(backup)
                backups.append((backup, destination))
        for source, destination in items:
            source.rename(destination)
            installed.append(destination)
    except Exception:
        for destination in reversed(installed):
            if destination.is_dir():
                shutil.rmtree(destination)
            else:
                destination.unlink()
        for backup, destination in reversed(backups):
            backup.rename(destination)
        raise
    for backup, _ in backups:
        if backup.is_dir():
            shutil.rmtree(backup)
        else:
            backup.unlink()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check-only", action="store_true",
                        help="Build and validate without replacing existing files")
    args = parser.parse_args()
    if not FREECAD.is_file():
        parser.error(f"FreeCADCmd not found: {FREECAD}")
    model = BED / "Bed.FCStd"
    if not model.is_file():
        parser.error(f"FreeCAD model not found: {model}")

    with tempfile.TemporaryDirectory(prefix=".manufacturing-build-", dir=BED) as temporary:
        stage = Path(temporary)
        raw = stage / "raw_profiles"
        publication = stage / "manufacturing"
        publication.mkdir()
        sheets = publication / "sheets"
        sheets.mkdir()
        metadata = stage / "body_metadata.json"
        placements = stage / "engraving_placements.json"
        layout = publication / "layout.json"
        baseline_layout = stage / "baseline_layout.json"
        env = os.environ.copy()
        env.update(LASER_BED_FILE=str(model), LASER_OUTPUT_DIR=str(raw),
                   LASER_PARAMETERS_JSON=str(stage / "model_parameters.json"),
                   LASER_ENGRAVING_PLACEMENTS_JSON=str(placements),
                   LASER_BODY_METADATA_JSON=str(metadata),
                   LASER_MANIFEST_JSON=str(raw / "manifest.json"),
                   LASER_LAYOUT_JSON=str(layout), LASER_SHEETS_DIR=str(sheets))
        run("Export profiles", [str(FREECAD), str(TOOLS / "export_laser_profiles.py")], env, stage)
        manifest = raw / "manifest.json"
        env["LASER_MANIFEST_JSON"] = str(manifest)
        run("Export engraving placements", [str(FREECAD), str(TOOLS / "export_engraving_placements.py")], env, stage)
        run("Pack sheets", [sys.executable, str(TOOLS / "pack_nested_frames.py"),
                             str(manifest), str(metadata), str(baseline_layout)], env, stage)
        run("Optimize groups", [sys.executable, str(TOOLS / "group_search.py"),
                                str(manifest), str(metadata), str(baseline_layout),
                                str(layout)], env, stage)
        run("Export sheets", [str(FREECAD), str(TOOLS / "export_laser_sheets.py")], env, stage)
        shutil.move(str(raw / "profiles"), str(publication / "profiles"))
        shutil.move(str(raw / "manifest.csv"), str(publication / "profiles/manifest.csv"))
        shutil.move(str(raw / "manifest.json"), str(publication / "profiles/manifest.json"))
        run("Add vector engravings", [sys.executable, str(TOOLS / "add_red_engravings.py"),
                                       str(publication / "profiles"), str(sheets),
                                       str(layout), str(metadata), str(placements)], env, stage)
        parameters = json.loads((stage / "model_parameters.json").read_text())
        bodies, sheet_count = validate(publication, model, parameters)
        selected_layout = json.loads(layout.read_text())
        (publication / "README.txt").write_text(readme(parameters, sheet_count, bodies,
                                                       selected_layout))
        with zipfile.ZipFile(publication / ARCHIVE, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for path in sorted(publication.rglob("*")):
                if path.is_file() and path.name != ARCHIVE:
                    archive.write(path, path.relative_to(publication))
        with zipfile.ZipFile(publication / ARCHIVE) as archive:
            if archive.testzip() is not None:
                raise ValueError("ZIP archive integrity check failed")
        print(f"Validated {bodies} profiles and {sheet_count} panels from Bed.FCStd "
              f"at {parameters['ply_mm']:g} mm ply.", flush=True)
        if args.check_only:
            print("Check only: existing manufacturing files were preserved.", flush=True)
            return
        publish([(publication, BED / "manufacturing")])
        print("Updated manufacturing/ from the current Bed.FCStd.", flush=True)


if __name__ == "__main__":
    main()
