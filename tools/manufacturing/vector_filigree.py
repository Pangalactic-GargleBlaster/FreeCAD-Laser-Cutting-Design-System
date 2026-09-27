"""Read the original Inkscape filigree path as lines and cubic Beziers."""
import re
import xml.etree.ElementTree as ET

NUMBER = r'[+-]?(?:\d*\.\d+|\d+\.?\d*)(?:[eE][+-]?\d+)?'
TOKENS = re.compile(r'[MmLlCcHhVvZz]|'+NUMBER)
SHIFT=(-35.923496,-32.131756)

def read_svg(path):
    root=ET.parse(path).getroot()
    paths=[e.attrib['d'] for e in root.iter() if e.tag.endswith('path')]
    if len(paths)!=1:raise ValueError(f'Expected one compound path, found {len(paths)}')
    raw=TOKENS.findall(paths[0]);i=0;cmd=None;point=(0.0,0.0);start=None
    contours=[];segments=[]
    def pair():
        nonlocal i
        value=(float(raw[i]),float(raw[i+1]));i+=2;return value
    def offset(a,b):return (a[0]+b[0],a[1]+b[1])
    while i<len(raw):
        if raw[i].isalpha():
            cmd=raw[i];i+=1
        if cmd in ('m','M'):
            value=pair();point=offset(point,value) if cmd=='m' else value
            if segments:raise ValueError('Unclosed contour before move')
            start=point;cmd='l' if cmd=='m' else 'L'
            continue
        if cmd in ('l','L'):
            value=pair();next_point=offset(point,value) if cmd=='l' else value
            segments.append(('L',point,next_point));point=next_point;continue
        if cmd in ('h','H'):
            value=float(raw[i]);i+=1
            next_point=(point[0]+value if cmd=='h' else value,point[1])
            segments.append(('L',point,next_point));point=next_point;continue
        if cmd in ('v','V'):
            value=float(raw[i]);i+=1
            next_point=(point[0],point[1]+value if cmd=='v' else value)
            segments.append(('L',point,next_point));point=next_point;continue
        if cmd in ('c','C'):
            a=pair();b=pair();c=pair()
            if cmd=='c':a,b,c=offset(point,a),offset(point,b),offset(point,c)
            segments.append(('C',point,a,b,c));point=c;continue
        if cmd in ('z','Z'):
            if start is None:raise ValueError('Close without start')
            if abs(point[0]-start[0])+abs(point[1]-start[1])>1e-7:
                segments.append(('L',point,start))
            contours.append(segments);segments=[];point=start;start=None;cmd=None
            continue
        raise ValueError((cmd,raw[i]))
    if segments:raise ValueError('Unclosed final contour')
    shifted=[]
    for contour in contours:
        shifted.append([tuple([segment[0],*[(p[0]+SHIFT[0],p[1]+SHIFT[1]) for p in segment[1:]]]) for segment in contour])
    return shifted

def midpoint(a,b):return ((a[0]+b[0])/2,(a[1]+b[1])/2)
def cubic_points(a,b,c,d,tolerance=.12):
    """Sample a Bezier until its control polygon stays close to its chord."""
    def flat(a,b,c,d):
        dx=d[0]-a[0];dy=d[1]-a[1];length=(dx*dx+dy*dy)**.5
        if length<1e-12:return max(((p[0]-a[0])**2+(p[1]-a[1])**2)**.5 for p in (b,c))
        return max(abs((p[0]-a[0])*dy-(p[1]-a[1])*dx)/length for p in (b,c))
    def split(a,b,c,d,depth):
        if depth>16 or flat(a,b,c,d)<=tolerance:return [d]
        ab=midpoint(a,b);bc=midpoint(b,c);cd=midpoint(c,d)
        abc=midpoint(ab,bc);bcd=midpoint(bc,cd);mid=midpoint(abc,bcd)
        return split(a,ab,abc,mid,depth+1)+split(mid,bcd,cd,d,depth+1)
    return split(a,b,c,d,0)

def to_polyline(contour,tolerance=.12):
    points=[contour[0][1]]
    for seg in contour:
        if seg[0]=='L':points.append(seg[-1])
        else:points.extend(cubic_points(*seg[1:],tolerance=tolerance))
    if len(points)>1 and abs(points[0][0]-points[-1][0])+abs(points[0][1]-points[-1][1])<1e-6:
        points.pop()
    return points

if __name__=='__main__':
    import sys
    contours=read_svg(sys.argv[1])
    lines=[to_polyline(c) for c in contours]
    print('CONTOURS',len(contours),'SEGMENTS',sum(len(c) for c in contours),
          'POINTS',sum(len(c) for c in lines),
          'BOUNDS',min(x for p in lines for x,y in p),min(y for p in lines for x,y in p),
          max(x for p in lines for x,y in p),max(y for p in lines for x,y in p))
