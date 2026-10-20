"""Freeze exact projection-char stages and measure a bounded flood-fill queue."""
from collections import deque
import argparse
import hashlib
import json
from pathlib import Path
import sys
import cv2
import numpy as np

ROOT=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(ROOT/'tools/blue_plate'))
import baseline as b
SOURCE=ROOT/'tmp/blue-plate-normal-g1/integer-geometry-solver'
OUT=ROOT/'tmp/blue-plate-char-segment'
BASELINE_SHA='2329329c2b90f22bb7554713b36c4771d90a015d73bdc4ee4233319b574e0a89'

def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()

def threshold(gray):
    hist=np.bincount((gray.ravel()>>3),minlength=32).tolist()
    n=sum(hist);total=sum(i*v for i,v in enumerate(hist));count=moment=0;best=None;bn=0;bd=1
    for t in range(31):
        count+=hist[t];moment+=t*hist[t]
        if count==0 or count==n:continue
        num=(moment*n-total*count)**2;den=count*(n-count)
        if best is None or num*bd>bn*den:best=t;bn=num;bd=den
    return best

def flood_components(mask):
    """Clear a visited bitmap when enqueuing, so a pixel enters the queue once."""
    remaining=mask.copy();components=[];peak=0
    for address in np.flatnonzero(mask):
        y,x=divmod(int(address),224)
        if not remaining[y,x]:continue
        queue=deque([(x,y)]);remaining[y,x]=0;points=[]
        while queue:
            peak=max(peak,len(queue));xx,yy=queue.popleft();points.append((xx,yy))
            for dy,dx in [(-1,-1),(-1,0),(-1,1),(0,-1),(0,1),(1,-1),(1,0),(1,1)]:
                nx,ny=xx+dx,yy+dy
                if 0<=nx<224 and 0<=ny<64 and remaining[ny,nx]:
                    remaining[ny,nx]=0;queue.append((nx,ny))
        xs,ys=zip(*points)
        components.append(dict(rect=(min(xs),min(ys),max(xs)-min(xs)+1,max(ys)-min(ys)+1),area=len(points),seed=[x,y],points=points))
    return components,peak

