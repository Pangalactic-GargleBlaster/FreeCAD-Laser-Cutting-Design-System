"""Write bounds and thickness axes for final Part Design bodies."""

import json
import os

import FreeCAD as App


def export(model_path, output_path):
    doc = App.openDocument(model_path)
    try:
        doc.recompute()
        metadata = []
        for body in doc.Objects:
            if body.TypeId != 'PartDesign::Body':
                continue
            box = body.Shape.BoundBox
            lengths = (box.XLength, box.YLength, box.ZLength)
            axis = 'XYZ'[min(range(3), key=lengths.__getitem__)]
            metadata.append({
                'name': body.Name, 'label': body.Label, 'axis': axis,
                'bbox': [[getattr(box, a+'Min'), getattr(box, a+'Max')]
                         for a in 'XYZ'],
                'parent': [p.Name for p in body.InList if p.TypeId == 'App::Part'],
            })
        with open(output_path, 'w') as stream:
            json.dump(metadata, stream, indent=2)
        print('BODY_METADATA', len(metadata), flush=True)
    finally:
        App.closeDocument(doc.Name)


if __name__ in ('__main__', 'export_body_metadata'):
    model = os.environ.get('LASER_MODEL_FILE')
    output = os.environ.get('LASER_BODY_METADATA_JSON')
    if not all((model, output)):
        raise SystemExit('Set LASER_MODEL_FILE and LASER_BODY_METADATA_JSON')
    export(model, output)
