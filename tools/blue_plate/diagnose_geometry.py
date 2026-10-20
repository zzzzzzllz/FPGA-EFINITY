"""Attribute full development failures using labels only for diagnostics.

Corner/foreground mappings below never feed the detector or classifier.
Categories use declared geometry thresholds and require visual review.
"""
from collections import Counter
import importlib.util
import json
from pathlib import Path
import sys
import cv2
import numpy as np

ROOT=Path(__file__).resolve().parents[2]
DATA=ROOT/'tmp/blue-plate-normal-g1'
SNAPSHOT=DATA/'candidate-20261018'
sys.path.insert(0,str(SNAPSHOT))
spec=importlib.util.spec_from_file_location('frozen_baseline',SNAPSHOT/'baseline.py')
b=importlib.util.module_from_spec(spec);spec.loader.exec_module(b)
b.ROOT=ROOT;b.DATA=ROOT/'tmp/blue-plate-g1'


def main():
    run=DATA/'full-binary-standard'
    samples=json.loads((run/'samples.json').read_text(encoding='utf8'))
    expected={(r['path'],r['mode']):r for r in json.loads((run/'results.json').read_text(encoding='utf8'))}
    model=SNAPSHOT/'char_model/candidate'
    config=json.loads((model/'interface.json').read_text(encoding='utf8'))
    context=(dict(np.load(model/'weights.npz')),config['thresholds'])
    canonical=np.float32([[0,0],[223,0],[223,63],[0,63]])
    records=[];counts=Counter();contacts={}
    for index,sample in enumerate(samples):
        if sample['split']!='development':continue
        source=b.read_image(ROOT/sample['path']);h,w=source.shape[:2]
        scale=min(1280/w,720/h);nw,nh=round(w*scale),round(h*scale);dx,dy=(1280-nw)//2,(720-nh)//2
        image=np.zeros((720,1280,3),np.uint8);image[dy:dy+nh,dx:dx+nw]=cv2.resize(source,(nw,nh),interpolation=cv2.INTER_AREA)
        gt=np.float32([[x*nw/w+dx,y*nh/h+dy] for x,y in sample['points']])[[2,3,0,1]]
        oracle=b.warp(image,gt);ores,omask,orects=b.recognize(oracle,'global',None,None,'xor','projection-char',context)
        assert ores==expected[sample['path'],'oracle']['result']
        attempts=[]
        for candidate in b.locate(image,'quad-binary'):
            plate=b.warp(image,candidate['points']);result,mask,rects=b.recognize(plate,'global',None,None,'xor','projection-char',context)
            attempts.append((candidate,result,plate,mask,rects))
        attempts.sort(key=b.candidate_key)
        exp=expected[sample['path'],'automatic']['result']
        if b.accepted(exp,0,0) and exp['raw']==sample['label']:continue
        fields={};plate=np.zeros_like(oracle);mask=np.zeros((64,224),np.uint8)
        if not attempts:category='no-candidate'
        else:
            candidate,result,plate,mask,rects=attempts[0];assert result==exp
            transform=cv2.getPerspectiveTransform(np.float32(candidate['points']),canonical)
            relative=transform@cv2.getPerspectiveTransform(canonical,gt)
            mapped=cv2.perspectiveTransform(gt[None,:,:],transform)[0]
            area=float(abs(cv2.contourArea(mapped)))/(224*64)
            rolls=[abs(float(np.degrees(np.arctan2(p[1]-q[1],p[0]-q[0])))) for q,p in [(mapped[0],mapped[1]),(mapped[3],mapped[2])]]
            side_slants=[abs(float(p[0]-q[0]))/max(1,abs(float(p[1]-q[1]))) for q,p in [(mapped[0],mapped[3]),(mapped[1],mapped[2])]]
            missing=[];heights=[]
            if len(orects)==7:
                for x,y,cw,ch in orects:
                    yy,xx=np.where(omask[y:y+ch,x:x+cw])
                    points=np.float32(np.column_stack([xx+x,yy+y]))
                    if not len(points):continue
                    converted=cv2.perspectiveTransform(points[None,:,:],relative)[0]
                    missing.append(float(((converted[:,0]<0)|(converted[:,0]>223)|(converted[:,1]<0)|(converted[:,1]>63)).mean()))
                    heights.append(float(np.ptp(converted[:,1])))
            fields=dict(mapped_truth_corners=mapped.tolist(),truth_area_fraction=area,
                mapped_top_bottom_roll=rolls,side_slants=side_slants,
                missing_foreground_fractions=missing,character_heights=heights)
            if missing and max(missing)>.15:category='cropped-character'
            elif area<.55 or heights and float(np.median(heights))<23:category='oversized-region'
            elif max(rolls)>5 or max(side_slants)>.3:category='slanted-region'
            elif result['status']=='segmentation':category='segmentation-rule'
            else:category='character-score'
        counts[category]+=1
        records.append(dict(index=index,source=sample['path'],label=sample['label'],category=category,
                            result=exp,oracle_result=ores,**fields))
        if len(contacts.setdefault(category,[]))<5:
            title=np.zeros((20,448,3),np.uint8);cv2.putText(title,f'{index}: {category}; auto / oracle',(3,14),0,.4,(255,255,255),1)
            contacts[category].append(np.vstack([title,np.hstack([plate,oracle]),np.hstack([cv2.cvtColor(mask*255,cv2.COLOR_GRAY2BGR),cv2.cvtColor(omask*255,cv2.COLOR_GRAY2BGR)])]))
    out=DATA/'geometry-diagnosis';out.mkdir(exist_ok=True)
    for category,tiles in contacts.items():cv2.imwrite(str(out/(category+'.jpg')),np.vstack(tiles))
    payload=dict(heldout_consumed=0,development_images=304,accepted_correct=134,failed_or_wrong=170,
        note='Geometry attribution is diagnostic, not a new recognition rule or human readability annotation.',
        criteria=dict(cropped='over 15% of any oracle-segmented glyph foreground maps outside automatic ROI',
                      oversized='mapped truth quadrilateral occupies less than 55% of ROI or median glyph height below 23',
                      slanted='mapped truth top/bottom roll over 5 degrees or side dx/dy over 0.3'),counts=dict(counts),records=records)
    (out/'report.json').write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding='utf8')
    print(dict(counts))


if __name__=='__main__':main()
