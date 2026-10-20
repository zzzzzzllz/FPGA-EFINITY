"""Real background-crop stress probe; not an independent negative-scene test.

Only development source photographs are used. The labeled plate is excluded by
cropping above its top corner. Other distant plates are not pre-certified absent;
every accepted output requires visual review before being called a false result.
"""
import hashlib
import json
from pathlib import Path
import cv2
import numpy as np
import baseline as b


def main():
    root=b.ROOT/'tmp/blue-plate-normal-g1'
    out=root/'background-probe';out.mkdir(exist_ok=True)
    samples=json.loads((root/'full-binary-standard/samples.json').read_text(encoding='utf8'))
    model=b.ROOT/'tmp/blue-plate-char-model/frozen-domain/geometry'
    config=json.loads((model/'interface.json').read_text(encoding='utf8'))
    context=(dict(np.load(model/'weights.npz')),config['thresholds'])
    records=[];tiles=[]
    for index,sample in enumerate(samples):
        if sample['split']!='development':continue
        original=b.read_image(b.ROOT/sample['path'])
        bottom=min(p[1] for p in sample['points'])-12;top=max(0,bottom-250)
        if bottom-top<100:continue
        crop=original[top:bottom,:]
        scale=min(1280/crop.shape[1],720/crop.shape[0]);nw,nh=round(crop.shape[1]*scale),round(crop.shape[0]*scale)
        dx,dy=(1280-nw)//2,(720-nh)//2
        image=np.zeros((720,1280,3),np.uint8);image[dy:dy+nh,dx:dx+nw]=cv2.resize(crop,(nw,nh),interpolation=cv2.INTER_AREA)
        attempts=[]
        for candidate in b.locate(image,'dual-local','none',context):
            plate=b.warp(image,candidate['points']);result,mask,rects=b.recognize(plate,'global',None,None,'xor','projection-char',context)
            attempts.append((candidate,result,plate,mask,rects))
        attempts.sort(key=b.candidate_key)
        result=attempts[0][1] if attempts else dict(status='no_candidate',raw='',scores=[])
        accepted=b.accepted(result,0,0)
        record=dict(index=index,source=sample['path'],source_sha256=sample['sha256'],source_split='development',
                    crop=[0,top,original.shape[1],bottom],known_plate_excluded=True,other_plates_manually_verified=False,
                    accepted=accepted,result=result)
        records.append(record)
        if accepted:
            cv2.imwrite(str(out/f'{index:03}-background.jpg'),crop)
            cv2.imwrite(str(out/f'{index:03}-candidate.png'),attempts[0][2])
            thumb=cv2.resize(crop,(448,160),interpolation=cv2.INTER_AREA)
            title=np.zeros((22,448,3),np.uint8);cv2.putText(title,f'{index}: accepted background candidate',(3,15),0,.45,(255,255,255),1)
            tiles.append(np.vstack([title,thumb,np.hstack([attempts[0][2],cv2.cvtColor(attempts[0][3]*255,cv2.COLOR_GRAY2BGR)])]))
    if tiles:cv2.imwrite(str(out/'accepted-contact.jpg'),np.vstack(tiles))
    payload=dict(purpose='Real development background crops; correlated stress diagnostics, not independent negative-scene acceptance',
        heldout_consumed=0,total=len(records),accepted_outputs=sum(r['accepted'] for r in records),
        baseline_sha256=hashlib.sha256(Path(b.__file__).read_bytes()).hexdigest(),
        auxiliary_sha256=hashlib.sha256((Path(b.__file__).parent/'mser_locator.py').read_bytes()).hexdigest(),
        model_sha256=hashlib.sha256((model/'weights.npz').read_bytes()).hexdigest(),records=records)
    (out/'report.json').write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding='utf8')
    print({k:payload[k] for k in ['total','accepted_outputs','heldout_consumed']})


if __name__=='__main__':main()
