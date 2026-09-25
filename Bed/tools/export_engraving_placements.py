import FreeCAD as App
import json
import os
BED_FILE=os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),'Bed.FCStd')
doc=App.openDocument(os.environ.get('LASER_BED_FILE',BED_FILE))
doc.recompute()
metadata=[]
for body in doc.Objects:
    if body.TypeId!='PartDesign::Body':continue
    box=body.Shape.BoundBox
    lengths=(box.XLength,box.YLength,box.ZLength)
    axis='XYZ'[min(range(3),key=lengths.__getitem__)]
    metadata.append({'name':body.Name,'label':body.Label,'axis':axis,
                     'bbox':[[getattr(box,a+'Min'),getattr(box,a+'Max')] for a in 'XYZ'],
                     'parent':[p.Name for p in body.InList if p.TypeId=='App::Part']})
rows=[]
for obj in doc.Objects:
    if obj.TypeId!='App::Link' or not hasattr(obj,'DrawerFront') or not hasattr(obj,'ImageFile'):
        continue
    if 'filigree' not in obj.ImageFile.lower():continue
    pos=obj.Placement.Base
    rows.append({'name':obj.Name,'front':obj.DrawerFront.Name,
                 'image':obj.LinkedObject.Name,
                 'source_width':obj.SourceWidth.Value,
                 'source_height':obj.SourceHeight.Value,
                 'scale':obj.Scale,'position':[pos.x,pos.y,pos.z]})
with open(os.environ['LASER_ENGRAVING_PLACEMENTS_JSON'],'w') as stream:
    json.dump(rows,stream,indent=2)
with open(os.environ['LASER_BODY_METADATA_JSON'],'w') as stream:
    json.dump(metadata,stream,indent=2)
print('ENGRAVING_LINKS',len(rows),'BODIES',len(metadata),flush=True)
App.closeDocument(doc.Name)
