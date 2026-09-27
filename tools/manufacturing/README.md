# Manufacturing tools

These scripts are part of the Design System. They accept a saved FreeCAD model,
part metadata, and a project configuration; they contain no Bed assembly names.
Run FreeCAD scripts with FreeCADCmd and the packing scripts with Python.

## Inputs

`export_laser_profiles.py` reads the model named by `LASER_MODEL_FILE` and the
JSON file named by `LASER_CONFIG_JSON`. Set `LASER_OUTPUT_DIR` for its output and,
optionally, `LASER_PARAMETERS_JSON` for model parameters. The configuration
contains:

- `model_parameter_object`: FreeCAD object name holding dimensions.
- `model_parameter_fields`: output names mapped to FreeCAD property names; it
  must include `ply_mm`.
- `mate_suffix_pairs`: suffix pairs identifying laminated neighbors. The face
  exposed away from each mate becomes the cutting face.
- `unpaired_suffix_normals`: suffixes mapped to explicit face normals, such as
  `"DrawerBottomBody": "+Z"`.
- `expected_body_count`: optional count check.

The exporter checks that each body is valid, has the configured thickness, has
a planar through-cut section, and has a defined cutting face. It writes one
millimetre DXF per body plus JSON and CSV manifests. Records include the face
normal, 2D orientation, thickness, bounds, and mate. No kerf is applied.

`export_body_metadata.py` creates body metadata JSON containing each body's
`name` and XYZ `bbox` (as three `[min, max]` pairs). Set `LASER_MODEL_FILE` and
`LASER_BODY_METADATA_JSON` to run it. The project configuration
contains:

- `sheet_width_mm`, `sheet_height_mm`, `part_gap_mm`.
- `nested_groups`: frame body names mapped to the bodies placed in their open
  areas. Every nested body must have the same view axes as its frame and a
  positive clearance on every side.
- `adjacent_stacks`: an optional mapping of assembly names to parts scheduled
  onto at most two adjacent sheets in the initial layout.
- `packing_groups`: a partition of every independent body into groups whose
  sheet span should be minimized.
- `hard_groups`: group names used to form adjacent-sheet blocks in the first
  sheet-order search. Later proximity searches can change their span; inspect
  the final layout's group metrics.

The packer uses buffered rectangular bounds for independent parts. It schedules
single parts, adjacent-sheet stacks, and laminated pairs, then positions nested
parts inside their frames. `group_search.py` reorders sheets, relocates parts,
and tries to eliminate sheets with a deterministic large-neighborhood search.
Its objective first minimizes the largest group span, then balances sheet count
and total span. The saved layout includes placements, group membership, sheet
size, clearances, and metrics. Configure groups explicitly; the algorithms do
not infer assembly meaning from body names.

`export_laser_sheets.py` reads `LASER_MODEL_FILE`, `LASER_MANIFEST_JSON`,
`LASER_LAYOUT_JSON`, and `LASER_SHEETS_DIR`. It regenerates oriented section
profiles from the model, checks them against the manifest and sheet bounds, and
writes one cut DXF and one labeled SVG map per sheet, plus a CSV part index.

`dxf_engraving.py` can add closed red engraving polylines to the resulting
ASCII DXFs. `vector_filigree.py` and `trace_filigree.py` provide SVG/vector
helpers. Projects decide which artwork to place and where; Bed's code in
`Bed/tools/add_red_engravings.py` is one example.

## Command sequence

Set the environment variables above, then run:

```text
FreeCADCmd tools/manufacturing/export_laser_profiles.py
FreeCADCmd tools/manufacturing/export_body_metadata.py
python tools/manufacturing/pack_nested_frames.py manifest.json metadata.json project-config.json baseline.json
python tools/manufacturing/group_search.py manifest.json metadata.json project-config.json baseline.json layout.json
FreeCADCmd tools/manufacturing/export_laser_sheets.py
```

The project supplies its own metadata export and publication script. See
`Bed/tools/build_manufacturing.py` for a complete, validated example.
