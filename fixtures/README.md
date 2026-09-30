# Test fixtures

The `finger joint/` and `half-lap/` subfolders contain immutable `.FCStd`
baseline inputs. Tests must never open and
save them in place or otherwise overwrite them. Copy a fixture to a temporary
directory before modifying it, and write all generated results outside this
folder.

`tools/generate_fixtures.py` is the source for generated fixtures. It refuses to
replace an existing fixture unless a developer deliberately sets
`DESIGN_SYSTEM_OVERWRITE_FIXTURES=1`; tests must not set that variable.
Run it through `python tools/run_freecad.py tools/generate_fixtures.py NAME`.
Quote `'#'` when generating the hash fixture from a shell.
Command-line generation writes saved visibility for both bodies and their Tip
features; when run from FreeCAD's GUI, it also saves the axonometric camera view.

## Half-lap fixtures

`half-lap/X.FCStd` contains two centered 100 x 100 x 10 mm vertical panels.
The first spans x = -50–50, y = -5–5, z = 0–100. The second crosses it at
90° around their shared vertical center axis.

`half-lap/AngledX.FCStd` uses the same panels at 60°.

`half-lap/X2.FCStd` and `half-lap/AngledX2.FCStd` have the same assembled
geometry as `X` and `AngledX`, respectively. Each 10 mm panel consists of two
separate 100 x 100 x 5 mm bodies that touch along their broad faces.

`half-lap/PartialX.FCStd` uses the 90° arrangement, with the second panel
raised 50 mm; the panels overlap vertically from z = 50 to 100 mm.

`half-lap/#.FCStd` contains four 100 x 100 x 10 mm vertical panels: two
parallel to XZ centered at y = -30 and 30 mm, and two parallel to YZ centered
at x = -30 and 30 mm. Each XZ panel overlaps both YZ panels; parallel panels
remain separate.

## Finger joint fixtures

## Acute.FCStd, Obtuse.FCStd, Edge90.FCStd, AngledT.FCStd

Each fixture contains two 100 x 100 x 5 mm panels. `BasePanel` occupies
`(0, 0, 0)` to `(100, 100, 5)`. `AngledPanel` is rotated around an X-directed
line on the base panel's top face; the panels touch along that 100 mm line
without overlapping volume.

- `Acute`: 60° rotation; both panels share the base edge from `(0, 0, 5)` to
  `(100, 0, 5)`.
- `Obtuse`: 120° rotation around the same shared base edge.
- `Edge90`: 90° rotation around the same shared base edge; the panels meet
  along a line rather than across an end face.
- `AngledT`: 60° rotation around the line from `(0, 50, 5)` to
  `(100, 50, 5)`, in the middle of the base face.

## Acute2.FCStd

The same angle and panel footprint as `Acute`, but with each panel made from two
separate 100 x 100 x 5 mm bodies. `BaseLower` spans z = 0–5 mm and `BaseUpper` spans
z = 5–10 mm. `AngledInner` and `AngledOuter` are the corresponding 5 mm plies
of the 60° panel. Each pair of plies shares a full face; `BaseUpper` and
`AngledInner` meet along the original 100 mm seam.

## AngledT2.FCStd

The 60° T layout of `AngledT`, with both panels laminated from two separate
100 x 100 x 5 mm plies. Each finished panel is 10 mm thick. `BaseLower` and
`BaseUpper` span z = 0–5 mm and 5–10 mm. `AngledInner` and `AngledOuter`
share a full face; the inner ply meets the base along the line from
`(0, 50, 10)` to `(100, 50, 10)`.

## Pyramid.FCStd

Five separate 5 mm panels form an outward-thickened square pyramid. The
100 x 100 mm base starts on z = 0 and extends down to z = -5. Four triangular
panels connect each edge of the square with the apex at `(0, 0, 100)` and
extend 5 mm outward, away from the pyramid interior.

## Corner.FCStd

Three 10 mm panels meet without overlapping:

- `BaseXY`: 100 x 100 mm, spanning `(0, 0, 0)` to `(100, 100, 10)`.
- `BackXZ`: 100 mm wide by 90 mm high, spanning `(0, 0, 10)` to
  `(100, 10, 100)`.
- `SideYZ`: 90 mm deep by 90 mm high, spanning `(0, 10, 10)` to
  `(10, 100, 100)`.

## Mismatched.FCStd

- `DrawerSideXZ`: 100 x 30 x 10 mm, spanning `(0, 0, 0)` to
  `(100, 10, 30)`.
- `DrawerFrontYZ`: 100 x 60 x 10 mm, spanning `(100, 0, 0)` to
  `(110, 100, 60)`.

The front's inside face contacts the side's 30 x 10 mm end face. Their bottom
and front edges are aligned, modeling a drawer face against a drawer-box side.

## Cycle.FCStd

Four 10 mm thick, 100 mm tall panels form a closed rectangular loop with no
overlapping volume:

- `FrontXZ`: spans `(0, 0, 0)` to `(100, 10, 100)`.
- `RightYZ`: spans `(100, 0, 0)` to `(110, 100, 100)`.
- `BackXZ`: spans `(10, 100, 0)` to `(110, 110, 100)`.
- `LeftYZ`: spans `(0, 10, 0)` to `(10, 110, 100)`.

The directed butt-joint sequence Front → Right → Back → Left → Front closes a
four-body dependency cycle.

## T.FCStd

- `CrossPanelXZ`: 100 x 100 x 10 mm, spanning `(0, 0, 0)` to
  `(100, 10, 100)`.
- `StemPanelYZ`: 90 x 100 x 10 mm, spanning `(45, 10, 0)` to
  `(55, 100, 100)`.

The stem's 10 x 100 mm end face contacts the center of the cross panel,
forming a T when viewed from above.
