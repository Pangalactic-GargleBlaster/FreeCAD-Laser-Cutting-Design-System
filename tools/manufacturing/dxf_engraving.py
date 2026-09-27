"""Add closed red engraving polylines to FreeCAD's ASCII DXF exports."""

import re


def poly_entities(polys):
    chunks = []
    for poly in polys:
        values = ['  0', 'LWPOLYLINE', '  8', 'ENGRAVE_RED', ' 62', '1',
                  ' 90', str(len(poly)), ' 70', '1']
        for x, y in poly:
            values += [' 10', f'{x:.6f}', ' 20', f'{y:.6f}']
        chunks.append('\n'.join(values) + '\n')
    return ''.join(chunks)


def add_to_dxf(path, polys):
    with open(path) as stream:
        content = stream.read()
    marker = '  0\nENDSEC\n  0\nSECTION\n  2\nOBJECTS'
    if marker not in content:
        raise ValueError(('DXF entities ending missing', path))
    previous = content.find('  0\nLWPOLYLINE\n  8\nENGRAVE_RED\n 62\n1\n 90\n')
    if previous >= 0:
        end = content.find(marker, previous)
        if end < 0:
            raise ValueError(('Engraving end missing', path))
        content = content[:previous] + content[end:]
    layer_start = content.find('  0\nTABLE\n  2\nLAYER\n')
    layer_end = content.find('  0\nENDTAB\n', layer_start)
    if layer_start < 0 or layer_end < 0:
        raise ValueError(('DXF layer table missing', path))
    table = content[layer_start:layer_end]
    if '\nENGRAVE_RED\n' not in table:
        table_handle = re.search(r'\n  5\n([A-Fa-f0-9]+)\n', table).group(1)
        table = re.sub(r'(\n 70\n)3(\n)', r'\g<1>4\g<2>', table, count=1)
        table += ('  0\nLAYER\n  5\nFFFFF0\n330\n' + table_handle +
                  '\n100\nAcDbSymbolTableRecord\n100\nAcDbLayerTableRecord\n'
                  '  2\nENGRAVE_RED\n 70\n0\n 62\n1\n  6\nCONTINUOUS\n')
        content = content[:layer_start] + table + content[layer_end:]
    content = content.replace(marker, poly_entities(polys) + marker, 1)
    with open(path, 'w') as stream:
        stream.write(content)


def placed(polys, placement):
    width = placement['width_mm']
    for poly in polys:
        if placement['rotation_deg'] == 90:
            yield [(placement['x_mm'] + width - y, placement['y_mm'] + x)
                   for x, y in poly]
        else:
            yield [(placement['x_mm'] + x, placement['y_mm'] + y)
                   for x, y in poly]
