BED LASER LAYOUT — FACE UP, NESTED DRAWER FACES

Source: the saved Bed.FCStd with DrawerClearance = 3 mm
and ply = 5.8 mm.
There is one DXF profile per final FreeCAD body (320 total).

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
The layout uses 52 panels, requiring 18 full 4 x 8 ft sheets cut in thirds;
2 of the available panels are unused.
Independent part bounding boxes have at least 5 mm of spacing. Drawer faces
are nested in their matching face-frame openings with at least
25.2 mm of profile clearance. Ninety-degree rotations within the sheet are allowed;
there are no flips or mirrors.
The layout search minimizes the widest assembly span, then balances panel
count against total span across laminate and cabinet/drawer side groups.
The widest assembly spans 4 sheet positions.

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
