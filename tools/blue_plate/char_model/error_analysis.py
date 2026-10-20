"""Trace frozen development ROI errors to geometry, thresholding and classifier.

Re-thresholding variants are diagnostic ablations, not training or production edits.
"""
import hashlib
import json
from pathlib import Path
import sys
import cv2
import numpy as np
from model import CLASSES, features, normalize, integer_scores, decide
ROOT=Path(__file__).resolve().parents[3]
OUT=ROOT/'tmp/blue-plate-char-model'
sys.path.insert(0,str(ROOT/'tools/blue_plate'));sys.dont_write_bytecode=True
import baseline as b


def panel(image):
    if image.ndim==2:image=cv2.cvtColor(image,cv2.COLOR_GRAY2BGR)
    h,w=image.shape[:2];scale=min(90/w,90/h)
    resized=cv2.resize(image,(max(1,round(w*scale)),max(1,round(h*scale))),interpolation=cv2.INTER_NEAREST)
    out=np.zeros((96,96,3),np.uint8);hh,ww=resized.shape[:2]
    out[(96-hh)//2:(96-hh)//2+hh,(96-ww)//2:(96-ww)//2+ww]=resized
    return out


def main():
    records=json.loads((OUT/'roi-records.json').read_text(encoding='utf8'))['records']
    frozen=np.load(OUT/'roi-masks.npy').reshape(-1,7,32,32)
    samples={s['path']:s for s in b.load_samples() if s['split']=='development'}
    weights=dict(np.load(OUT/'linear0.1/weights.npz'))
    thresholds=json.loads((OUT/'linear0.1/interface.json').read_text(encoding='utf8'))['thresholds']
    selected={(39,3),(69,6),(71,6),(65,0),(65,6),(60,0),(62,0),(62,6),(1,4),(57,4),(72,3),(72,5),(73,2),(75,6)}
    rows=[];panels=[];matches=0
    for record,canonical in zip(records,frozen):
        sample=samples[record['path']]
        plate=b.warp(b.read_image(ROOT/sample['path']),np.array(sample['points'])[[2,3,0,1]])
        gray=((plate[:,:,2].astype(np.uint16)*77+plate[:,:,1].astype(np.uint16)*150+plate[:,:,0].astype(np.uint16)*29)>>8).astype(np.uint8)
        chars,mask,rects=b.segment(plate,'global','projection')
        # Current source may evolve, but raw-mask reconstruction must exactly
        # reproduce every frozen canonical input before any error conclusion.
        assert rects==[tuple(v) for v in record['rects']]
        assert np.array_equal(np.array([normalize(c) for c in chars]),canonical),record['index']
        matches+=1
        global_mask=b.otsu32(gray)
        for pos,(x,y,w,h) in enumerate(rects):
            base=chars[pos]
            roi=gray[y:y+h,x:x+w]
            padded=gray[max(0,y-2):min(64,y+h+2),max(0,x-2):min(224,x+w+2)]
            variants={'frozen':canonical[pos], 'uncleaned_global':normalize(global_mask[y:y+h,x:x+w]),
                'roi_otsu':normalize(b.otsu32(roi)) if b.otsu32(roi) is not None else None,
                'roi_otsu_pad2':normalize(b.otsu32(padded)) if b.otsu32(padded) is not None else None}
            predictions={}
            for name,norm in variants.items():
                if norm is None:predictions[name]={'error':'single-intensity ROI'};continue
                result=decide(integer_scores(features(norm),weights),pos,thresholds)
                result['correct']=result['char']==record['label'][pos]
                result['normalized_foreground']=int(norm.sum())
                predictions[name]=result
            row=dict(index=record['index'],position=pos,truth=record['label'][pos],raw_roi_shape=[h,w],
                raw_foreground=int(base.sum()),raw_density=float(base.mean()),
                removed_global_pixels=int(global_mask[y:y+h,x:x+w].sum())-int(base.sum()),
                decisions=predictions)
            rows.append(row)
            if (record['index'],pos) in selected:
                tiles=[panel(plate[y:y+h,x:x+w]),panel(base*255),panel(canonical[pos]*255),
                    panel(variants['uncleaned_global']*255),panel(variants['roi_otsu_pad2']*255)]
                strip=np.hstack(tiles)
                header=np.zeros((22,strip.shape[1],3),np.uint8)
                text=f"{record['index']}/{pos} {w}x{h} density={base.mean():.2f} oldID={predictions['frozen']['id']} padID={predictions['roi_otsu_pad2']['id']}"
                cv2.putText(header,text,(2,15),0,.42,(255,255,255),1)
                panels.append(np.vstack([header,strip]))
    summary={}
    for variant in ['frozen','uncleaned_global','roi_otsu','roi_otsu_pad2']:
        values=[r['decisions'][variant] for r in rows]
        summary[variant]=dict(characters=len(values),correct=sum(v.get('correct',False) for v in values),
            accepted_wrong=sum(v.get('accepted',False) and not v.get('correct',False) for v in values),
            rejected=sum(not v.get('accepted',False) for v in values))
    result=dict(current_baseline_sha256=hashlib.sha256((ROOT/'tools/blue_plate/baseline.py').read_bytes()).hexdigest(),
        reconstructed_frozen_plates=matches,summary=summary,rows=rows)
    (OUT/'error-analysis.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8')
    for start in range(0,len(panels),7):cv2.imwrite(str(OUT/f'error-contact-{start//7}.png'),np.vstack(panels[start:start+7]))
    print(json.dumps(summary))


if __name__=='__main__':main()
