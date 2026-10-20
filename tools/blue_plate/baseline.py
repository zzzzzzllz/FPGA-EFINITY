"""G1 algorithm baseline. OpenCV geometry is a diagnostic, not RTL equivalence.

Run from the repository root after prepare_data.py. No test label enters locate,
segment or classify. Oracle crops are scored separately and never count as detection.
"""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import time

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / 'tmp/blue-plate-g1'
PROVINCES = '皖沪津渝冀晋蒙辽吉黑苏浙京闽赣鲁豫鄂湘粤桂琼川贵云藏陕甘青宁新'
LETTERS = 'ABCDEFGHJKLMNPQRSTUVWXYZ'
ADS = LETTERS + '0123456789'


def read_image(path, gray=False):
    image = cv2.imdecode(np.fromfile(path, dtype=np.uint8), 0 if gray else 1)
    if image is None:
        raise ValueError(f'Cannot decode {path}')
    return image


def otsu32(gray, target=None):
    """Exact integer between-class variance; low threshold wins ties.

    Empty or single-bin data is an explicit failure. Python arbitrary precision
    is intentional: RTL must size the cross products, not silently truncate.
    """
    hist = np.bincount((gray.ravel() >> 3), minlength=32).tolist()
    count, total = sum(hist), sum(i * n for i, n in enumerate(hist))
    weight = moment = best_num = 0
    best_den, best = 1, None
    for threshold in range(31):
        weight += hist[threshold]
        moment += threshold * hist[threshold]
        if weight == 0 or weight == count:
            continue
        num = (moment * count - total * weight) ** 2
        den = weight * (count - weight)
        if best is None or num * best_den > best_num * den:
            best_num, best_den, best = num, den, threshold
    if best is None:
        return None
    return ((gray if target is None else target) >> 3) > best


def binary(gray, mode='global'):
    if mode == 'global':
        return otsu32(gray)
    result = np.zeros(gray.shape, np.uint8)
    # Every pixel is covered, including dimensions not divisible by the grid.
    for yy in np.array_split(np.arange(gray.shape[0]), 2):
        for xx in np.array_split(np.arange(gray.shape[1]), 4):
            tile = otsu32(gray[np.ix_(yy, xx)])
            if tile is not None:
                result[np.ix_(yy, xx)] = tile
    return result


def normalize(mask):
    yy, xx = np.where(mask)
    if len(xx) < 4:
        return None
    tight = mask[yy.min():yy.max()+1, xx.min():xx.max()+1].astype(np.uint8)
    h, w = tight.shape
    scale = min(14 / w, 28 / h)
    nw, nh = max(1, round(w * scale)), max(1, round(h * scale))
    result = np.zeros((32, 16), np.uint8)
    result[(32-nh)//2:(32-nh)//2+nh, (16-nw)//2:(16-nw)//2+nw] = cv2.resize(
        tight, (nw, nh), interpolation=cv2.INTER_NEAREST)
    return result


def feature(mask, metric):
    if metric == 'xor':
        return mask.reshape(-1).astype(np.int16)
    return mask.reshape(8, 4, 8, 2).sum(axis=(1, 3)).reshape(-1).astype(np.int16)


def make_templates(metric, per_class):
    mapping = dict(line.split() for line in (DATA / 'easypr/model/province_mapping').read_text(encoding='utf-8').splitlines() if line.strip())
    classes, arrays, provenance, counts = [], [], [], {}
    cv2.setRNGSeed(701)
    for folder in sorted((DATA / 'characters').iterdir()):
        if not folder.is_dir():
            continue
        char = mapping.get(folder.name, folder.name)
        samples, paths = [], []
        for path in sorted(folder.glob('*')):
            if path.suffix.lower() not in ('.jpg', '.png', '.bmp'):
                continue
            mask = otsu32(read_image(path, True))
            norm = normalize(mask) if mask is not None else None
            if norm is not None:
                samples.append(feature(norm, metric)); paths.append(path)
        if not samples:
            raise ValueError(f'No usable training characters for {char}')
        matrix = np.array(samples, np.float32)
        counts[char] = len(samples)
        k = min(per_class, len(samples))
        _, assignment, centers = cv2.kmeans(matrix, k, None,
            (cv2.TERM_CRITERIA_MAX_ITER | cv2.TERM_CRITERIA_EPS, 40, 0.05),
            3, cv2.KMEANS_PP_CENTERS)
        for c in range(k):
            candidates = np.flatnonzero(assignment.ravel() == c)
            index = int(candidates[np.argmin(((matrix[candidates] - centers[c])**2).sum(axis=1))])
            classes.append(char); arrays.append(samples[index])
            path = paths[index]
            provenance.append(dict(char=char, path=path.relative_to(ROOT).as_posix(),
                                   sha256=hashlib.sha256(path.read_bytes()).hexdigest()))
    if set(classes) != set(PROVINCES + ADS):
        raise ValueError('Training corpus does not cover the 65 required classes')
    return np.array(classes), np.array(arrays), provenance, counts


