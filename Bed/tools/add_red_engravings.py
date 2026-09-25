"""Register smooth filigree SVG paths on the face-up laser DXFs."""
import hashlib, json, os, sys
from collections import defaultdict
import xml.etree.ElementTree as ET
from vector_filigree import read_svg, to_polyline

BED_ROOT=os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ASSETS=os.environ.get('LASER_ASSETS_DIR',os.path.join(BED_ROOT,'assets'))
SOURCE_SVG='filigree.svg'
SOURCE_SHA256='f90250ba8d5efa11dc8a2736631d702947776d43c4b14f68260c0f27ce8814bb'
FULL_SOURCE_SIZE=(897.53418,606.05786)
SMALL_SOURCE_SIZE=(454.0,323.0)
# These are the SVG's original top-left motif contours. The right motif is
# its horizontal mirror, matching the two saved bedside preview images.
LEFT_CONTOUR_RANGE=range(325,438)

def vector_artwork():
    path=os.path.join(ASSETS,SOURCE_SVG)
    if hashlib.sha256(open(path,'rb').read()).hexdigest()!=SOURCE_SHA256:
        raise ValueError('Filigree SVG changed; recheck the bedside motif contour selection')
    root=ET.parse(path).getroot()
    viewbox=tuple(float(x) for x in root.attrib['viewBox'].split())
    if viewbox!=(0.0,0.0,*FULL_SOURCE_SIZE):
        raise ValueError(('Unexpected filigree SVG viewBox',viewbox))
    contours=read_svg(path)
    if len(contours)!=505:
        raise ValueError(('Filigree contour ordering changed',len(contours)))
    # Sampling bound is in SVG source units. At the largest installed scale,
    # 0.08 source units is under 0.031 mm from the original Bezier curves.
    polys=[to_polyline(contour,tolerance=.08) for contour in contours]
    small_left=polys[LEFT_CONTOUR_RANGE.start:LEFT_CONTOUR_RANGE.stop]
    if len(small_left)!=113 or any(
        not (0<=x<=454 and 0<=y<=323)
        for poly in small_left for x,y in poly
    ):
        raise ValueError('Top-left vector motif no longer fits its image plane')
    small_right=[[(SMALL_SOURCE_SIZE[0]-x,y) for x,y in poly]
                 for poly in small_left]
    data={
        'FiligreeImageSource':(*FULL_SOURCE_SIZE,polys),
        'FiligreeSmallLeftSource':(*SMALL_SOURCE_SIZE,small_left),
        'FiligreeSmallRightSource':(*SMALL_SOURCE_SIZE,small_right),
    }
    print('SVG_VECTORS',[(k,len(v[2]),sum(len(p) for p in v[2])) for k,v in data.items()],flush=True)
    return data

def projected_min(name,vector,meta):
    axis=next(i for i,x in enumerate(vector) if abs(x)>.5)
    low,high=meta[name]['bbox'][axis]
    return low if vector[axis]>0 else -high

def engraving_points(links,records,meta):
    image_data=vector_artwork()
    result=defaultdict(list)
    for link in links:
        body=link['front']+'Body'
        rec=records[body]
        u,v=rec['view_u'],rec['view_v']
        min_u=projected_min(body,u,meta);min_v=projected_min(body,v,meta)
        pixel_w,pixel_h,loops=image_data[link['image']]
        src_w,src_h=link['source_width'],link['source_height']
        scale=link['scale'];position=link['position']
        axis=rec['good_face_normal'][1]
        for loop in loops:
            points=[]
            for px,py in loop:
                lx=(px/pixel_w-.5)*src_w*scale
                ly=(.5-py/pixel_h)*src_h*scale
                world=[position[0],position[1],position[2]]
                if axis=='X':world[1]+=lx
                else:world[0]+=lx
                world[2]+=ly
                x=sum(u[i]*world[i] for i in range(3))-min_u
                y=sum(v[i]*world[i] for i in range(3))-min_v
                points.append((x,y))
            if min(x for x,y in points)<-1e-4 or min(y for x,y in points)<-1e-4 or \
               max(x for x,y in points)>rec['width_mm']+1e-4 or \
               max(y for x,y in points)>rec['height_mm']+1e-4:
                raise ValueError(('Engraving outside face',body,link['name']))
            result[body].append(points)
    return result

