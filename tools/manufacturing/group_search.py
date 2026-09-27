"""Improve a sheet layout for explicitly configured assembly groups."""
import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path

from optimize_hard_blocks import optimize as optimize_hard_blocks
from optimize_sheet_order import optimize as optimize_sheet_order


def group_definitions(layout, manifest, config):
    records={r['body_name']:r for r in manifest}
    nested={n for faces in layout.get('nested_groups',{}).values() for n in faces}
    packing=set(records)-nested
    groups=config['packing_groups']
    members=[name for names in groups.values() for name in names]
    if len(members)!=len(set(members)) or set(members)!=packing:
        raise ValueError('Packing groups must cover each independent body exactly once')
    return groups


def metrics(layout,groups):
    at={p['body_name']:i for i,sheet in enumerate(layout['sheets'])
        for p in sheet['parts']}
    spans={group:max(at[n] for n in names)-min(at[n] for n in names)
           for group,names in groups.items()}
    return (len(layout['sheets']),max(spans.values(),default=0),sum(spans.values()))


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
    parser.add_argument('config')
    parser.add_argument('baseline')
    parser.add_argument('output')
    args=parser.parse_args()
    manifest=json.load(open(args.manifest))
    config=json.load(open(args.config))
    baseline=json.load(open(args.baseline))
    groups=group_definitions(baseline,manifest,config)
    baseline['packing_groups']=groups
    baseline['hard_groups']=config.get('hard_groups',[])
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