def classify(mask, position, classes, templates, metric):
    norm = normalize(mask)
    if norm is None:
        return dict(char='?', distance=512, margin=0)
    allowed = PROVINCES if position == 0 else LETTERS if position == 1 else ADS
    distances = np.abs(templates - feature(norm, metric)).sum(axis=1)
    ranked = sorted((int(distances[classes == c].min()), c) for c in allowed)
    best, second = ranked[:2]
    return dict(char=best[1], distance=best[0], margin=second[0]-best[0])


def warp(image, points):
    # Points are clockwise TL, TR, BR, BL. Used only for offline geometry.
    transform = cv2.getPerspectiveTransform(np.float32(points), np.float32([[0,0],[223,0],[223,63],[0,63]]))
    return cv2.warpPerspective(image, transform, (224, 64))


def refine_plate(plate, method='none'):
    if method=='none':
        return plate
    if method=='moment-shear':
        # OpenCV's OCR deskew uses mu11/mu02. A median across separate glyphs
        # estimates shared plate shear without treating one asymmetric letter
        # as evidence that the entire plate is tilted.
        mask=otsu32(cv2.cvtColor(plate,cv2.COLOR_BGR2GRAY))
        if mask is None:
            return plate
        mask=mask.astype(np.uint8);mask[:5]=0;mask[-5:]=0;mask[:,:4]=0;mask[:,-4:]=0
        count,labels,stats,_=cv2.connectedComponentsWithStats(mask,8)
        slopes=[]
        for i in range(1,count):
            x,y,w,h,area=stats[i]
            if h>=23 and 3<=w<=50:
                moments=cv2.moments((labels[y:y+h,x:x+w]==i).astype(np.uint8),binaryImage=True)
                if moments['mu02']>0:
                    slopes.append(moments['mu11']/moments['mu02'])
        if len(slopes)<4:
            return plate
        slope=float(np.median(slopes))
        if not .2<=abs(slope)<=.9 or float(np.median(abs(np.array(slopes)-slope)))>.22:
            return plate
        transform=np.float32([[1,-slope,slope*31.5],[0,1,0]])
        return cv2.warpAffine(plate,transform,(224,64),borderMode=cv2.BORDER_REPLICATE)
    if method=='text-lines':
        # HyperLPR fine mapping gathers glyph bounds at several local thresholds
        # and robustly fits the upper/lower text lines. Keep horizontal extent:
        # the first/last glyph's ink width must not rescale the plate layout.
        gray=cv2.cvtColor(plate,cv2.COLOR_BGR2GRAY).astype(np.float32)
        mean=cv2.boxFilter(gray,-1,(41,41),borderType=cv2.BORDER_REFLECT)
        variance=cv2.boxFilter(gray*gray,-1,(41,41),borderType=cv2.BORDER_REFLECT)-mean*mean
        std=np.sqrt(np.maximum(variance,0))
        boxes=set()
        for factor in (.2,.6,1.,1.4,1.8):
            mask=(gray>mean+factor*std).astype(np.uint8)
            contours,_=cv2.findContours(mask,cv2.RETR_EXTERNAL,cv2.CHAIN_APPROX_SIMPLE)
            for contour in contours:
                x,y,w,h=cv2.boundingRect(contour)
                if h>=23 and w>=3 and ((h>.5*w and 290<w*h<3800) or (h>3*w and w*h<=290)):
                    boxes.add((x,y,w,h))
        if len(boxes)<5 or max(x for x,y,w,h in boxes)-min(x for x,y,w,h in boxes)<110:
            return plate
        bounds=[]
        for lower in (False,True):
            points=np.float32([[x+w if lower else x,y+h if lower else y] for x,y,w,h in boxes])
            vx,vy,cx,cy=cv2.fitLine(points,cv2.DIST_HUBER,0,.01,.01).ravel()
            if abs(vx)<.01:
                return plate
            slope=float(vy/vx)
            if abs(slope)>.4:
                return plate
            bounds.append([float(cy-cx*slope),float(cy+(223-cx)*slope)])
        upper,lower=np.array(bounds)
        if np.any(lower-upper<23) or np.any(lower-upper>60):
            return plate
        source=np.float32([[0,upper[0]-2],[223,upper[1]-2],[223,lower[1]+2],[0,lower[0]+2]])
        target=np.float32([[0,8],[223,8],[223,55],[0,55]])
        transform=cv2.getPerspectiveTransform(source,target)
        return cv2.warpPerspective(plate,transform,(224,64),borderMode=cv2.BORDER_REPLICATE)
    if method=='blue-shear':
        # EasyPR isdeflection/affine estimate skew from the blue plate outline.
        # Use row bands and require both sides to agree before shearing.
        hsv=cv2.cvtColor(plate,cv2.COLOR_BGR2HSV)
        blue=(hsv[:,:,0]>100)&(hsv[:,:,0]<140)&(hsv[:,:,1]>95)
        edges=[]
        for y in (16,32,48):
            band=[]
            for row in blue[y-2:y+3]:
                xx=np.flatnonzero(row)
                if len(xx)>=80:band.append((xx[0],xx[-1]))
            if len(band)<3:
                return plate
            edges.append(np.median(band,axis=0))
        edges=np.array(edges)
        slopes=(edges[2]-edges[0])/32
        if abs(slopes[0]-slopes[1])>.15 or np.max(abs(edges[1]-(edges[0]+edges[2])/2))>4:
            return plate
        slope=float(slopes.mean())
        if not .03<=abs(slope)<=.5:
            return plate
        transform=np.float32([[1,-slope,slope*31.5],[0,1,0]])
        return cv2.warpAffine(plate,transform,(224,64),borderMode=cv2.BORDER_REPLICATE)
    # EasyPR deleteNotArea: middle-area threshold, horizontal-border trimming,
    # and density-window left boundary. Preserve the right edge as upstream does.
    gray=cv2.cvtColor(plate,cv2.COLOR_BGR2GRAY)
    mask=otsu32(gray[9:54,33:190],gray)
    if mask is None:
        return plate
    jumps=np.count_nonzero(np.diff(mask.astype(np.int16),axis=1),axis=1)
    white=mask.sum(axis=1)
    invalid=((jumps<7)&(white>224*.15))|(white<4)
    upper=np.flatnonzero(invalid[:32]);lower=np.flatnonzero(invalid[32:])+32
    top=max(0,int(upper[-1])-1) if len(upper) else 0
    bottom=min(63,int(lower[0])+1) if len(lower) else 63
    if top>=bottom:
        return plate
    left=right=0
    for x in range(0,210,3):
        if mask[:,x:x+13].mean()>.15:
            left=x;break
    for x in range(223,13,-2):
        if mask[:,x-12:x+1].mean()>.06:
            right=min(223,x+5);break
    if left>=right:
        return plate
    crop=plate[top:bottom,left:]
    if method=='easypr-pad':
        # Our segmenter clears five outer rows. Keep trimmed glyphs inside that
        # border instead of stretching their strokes onto rows that it removes.
        resized=cv2.resize(crop,(224,48),interpolation=cv2.INTER_AREA)
        return cv2.copyMakeBorder(resized,8,8,0,0,cv2.BORDER_REPLICATE)
    return cv2.resize(crop,(224,64),interpolation=cv2.INTER_AREA)


