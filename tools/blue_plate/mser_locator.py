"""Offline character-first detector, informed by EasyPR mserCharMatch.

Uses native OpenCV MSER for research; no claim of FPGA implementation parity.
No plate labels, identities, or known coordinates are detector inputs.
"""
import cv2
import numpy as np
from char_model import model


def propose(image, context, detector='mser'):
    weights,thresholds=context
    gray=cv2.cvtColor(image,cv2.COLOR_BGR2GRAY)
    def regions():
        if detector=='mser':
            pixels,boxes=cv2.MSER_create(5,30,4000).detectRegions(gray)
            yield from zip(pixels,boxes)
        else:
            # Adaptive-mean thresholding replaces an extremal-region tree with
            # four simple scans. Each scan keeps actual connected foreground.
            mean=cv2.boxFilter(gray,cv2.CV_32F,(41,41),borderType=cv2.BORDER_REFLECT)
            for offset in (8,16,24,32):
                count,labels,stats,_=cv2.connectedComponentsWithStats((gray>mean+offset).astype(np.uint8),8)
                for i in range(1,count):
                    x,y,w,h,area=map(int,stats[i])
                    if 23<=h<=80 and 3<=w<=55 and w<=1.05*h:
                        yy,xx=np.where(labels[y:y+h,x:x+w]==i)
                        yield np.column_stack([xx+x,yy+y]),(x,y,w,h)
    b,g,r=(image[:,:,i].astype(np.int16) for i in range(3))
    blue=(b>35)&(b*10>r*12)&(b*10>g*8)
    candidates=[]
    for points,box in regions():
        x,y,w,h=map(int,box)
        if not (23<=h<=80 and 3<=w<=55 and w<=1.05*h):
            continue
        x0,y0=max(0,x-5),max(0,y-4);x1,y1=min(gray.shape[1],x+w+5),min(gray.shape[0],y+h+4)
        if blue[y0:y1,x0:x1].mean()<.2:
            continue
        foreground=gray[points[:,1],points[:,0]]
        if foreground.mean()<gray[y0:y1,x0:x1].mean()+8:
            continue
        mask=np.zeros((h,w),np.uint8);mask[points[:,1]-y,points[:,0]-x]=1
        if not .08<mask.mean()<.85:
            continue
        vector=model.features(model.normalize(mask))
        scores=model.integer_scores(vector,weights)
        result=model.decide(scores,2,thresholds)
        province=model.decide(scores,0,thresholds)
        is_province=province['accepted'] and province['score']>result['score']
        if is_province:result=province
        if result['accepted']:
            candidates.append(dict(rect=(x,y,w,h),center=(x+w/2,y+h/2),margin=result['margin'],province=is_province))
    # Multiple MSER thresholds often describe the same glyph. Keep one seed.
    seeds=[]
    for candidate in sorted(candidates,key=lambda c:-c['margin']):
        x,y,w,h=candidate['rect'];duplicate=False
        for kept in seeds:
            a,b,c,d=kept['rect']
            overlap=max(0,min(x+w,a+c)-max(x,a))*max(0,min(y+h,b+d)-max(y,b))
            if overlap>.6*min(w*h,c*d):duplicate=True;break
        if not duplicate:seeds.append(candidate)
    parent=list(range(len(seeds)))
    def root(i):
        while parent[i]!=i:
            parent[i]=parent[parent[i]];i=parent[i]
        return i
    for i,left in enumerate(seeds):
        for j in range(i):
            right=seeds[j]
            dx=abs(left['center'][0]-right['center'][0]);dy=abs(left['center'][1]-right['center'][1])
            h1,h2=left['rect'][3],right['rect'][3];height=(h1+h2)/2
            if min(h1,h2)>=.7*max(h1,h2) and .2*height<dx<1.6*height and dy<.18*height+.12*dx:
                parent[root(i)]=root(j)
    groups={}
    for i,seed in enumerate(seeds):groups.setdefault(root(i),[]).append(seed)
    proposals=[]
    for group in groups.values():
        if not 5<=len(group)<=7:continue
        group.sort(key=lambda c:c['center'][0])
        centers=np.float32([c['center'] for c in group]);heights=[c['rect'][3] for c in group]
        pitch=float(np.median(np.diff(centers[:,0])));height=float(np.median(heights))
        if not .4*height<=pitch<=1.1*height:continue
        vx,vy,cx,cy=cv2.fitLine(centers,cv2.DIST_HUBER,0,.01,.01).ravel()
        if abs(vx)<.01:continue
        slope=float(vy/vx);intercept=float(cy-slope*cx)
        if abs(slope)>.12:continue
        if max(abs(centers[:,1]-(slope*centers[:,0]+intercept)))>.2*height:continue
        # Six Latin/digit cells follow the province. Their pitch, rather than
        # the narrow last glyph's ink edge, defines the full plate extent.
        left=float(centers[0,0]-1.65*pitch);right=float(centers[0,0]+5.85*pitch)
        if group[0]['province']:left+=pitch;right+=pitch
        top_left=slope*left+intercept-.8*height;bottom_left=top_left+1.6*height
        top_right=slope*right+intercept-.8*height;bottom_right=top_right+1.6*height
        points=np.float32([[left,top_left],[right,top_right],[right,bottom_right],[left,bottom_left]])
        if points[:,0].min()<0 or points[:,1].min()<0 or points[:,0].max()>=image.shape[1] or points[:,1].max()>=image.shape[0]:continue
        proposals.append(dict(points=points,box=[left,min(top_left,top_right),right,max(bottom_left,bottom_right)],
                              score=len(group)*1000+float(np.median([c['margin'] for c in group]))/100))
    return sorted(proposals,key=lambda c:-c['score'])[:2]
