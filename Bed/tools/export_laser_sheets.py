"""Place face-up bed profiles into cut-only sheet DXFs and labeled SVG maps."""

import csv
import hashlib
import html
import json
import os
import sys

import FreeCAD as App
import Part
import importDXF


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROJECT_ROOT = os.path.dirname(ROOT)
sys.path.insert(0, os.path.join(PROJECT_ROOT, 'freecad', 'DesignSystem'))


def profile_for_body(body, record):
    shape = body.Shape
    axis = record['good_face_normal'][1]
    sign = 1 if record['good_face_normal'][0] == '+' else -1
    bounds = shape.BoundBox
    mid = (getattr(bounds, axis + 'Min') + getattr(bounds, axis + 'Max')) / 2
    positive_normal = {'X': App.Vector(1, 0, 0),
                       'Y': App.Vector(0, 1, 0),
                       'Z': App.Vector(0, 0, 1)}[axis]
    wires = shape.slice(positive_normal, mid)
    if not wires or not all(wire.isClosed() for wire in wires):
        raise ValueError(f'Profile wires are invalid: {body.Name}')
    profile = Part.makeCompound(wires)
    u, v = (App.Vector(*record[key]) for key in ('view_u', 'view_v'))
    normal = positive_normal * sign
    matrix = App.Matrix()
    matrix.A11, matrix.A12, matrix.A13 = u.x, u.y, u.z
    matrix.A21, matrix.A22, matrix.A23 = v.x, v.y, v.z
    matrix.A31, matrix.A32, matrix.A33 = normal.x, normal.y, normal.z
    profile.transformShape(matrix, False, False)
    b = profile.BoundBox
    profile.translate(App.Vector(-b.XMin, -b.YMin, -b.ZMin))
    b = profile.BoundBox
    if abs(b.XLength - record['width_mm']) > 1e-5 or abs(b.YLength - record['height_mm']) > 1e-5:
        raise ValueError(f'Profile dimensions changed: {body.Name}')
    return profile


def placed_profile(profile, placement):
    shape = profile.copy()
    if placement['rotation_deg'] == 90:
        shape.rotate(App.Vector(0, 0, 0), App.Vector(0, 0, 1), 90)
    elif placement['rotation_deg'] != 0:
        raise ValueError(f"Unsupported rotation: {placement['rotation_deg']}")
    b = shape.BoundBox
    shape.translate(App.Vector(placement['x_mm']-b.XMin,
                               placement['y_mm']-b.YMin,-b.ZMin))
    return shape


def svg_paths(shape):
    paths = []
    for wire in shape.Wires:
        points = wire.discretize(Deflection=0.2)
        if len(points) < 3:
            raise ValueError('Section wire had too few preview points')
        first = points[0]
        path = f'M {first.x:.3f} {first.y:.3f} ' + ' '.join(
            f'L {point.x:.3f} {point.y:.3f}' for point in points[1:]) + ' Z'
        paths.append(path)
    return ' '.join(paths)


def color_for(text):
    digest = hashlib.sha1(text.encode()).digest()
    palette = ('#6baed6', '#fd8d3c', '#74c476', '#9e9ac8',
               '#fdae6b', '#a1d99b', '#bcbddc', '#9ecae1')
    return palette[digest[0] % len(palette)]


