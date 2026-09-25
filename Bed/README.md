# Bed

`Bed.FCStd` is the current parametric model. `prototypes/` holds the earlier
cabinet and drawer studies. `assets/` contains its
filigree sources; `tools/` contains generation, validation, and laser
export scripts. `manufacturing/` holds the face-up 47 × 31 in laser
layout, individual body profiles, sheet DXFs, and placement maps.

Update the parameters in `Bed.FCStd`, recompute, and save it in FreeCAD. Then,
from the Design System root, run `python3 Bed/tools/build_manufacturing.py` to
rebuild the manufacturing files from that saved model. This command leaves
`Bed.FCStd` and `design_parameters.json` unchanged. Each rebuild searches for
one sheet layout, balancing panel count and overall
proximity of laminate pairs and cabinet/drawer side assemblies. The selected
layout and its metrics are saved in
`manufacturing/layout.json`.
Run `mise run bed:overlaps` to check positive-volume overlaps. Read
`manufacturing/README.txt` before cutting.
