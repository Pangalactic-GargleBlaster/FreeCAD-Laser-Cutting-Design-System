"""Order hard-linked sheet blocks to minimize full assembly group spans."""
import argparse
import json
import math
import random


def optimize(layout,groups,iterations=300000,seed=17):
    sheets=layout['sheets']; n=len(sheets)
    at={p['body_name']:i for i,s in enumerate(sheets) for p in s['parts']}
    required=set()
    for group,names in groups.items():
        if not (group.startswith('Pair:') or group.endswith('CabinetSide')):continue
        occupied=sorted({at[name] for name in names})
        if occupied[-1]-occupied[0]>1:raise ValueError(('Input violates hard group',group,occupied))
        if len(occupied)==2:required.add(occupied[0])
    blocks=[];start=0
    for i in range(n-1):
        if i not in required:
            blocks.append(tuple(range(start,i+1)));start=i+1
    blocks.append(tuple(range(start,n)))
    used=[tuple(sorted({at[name] for name in names})) for names in groups.values() if len(names)>1]
    used=[x for x in used if len(x)>1]
    def flatten(order,flip):
        result=[]
        for b in order:
            items=blocks[b]
            result.extend(reversed(items) if flip[b] else items)
        return result
    def metrics(order,flip):
        positions=[0]*n
        for pos,source in enumerate(flatten(order,flip)):positions[source]=pos
        spans=[max(positions[i] for i in x)-min(positions[i] for i in x) for x in used]
        return max(spans,default=0),sum(spans),sum(v>1 for v in spans)
    def cost(order,flip):
        maximum,total,over_one=metrics(order,flip)
        return maximum*1000+total+over_one*.01
    rng=random.Random(seed);order=list(range(len(blocks)));flip=[False]*len(blocks)
    best_order=order[:];best_flip=flip[:];best_cost=cost(order,flip)
    original=metrics(order,flip)
    for run in range(10):
        if run%2==0:order=best_order[:];flip=best_flip[:]
        else:order=list(range(len(blocks)));flip=[False]*len(blocks)
        current=cost(order,flip)
        for step in range(iterations//10):
            trial_order=order[:];trial_flip=flip[:]
            move=rng.randrange(3)
            if move==0:
                a,b=rng.sample(range(len(blocks)),2)
                trial_order[a],trial_order[b]=trial_order[b],trial_order[a]
            elif move==1:
                a,b=rng.sample(range(len(blocks)),2)
                trial_order.insert(b,trial_order.pop(a))
            else:
                trial_flip[rng.randrange(len(blocks))]^=True
            trial_cost=cost(trial_order,trial_flip)
            temperature=12*(1-step/(iterations//10))+.1
            if trial_cost<current or rng.random()<math.exp((current-trial_cost)/temperature):
                order,flip,current=trial_order,trial_flip,trial_cost
                if current<best_cost:
                    best_order,best_flip,best_cost=order[:],flip[:],current
    indices=flatten(best_order,best_flip)
    return indices,len(blocks),original,metrics(best_order,best_flip)


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('layout');parser.add_argument('groups');parser.add_argument('output')
    parser.add_argument('--iterations',type=int,default=300000)
    args=parser.parse_args()
    l=json.load(open(args.layout));g=json.load(open(args.groups))['packing_groups']
    order,count,before,after=optimize(l,g,args.iterations)
    l['sheets']=[l['sheets'][i] for i in order]
    for i,s in enumerate(l['sheets'],1):s['number']=i
    l['packing_groups']=g
    l['packing_strategy']=l.get('packing_strategy','')+'_hard_block_order_search'
    json.dump(l,open(args.output,'w'),indent=2)
    print('HARD_BLOCKS',count,'BEFORE',before,'AFTER',after,'SHEETS',len(order),flush=True)


if __name__=='__main__':main()
