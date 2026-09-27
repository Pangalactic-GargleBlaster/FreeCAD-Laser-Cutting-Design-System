"""Export a face-up, millimetre DXF cut profile for each final panel body."""

import csv
import json
import os
import sys

import FreeCAD as App
import Part
import importDXF


def mate_name(name, pairs):
    for first, second in pairs:
        for ending, replacement in ((first, second), (second, first)):
            if name.endswith(ending):
                return name[:-len(ending)] + replacement
    return None


def face_frame(axis, sign):
    """Return right-handed 2D axes as viewed from the selected face."""
    if axis == 'X':
        return App.Vector(0, sign, 0), App.Vector(0, 0, 1)
    if axis == 'Y':
        return App.Vector(-sign, 0, 0), App.Vector(0, 0, 1)
    return App.Vector(sign, 0, 0), App.Vector(0, 1, 0)


def vector_list(vector):
    return [vector.x, vector.y, vector.z]


def generate(model_path, config_path, destination):
    config = json.load(open(config_path))
    os.makedirs(destination, exist_ok=True)
    profiles_dir = os.path.join(destination, 'profiles')
    os.makedirs(profiles_dir, exist_ok=True)
    doc = App.openDocument(model_path)
    doc.recompute()
    parameter_object = doc.getObject(config['model_parameter_object'])
    if parameter_object is None:
        raise ValueError('Model parameter object was not found')
    parameters = {name: getattr(parameter_object, property_name).Value
                  for name, property_name in config['model_parameter_fields'].items()}
    if os.environ.get('LASER_PARAMETERS_JSON'):
        with open(os.environ['LASER_PARAMETERS_JSON'], 'w') as stream:
            json.dump(parameters, stream, indent=2)
    output_doc = App.newDocument('LaserProfiles')
    export_feature = output_doc.addObject('Part::Feature', 'CutProfile')
    bodies = [o for o in doc.Objects if o.TypeId == 'PartDesign::Body']
    by_name = {b.Name: b for b in bodies}
    expected = config.get('expected_body_count')
    if expected is not None and len(bodies) != expected:
        raise ValueError(f'Expected {expected} bodies, found {len(bodies)}')
    records = []
    for index, body in enumerate(bodies, 1):
        shape = body.Shape
        if shape.isNull() or not shape.isValid():
            raise ValueError(f'Invalid final shape: {body.Name}')
        bounds = shape.BoundBox
        lengths = [bounds.XLength, bounds.YLength, bounds.ZLength]
        thin_index = min(range(3), key=lengths.__getitem__)
        axis = 'XYZ'[thin_index]
        thickness = lengths[thin_index]
        if abs(thickness - parameters['ply_mm']) > 1e-5:
            raise ValueError(f'Unexpected thickness on {body.Name}: {thickness}')
        mate = mate_name(body.Name, config.get('mate_suffix_pairs', []))
        if mate is None:
            normal = next((normal for suffix, normal in
                           config.get('unpaired_suffix_normals', {}).items()
                           if body.Name.endswith(suffix)), None)
            if normal is None or normal[1] != axis:
                raise ValueError(f'Unpaired body has no defined face: {body.Name}')
            sign = 1 if normal[0] == '+' else -1
        else:
            if mate not in by_name:
                raise ValueError(f'Mate missing: {body.Name}, {mate}')
            other = by_name[mate]
            other_bounds = other.Shape.BoundBox
            other_lengths = [other_bounds.XLength, other_bounds.YLength, other_bounds.ZLength]
            if thin_index != min(range(3), key=other_lengths.__getitem__):
                raise ValueError(f'Mate thickness axis differs: {body.Name}, {mate}')
            this_center = (getattr(bounds, axis + 'Min') + getattr(bounds, axis + 'Max')) / 2
            mate_center = (getattr(other_bounds, axis + 'Min') + getattr(other_bounds, axis + 'Max')) / 2
            if abs(this_center - mate_center) < thickness * 0.9:
                raise ValueError(f'Mate does not lie beside body: {body.Name}, {mate}')
            sign = 1 if this_center > mate_center else -1
            gap = max(getattr(bounds, axis + 'Min'), getattr(other_bounds, axis + 'Min')) - min(
                getattr(bounds, axis + 'Max'), getattr(other_bounds, axis + 'Max'))
            if abs(gap) > 1e-5:
                raise ValueError(f'Mate does not touch body: {body.Name}, {mate}, gap {gap}')

        normal = (App.Vector(1, 0, 0) if axis == 'X' else
                  App.Vector(0, 1, 0) if axis == 'Y' else App.Vector(0, 0, 1)) * sign
        face_coordinate = getattr(bounds, axis + ('Max' if sign > 0 else 'Min'))
        visible_area = 0.0
        for face in shape.Faces:
            fn = face.normalAt(0, 0)
            if fn.dot(normal) < 0.999999:
                continue
            if abs(getattr(face.CenterOfMass, axis.lower()) - face_coordinate) > 1e-5:
                continue
            visible_area += face.Area
        cross_section_area = shape.Volume / thickness
        if abs(visible_area - cross_section_area) > max(0.02, cross_section_area * 1e-6):
            raise ValueError(f'Body is not a through-cut extrusion: {body.Name}; '
                             f'face area {visible_area}, volume area {cross_section_area}')

        mid = (getattr(bounds, axis + 'Min') + getattr(bounds, axis + 'Max')) / 2
        positive_normal = App.Vector(abs(normal.x), abs(normal.y), abs(normal.z))
        wires = shape.slice(positive_normal, mid)
        if not wires or not all(wire.isClosed() for wire in wires):
            raise ValueError(f'Open or missing section wires: {body.Name}')
        profile = Part.makeCompound(wires)
        u, v = face_frame(axis, sign)
        matrix = App.Matrix()
        matrix.A11, matrix.A12, matrix.A13 = u.x, u.y, u.z
        matrix.A21, matrix.A22, matrix.A23 = v.x, v.y, v.z
        matrix.A31, matrix.A32, matrix.A33 = normal.x, normal.y, normal.z
        profile.transformShape(matrix, False, False)
        p_bounds = profile.BoundBox
        profile.translate(App.Vector(-p_bounds.XMin, -p_bounds.YMin, -p_bounds.ZMin))
        p_bounds = profile.BoundBox
        if p_bounds.ZLength > 1e-5:
            raise ValueError(f'Profile is not planar: {body.Name}')
        filename = body.Name + '.dxf'
        path = os.path.join(profiles_dir, filename)
        export_feature.Shape = profile
        importDXF.export([export_feature], path)
        if os.path.getsize(path) < 300:
            raise ValueError(f'Empty DXF export: {body.Name}')
        parent = next((p for p in body.InList if p.TypeId == 'App::Part'), None)
        records.append({
            'body_name': body.Name,
            'body_label': body.Label,
            'assembly': parent.Label if parent else '',
            'mate_name': mate or '',
            'good_face_normal': ('+' if sign > 0 else '-') + axis,
            'view_u': vector_list(u),
            'view_v': vector_list(v),
            'thickness_mm': thickness,
            'width_mm': p_bounds.XLength,
            'height_mm': p_bounds.YLength,
            'area_mm2': cross_section_area,
            'wire_count': len(wires),
            'edge_count': len(profile.Edges),
            'dxf_file': 'profiles/' + filename,
        })
        if index % 50 == 0:
            print('EXPORTED', index, len(bodies), flush=True)
    manifest = os.path.join(destination, 'manifest.csv')
    with open(manifest, 'w', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=[k for k in records[0] if k not in ('view_u', 'view_v')])
        writer.writeheader()
        writer.writerows({k: v for k, v in record.items() if k not in ('view_u', 'view_v')} for record in records)
    with open(os.path.join(destination, 'manifest.json'), 'w') as stream:
        json.dump(records, stream, indent=2)
    print('DONE', len(records), 'PROFILES', destination, flush=True)
    App.closeDocument(output_doc.Name)
    App.closeDocument(doc.Name)


if __name__ in ('__main__', 'export_laser_profiles'):
    model = os.environ.get('LASER_MODEL_FILE')
    config = os.environ.get('LASER_CONFIG_JSON')
    destination = os.environ.get('LASER_OUTPUT_DIR')
    if not all((model, config, destination)):
        raise SystemExit('Set LASER_MODEL_FILE, LASER_CONFIG_JSON, and LASER_OUTPUT_DIR')
    generate(model, config, os.path.abspath(destination))