def stages(gray):
    t=threshold(gray)
    raw=np.zeros((64,224),np.uint8) if t is None else ((gray>>3)>t).astype(np.uint8)
    raw[:5]=0;raw[-5:]=0;raw[:,:4]=0;raw[:,-4:]=0
    transitions=np.count_nonzero(np.diff(raw.astype(np.int16),axis=1),axis=1)
    keep=(transitions>=8)&(raw.sum(axis=1)<=190)
    rows=raw*keep[:,None]
    components,peak=flood_components(rows)
    count,labels,stats,_=cv2.connectedComponentsWithStats(rows,connectivity=8)
    assert sorted([(*c['rect'],c['area']) for c in components])==sorted(map(tuple,stats[1:].tolist()))
    clean=rows.copy();records=[]
    for c in components:
        x,y,w,h=c['rect'];rim=False;preceding=[];pitch4=None
        if x>=210 and w<=10:
            preceding=sorted(a['rect'] for a in components if a['rect'][0]+a['rect'][2]<=x and a['rect'][3]>=23 and 3<=a['rect'][2]<=36)[-6:]
            if len(preceding)==6:
                c2=[2*a+cw for a,cy,cw,ch in preceding];gaps=sorted(c2[i+1]-c2[i] for i in range(1,5));pitch4=gaps[1]+gaps[2]
                rim=68<=pitch4<=152 and 8*(2*x+w-c2[-1])<3*pitch4
        remove=h<12 or rim
        if remove:
            for xx,yy in c['points']:clean[yy,xx]=0
        records.append(dict(rect=c['rect'],area=c['area'],seed=c['seed'],remove=remove,rim=rim,preceding=preceding,pitch4=pitch4))
    projection=clean.sum(axis=0);cuts=[4];rects=[];char_thresholds=[];chars=[];failure=None
    if t is None:failure='global_single_bin'
    if failure is None:
        for center in [34,70,101,132,163,194]:
            cut=min(range(center-9,center+10),key=lambda x:(int(projection[x]),abs(x-center),x))
            if projection[cut]>8:failure='no_valley';break
            cuts.append(cut)
    if failure is None:
        cuts.append(220)
        for left,right in zip(cuts,cuts[1:]):
            yy,xx=np.where(clean[:,left:right])
            if not len(xx) or yy.max()-yy.min()<23:failure='short_or_empty';break
            x0,x1=left+int(xx.min()),left+int(xx.max())+1;y0,y1=int(yy.min()),int(yy.max())+1
            if x1-x0>36 or y1-y0<23:failure='wide_or_short';break
            rects.append([x0,y0,x1-x0,y1-y0])
    if failure is None:
        for x,y,w,h in rects:
            roi=gray[max(0,y-2):min(64,y+h+2),x:x+w];ct=threshold(roi)
            if ct is None:failure='char_single_bin';break
            char_thresholds.append(ct);chars.append(((roi>>3)>ct).astype(np.uint8))
    if failure is not None:chars=[]
    return dict(threshold=t,row_keep=keep.astype(int).tolist(),components=records,queue_peak=peak,cuts=cuts,rects=rects,
                char_thresholds=char_thresholds,failure=failure),rows,clean,chars

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--q32',action='store_true');args=parser.parse_args()
    prefix='q32-' if args.q32 else ''
    OUT.mkdir(parents=True,exist_ok=True)
    assert sha(Path(b.__file__))==BASELINE_SHA
    manifest=json.loads((SOURCE/'candidates.json').read_text(encoding='utf8'))
    assert len(manifest)==656 and all(r['split'] in ['development','validation'] for r in manifest)
    plates=np.load(SOURCE/'candidate-plates.npz')['rgb_bgr'];assert plates.shape==(656,64,224,3)
    all_gray=[];all_rows=[];all_clean=[];records=[];char_pixels=[];max_eligible=0
    source_hashes={};last_path=None;rgb_differences=0;rgb_max_error=0
    if args.q32:
        import geometry_sampler as geometry
        matrices=np.load(SOURCE/'candidate-plates.npz')['inverse_q32']
    for i,(entry,plate) in enumerate(zip(manifest,plates)):
        assert entry['plate_index']==i
        if args.q32:
            if entry['path']!=last_path:
                path=ROOT/entry['path'];source_hashes[entry['path']]=sha(path)
                original=b.read_image(path);h,w=original.shape[:2];scale=min(1280/w,720/h)
                nw,nh=round(w*scale),round(h*scale);dx,dy=(1280-nw)//2,(720-nh)//2
                image=np.zeros((720,1280,3),np.uint8)
                image[dy:dy+nh,dx:dx+nw]=cv2.resize(original,(nw,nh),interpolation=cv2.INTER_AREA)
                last_path=entry['path']
            sampled,matrix=geometry.sample_integer(image,entry['points'],32,True)
            assert np.array_equal(matrix,matrices[i]),(i,'matrix drift')
            delta=np.abs(sampled.astype(np.int16)-plate.astype(np.int16))
            rgb_differences+=int(np.count_nonzero(delta));rgb_max_error=max(rgb_max_error,int(delta.max()))
            plate=sampled
        p=plate.astype(np.uint16);gray=((p[...,2]*77+p[...,1]*150+p[...,0]*29)>>8).astype(np.uint8)
        record,rows,clean,chars=stages(gray);gold,mask,rects=b.segment(plate,'global','projection-char')
        assert np.array_equal(clean,mask),(i,'mask')
        assert record['rects']==[list(r) for r in rects],(i,'rects')
        assert len(chars)==len(gold) and all(np.array_equal(a,c) for a,c in zip(chars,gold)),(i,'chars')
        record.update(index=i,split=entry['split'],source_path=entry['path'],char_offsets=[])
        for char in chars:
            record['char_offsets'].append([len(char_pixels),*char.shape]);char_pixels.extend(char.ravel().tolist())
        max_eligible=max(max_eligible,sum(c['rect'][3]>=23 and 3<=c['rect'][2]<=36 for c in record['components']))
        all_gray.append(gray);all_rows.append(rows);all_clean.append(clean);records.append(record)
        if i%100==0:print('checked',i,flush=True)
    np.savez_compressed(OUT/f'{prefix}reference.npz',gray=np.array(all_gray),rows=np.array(all_rows),clean=np.array(all_clean),char_pixels=np.array(char_pixels,np.uint8))
    (OUT/f'{prefix}reference.json').write_text(json.dumps(records,ensure_ascii=False,indent=2),encoding='utf8')
    summary=dict(candidates=656,accepted=sum(r['failure'] is None for r in records),queue_peak=max(r['queue_peak'] for r in records),
        max_components=max(len(r['components']) for r in records),max_eligible_components=max_eligible,
        max_foreground=max(int(m.sum()) for m in all_rows),heldout_consumed=0,
        sources={str(p.relative_to(ROOT)):sha(p) for p in [Path(b.__file__),SOURCE/'candidates.json',SOURCE/'candidate-plates.npz',Path(__file__)]})
    summary['sampling']='integer Q16 corner solver, Q32 matrix and sampling' if args.q32 else 'frozen OpenCV warp'
    summary['input_gray_sha256']=hashlib.sha256(np.array(all_gray).tobytes()).hexdigest()
    summary['reference_npz_sha256']=sha(OUT/f'{prefix}reference.npz')
    if args.q32:
        assert rgb_differences==871 and rgb_max_error==4,(rgb_differences,rgb_max_error)
        summary.update(rgb_differences=rgb_differences,rgb_max_error=rgb_max_error,source_images_sha256=source_hashes,
                       geometry_source_sha256=sha(Path(geometry.__file__)))
    (OUT/f'{prefix}resource-audit.json').write_text(json.dumps(summary,indent=2),encoding='utf8')
    print({k:v for k,v in summary.items() if k not in ['source_images_sha256','sources']},flush=True)

if __name__=='__main__':main()
