"""Optimize cutting order for a fixed geometric layout and assembly groups."""
import argparse
import json
import math
import random


def optimize(layout, groups, iterations=120000, restarts=8, seed=7):
    sheets = layout['sheets']
    at = {p['body_name']: i for i, sheet in enumerate(sheets)
          for p in sheet['parts']}
    members = [tuple(sorted({at[n] for n in names}))
               for names in groups.values() if len(names) > 1]
    members = [x for x in members if len(x) > 1]
    n = len(sheets)

    def metrics(order):
        rank = [0] * n
        for i, sheet in enumerate(order):
            rank[sheet] = i
        spans = [max(rank[s] for s in group) - min(rank[s] for s in group)
                 for group in members]
        return max(spans, default=0), sum(spans), sum(s > 1 for s in spans)

    def cost(order):
        maximum, total, over_one = metrics(order)
        return maximum * 1000 + total + over_one * 0.1

    rng = random.Random(seed)
    initial = list(range(n))
    best = initial[:]
    best_cost = cost(best)
    for run in range(restarts):
        current = best[:] if run % 2 == 0 else initial[:]
        current_cost = cost(current)
        for step in range(iterations // restarts):
            trial = current[:]
            a, b = rng.sample(range(n), 2)
            if rng.random() < 0.65:
                trial[a], trial[b] = trial[b], trial[a]
            else:
                value = trial.pop(a)
                trial.insert(b, value)
            trial_cost = cost(trial)
            temperature = 8 * (1 - step / (iterations // restarts)) + 0.2
            if trial_cost < current_cost or rng.random() < math.exp((current_cost - trial_cost) / temperature):
                current, current_cost = trial, trial_cost
                if current_cost < best_cost:
                    best, best_cost = current[:], current_cost
    return best, metrics(initial), metrics(best)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('layout')
    parser.add_argument('groups')
    parser.add_argument('output')
    parser.add_argument('--iterations', type=int, default=120000)
    args = parser.parse_args()
    layout = json.load(open(args.layout))
    groups = json.load(open(args.groups))['packing_groups']
    order, before, after = optimize(layout, groups, args.iterations)
    layout['sheets'] = [layout['sheets'][i] for i in order]
    for i, sheet in enumerate(layout['sheets'], 1):
        sheet['number'] = i
    layout['packing_strategy'] += '_sheet_order_optimized'
    json.dump(layout, open(args.output, 'w'), indent=2)
    print('BEFORE', before, 'AFTER', after, 'SHEETS', len(order), flush=True)


if __name__ == '__main__':
    main()
