"""Partition by declared geometry before reading recognition outcomes.

Truth is used only for diagnosis. It never enters baseline.locate/recognize.
"""
import json
import math
from collections import Counter
import cv2
import numpy as np
import baseline as b


def geometry(sample, width, height, mode):
    scale=min(1280/width,720/height) if mode=='letterbox720' else 1.
    br,bl,tl,tr=np.array(sample['points'],float)*scale
    plate_width=float((np.linalg.norm(tr-tl)+np.linalg.norm(br-bl))/2)
    plate_height=float((np.linalg.norm(bl-tl)+np.linalg.norm(br-tr))/2)
    top_angle=math.degrees(math.atan2(tr[1]-tl[1],tr[0]-tl[0]))
    bottom_angle=math.degrees(math.atan2(br[1]-bl[1],br[0]-bl[0]))
    roll=max(abs(top_angle),abs(bottom_angle))
    reasons=[]
    if plate_width<160:reasons.append('width_below_160')
    if plate_width>300:reasons.append('width_above_300')
    if roll>5:reasons.append('roll_above_5deg')
    if plate_height>96:reasons.append('roi_height_above_96')
    if plate_height<32:reasons.append('plate_height_below_required_character_height')
    return dict(width=plate_width,height=plate_height,roll=roll,
                geometric_eligible=not reasons,reasons=reasons,
                character_height_verified=False,sharpness_verified=False,
                note='Geometry only; eligibility is not a claim that characters reach 32 pixels or are readable.')


def main():
    out=b.DATA/'failure-analysis';out.mkdir(exist_ok=True)
    samples=b.load_samples()
    entries=[]
    # Freeze the partition before loading any recognition result.
    for sample in samples:
        if not sample['label']:continue
        image=b.read_image(b.ROOT/sample['path']);height,width=image.shape[:2]
        entries.append(dict(path=sample['path'],label=sample['label'],split=sample['split'],
            native=geometry(sample,width,height,'native'),
            letterbox720=geometry(sample,width,height,'letterbox720')))
    (out/'geometry-before-results.json').write_text(json.dumps(entries,ensure_ascii=False,indent=2),encoding='utf8')
    rows=json.loads((b.DATA/'final-native/results.json').read_text(encoding='utf8'))
    lookup={r['path']:r for r in rows if r['mode']=='automatic'}
    templates=np.load(b.DATA/'final-native/templates.npz')
    classes,features=templates['classes'],templates['features']
    counts=Counter()
    for entry in entries:
        if entry['split']!='development':continue
        image=b.read_image(b.ROOT/entry['path'])
        sample=next(s for s in samples if s['path']==entry['path'])
        row=lookup[entry['path']]
        candidates=b.locate(image,'easypr-color')
        attempts=[]
        for candidate in candidates:
            plate=b.warp(image,candidate['points'])
            result,mask,rects=b.recognize(plate,'global',classes,features,'xor','projection-char')
            attempts.append((candidate,result,mask,rects))
        attempts.sort(key=lambda a:(a[1]['status']!='scored',sum(s['distance'] for s in a[1]['scores']) if a[1]['scores'] else 9999))
        if not attempts:
            status='no_candidate';reason='color_or_contour_gate'
        else:
            candidate,result,mask,rects=attempts[0]
            assert result['raw']==row['result']['raw'] and result['status']==row['result']['status']
            status=result['status']
            if b.iou(candidate['box'],sample['box'])<.5:
                reason='wrong_or_oversized_selected_region'
            elif status=='segmentation':
                projection=mask.sum(axis=0)
                valleys=[int(projection[c-9:c+10].min()) for c in [34,70,101,132,163,194]]
                entry['valley_counts']=valleys;entry['rectangles']=rects
                reason='no_separating_valley' if max(valleys)>8 else 'character_extent_or_grouping'
            else:
                reason='raw_exact_then_confidence_reject' if result['raw']==entry['label'] else 'character_or_crop_error'
            entry['selected_box']=candidate['box']
        entry['status']=status;entry['failure_reason']=reason
        entry['result']=row['result']
        counts[('eligible_' if entry['native']['geometric_eligible'] else 'outside_')+reason]+=1
        # Measure original hue coverage at the annotation only for diagnosis.
        hsv=cv2.cvtColor(image,cv2.COLOR_BGR2HSV);value=cv2.equalizeHist(hsv[...,2])
        blue=((hsv[...,0]>100)&(hsv[...,0]<140)&(hsv[...,1]>95)&(hsv[...,1]<255)&(value>95)&(value<255))
        x0,y0,x1,y1=sample['box'];entry['truth_blue_fraction']=float(blue[y0:y1,x0:x1].mean())
        closed=cv2.morphologyEx(blue.astype(np.uint8),cv2.MORPH_CLOSE,np.ones((2,10),np.uint8))
        contours,_=cv2.findContours(closed,cv2.RETR_EXTERNAL,cv2.CHAIN_APPROX_SIMPLE)
        overlaps=[]
        for c in contours:
            x,y,w,h=cv2.boundingRect(c)
            intersection=max(0,min(x+w,x1)-max(x,x0))*max(0,min(y+h,y1)-max(y,y0))
            coverage=intersection/((x1-x0)*(y1-y0))
            if coverage>.25:
                overlaps.append(dict(box=[x,y,x+w,y+h],truth_coverage=coverage,iou=b.iou([x,y,x+w,y+h],sample['box'])))
        entry['overlapping_color_components']=overlaps
        # Whole-frame overlays distinguish the detector from oracle crops.
        cv2.rectangle(image,(x0,y0),(x1,y1),(0,255,0),2)
        for c in candidates:
            x0,y0,x1,y1=c['box'];cv2.rectangle(image,(x0,y0),(x1,y1),(0,0,255),2)
        index=samples.index(sample)
        cv2.imwrite(str(out/f'{index:02}-full-frame.jpg'),image)
    (out/'development-failures.json').write_text(json.dumps([e for e in entries if e['split']=='development'],ensure_ascii=False,indent=2),encoding='utf8')
    summary=dict(geometry={},failures=dict(counts))
    for mode in ['native','letterbox720']:
        summary['geometry'][mode]={split:dict(total=sum(e['split']==split for e in entries),eligible=sum(e['split']==split and e[mode]['geometric_eligible'] for e in entries)) for split in ['development','validation','heldout']}
    (out/'summary.json').write_text(json.dumps(summary,indent=2),encoding='utf8')
    print(json.dumps(summary,indent=2))


if __name__=='__main__':main()
