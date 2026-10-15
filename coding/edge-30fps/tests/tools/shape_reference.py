"""M10 integer geometry on the selected final edge map (x,y coordinates)."""
import numpy as np

# Clockwise, with screen y increasing downwards.
DIRECTIONS = ((-1,-1),(0,-1),(1,-1),(1,0),(1,1),(0,1),(-1,1),(-1,0))


def cross(a, b, p):
    return (b[0]-a[0])*(p[1]-a[1])-(b[1]-a[1])*(p[0]-a[0])


def distance2(a, b):
    return (a[0]-b[0])**2+(a[1]-b[1])**2


def trace(component, start):
    """Follow the outer boundary; stop only when the initial directed edge recurs."""
    point, back, first = start, (start[0]-1,start[1]), None
    contour = []
    for _ in range(min(8*len(component)+1,8193)):
        base = DIRECTIONS.index((back[0]-point[0],back[1]-point[1]))
        for step in range(1,9):
            index = (base+step)%8
            dx,dy = DIRECTIONS[index]
            nxt = point[0]+dx,point[1]+dy
            if nxt in component:
                break
        else:
            return []
        if first is not None and point == start and nxt == first:
            return contour
        if first is None:
            first = nxt
        contour.append(point)
        dx,dy = DIRECTIONS[(index-1)%8]
        back = point[0]+dx,point[1]+dy
        point = nxt
    return []


def geometry(component, contour, w, h, minimum=64, maximum=400, margin=16):
    xs,ys = zip(*component)
    xmin,xmax,ymin,ymax = min(xs),max(xs),min(ys),max(ys)
    bw,bh = xmax-xmin,ymax-ymin
    result = dict(kind=0, box=[xmin,ymin,xmax,ymax], pixels=len(component), points=len(contour))
    if min(bw,bh)<minimum or xmin<margin or ymin<margin or xmax>=w-margin or ymax>=h-margin or not contour:
        return result
    twice_area, perimeter = 0,0
    for a,b in zip(contour,contour[1:]+contour[:1]):
        twice_area += a[0]*b[1]-a[1]*b[0]
        perimeter += 362 if a[0]!=b[0] and a[1]!=b[1] else 256
    twice_area = abs(twice_area)
    result.update(area2=twice_area, perimeter_q8=perimeter)
    if twice_area == 0 or len(contour)>8192:
        return result
    cx2,cy2 = xmin+xmax,ymin+ymax
    radial = [(2*x-cx2)**2+(2*y-cy2)**2 for x,y in component]
    rmin,rmax = min(radial),max(radial)
    # 4*pi*A/P^2, pi = 355/113. All decisions use integer cross products.
    circularity_numerator = 2*355*twice_area*65536
    circularity_denominator = 113*perimeter*perimeter
    if (max(bw,bh)<=maximum and min(bw,bh)*100>=max(bw,bh)*90
            and (rmax-rmin)*100<=(rmax+rmin)*10
            and circularity_numerator*100>=circularity_denominator*80
            and circularity_numerator*100<=circularity_denominator*115):
        result['kind'] = 1
        return result
    seed = contour[0]
    a = max(component,key=lambda p:(distance2(seed,p),-p[1],-p[0]))
    c = max(component,key=lambda p:(distance2(a,p),-p[1],-p[0]))
    b = max(component,key=lambda p:(cross(a,c,p),-p[1],-p[0]))
    d = min(component,key=lambda p:(cross(a,c,p),p[1],p[0]))
    corners = [a,b,c,d]
    result['corners'] = corners
    side2 = [distance2(corners[i],corners[(i+1)%4]) for i in range(4)]
    result['side2'] = side2
    if min(side2)<minimum**2 or min(side2)>maximum**2:
        return result
    for i in range(4):
        p,q,r = corners[i],corners[(i+1)%4],corners[(i+2)%4]
        dot = (q[0]-p[0])*(r[0]-q[0])+(q[1]-p[1])*(r[1]-q[1])
        if dot*dot*100>side2[i]*side2[(i+1)%4]*4:
            result['reject'] = 'angle'
            return result
    polygon_area2 = abs(sum(corners[i][0]*corners[(i+1)%4][1]-corners[i][1]*corners[(i+1)%4][0] for i in range(4)))
    if twice_area*100<polygon_area2*90 or twice_area*100>polygon_area2*115:
        return result
    tolerance = max(3,min(bw,bh)//32)
    for p in component:
        matched = False
        for i in range(4):
            a,b = corners[i],corners[(i+1)%4]
            dot = (p[0]-a[0])*(b[0]-a[0])+(p[1]-a[1])*(b[1]-a[1])
            if (cross(a,b,p)**2<=side2[i]*tolerance*tolerance
                    and -tolerance*maximum<=dot<=side2[i]+tolerance*maximum):
                matched = True
                break
        if not matched:
            result['reject'] = 'residual'
            result['residual_point'] = p
            return result
    result.update(kind=2,corners=corners)
    return result


def row_components(edge):
    """Label horizontal runs by overlap with the previous row (8-connectivity)."""
    parent, runs, previous = [], [], []

    def root(label):
        while parent[label] != label:
            parent[label] = parent[parent[label]]
            label = parent[label]
        return label

    for y, row in enumerate(edge):
        transitions = np.flatnonzero(np.diff(np.r_[False, row, False]))
        current = []
        first = 0
        for left, stop in zip(transitions[::2], transitions[1::2]):
            left, right = int(left), int(stop)-1
            label = len(parent)
            parent.append(label)
            runs.append((left, right, y))
            current.append((left, right, label))
            while first < len(previous) and previous[first][1] < left-1:
                first += 1
            for a, b, old in previous[first:]:
                if a > right+1:
                    break
                one, two = root(label), root(old)
                parent[max(one, two)] = min(one, two)
        previous = current
    groups = {}
    for label, (left, right, y) in enumerate(runs):
        groups.setdefault(root(label), set()).update((x, y) for x in range(left, right+1))
    return [(groups[label], (runs[label][0], runs[label][2])) for label in sorted(groups)]


def recognize(edge, minimum=64, maximum=400, margin=16):
    edge = np.asarray(edge,dtype=bool)
    h,w = edge.shape
    candidates = []
    for component, seed in row_components(edge):
        contour = trace(component,seed)
        candidates.append(geometry(component,contour,w,h,minimum,maximum,margin))
    targets = [c for c in candidates if c['kind']]
    return dict(targets=targets[:4], overflow=len(targets)>4, candidates=candidates)
