# Design System

Reusable FreeCAD tools for designing and manufacturing laser-cut sheet
structures. The [LaserCutBed](https://github.com/Pangalactic-GargleBlaster/LaserCutBed)
project uses this repository as a pinned submodule.

## Repository map

| Location | Purpose |
| --- | --- |
| `freecad/DesignSystem/` | FreeCAD workbench, parametric finger and half-lap joints, panel and drawer helpers. |
| `tools/manufacturing/` | Reusable profile DXF export, group-aware sheet packing, sheet DXF export, and engraving helpers. See its README for inputs and command sequence. |
| `tools/check_overlaps.py` | Positive-volume collision check for any saved FreeCAD project. |
| `tools/audit_panel_symmetry.py` | In-plane symmetry audit of saved panel bodies. |
| `fixtures/`, `tests/` | Workbench examples and integration checks. |

The shared manufacturing tools use explicit project configuration and the
saved FreeCAD model. For another project, supply a packing configuration,
body metadata, and any artwork placement, then run the commands in
`tools/manufacturing/README.md`. LaserCutBed provides one complete example.

Run `python tools/run_freecad.py tools/check_overlaps.py model.FCStd` for
intersections and `python tools/run_freecad.py tools/audit_panel_symmetry.py
model.FCStd` for panel symmetry.
Set `PANEL_AUDIT_CSV` for a per-body symmetry report.

## Finger Joint

The **Finger Joint** command creates a parametric joint between a source panel
(Panel A) and one or more receiving panels (Panel B). Panel A receives rounded
fingers; every selected Panel B receives the matching cutouts.

### Workflow

1. Activate **Finger Joint**.
2. Click each receiving body in the 3D scene or model tree. Each selected body
   is temporarily hidden so bodies behind it remain accessible.
3. Click **Done (N)** or press Enter.
4. Click each rectangular source end face. Selected source bodies stay visible.
5. Click **Done (N)** or press Enter.
6. Adjust the parameters and click **Create Joint**.

The selectors accept multiple receiving bodies and source faces. For a laminated
source panel, select the end face of each ply. Hidden receiving bodies are
restored when the command is completed or cancelled.

### Parameters

- **Number of fingers**: Number of Panel A fingers. The pattern is centered on
  the face, and each finger is `face width / (2 × number of fingers)` wide.
- **Overshoot**: Distance Panel A's fingers extend past the furthest receiving
  face. Its default formula follows Panel A's selected thickness edge.
- **Fillet radius**: Radius on Panel A's finger tips. Its default follows the
  same selected thickness edge.
- **Receiving-panel overshoot**: Extension of Panel B's effective fingers when
  the matching slots are open at a panel edge.
- **Receiving-panel fillet radius**: Radius on those extended Panel B tips. Its
  default follows the receiving panel's thickness.

All numerical controls support FreeCAD expressions through their `fx` buttons.
For a parallel-face joint, edit the **Parameters** group on `Finger Joint
(added)`. For an angled or laminated joint, edit `Finger Joint group`. All
affected bodies recompute from those parameters.

When the cutouts are enclosed within Panel B, as in `fixtures/finger joint/T.FCStd`, Panel B has no
effective edge fingers. The two receiving-panel controls are disabled and have
no geometric effect. When the slots meet an edge, as in
`fixtures/finger joint/Corner.FCStd` and
`fixtures/finger joint/Mismatched.FCStd`, those controls are enabled.

### Validation and generated features

The command requires rectangular source faces and at least one complete edge
of one selected face to lie on a receiving body surface. Every selected body
must be a panel with two broad parallel faces. It supports angled
edge and T joints, including laminated panels. The older parallel-face joint
path remains available for a single source face.

The exact requested radii are used. A joint is rejected if two tip fillets
cannot fit within a finger width or if FreeCAD cannot construct the requested
fillet.

The parallel-face path creates `Finger Joint (inputs)` and `Finger Joint
(added)` in Panel A, plus one `Finger Joint (cut)` in every Panel B. Angled and
laminated joints create a `Finger Joint group` controller and a result feature
in each affected body. Edit the controller's parameters to recompute the group.

### Manual test with Corner

Never save changes over a file in `fixtures/`. First duplicate
`fixtures/finger joint/Corner.FCStd`
to a working location, then:

1. Restart FreeCAD and select the **Design System** workbench.
2. Open the working copy.
3. Click **Finger Joint**.
4. Click `Base (XY)` in the scene, then press Enter. It hides temporarily.
5. Click the exposed bottom 100 x 10 mm face of `Back (XZ)`.
6. Set the finger count to `2` and click **Create Joint**.
7. Inspect both sides of the base edge and edit `Finger Joint (added)` to test
   live recomputation.

`fixtures/finger joint/Mismatched.FCStd` demonstrates the exact-radius guard: reduce the relevant
fillet radius when the requested finger width is too narrow for the default.

Run all automated checks with `mise run test`. Tests modify temporary fixture
copies only.

## Half Lap

The **Half Lap** command takes two sets of panel bodies. Bodies in the same
set must not overlap, and each body must overlap a body in the other set.
Select the first set, pressing Enter when done; selected bodies hide so the
second set is accessible. Bodies in the second set hide as they are selected.
Press Enter after the second set. If an end face is needed, the dialog prompts
for one and then focuses the fillet radius; otherwise it focuses the radius
immediately. Its default is the thinnest selected panel's thickness.

Each intersecting pair gets complementary slots meeting halfway along their
overlap. The slot outline is projected through the full panel thickness for
angled crossings. Only the edges at each slot mouth are filleted (normally
two; one when a slot reaches a panel corner).
`fixtures/half-lap/PartialX.FCStd` determines its opening sides from the
offset panel ends. For aligned panels, select an end face to leave intact:
its set opens on the opposite end, and the other set opens on that face's end.
The resulting **Half Lap** controller holds the editable fillet radius.

The bed model, design assets, and manufacturing DXFs live in
[LaserCutBed](https://github.com/Pangalactic-GargleBlaster/LaserCutBed).
