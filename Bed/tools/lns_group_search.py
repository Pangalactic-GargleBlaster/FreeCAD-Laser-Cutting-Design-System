"""Small large-neighborhood search for the bed's sheet count and group spans."""
import argparse
import copy
import json
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from pack_laser_rectangles import Sheet, SHEET_W, SHEET_H, ceil_mm, validate


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('input')
    parser.add_argument('manifest')
    parser.add_argument('metadata')
    parser.add_argument('output')
    parser.add_argument('--passes', type=int, default=4)
    parser.add_argument('--eliminate', action='store_true')
    args = parser.parse_args()
    layout = json.load(open(args.input))
    records = {r['body_name']: r for r in json.load(open(args.manifest))}
    metadata = {r['name']: r for r in json.load(open(args.metadata))}
    groups = layout['packing_groups']
    nested_groups = layout['nested_groups']
    nested = {name for names in nested_groups.values() for name in names}
    names = [name for name in records if name not in nested]
    dims = {name: (ceil_mm(records[name]['width_mm']),
                   ceil_mm(records[name]['height_mm'])) for name in names}
    gap = layout['part_gap_mm']
    rng = random.Random(19)

    def key(name):
        w, h = dims[name]
        return (w * h, records[name]['area_mm2'], name)

    def place_options(sheet, name):
        w0, h0 = dims[name]
        options = {}
        for rotation, (w, h) in enumerate(((w0, h0), (h0, w0))):
            if rotation and abs(w-h) < 1e-7: continue
            for fx, fy, fw, fh in sheet.free:
                if w+gap > fw+1e-7 or h+gap > fh+1e-7: continue
                for x in (fx, fx+fw-w-gap):
                    for y in (fy, fy+fh-h-gap):
                        if x+w>SHEET_W+1e-7 or y+h>SHEET_H+1e-7:continue
                        p=(x,y,w,h,rotation)
                        options[tuple(round(v,4) for v in p)]=p
        return list(options.values())

    def repack(parts, mode=0):
        sheet=Sheet(gap)
        ordered=sorted(parts,key=key,reverse=True)
        for index,name in enumerate(ordered):
            choices=place_options(sheet,name)
            if not choices:return None
            if index==0:
                choices=[p for p in choices if abs(p[0])<1e-7 and abs(p[1])<1e-7]
            scored=[]
            for p in choices:
                trial=copy.deepcopy(sheet)
                trial.place(name,p)
                usable=[(max(0,fw-gap),max(0,fh-gap))
                        for _,_,fw,fh in trial.free]
                largest=max((w*h for w,h in usable),default=0)
                total=sum(w*h for w,h in usable)
                if mode==0:score=(-round(largest,3),p[1],p[0],p[4])
                elif mode==1:score=(-round(total,3),p[1],p[0],p[4])
                elif mode==2:score=(p[1],p[0],-round(largest,3),p[4])
                else:score=(-round(largest,3),p[0],p[1],p[4])
                scored.append((score,p))
            _,chosen=min(scored)
            sheet.place(name,chosen)
        return sheet

    def repack_any(parts):
        for mode in range(4):
            sheet=repack(parts,mode)
            if sheet is not None:return sheet
        return None

    def contents(sheet):
        parts=sheet.parts if isinstance(sheet,Sheet) else sheet['parts']
        return [p['body_name'] for p in parts if p['body_name'] not in nested]

    def from_positions(parts):
        sheet=Sheet(gap)
        for p in sorted(parts,key=lambda p:key(p['body_name']),reverse=True):
            sheet.place(p['body_name'],(p['x_mm'],p['y_mm'],p['width_mm'],
                                        p['height_mm'],int(p['rotation_deg']==90)))
        return sheet

    sheets=[from_positions([p for p in s['parts'] if p['body_name'] not in nested])
            for s in layout['sheets']]

    def metrics(ss):
        at={p['body_name']:i for i,s in enumerate(ss) for p in s.parts}
        spans=[max(at[n] for n in group)-min(at[n] for n in group)
               for group in groups.values() if len(group)>1]
        return (len(ss),max(spans,default=0),sum(spans),sum(v>1 for v in spans))

    def score(value):
        count,maximum,total,over_one=value
        return count*100000 + maximum*1000 + total + over_one*0.01

    initial=metrics(sheets)
    print('REPACKED_START',initial,flush=True)
    accepted=0
    attempted=0
    for pass_number in range(args.passes):
        improved=False
        at={p['body_name']:i for i,s in enumerate(sheets) for p in s.parts}
        targets=[]
        for group,names_in_group in groups.items():
            distinct=sorted({at[n] for n in names_in_group})
            if len(distinct)<2:continue
            span=distinct[-1]-distinct[0]
            for end in (distinct[0],distinct[-1]):
                moving=[n for n in names_in_group if at[n]==end]
                for dest in sorted(distinct,key=lambda i:(abs(i-end),i)):
                    if dest!=end:targets.append((-span,group,end,dest,tuple(moving)))
        targets.sort()
        for _,group,src,dst,moving in targets:
            if any(at.get(n)!=src for n in moving):continue
            attempted+=1
            new_src=[n for n in contents(sheets[src]) if n not in moving]
            new_dst=contents(sheets[dst])+list(moving)
            packed_dst=repack_any(new_dst)
            if packed_dst is None:continue
            packed_src=repack_any(new_src) if new_src else None
            if new_src and packed_src is None:
                packed_src=from_positions([p for p in sheets[src].parts
                                           if p['body_name'] in new_src])
            if new_src and packed_src is None:continue
            candidate=sheets[:]
            candidate[dst]=packed_dst
            if packed_src is None:candidate.pop(src)
            else:candidate[src]=packed_src
            old_value=metrics(sheets)
            new_value=metrics(candidate)
            if score(new_value)<score(old_value):
                sheets=candidate
                accepted+=1
                improved=True
                print('IMPROVED',group,old_value,'->',new_value,flush=True)
                break
        if not improved:break

    if args.eliminate:
        owner={name:group for group,members in groups.items() for name in members}
        candidates=sorted(range(len(sheets)),
                          key=lambda i:sum(records[n]['area_mm2'] for n in contents(sheets[i])))
        attempts=0
        for src in candidates:
            source_items=contents(sheets[src])
            if len(source_items)>12:continue
            for variant in range(4):
                attempts+=1
                candidate=sheets[:]
                ordered=sorted(source_items,key=key,reverse=True)
                if variant==1:ordered.reverse()
                elif variant==2:ordered.sort(key=lambda n:(owner[n],-key(n)[0]))
                elif variant==3:rng.shuffle(ordered)
                success=True
                for name in ordered:
                    current_at={p['body_name']:i for i,s in enumerate(candidate)
                                if i!=src for p in s.parts}
                    group=owner[name]
                    other_group_sheets=[current_at[n] for n in groups[group]
                                        if n in current_at and n!=name and current_at[n]!=src]
                    destination=[]
                    for dst in range(len(candidate)):
                        if dst==src:continue
                        packed=repack_any(contents(candidate[dst])+[name])
                        if packed is None:continue
                        near=min((abs(dst-i) for i in other_group_sheets),default=abs(dst-src))
                        destination.append(((near,abs(dst-src),-sum(key(n)[0]
                                              for n in contents(candidate[dst]))),dst,packed))
                    if not destination:
                        success=False
                        break
                    _,dst,packed=min(destination)
                    candidate[dst]=packed
                if not success:continue
                candidate.pop(src)
                print('ELIMINATED_SHEET',src+1,'BY',variant,
                      metrics(sheets),'->',metrics(candidate),flush=True)
                sheets=candidate
                break
            if len(sheets)<len(candidates):break
        print('ELIMINATION_ATTEMPTS',attempts,flush=True)

    # Expand the drawer faces in the existing face-frame openings.
    def projected_min(name,axis_key):
        vector=records[name][axis_key]
        axis=next(i for i,v in enumerate(vector) if abs(v)>0.5)
        low,high=metadata[name]['bbox'][axis]
        return low if vector[axis]>0 else -high
    offsets={frame:{face:(projected_min(face,'view_u')-projected_min(frame,'view_u'),
                          projected_min(face,'view_v')-projected_min(frame,'view_v'))
                    for face in faces} for frame,faces in nested_groups.items()}
    validate(sheets,names,gap)
    for sheet in sheets:
        expanded=[]
        for p in sheet.parts:
            expanded.append(p)
            frame=p['body_name']
            for face in nested_groups.get(frame,[]):
                dx,dy=offsets[frame][face]
                fw,fh=dims.get(face,(ceil_mm(records[face]['width_mm']),
                                      ceil_mm(records[face]['height_mm'])))
                if p['rotation_deg']==0:
                    x,y,w,h=p['x_mm']+dx,p['y_mm']+dy,fw,fh
                else:
                    x=p['x_mm']+ceil_mm(records[frame]['height_mm'])-dy-fh
                    y=p['y_mm']+dx
                    w,h=fh,fw
                expanded.append({'body_name':face,'x_mm':x,'y_mm':y,
                                 'width_mm':w,'height_mm':h,
                                 'rotation_deg':p['rotation_deg']})
        sheet.parts=expanded
    if sorted(p['body_name'] for s in sheets for p in s.parts)!=sorted(records):
        raise ValueError('Missing or duplicated output body')
    layout['sheets']=[{'number':i+1,'parts':s.parts} for i,s in enumerate(sheets)]
    layout['packing_strategy']='large_neighborhood_group_relocation_with_sheet_repack'
    json.dump(layout,open(args.output,'w'),indent=2)
    print('FINAL',metrics(sheets),'ATTEMPTED',attempted,'ACCEPTED',accepted,flush=True)


if __name__=='__main__':main()
