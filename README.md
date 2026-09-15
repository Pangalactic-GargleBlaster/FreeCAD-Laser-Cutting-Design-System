# Design System

FreeCAD tools for designing laser-cut sheet structures.

## Finger Joint

The **Finger Joint** command creates a parametric joint between a source panel
(Panel A) and one or more receiving panels (Panel B). Panel A receives rounded
fingers; every selected Panel B receives the matching cutouts.

### Workflow

1. Activate **Finger Joint**.
2. Click each receiving body in the 3D scene or model tree. Each selected body
   is temporarily hidden so bodies behind it remain accessible.
3. Click **Done (N)** or press Enter.
4. Select Panel A's rectangular end face.
5. Select the thickness edge on that face where the first finger begins.
6. Adjust the parameters and click **Create Joint**.

The selector accepts multiple receiving bodies. Their furthest parallel face
determines the finger depth, and the finger cutting tool is subtracted from all
of them. Hidden bodies are restored when the command is completed or cancelled.

### Parameters

- **Number of fingers**: Number of alternating Panel A fingers. Finger width
  and gap width are both derived from the usable face length.
- **Overshoot**: Distance Panel A's fingers extend past the furthest receiving
  face. Its default formula follows Panel A's selected thickness edge.
- **Fillet radius**: Radius on Panel A's finger tips. Its default follows the
  same selected thickness edge.
- **Receiving-panel overshoot**: Extension of Panel B's effective fingers when
  the matching slots are open at a panel edge.
- **Receiving-panel fillet radius**: Radius on those extended Panel B tips.
  Both receiving-panel defaults follow the combined receiving-panel thickness.

All numerical controls support FreeCAD expressions through their `fx` buttons.
After creation, select `Finger Joint (added)` and edit its **Parameters** group;
both Panel A and every Panel B recompute immediately.

When the cutouts are enclosed within Panel B, as in `T.FCStd`, Panel B has no
effective edge fingers. The two receiving-panel controls are disabled and have
no geometric effect. When the slots meet an edge, as in `Corner.FCStd` and
`Mismatched.FCStd`, those controls are enabled.

### Validation and generated features

The command requires:

- a planar rectangular source face at any orientation;
- a straight selected edge belonging to that face;
- positive-area contact with exactly one selected receiving face; and
- exactly two faces on every receiving body parallel to the source face.

The exact requested radii are used. A joint is rejected if two tip fillets
cannot fit within a finger width or if FreeCAD cannot construct the requested
fillet.

The operation creates `Finger Joint (inputs)` and `Finger Joint (added)` in
Panel A, plus one `Finger Joint (cut)` feature in every Panel B. Earlier objects
inside each body are normal FreeCAD feature history; the tool does not leave a
standalone body or controller.

### Manual test with Corner

Never save changes over a file in `fixtures/`. First duplicate `Corner.FCStd`
to a working location, then:

1. Restart FreeCAD and select the **Design System** workbench.
2. Open the working copy.
3. Click **Finger Joint**.
4. Click `Base (XY)` in the scene, then press Enter. It hides temporarily.
5. Click the exposed bottom 100 x 10 mm face of `Back (XZ)`.
6. Click its short 10 mm edge at the desired end.
7. Set the finger count to `2` and click **Create Joint**.
8. Inspect both sides of the base edge and edit `Finger Joint (added)` to test
   live recomputation.

`Mismatched.FCStd` demonstrates the exact-radius guard: reduce the relevant
fillet radius when the requested finger width is too narrow for the default.

Run all automated checks with `mise run test`. Tests modify temporary fixture
copies only.
