# Test fixtures

These `.FCStd` files are immutable baseline inputs. Tests must never open and
save them in place or otherwise overwrite them. Copy a fixture to a temporary
directory before modifying it, and write all generated results outside this
folder.

`tools/generate_fixtures.py` is the source for these files. It refuses to
replace an existing fixture unless a developer deliberately sets
`DESIGN_SYSTEM_OVERWRITE_FIXTURES=1`; tests must not set that variable.
It must be run from FreeCAD's GUI Python console so visibility and camera state
are included in the saved document.

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

## T.FCStd

- `CrossPanelXZ`: 100 x 100 x 10 mm, spanning `(0, 0, 0)` to
  `(100, 10, 100)`.
- `StemPanelYZ`: 90 x 100 x 10 mm, spanning `(45, 10, 0)` to
  `(55, 100, 100)`.

The stem's 10 x 100 mm end face contacts the center of the cross panel,
forming a T when viewed from above.