def locate(image, method='color', refinement='none', model_context=None):
    if method=='dual-local':
        primary=locate(image,'binary-dual',refinement,model_context)
        if primary:
            return primary
    if method in ('mser-text','local-text','dual-local'):
        if model_context is None:
            raise ValueError('MSER character seeds require an explicit linear model context')
        from mser_locator import propose
        proposed=propose(image,model_context,'mser' if method=='mser-text' else 'local')
        for candidate in proposed:candidate['source']='mser-text' if method=='mser-text' else 'local-text'
        return proposed
    hsv_mode=method in ('easypr-color','opened-color','color-sobel','quad-color','quad-guarded','quad-sobel','quad-binary','binary-guarded','binary-rect','binary-dual')
    quad_mode=method in ('quad-color','quad-guarded','quad-sobel','quad-binary','binary-guarded','binary-dual')
    b, g, r = (image[..., i].astype(np.int16) for i in range(3))
    blue = ((b > 55) & (b-r > 20) & (b-g > 10)).astype(np.uint8)
    if method == 'saturation-edge':
        blue = ((b > 40) & (3*b > 4*r) & (3*b > 4*g)).astype(np.uint8)
    if hsv_mode:
        hsv=cv2.cvtColor(image,cv2.COLOR_BGR2HSV)
        value=cv2.equalizeHist(hsv[...,2])
        blue=((hsv[...,0]>100)&(hsv[...,0]<140)&(hsv[...,1]>95)&
              (hsv[...,1]<255)&(value>95)&(value<255)).astype(np.uint8)
    closed = cv2.morphologyEx(blue, cv2.MORPH_CLOSE, np.ones((5, 11), np.uint8))
    if method == 'opened-color':
        blue=cv2.morphologyEx(blue,cv2.MORPH_OPEN,np.ones((3,3),np.uint8))
    if hsv_mode:
        closed=cv2.morphologyEx(blue,cv2.MORPH_CLOSE,np.ones((2,10),np.uint8))
    contours, _ = cv2.findContours(closed, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    contours=[(c,False) for c in contours]
    if method in ('color-sobel','quad-sobel'):
        # EasyPR's sobelOper: horizontal gradient, Otsu, horizontal closing.
        gray=cv2.GaussianBlur(cv2.cvtColor(image,cv2.COLOR_BGR2GRAY),(3,3),0)
        gradient=cv2.convertScaleAbs(cv2.Sobel(gray,cv2.CV_16S,1,0,ksize=3))
        edges=otsu32(gradient)
        if edges is not None:
            joined=cv2.morphologyEx(edges.astype(np.uint8),cv2.MORPH_CLOSE,np.ones((3,17),np.uint8))
            extra,_=cv2.findContours(joined,cv2.RETR_EXTERNAL,cv2.CHAIN_APPROX_SIMPLE)
            contours.extend((c,True) for c in extra)
    proposals=[(c,e,force_rect) for c,e in contours
               for force_rect in ((False,True) if method=='binary-dual' else (False,))]
    candidates = []
    for contour,from_edges,force_rect in proposals:
        rect = cv2.minAreaRect(contour)
        rw, rh = sorted(rect[1], reverse=True)
        if rh < 16 or rw < 80 or not 2.3 < rw/rh < 5.8:
            continue
        x, y, w, h = cv2.boundingRect(contour)
        coverage = float(blue[y:y+h, x:x+w].mean())
        if coverage < .25:
            continue
        if from_edges:
            # Edge bounds enclose strokes; add border allowance before cropping.
            factors=(1.08,1.4) if rect[1][0]>rect[1][1] else (1.4,1.08)
            rect=(rect[0],(rect[1][0]*factors[0],rect[1][1]*factors[1]),rect[2])
        box = cv2.boxPoints(rect)
        if quad_mode and not from_edges and not force_rect:
            hull=cv2.convexHull(contour)
            polygon=cv2.approxPolyDP(hull,.025*cv2.arcLength(hull,True),True)
            if len(polygon)==4:
                proposed=polygon.reshape(4,2).astype(np.float32)
                order=np.argsort(proposed[:,0]);ll,rr=proposed[order[:2]],proposed[order[2:]]
                ll=ll[np.argsort(ll[:,1])];rr=rr[np.argsort(rr[:,1])]
                heights=[np.linalg.norm(ll[1]-ll[0]),np.linalg.norm(rr[1]-rr[0])]
                widths=[np.linalg.norm(rr[0]-ll[0]),np.linalg.norm(rr[1]-ll[1])]
                plausible=min(heights)>0 and min(widths)>0 and max(heights)<1.25*min(heights) and max(widths)<1.2*min(widths)
                if method in ('quad-color','quad-binary','binary-dual') or plausible:
                    box=proposed
        order = np.argsort(box[:, 0]); left, right = box[order[:2]], box[order[2:]]
        left = left[np.argsort(left[:,1])]; right = right[np.argsort(right[:,1])]
        points = np.array([left[0], right[0], right[1], left[1]])
        score=rw*rh*coverage
        if method=='saturation-edge' or hsv_mode:
            crop=refine_plate(warp(image,points),refinement)
            gray=cv2.cvtColor(crop,cv2.COLOR_BGR2GRAY).astype(np.int16)
            edge_count=np.count_nonzero(abs(np.diff(gray,axis=1))>20,axis=1)
            text_rows=np.count_nonzero((edge_count>14)&(edge_count<85))
            if method in ('quad-binary','binary-guarded','binary-rect','binary-dual'):
                # EasyPR validates plate rows by transitions after thresholding;
                # a fixed gray-gradient threshold drops low-contrast text.
                text=otsu32(gray.astype(np.uint8))
                if text is None:
                    continue
                jumps=np.count_nonzero(np.diff(text.astype(np.int16),axis=1),axis=1)
                text_rows=np.count_nonzero((jumps>=16)&(jumps<=45))
            if text_rows<16:
                continue
            score=text_rows*coverage/(1+abs(rw/rh-3.5))
        bounds=[x,y,x+w,y+h]
        if from_edges:
            bounds=[int(np.floor(points[:,0].min())),int(np.floor(points[:,1].min())),
                    int(np.ceil(points[:,0].max()))+1,int(np.ceil(points[:,1].max()))+1]
        candidates.append(dict(box=bounds, points=points, score=score))
    ranked=sorted(candidates,key=lambda c:c['score'],reverse=True)
    if method=='binary-dual':
        unique={}
        for candidate in ranked:
            key=tuple(np.round(candidate['points'],1).ravel())
            unique.setdefault(key,candidate)
        ranked=list(unique.values())
    return ranked[:2]


def segment(plate, mode, method='component'):
    gray = ((plate[...,2].astype(np.uint16)*77 + plate[...,1].astype(np.uint16)*150 + plate[...,0].astype(np.uint16)*29) >> 8).astype(np.uint8)
    mask = binary(gray, mode)
    if mask is None:
        return [], np.zeros(gray.shape, np.uint8), []
    mask = mask.astype(np.uint8)
    mask[:5] = 0; mask[-5:] = 0; mask[:,:4] = 0; mask[:,-4:] = 0
    # Remove bright horizontal border rows without erasing letter strokes.
    transitions = np.count_nonzero(np.diff(mask.astype(np.int16),axis=1),axis=1)
    for y in range(mask.shape[0]):
        if transitions[y] < 8 or mask[y].sum() > 190:
            mask[y] = 0
    if method in ('projection','projection-char','adaptive-char','anchor-char'):
        # Plate layout supplies a search window, never the final cut. Each cut
        # needs a measured valley; touching/occluded characters fail explicitly.
        count, labels, stats, _ = cv2.connectedComponentsWithStats(mask, 8)
        for i in range(1,count):
            x,y,w,h,area = stats[i]
            rim=False
            if x>=210 and w<=10:
                # A shifted narrow final glyph can also reach the right edge.
                # Remove a rim only when six preceding text components already
                # exist and this extra component is closer than a glyph pitch.
                preceding=sorted((int(a),int(b),int(c),int(d)) for a,b,c,d,n in stats[1:]
                                 if a+c<=x and d>=23 and 3<=c<=36)
                if len(preceding)>=6:
                    centers=np.array([a+c/2 for a,b,c,d in preceding[-6:]])
                    pitch=float(np.median(np.diff(centers)[1:]))
                    rim=(17<=pitch<=38 and x+w/2-centers[-1]<.75*pitch)
            if h < 12 or rim:
                mask[labels==i] = 0
        projection = mask.sum(axis=0)
        cuts=[4]
        centers=[34,70,101,132,163,194]
        radius=9;end=220
        if method=='anchor-char':
            # EasyPR anchors the sequence on its second (alphabetic) symbol.
            # Require six distinct, aligned alphanumeric components; their
            # actual gaps determine cuts, independent of the last glyph width.
            tall=sorted((int(x),int(y),int(w),int(h)) for x,y,w,h,area in stats[1:]
                        if h>=23 and 3<=w<=36 and not (x>=210 and w<=10))
            if len(tall)<6:
                return [],mask,[]
            anchors=tall[-6:]
            xs=np.array([x+w/2 for x,y,w,h in anchors])
            ys=np.array([y+h/2 for x,y,w,h in anchors])
            heights=[h for x,y,w,h in anchors]
            pitch=float(np.median(np.diff(xs)[1:]))
            if not (22<=xs[0]<=80 and 17<=pitch<=38 and min(heights)>=.65*max(heights)):
                return [],mask,[]
            if np.ptp(ys)>.3*max(heights) or np.any(np.diff(xs)<.45*pitch) or np.any(np.diff(xs)>1.8*pitch):
                return [],mask,[]
            if any(a[0]+a[2]>=c[0] for a,c in zip(anchors,anchors[1:])):
                return [],mask,[]
            cuts=[max(4,round(anchors[0][0]-1.25*pitch)),anchors[0][0]-1]
            cuts.extend((a[0]+a[2]+c[0])//2 for a,c in zip(anchors,anchors[1:]))
            end=min(220,anchors[-1][0]+anchors[-1][2]+1)
            centers=[]
        if method=='adaptive-char':
            foreground=np.flatnonzero(projection>=3)
            if len(foreground)==0 or foreground[-1]-foreground[0]<110:
                return [],mask,[]
            start,end_content=int(foreground[0]),int(foreground[-1])
            span=end_content-start
            centers=[start+((c-6)*span+102)//205 for c in centers]
            radius=max(5,(9*span+102)//205)
            cuts=[max(4,start-1)];end=min(220,end_content+2)
        for center in centers:
            xs=np.arange(max(4,center-radius),min(220,center+radius+1))
            minimum=projection[xs].min()
            if minimum>8:
                return [],mask,[]
            tied=xs[projection[xs]==minimum]
            cuts.append(int(tied[np.argmin(abs(tied-center))]))
        cuts.append(end)
        rects=[]
        for left,right in zip(cuts,cuts[1:]):
            yy,xx=np.where(mask[:,left:right])
            if not len(xx) or yy.max()-yy.min()<23:
                return [],mask,rects
            x0,x1=left+int(xx.min()),left+int(xx.max())+1
            y0,y1=int(yy.min()),int(yy.max())+1
            if x1-x0>36 or y1-y0<23:
                return [],mask,rects
            rects.append((x0,y0,x1-x0,y1-y0))
        chars=[mask[y:y+h,x:x+w] for x,y,w,h in rects]
        if method in ('projection-char','adaptive-char','anchor-char'):
            # EasyPR re-thresholds the original gray character after geometry.
            # Preserve pixels suppressed by plate-wide row cleanup.
            chars=[]
            for x,y,w,h in rects:
                roi=gray[max(0,y-2):min(64,y+h+2),x:x+w]
                char=otsu32(roi)
                if char is None:
                    return [],mask,rects
                chars.append(char.astype(np.uint8))
        return chars,mask,rects
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    rects = [cv2.boundingRect(c) for c in contours]
    rects = sorted((x,y,w,h) for x,y,w,h in rects if h >= 23 and 3 <= w <= 36 and x >= 36)
    if len(rects) != 6:
        return [], mask, rects
    heights = [r[3] for r in rects]
    centers = np.array([x+w/2 for x,y,w,h in rects])
    pitch = float(np.median(np.diff(centers)[1:]))
    if min(heights) < max(heights)*.65 or not 19 < pitch < 36:
        return [], mask, rects
    if np.any(np.diff(centers) < 15) or np.any(np.diff(centers) > 49):
        return [], mask, rects
    x,y,w,h = rects[0]
    width = int(np.median([r[2] for r in rects]))
    chinese_x = max(4, round(centers[0] - pitch - width*.65))
    chinese_end = x-3
    if chinese_end-chinese_x < 12:
        return [], mask, rects
    rects.insert(0, (chinese_x, max(5,y-2), chinese_end-chinese_x, min(54-y,h+4)))
    chars = [mask[y:y+h,x:x+w] for x,y,w,h in rects]
    if any(c.size == 0 or not .08 < float(c.mean()) < .85 for c in chars):
        return [], mask, rects
    return chars, mask, rects


def recognize(plate, mode, classes, templates, metric, segmentation='component', model_context=None):
    chars, mask, rects = segment(plate, mode,segmentation)
    if len(chars) != 7:
        return dict(status='segmentation', raw='', scores=[]), mask, rects
    if model_context is None:
        scores = [classify(c,i,classes,templates,metric) for i,c in enumerate(chars)]
    else:
        from char_model import model
        weights,thresholds=model_context
        scores=[]
        for i,char in enumerate(chars):
            if np.count_nonzero(char)<4:
                return dict(status='segmentation',raw='',scores=[]),mask,rects
            # These are original binary character ROIs. Normalize exactly once.
            vector=model.features(model.normalize(char))
            scores.append(model.decide(model.integer_scores(vector,weights),i,thresholds))
    return dict(status='scored', raw=''.join(s['char'] for s in scores), scores=scores), mask, rects


def candidate_key(attempt):
    result=attempt[1]
    if result['status']!='scored':
        return (1,9999)
    if 'accepted' in result['scores'][0]:
        return (0,-sum(s['accepted'] for s in result['scores']),-min(s['margin'] for s in result['scores']))
    return (0,sum(s['distance'] for s in result['scores']))


def load_samples(image_dir=None):
    seen, records = {}, []
    image_root=(image_dir or DATA / 'images').resolve()
    if not image_root.is_dir():
        raise ValueError(f'Image directory is missing: {image_root}')
    for path in sorted(image_root.glob('*/*.jpg')):
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if digest in seen:
            seen[digest]['duplicate_paths'].append(path.relative_to(ROOT).as_posix())
            continue
        parts = path.stem.split('-')
        ids = [int(n) for n in parts[4].split('_')] if len(parts) == 7 else []
        label = ''
        if len(ids) == 7 and ids[0] < 31 and ids[1] < 24 and all(n < 34 for n in ids[2:]):
            label = PROVINCES[ids[0]] + LETTERS[ids[1]] + ''.join(ADS[n] for n in ids[2:])
        points = [[int(n) for n in pair.split('&')] for pair in parts[3].split('_')] if ids else []
        bounds = [[int(n) for n in pair.split('&')] for pair in parts[2].split('_')] if ids else [[0,0],[0,0]]
        # No timestamp/session information is available. Identity split is not a
        # session-disjoint acceptance test; this limitation is retained in output.
        bucket = int(hashlib.sha256((label or digest).encode()).hexdigest()[:8],16) % 5
        split = 'development' if bucket < 3 else 'validation' if bucket == 3 else 'heldout'
        record = dict(path=path.relative_to(ROOT).as_posix(), sha256=digest, label=label,
                      split=split, subset=path.parent.name, box=bounds[0]+bounds[1],
                      points=points, duplicate_paths=[], session='unknown', real=True)
        records.append(record); seen[digest] = record
    if not records:
        raise ValueError(f'No JPEG inputs under dataset subdirectories: {image_root}')
    return records


def iou(a,b):
    overlap = max(0,min(a[2],b[2])-max(a[0],b[0]))*max(0,min(a[3],b[3])-max(a[1],b[1]))
    union = (a[2]-a[0])*(a[3]-a[1])+(b[2]-b[0])*(b[3]-b[1])-overlap
    return overlap/union if union else 0.


def accepted(result, distance, margin):
    if result['status']=='scored' and 'accepted' in result['scores'][0]:
        return all(s['accepted'] for s in result['scores'])
    return result['status']=='scored' and all(s['distance'] <= distance and s['margin'] >= margin for s in result['scores'])


def summarize(rows, distance, margin):
    counts = Counter(total=len(rows))
    for key in ['labeled','correct','wrong_number','reject','no_candidate','segmentation_failure',
                'classifier_reject','raw_exact','raw_wrong','localized_iou50','localized_iou70',
                'localization_failure_iou50','scored','first_correct_raw','characters_correct_raw',
                'unlabeled_output','unlabeled_reject']:
        counts[key]=0
    for row in rows:
        result = row['result']
        ok = accepted(result,distance,margin)
        if not row['label']:
            counts['unlabeled_output' if ok else 'unlabeled_reject'] += 1
            continue
        counts['labeled'] += 1
        counts['localized_iou50'] += row['iou'] >= .5
        counts['localized_iou70'] += row['iou'] >= .7
        counts['localization_failure_iou50'] += row['iou'] < .5
        counts['raw_exact'] += result['raw'] == row['label']
        counts['correct' if ok and result['raw']==row['label'] else 'wrong_number' if ok else 'reject'] += 1
        counts['no_candidate'] += result['status']=='no_candidate'
        counts['segmentation_failure'] += result['status']=='segmentation'
        if result['raw']:
            counts['scored'] += 1
            counts['raw_wrong'] += result['raw'] != row['label']
            counts['classifier_reject'] += not ok
            counts['first_correct_raw'] += result['raw'][0] == row['label'][0]
            counts['characters_correct_raw'] += sum(a==b for a,b in zip(result['raw'],row['label']))
    return dict(counts)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--metric', choices=['xor','grid'], default='xor')
    parser.add_argument('--templates', type=int, default=3)
    parser.add_argument('--threshold', choices=['global','local'], default='global')
    parser.add_argument('--segmentation', choices=['component','projection','projection-char','adaptive-char','anchor-char'], default='component')
    parser.add_argument('--locator', choices=['color','saturation-edge','easypr-color','opened-color','color-sobel','quad-color','quad-guarded','quad-sobel','quad-binary','binary-guarded','binary-rect','binary-dual','mser-text','local-text','dual-local'], default='color')
    parser.add_argument('--input', choices=['native','letterbox720'], default='native')
    parser.add_argument('--refinement', choices=['none','easypr','easypr-pad','blue-shear','text-lines','moment-shear'], default='none')
    parser.add_argument('--model-dir',type=Path,default=Path(__file__).parent/'char_model/candidate')
    parser.add_argument('--images', type=Path)
    parser.add_argument('--splits', nargs='+', choices=['development','validation','heldout'],default=['development','validation','heldout'])
    parser.add_argument('--classifier',choices=['template','linear'],default='template')
    parser.add_argument('--operating-point',choices=['standard','strict'],default='standard')
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    args.out.mkdir(parents=True,exist_ok=True)
    model_context=None;model_record=None
    if args.classifier=='template':
        classes, templates, provenance, training_counts = make_templates(args.metric,args.templates)
        np.savez_compressed(args.out/'templates.npz',classes=classes,features=templates)
        (args.out/'template-sources.json').write_text(json.dumps(provenance,ensure_ascii=False,indent=2),encoding='utf-8')
    else:
        model_dir=args.model_dir.resolve()
        config=json.loads((model_dir/'interface.json').read_text(encoding='utf8'))
        if args.operating_point=='strict' and 'strict_operating_point' not in config:
            parser.error('Selected model has no strict operating point; use its documented standard thresholds')
        thresholds=config['thresholds' if args.operating_point=='standard' else 'strict_operating_point']
        model_context=(dict(np.load(model_dir/'weights.npz')),thresholds)
        model_record=dict(directory=model_dir.relative_to(ROOT).as_posix(),operating_point=args.operating_point,
                          thresholds=thresholds,weights_sha256=hashlib.sha256((model_dir/'weights.npz').read_bytes()).hexdigest())
        classes=templates=None;training_counts={}
    samples = load_samples(args.images)
    (args.out/'samples.json').write_text(json.dumps(samples,ensure_ascii=False,indent=2),encoding='utf-8')
    rows, previews = [], []
    start=time.perf_counter()
    for index,sample in enumerate(samples):
        if sample['split'] not in args.splits:
            continue
        image=read_image(ROOT/sample['path'])
        sample=sample.copy()
        if args.input=='letterbox720':
            height,width=image.shape[:2]
            scale=min(1280/width,720/height)
            nw,nh=round(width*scale),round(height*scale)
            resized=cv2.resize(image,(nw,nh),interpolation=cv2.INTER_AREA)
            image=np.zeros((720,1280,3),np.uint8)
            dx,dy=(1280-nw)//2,(720-nh)//2
            image[dy:dy+nh,dx:dx+nw]=resized
            # Account for independent integer rounding of width/height.
            sx,sy=nw/width,nh/height
            sample['points']=[[x*sx+dx,y*sy+dy] for x,y in sample['points']]
            x0,y0,x1,y1=sample['box']
            sample['box']=[x0*sx+dx,y0*sy+dy,x1*sx+dx,y1*sy+dy]
        candidates=locate(image,args.locator,args.refinement,model_context)
        attempts=[]
        for candidate in candidates:
            plate=refine_plate(warp(image,candidate['points']),args.refinement)
            result,mask,rects=recognize(plate,args.threshold,classes,templates,args.metric,args.segmentation,model_context)
            attempts.append((candidate,result,plate,mask,rects))
        # Selection depends only on observed scores, never on ground truth.
        attempts.sort(key=candidate_key)
        if attempts:
            candidate,result,plate,mask,rects=attempts[0]
            overlap=iou(candidate['box'],sample['box'])
        else:
            result=dict(status='no_candidate',raw='',scores=[]);overlap=0.
            plate=np.zeros((64,224,3),np.uint8);mask=np.zeros((64,224),np.uint8);rects=[]
        for x,y,w,h in rects:
            cv2.rectangle(plate,(x,y),(x+w,y+h),(0,0,255),1)
        preview=np.vstack([plate,cv2.cvtColor(mask*255,cv2.COLOR_GRAY2BGR)])
        cv2.putText(preview,f'{index:02} {sample["split"]} {result["status"]}',(2,12),0,.35,(0,255,255),1)
        cv2.imwrite(str(args.out/f'{index:02}-auto.png'),preview)
        previews.append(preview)
        row={k:sample[k] for k in ['path','label','split','subset']}
        rows.append(dict(**row,mode='automatic',result=result,iou=overlap,candidates=len(candidates),
                         candidate_source=candidate.get('source','primary') if attempts else 'none',
                         fallback_attempted=args.locator=='dual-local' and (not candidates or any(c.get('source')=='local-text' for c in candidates))))
        if sample['label']:
            # CCPD order BR, BL, TL, TR: oracle rectification is diagnostic only.
            plate=refine_plate(warp(image,np.array(sample['points'])[[2,3,0,1]]),args.refinement)
            result,mask,rects=recognize(plate,args.threshold,classes,templates,args.metric,args.segmentation,model_context)
            for x,y,w,h in rects:cv2.rectangle(plate,(x,y),(x+w,y+h),(0,0,255),1)
            cv2.imwrite(str(args.out/f'{index:02}-oracle.png'),np.vstack([plate,cv2.cvtColor(mask*255,cv2.COLOR_GRAY2BGR)]))
            rows.append(dict(**row,mode='oracle',result=result,iou=1.))
    validation=[r for r in rows if r['mode']=='automatic' and r['split']=='validation' and r['label']]
    # Calibrate on validation only. Favor fewer wrong numbers, then more correct.
    choices=[]
    for distance in (range(40,201,10) if model_context is None else [0]):
        for margin in ([0,2,4,8,12,16,24] if model_context is None else [0]):
            stats=summarize(validation,distance,margin)
            choices.append(((stats.get('wrong_number',0),-stats.get('correct',0),-margin,distance),distance,margin))
    _,distance,margin=min(choices)
    summary=dict(metric=args.metric if args.classifier=='template' else 'linear_score',
                 templates_per_class=args.templates if args.classifier=='template' else None,
                 threshold=args.threshold,segmentation=args.segmentation,locator=args.locator,
                 classifier=args.classifier,model=model_record,
                 training_characters=training_counts,training_identity_metadata='not provided by EasyPR',
                 real_unique=len(samples),synthetic=0,scene_disjoint=False,
                 thresholds=dict(distance=distance if model_context is None else None,margin=margin if model_context is None else None,
                                 calibration_count=len(validation) if model_context is None else 0,
                                 usable=summarize(validation,distance,margin)['correct']>0),
                 input_transform=args.input,
                 refinement=args.refinement,
                 evaluated_splits=args.splits,
                 source_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                 auxiliary_source_sha256=({'mser_locator.py':hashlib.sha256((Path(__file__).parent/'mser_locator.py').read_bytes()).hexdigest()}
                                          if args.locator in ('mser-text','local-text','dual-local') else {}),
                 seconds=time.perf_counter()-start,metrics={})
    for mode in ['automatic','oracle']:
        summary['metrics'][mode]={split:summarize([r for r in rows if r['mode']==mode and r['split']==split],distance,margin)
                                  for split in ['development','validation','heldout']}
    (args.out/'results.json').write_text(json.dumps(rows,ensure_ascii=False,indent=2),encoding='utf-8')
    (args.out/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(summary,ensure_ascii=True,indent=2))


if __name__=='__main__':
    main()
