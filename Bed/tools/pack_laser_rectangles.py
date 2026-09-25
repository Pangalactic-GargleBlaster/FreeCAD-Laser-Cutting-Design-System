"""Conservative 47 x 31 inch laser layout using buffered part bounding boxes."""

import csv
import json
import math
import os
import random
import sys

SHEET_W = 47 * 25.4
SHEET_H = 31 * 25.4


def ceil_mm(value):
    return math.ceil(value * 1000 - 1e-7) / 1000


def intersects(a, b):
    return a[0] < b[0] + b[2] - 1e-7 and a[0] + a[2] > b[0] + 1e-7 and \
        a[1] < b[1] + b[3] - 1e-7 and a[1] + a[3] > b[1] + 1e-7


def contained(a, b):
    return a[0] >= b[0] - 1e-7 and a[1] >= b[1] - 1e-7 and \
        a[0] + a[2] <= b[0] + b[2] + 1e-7 and \
        a[1] + a[3] <= b[1] + b[3] + 1e-7


class Sheet:
    def __init__(self, gap):
        self.gap = gap
        self.free = [(0.0, 0.0, SHEET_W + gap, SHEET_H + gap)]
        self.parts = []

    def choices(self, width, height, rotate):
        for orientation, (w, h) in enumerate(((width, height), (height, width))):
            if orientation and (not rotate or abs(width-height) < 1e-7):
                continue
            buffered_w, buffered_h = w+self.gap, h+self.gap
            for x, y, free_w, free_h in self.free:
                if buffered_w > free_w + 1e-7 or buffered_h > free_h + 1e-7:
                    continue
                short = min(free_w-buffered_w, free_h-buffered_h)
                long = max(free_w-buffered_w, free_h-buffered_h)
                yield (short, long, y, x), (x, y, w, h, orientation)

    def place(self, name, placement):
        x, y, w, h, orientation = placement
        occupied = (x, y, w+self.gap, h+self.gap)
        next_free = []
        for free in self.free:
            if not intersects(free, occupied):
                next_free.append(free)
                continue
            fx, fy, fw, fh = free
            if x > fx + 1e-7:
                next_free.append((fx, fy, x-fx, fh))
            if x+w+self.gap < fx+fw-1e-7:
                next_free.append((x+w+self.gap, fy, fx+fw-(x+w+self.gap), fh))
            if y > fy + 1e-7:
                next_free.append((fx, fy, fw, y-fy))
            if y+h+self.gap < fy+fh-1e-7:
                next_free.append((fx, y+h+self.gap, fw, fy+fh-(y+h+self.gap)))
        self.free = [r for i, r in enumerate(next_free)
                     if not any(i != j and contained(r, other)
                                for j, other in enumerate(next_free))]
        self.parts.append({'body_name': name, 'x_mm': x, 'y_mm': y,
                           'width_mm': w, 'height_mm': h,
                           'rotation_deg': 90 if orientation else 0})


def pack(parts, gap, rotate, order):
    sheets = []
    for part in order:
        name = part['body_name']
        w, h = part['width_mm'], part['height_mm']
        best = None
        for sheet_index, sheet in enumerate(sheets):
            for score, placement in sheet.choices(w, h, rotate):
                key = (sheet_index, *score)
                if best is None or key < best[0]:
                    best = (key, sheet_index, placement)
        if best is None:
            sheet = Sheet(gap)
            choices = list(sheet.choices(w, h, rotate))
            if not choices:
                raise ValueError(f'Part cannot fit a 47 x 31 inch sheet: {name}, {w} x {h}')
            placement = min(choices)[1]
            sheets.append(sheet)
            sheet_index = len(sheets)-1
        else:
            _, sheet_index, placement = best
        sheets[sheet_index].place(name, placement)
    return sheets


def validate(sheets, names, gap):
    seen = []
    for index, sheet in enumerate(sheets):
        for part in sheet.parts:
            seen.append(part['body_name'])
            x,y,w,h = (part[k] for k in ('x_mm','y_mm','width_mm','height_mm'))
            if x < -1e-6 or y < -1e-6 or x+w > SHEET_W+1e-6 or y+h > SHEET_H+1e-6:
                raise ValueError(('outside sheet',index,part))
        for i, a in enumerate(sheet.parts):
            for b in sheet.parts[i+1:]:
                ax,ay,aw,ah = (a[k] for k in ('x_mm','y_mm','width_mm','height_mm'))
                bx,by,bw,bh = (b[k] for k in ('x_mm','y_mm','width_mm','height_mm'))
                if ax < bx+bw+gap-1e-6 and ax+aw+gap > bx+1e-6 and \
                   ay < by+bh+gap-1e-6 and ay+ah+gap > by+1e-6:
                    raise ValueError(('too close',index,a['body_name'],b['body_name']))
    if sorted(seen) != sorted(names):
        raise ValueError('Missing or duplicate bodies in layout')


def main(manifest_path, output_path, gap, rotate):
    with open(manifest_path) as stream:
        parts = list(csv.DictReader(stream))
    for part in parts:
        for key in ('width_mm','height_mm','area_mm2'):
            part[key] = ceil_mm(float(part[key]))
    best = None
    for seed in range(24):
        rng = random.Random(seed)
        order = parts[:]
        if seed == 0:
            order.sort(key=lambda p: (-p['width_mm']*p['height_mm'],
                                      -max(p['width_mm'],p['height_mm'])))
        elif seed == 1:
            order.sort(key=lambda p: (-max(p['width_mm'],p['height_mm']),
                                      -p['width_mm']*p['height_mm']))
        else:
            order.sort(key=lambda p: -(p['width_mm']*p['height_mm'])
                       *rng.uniform(0.8, 1.2))
        sheets = pack(parts, gap, rotate, order)
        total_unused = sum(SHEET_W*SHEET_H-sum(
            p['width_mm']*p['height_mm'] for p in sheet.parts)
            for sheet in sheets)
        score = (len(sheets), total_unused)
        if best is None or score < best[0]:
            best = (score, seed, sheets)
    _, seed, sheets = best
    validate(sheets, [p['body_name'] for p in parts], gap)
    result = {'sheet_width_mm': SHEET_W, 'sheet_height_mm': SHEET_H,
              'part_gap_mm': gap, 'allow_90_degree_rotation': rotate,
              'selection_seed': seed,
              'sheets': [{'number': i+1, 'parts': sheet.parts}
                         for i, sheet in enumerate(sheets)]}
    with open(output_path, 'w') as stream:
        json.dump(result, stream, indent=2)
    print('LAYOUT',len(parts),'BODIES',len(sheets),'SHEETS',
          'GAP_MM',gap,'ROTATE',rotate,'SEED',seed,flush=True)


if __name__ == '__main__':
    main(sys.argv[1],sys.argv[2],float(sys.argv[3]),sys.argv[4].lower()=='true')
