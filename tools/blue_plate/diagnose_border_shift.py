"""Translate real automatic ROIs to check whether rim cleanup erases a final glyph.

Only the frozen 196-image cohort's development/validation split is consumed.
Translations are boundary diagnostics, never independent accuracy samples.
"""
import importlib.util
import json
from pathlib import Path
import cv2
import numpy as np
import baseline as b


def geometry(plate):
    gray=((plate[...,2].astype(np.uint16)*77+plate[...,1].astype(np.uint16)*150+plate[...,0].astype(np.uint16)*29)>>8).astype(np.uint8)
    mask=b.otsu32(gray).astype(np.uint8)
    mask[:5]=0;mask[-5:]=0;mask[:,:4]=0;mask[:,-4:]=0
    for y in range(64):
        if np.count_nonzero(np.diff(mask[y].astype(np.int16)))<8 or mask[y].sum()>190:mask[y]=0
    return mask


def main():
    root=b.ROOT/'tmp/blue-plate-normal-g1'
    snapshot=root/'baseline-border-unconditional.py'
    spec=importlib.util.spec_from_file_location('unconditional',snapshot)
    old=importlib.util.module_from_spec(spec);spec.loader.exec_module(old)
    old.ROOT,old.DATA=b.ROOT,b.DATA
    samples=json.loads((root/'border-standard/samples.json').read_text(encoding='utf8'))
    model=b.ROOT/'tools/blue_plate/char_model/candidate'
    config=json.loads((model/'interface.json').read_text(encoding='utf8'))
    context=(dict(np.load(model/'weights.npz')),config['thresholds'])
    cases=[];positions=[];contact=[]
    for index,sample in enumerate(samples):
        if sample['split']=='heldout':continue
        image=b.read_image(b.ROOT/sample['path']);height,width=image.shape[:2]
        scale=min(1280/width,720/height);nw,nh=round(width*scale),round(height*scale);dx,dy=(1280-nw)//2,(720-nh)//2
        full=np.zeros((720,1280,3),np.uint8);full[dy:dy+nh,dx:dx+nw]=cv2.resize(image,(nw,nh),interpolation=cv2.INTER_AREA)
        attempts=[]
        for candidate in b.locate(full,'quad-color'):
            plate=b.warp(full,candidate['points'])
            result,mask,rects=old.recognize(plate,'global',None,None,'xor','projection-char',context)
            attempts.append((candidate,result,plate,mask,rects))
        if not attempts:continue
        attempts.sort(key=b.candidate_key);candidate,result,plate,mask,rects=attempts[0]
        if result['status']!='scored':continue
        x,y,w,h=rects[-1]
        positions.append(dict(index=index,source=sample['path'],last_rect=rects[-1],last_label=sample['label'][-1],raw=result['raw']))
        if w>10:continue
        for shift in [-12,-8,-4,0,4,8,12,16]:
            if not (4<=x+shift and x+w+shift<=220):continue
            moved=cv2.warpAffine(plate,np.float32([[1,0,shift],[0,1,0]]),(224,64))
            raw=geometry(moved)
            _,old_mask,_=old.segment(moved,'global','projection-char')
            _,new_mask,_=b.segment(moved,'global','projection-char')
            target=(slice(y,y+h),slice(x+shift,x+shift+w))
            before=int(raw[target].sum());unconditional=int(old_mask[target].sum());guarded=int(new_mask[target].sum())
            record=dict(index=index,shift=shift,last_rect=[x+shift,y,w,h],foreground_before=before,
                        unconditional_retained=unconditional,guarded_retained=guarded)
            cases.append(record)
            if before and unconditional==0:
                label=np.zeros((20,224*3,3),np.uint8);cv2.putText(label,f'case {index}, shift {shift}: moved / old / guarded',(3,14),0,.4,(255,255,255),1)
                contact.append(np.vstack([label,np.hstack([moved,cv2.cvtColor(old_mask*255,cv2.COLOR_GRAY2BGR),cv2.cvtColor(new_mask*255,cv2.COLOR_GRAY2BGR)])]))
    summary=dict(heldout_consumed=0,scored_automatic_rois=len(positions),translation_cases=len(cases),
                 unconditional_erased=sum(r['foreground_before']>0 and r['unconditional_retained']==0 for r in cases),
                 guarded_erased=sum(r['foreground_before']>0 and r['guarded_retained']==0 for r in cases))
    (root/'border-shift-diagnosis.json').write_text(json.dumps(dict(summary=summary,positions=positions,cases=cases),ensure_ascii=False,indent=2),encoding='utf8')
    if contact:cv2.imwrite(str(root/'border-shift-erased.png'),np.vstack(contact))
    print(summary)


if __name__=='__main__':main()