def poly_entities(polys):
    chunks=[]
    for poly in polys:
        values=['  0','LWPOLYLINE','  8','ENGRAVE_RED',' 62','1',' 90',str(len(poly)),' 70','1']
        for x,y in poly:values+=[' 10',f'{x:.6f}',' 20',f'{y:.6f}']
        chunks.append('\n'.join(values)+'\n')
    return ''.join(chunks)

def add_to_dxf(path,polys):
    with open(path) as stream:content=stream.read()
    marker='  0\nENDSEC\n  0\nSECTION\n  2\nOBJECTS'
    if marker not in content:raise ValueError(('DXF entities ending missing',path))
    previous=content.find('  0\nLWPOLYLINE\n  8\nENGRAVE_RED\n 62\n1\n 90\n')
    if previous>=0:
        end=content.find(marker,previous)
        if end<0:raise ValueError(('Engraving end missing',path))
        content=content[:previous]+content[end:]
    layer_start=content.find('  0\nTABLE\n  2\nLAYER\n')
    layer_end=content.find('  0\nENDTAB\n',layer_start)
    if layer_start<0 or layer_end<0:raise ValueError(('DXF layer table missing',path))
    table=content[layer_start:layer_end]
    if '\nENGRAVE_RED\n' not in table:
        import re
        table_handle=re.search(r'\n  5\n([A-Fa-f0-9]+)\n',table).group(1)
        table=re.sub(r'(\n 70\n)3(\n)',r'\g<1>4\g<2>',table,count=1)
        table+=('  0\nLAYER\n  5\nFFFFF0\n330\n'+table_handle+
                '\n100\nAcDbSymbolTableRecord\n100\nAcDbLayerTableRecord\n'
                '  2\nENGRAVE_RED\n 70\n0\n 62\n1\n  6\nCONTINUOUS\n')
        content=content[:layer_start]+table+content[layer_end:]
    content=content.replace(marker,poly_entities(polys)+marker,1)
    with open(path,'w') as stream:stream.write(content)

def placed(polys,p):
    w=p['width_mm']
    for poly in polys:
        if p['rotation_deg']==90:
            yield [(p['x_mm']+w-y,p['y_mm']+x) for x,y in poly]
        else:yield [(p['x_mm']+x,p['y_mm']+y) for x,y in poly]

def main(profiles_dir,sheets_dir,layout_path,metadata_path,links_path):
    records={r['body_name']:r for r in json.load(open(os.path.join(profiles_dir,'manifest.json')))}
    dxf_dir=os.path.join(profiles_dir,'profiles')
    if not os.path.isdir(dxf_dir):dxf_dir=profiles_dir
    meta={r['name']:r for r in json.load(open(metadata_path))}
    links=json.load(open(links_path))
    paths=engraving_points(links,records,meta)
    for body,polys in paths.items():
        add_to_dxf(os.path.join(dxf_dir,body+'.dxf'),polys)
    layout=json.load(open(layout_path))
    for sheet in layout['sheets']:
        number=sheet['number'];all_polys=[]
        svg=[]
        for p in sheet['parts']:
            if p['body_name'] not in paths:continue
            for poly in placed(paths[p['body_name']],p):
                all_polys.append(poly)
                svg.append('M '+' L '.join(f'{x:.3f} {y:.3f}' for x,y in poly)+' Z')
        if not all_polys:continue
        add_to_dxf(os.path.join(sheets_dir,f'sheet-{number:02d}-cut.dxf'),all_polys)
        map_path=os.path.join(sheets_dir,f'sheet-{number:02d}-map.svg')
        with open(map_path) as stream:content=stream.read()
        previous=content.rfind('<path d="M ')
        if previous>=0 and 'stroke="red"' in content[previous:]:
            end=content.find('</g>',previous)
            if end<0:raise ValueError(('Engraving map end missing',map_path))
            content=content[:previous]+content[end:]
        content=content.replace('</g>',f'<path d="{" ".join(svg)}" fill="none" stroke="red" stroke-width="0.3"/></g>',1)
        with open(map_path,'w') as stream:stream.write(content)
    print('ENGRAVED',len(links),'MOTIFS',len(paths),'FACE_DXFS',flush=True)

if __name__=='__main__':main(*sys.argv[1:6])
