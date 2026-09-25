"""Produce one deterministic, group-aware bed sheet layout."""
import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path

from optimize_hard_blocks import optimize as optimize_hard_blocks
from optimize_sheet_order import optimize as optimize_sheet_order


def group_definitions(layout, manifest):
    records={r['body_name']:r for r in manifest}
    nested={n for faces in layout['nested_groups'].values() for n in faces}
    packing={name for name in records if name not in nested}
    groups={}
    for name,names in layout['cabinet_side_stacks'].items():
        groups[name.replace('Side','CabinetSide')]=names
    for cabinet in (1,2,3,4):
        prefix=f'Cabinet{cabinet}Drawer'
        for side in ('Low','High'):
            names=[f'{prefix}Side{side}{ply}Body' for ply in ('Outer','Inner')]
            names += [f'{prefix}{side}SlideLayer{layer}Body' for layer in (1,2)]
            groups[f'{prefix}{side}Side']=names
    for cabinet in (7,8):
        for drawer in ('Lower','Upper'):
            prefix=f'Cabinet{cabinet}{drawer}Drawer'
            for side in ('Low','High'):
                names=[f'{prefix}Side{side}{ply}Body' for ply in ('Outer','Inner')]
                names += [f'{prefix}{side}SlideLayer{layer}Body' for layer in (1,2)]
                groups[f'{prefix}{side}Side']=names
    owner={}
    for group,names in groups.items():
        for name in names:
            if name not in packing or name in owner:
                raise ValueError(('Invalid assembly group',group,name))
            owner[name]=group
    for name in sorted(packing):
        if name in owner:continue
        mate=records[name]['mate_name']
        if mate and mate in packing:
            group='Pair:'+'|'.join(sorted((name,mate)))
            groups.setdefault(group,sorted((name,mate)))
            owner[name]=group
        elif mate and mate in nested:
            group='Pair:'+'|'.join(sorted((name,mate)))
            groups.setdefault(group,[name])
            owner[name]=group
        else:
            group='Single:'+name
            groups[group]=[name]
            owner[name]=group
    if set(owner)!=packing or len(groups)!=92:
        raise ValueError(('Incomplete packing groups',len(groups),len(owner)))
    return groups


def metrics(layout,groups):
    at={p['body_name']:i for i,sheet in enumerate(layout['sheets'])
        for p in sheet['parts']}
    spans={group:max(at[n] for n in names)-min(at[n] for n in names)
           for group,names in groups.items()}
    return (len(layout['sheets']),max(spans.values()),sum(spans.values()))


def reorder(layout,groups,hard_blocks=False):
    if hard_blocks:
        try:
            order,blocks,before,after=optimize_hard_blocks(layout,groups)
        except ValueError:
            order,before,after=optimize_sheet_order(layout,groups)
            blocks='unrestricted fallback'
    else:
        order,before,after=optimize_sheet_order(layout,groups)
        blocks='unrestricted'
    result=dict(layout)
    result['sheets']=[dict(layout['sheets'][i],number=j+1)
                      for j,i in enumerate(order)]
    print('REORDER',blocks,before,'->',after,flush=True)
    return result


def objective(layout,groups):
    sheets,maximum,total=metrics(layout,groups)
    # One extra sheet costs about 30 sheet positions of total group spread.
    # Minimize the worst assembly span before trading sheets against spread.
    return (maximum,30*sheets+total)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('manifest')
    parser.add_argument('metadata')
    parser.add_argument('baseline')
    parser.add_argument('output')
    args=parser.parse_args()
    manifest=json.load(open(args.manifest))
    baseline=json.load(open(args.baseline))
    groups=group_definitions(baseline,manifest)
    baseline['packing_groups']=groups
    best=reorder(baseline,groups,hard_blocks=True)
    with tempfile.TemporaryDirectory(prefix='group-search-') as temporary:
        directory=Path(temporary)
        for round_number in range(2):
            ordered=reorder(best,groups)
            start=directory / f'start-{round_number}.json'
            candidate=directory / f'candidate-{round_number}.json'
            start.write_text(json.dumps(ordered))
            subprocess.run([sys.executable,str(Path(__file__).with_name('lns_group_search.py')),
                            str(start),args.manifest,args.metadata,str(candidate),
                            '--passes','50'],check=True)
            improved=json.loads(candidate.read_text())
            improved=reorder(improved,groups)
            if objective(improved,groups)<objective(best,groups):best=improved
            else:break
        start=directory/'eliminate-start.json'
        candidate=directory/'eliminate-candidate.json'
        start.write_text(json.dumps(best))
        subprocess.run([sys.executable,str(Path(__file__).with_name('lns_group_search.py')),
                        str(start),args.manifest,args.metadata,str(candidate),
                        '--passes','1','--eliminate'],check=True)
        compact=json.loads(candidate.read_text())
        if len(compact['sheets'])<len(best['sheets']):
            compact=reorder(compact,groups)
            if objective(compact,groups)<objective(best,groups):best=compact
    best['packing_strategy']='group_search_overall_proximity'
    best['group_span_max']=metrics(best,groups)[1]
    best['group_span_total']=metrics(best,groups)[2]
    Path(args.output).write_text(json.dumps(best,indent=2))
    print('GROUP_LAYOUT',*metrics(best,groups),'GROUPS',len(groups),flush=True)


if __name__=='__main__':main()