def generate(manifest_path, layout_path, destination):
    os.makedirs(destination, exist_ok=True)
    records = json.load(open(manifest_path))
    record_by_name = {r['body_name']: r for r in records}
    layout = json.load(open(layout_path))
    doc = App.openDocument(os.environ.get('LASER_BED_FILE', os.path.join(ROOT, 'Bed.FCStd')))
    out_doc = App.newDocument('LaserSheets')
    feature = out_doc.addObject('Part::Feature', 'SheetCutProfiles')
    bodies = {b.Name: b for b in doc.Objects if b.TypeId == 'PartDesign::Body'}
    profiles = {name: profile_for_body(bodies[name], record)
                for name, record in record_by_name.items()}
    id_by_name = {record['body_name']: f'P{index:03d}'
                  for index, record in enumerate(records, 1)}
    index_rows = []
    total = 0
    for sheet in layout['sheets']:
        number = sheet['number']
        shapes = []
        svg_elements = []
        expected_wires = 0
        for placement in sheet['parts']:
            name = placement['body_name']
            record = record_by_name[name]
            placed = placed_profile(profiles[name], placement)
            b = placed.BoundBox
            if b.XMin < -1e-5 or b.YMin < -1e-5 or \
               b.XMax > layout['sheet_width_mm']+1e-5 or \
               b.YMax > layout['sheet_height_mm']+1e-5:
                raise ValueError(f'Part outside sheet: {name}, sheet {number}')
            shapes.append(placed)
            expected_wires += len(placed.Wires)
            part_id = id_by_name[name]
            fill = color_for(record['assembly'])
            svg_elements.append(
                f'<path d="{svg_paths(placed)}" fill="{fill}" fill-opacity="0.45" '
                'fill-rule="evenodd" stroke="#1f2937" stroke-width="0.8"/>'
            )
            cx = (b.XMin + b.XMax)/2
            cy = layout['sheet_height_mm']-(b.YMin+b.YMax)/2
            svg_elements.append(
                f'<text x="{cx:.3f}" y="{cy:.3f}" text-anchor="middle" '
                f'dominant-baseline="central" font-size="11" fill="#111827">'
                f'{html.escape(part_id)}</text>'
            )
            index_rows.append({
                'part_id': part_id, 'sheet': number,
                'body_name': name, 'body_label': record['body_label'],
                'assembly': record['assembly'],
                'good_face_normal': record['good_face_normal'],
                'x_mm': placement['x_mm'], 'y_mm': placement['y_mm'],
                'rotation_deg': placement['rotation_deg'],
                'width_mm': placement['width_mm'],
                'height_mm': placement['height_mm'],
                'dxf_file': record['dxf_file'],
            })
        compound = Part.makeCompound(shapes)
        if len(compound.Wires) != expected_wires:
            raise ValueError(f'Lost section wires on sheet {number}')
        feature.Shape = compound
        path = os.path.join(destination, f'sheet-{number:02d}-cut.dxf')
        importDXF.export([feature], path)
        if os.path.getsize(path) < 300:
            raise ValueError(f'Empty sheet DXF: {number}')
        W, H = layout['sheet_width_mm'], layout['sheet_height_mm']
        svg = (f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}mm" height="{H}mm" '
               f'viewBox="0 0 {W} {H}">'
               f'<rect width="{W}" height="{H}" fill="white" stroke="#111827" stroke-width="2"/>'
               f'<g transform="translate(0 {H}) scale(1 -1)">')
        # Cut geometry is mirrored vertically for SVG's screen coordinate system.
        for element in svg_elements:
            if element.startswith('<path'):
                svg += element
        svg += '</g>'
        for element in svg_elements:
            if element.startswith('<text'):
                svg += element
        svg += '</svg>'
        with open(os.path.join(destination, f'sheet-{number:02d}-map.svg'), 'w') as stream:
            stream.write(svg)
        total += len(sheet['parts'])
        if number % 10 == 0 or number == len(layout['sheets']):
            print('SHEETS_EXPORTED', number, len(layout['sheets']), flush=True)
    with open(os.path.join(destination, 'sheet-index.csv'), 'w', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=list(index_rows[0]))
        writer.writeheader()
        writer.writerows(index_rows)
    if total != len(records):
        raise ValueError(f'Placed {total} of {len(records)} bodies')
    print('DONE',len(layout['sheets']),'SHEETS',total,'BODIES',flush=True)
    App.closeDocument(out_doc.Name)
    App.closeDocument(doc.Name)


if __name__ in ('__main__', 'export_laser_sheets'):
    manifest = os.environ.get('LASER_MANIFEST_JSON')
    layout = os.environ.get('LASER_LAYOUT_JSON')
    destination = os.environ.get('LASER_SHEETS_DIR')
    if not all((manifest, layout, destination)):
        raise SystemExit('Set LASER_MANIFEST_JSON, LASER_LAYOUT_JSON, and LASER_SHEETS_DIR')
    generate(manifest, layout, destination)
