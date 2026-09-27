import FreeCAD as App
import json
import os
BED_FILE=os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),'Bed.FCStd')
doc=App.openDocument(os.environ.get('LASER_BED_FILE',BED_FILE))
doc.recompute()
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
print('ENGRAVING_LINKS',len(rows),flush=True)
App.closeDocument(doc.Name)
