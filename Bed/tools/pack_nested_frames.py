"""Pack each drawer face inside its matching face-frame opening."""
import copy, json, os, random, sys
sys.path.insert(0, os.path.dirname(__file__))
from pack_laser_rectangles import Sheet, SHEET_W, SHEET_H, ceil_mm, validate

def main(manifest_path, metadata_path, output_path, gap=5.0):
    records={r['body_name']:r for r in json.load(open(manifest_path))}
    metadata={r['name']:r for r in json.load(open(metadata_path))}
    groups={}
    nested=set()
    minimum_frame_clearance=float('inf')
    for cabinet in (1,2,3,4,7,8):
        for ply in ('Outer','Inner'):
            if cabinet<=4:
                frame=f'Cabinet{cabinet}DrawerFaceFrame{ply}Body'
                faces=[f'Cabinet{cabinet}DrawerFace{ply}Body']
            else:
                frame=f'Cabinet{cabinet}LowerDrawerCombinedFaceFrame{ply}Body'
                faces=[f'Cabinet{cabinet}{position}DrawerFace{ply}Body' for position in ('Lower','Upper')]
            groups[frame]=faces
            nested.update(faces)
    items=[]
    for name,r in records.items():
        if name not in nested:
            items.append({'body_name':name,'width_mm':ceil_mm(r['width_mm']),
                          'height_mm':ceil_mm(r['height_mm']),
                          'area_mm2':ceil_mm(r['area_mm2'])})
    def projected_min(name, key):
        axis_vector=records[name][key]
        axis=next(i for i,x in enumerate(axis_vector) if abs(x)>0.5)
        low,high=metadata[name]['bbox'][axis]
        return low if axis_vector[axis]>0 else -high
    offsets={}
    for frame,faces in groups.items():
        offsets[frame]={}
        for face in faces:
            if records[face]['view_u']!=records[frame]['view_u'] or records[face]['view_v']!=records[frame]['view_v']:
                raise ValueError(('Frame/face coordinate system differs',frame,face))
            dx=projected_min(face,'view_u')-projected_min(frame,'view_u')
            dy=projected_min(face,'view_v')-projected_min(frame,'view_v')
            fw,fh=records[face]['width_mm'],records[face]['height_mm']
            gw,gh=records[frame]['width_mm'],records[frame]['height_mm']
            clearance=min(dx,dy,gw-dx-fw,gh-dy-fh)
            if clearance<=1e-4:
                raise ValueError(('Face not inside frame with clearance',frame,face,dx,dy))
            minimum_frame_clearance=min(minimum_frame_clearance,clearance)
            offsets[frame][face]=(dx,dy)
    # A pair is placed as one scheduling unit: both pieces must land on the
    # same panel or on consecutive panels. Nested drawer faces follow frames.
    by_name={p['body_name']:p for p in items}
    stacks={}
    for cabinet in (1,2,3,4):
        for side,position in (('Low','LowerSide'),('High','UpperSide')):
            prefix=f'Cabinet{cabinet}'
            names=[f'{prefix}{position}{ply}Body' for ply in ('Outer','Inner')]
            names += [f'{prefix}DrawerCabinet{side}{kind}Layer{layer}Body'
                      for kind in ('Support','AntiTip') for layer in (3,4)]
            names += [f'{prefix}DrawerCabinet{side}ChannelBackLayer{layer}Body'
                      for layer in (1,2)]
            stacks[f'{prefix}{side}Side']=names
    for cabinet in (7,8):
        for side,position in (('Low','LeftSide'),('High','RightSide')):
            prefix=f'Cabinet{cabinet}'
            names=[f'{prefix}{position}{ply}Body' for ply in ('Outer','Inner')]
            names += [f'{prefix}{drawer}DrawerCabinet{side}{kind}Layer{layer}Body'
                      for drawer in ('Lower','Upper')
                      for kind in ('Support','AntiTip') for layer in (3,4)]
            names += [f'{prefix}{drawer}DrawerCabinet{side}ChannelBackLayer{layer}Body'
                      for drawer in ('Lower','Upper') for layer in (1,2)]
            stacks[f'{prefix}{side}Side']=names
    stack_members=[name for names in stacks.values() for name in names]
    if len(stack_members)!=len(set(stack_members)) or any(name not in by_name for name in stack_members):
        raise ValueError('Cabinet side stack names are missing or duplicated')
    seen=set(stack_members); pairs=[]; singles=[]
    for part in items:
        name=part['body_name']
        if name in seen:continue
        mate=records[name]['mate_name']
        if mate:
            if mate not in by_name:
                raise ValueError(('Mate missing from packing items',name,mate))
            seen.update((name,mate))
            pairs.append((part,by_name[mate]))
        else:
            seen.add(name);singles.append(part)

    def options(sheet,part):
        return sorted(sheet.choices(part['width_mm'],part['height_mm'],True))

    def fit_stack(base,indices,members):
        trial={i:copy.deepcopy(base[i]) for i in indices}
        for part in members:
            candidate=None
            for i in indices:
                choices=options(trial[i],part)
                if not choices:continue
                score,placement=choices[0]
                key=(i,*score)
                if candidate is None or key<candidate[0]:candidate=(key,i,placement)
            if candidate is None:return None
            _,i,placement=candidate
            trial[i].place(part['body_name'],placement)
        return trial

    def pack(seed):
        rng=random.Random(seed)
        order=pairs[:]
        if seed==0:
            order.sort(key=lambda pair:-sum(p['width_mm']*p['height_mm'] for p in pair))
        else:
            order.sort(key=lambda pair:-sum(p['width_mm']*p['height_mm'] for p in pair)*rng.uniform(.3,1.7))
        sheets=[]
        for part in sorted(singles,key=lambda p:-p['width_mm']*p['height_mm']):
            candidate=None
            for si,sheet in enumerate(sheets):
                for score,placement in options(sheet,part):
                    key=(*score,si)
                    if candidate is None or key<candidate[0]:candidate=(key,si,placement)
            if candidate is None:
                sheets.append(Sheet(gap));si=len(sheets)-1
                placement=options(sheets[si],part)[0][1]
            else:_,si,placement=candidate
            sheets[si].place(part['body_name'],placement)
        for names in stacks.values():
            members=sorted((by_name[name] for name in names),
                           key=lambda p:-p['width_mm']*p['height_mm'])
            choice=None
            # Try occupied panels first, then add one or two consecutive panels.
            for width in (1,2):
                for start in range(len(sheets)-width+1):
                    indices=tuple(range(start,start+width))
                    trial=fit_stack(sheets,indices,members)
                    if trial is not None:
                        choice=(indices,trial);break
                if choice is not None:break
            if choice is None:
                for count in (1,2):
                    expanded=sheets+[Sheet(gap) for _ in range(count)]
                    starts=(len(sheets)-1,) if count==1 and sheets else ()
                    starts+= (len(sheets),)
                    for start in starts:
                        indices=tuple(range(start,len(expanded)))
                        trial=fit_stack(expanded,indices,members)
                        if trial is not None:
                            sheets=expanded;choice=(indices,trial);break
                    if choice is not None:break
            if choice is None:raise ValueError(('Side stack does not fit two panels',names))
            _,trial=choice
            for i,repacked in trial.items():sheets[i]=repacked
        for first,second in order:
            choice=None
            # Search same-sheet placements before neighboring-sheet placements.
            for separation in (0,1):
                for si,sheet in enumerate(sheets):
                    for score,placement in options(sheet,first):
                        trial=copy.deepcopy(sheet)
                        trial.place(first['body_name'],placement)
                        neighbors=(si,) if separation==0 else (si-1,si+1)
                        for sj in neighbors:
                            if sj<0 or sj>=len(sheets):continue
                            candidates=options(trial if sj==si else sheets[sj],second)
                            if not candidates:continue
                            mate_score,mate_placement=candidates[0]
                            key=(*score,*mate_score,si)
                            if choice is None or key<choice[0]:
                                choice=(key,si,sj,placement,mate_placement)
                if choice is not None:break
            if choice is not None:
                _,si,sj,first_placement,second_placement=choice
                sheets[si].place(first['body_name'],first_placement)
                sheets[sj].place(second['body_name'],second_placement)
                continue
            # One part can use the last panel while its mate starts the next.
            last=len(sheets)-1
            if last>=0 and options(sheets[last],first):
                sheets[last].place(first['body_name'],options(sheets[last],first)[0][1])
                sheets.append(Sheet(gap))
                sheets[-1].place(second['body_name'],options(sheets[-1],second)[0][1])
                continue
            sheets.append(Sheet(gap))
            sheets[-1].place(first['body_name'],options(sheets[-1],first)[0][1])
            same=options(sheets[-1],second)
            if same:
                sheets[-1].place(second['body_name'],same[0][1])
            else:
                sheets.append(Sheet(gap))
                sheets[-1].place(second['body_name'],options(sheets[-1],second)[0][1])
        return sheets

    best=None
    for seed in range(24):
        candidate=pack(seed)
        if best is None or len(candidate)<len(best[1]):best=(seed,candidate)
    seed,sheets=best
    validate(sheets,[p['body_name'] for p in items],gap)
    for sheet in sheets:
        expanded=[]
        for p in sheet.parts:
            expanded.append(p)
            frame=p['body_name']
            if frame not in groups:continue
            for face in groups[frame]:
                dx,dy=offsets[frame][face]
                fw=ceil_mm(records[face]['width_mm'])
                fh=ceil_mm(records[face]['height_mm'])
                if p['rotation_deg']==0:
                    x,y=p['x_mm']+dx,p['y_mm']+dy
                    w,h=fw,fh
                else:
                    # Rotation about the local origin, then shift to positive bounds.
                    x=p['x_mm']+ceil_mm(records[frame]['height_mm'])-dy-fh
                    y=p['y_mm']+dx
                    w,h=fh,fw
                expanded.append({'body_name':face,'x_mm':x,'y_mm':y,
                                 'width_mm':w,'height_mm':h,
                                 'rotation_deg':p['rotation_deg']})
        sheet.parts=expanded
    all_names=[p['body_name'] for s in sheets for p in s.parts]
    if sorted(all_names)!=sorted(records):raise ValueError('Missing or duplicate bodies')
    sheet_for={p['body_name']:i for i,sheet in enumerate(sheets) for p in sheet.parts}
    for name,record in records.items():
        mate=record['mate_name']
        if mate and abs(sheet_for[name]-sheet_for[mate])>1:
            raise ValueError(('Laminated pair exceeds one panel',name,mate))
    for stack,names in stacks.items():
        if max(sheet_for[name] for name in names)-min(sheet_for[name] for name in names)>1:
            raise ValueError(('Cabinet side stack exceeds two adjacent panels',stack))
    result={'sheet_width_mm':SHEET_W,'sheet_height_mm':SHEET_H,
            'part_gap_mm':gap,'nested_face_frame_gap_mm':minimum_frame_clearance,
            'allow_90_degree_rotation':True,'selection_seed':seed,
            'nested_groups':groups,
            'cabinet_side_stacks':stacks,
            'sheets':[{'number':i+1,'parts':s.parts} for i,s in enumerate(sheets)]}
    with open(output_path,'w') as out:json.dump(result,out,indent=2)
    print('NESTED_LAYOUT',len(sheets),'SHEETS',len(items),'PACKING_ITEMS',len(all_names),'BODIES',flush=True)

if __name__=='__main__':main(sys.argv[1],sys.argv[2],sys.argv[3])
