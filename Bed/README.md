# Bed project

`Bed.FCStd` is the current parametric bed model. `design_parameters.json`
contains its generation inputs. `prototypes/` holds earlier cabinet and drawer
studies; `assets/` contains the filigree sources.

`tools/generate_bed.py` builds the model with the shared FreeCAD panel and
finger-joint code in `../freecad/DesignSystem/`. The Bed generation and
engraving-placement scripts stay here because they encode this bed's structure
and artwork.

`packing_config.json` names this project's 320 bodies, nested drawer faces,
cabinet-side stacks, laminated pairs, and assembly groups. It also
sets 1193.8 × 787.4 mm usable panels and a 5 mm rectangular-part gap. The
packing and DXF code that consumes it lives in `../tools/manufacturing/`.
Update the config when body names or assembly groups change. Every independent
body must appear in exactly one `packing_groups` entry.

## Checks and manufacturing

From the repository root, run:

```text
mise run bed:generate
mise run bed:overlaps
mise run bed:symmetry
python3 Bed/tools/build_manufacturing.py --check-only
python3 Bed/tools/build_manufacturing.py
```

The last command publishes `manufacturing/`; `--check-only` builds and
validates in a temporary directory. Set `FREECAD_CMD` to the FreeCADCmd path if
it is not on `PATH`. The publication script exports one face-up DXF per body,
packs the sheets using the configured nesting and groups, builds sheet DXFs and
SVG maps, adds Bed filigree engravings, checks counts and thicknesses, and
creates an archive. Read `manufacturing/README.txt` before cutting.

`manufacturing/` reflects the last published build. Rebuild it after model
changes before using its files to manufacture parts.
