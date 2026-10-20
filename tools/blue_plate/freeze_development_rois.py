"""Freeze exact development ROIs for cross-window failure diagnosis.

Never consumes heldout images. Labels identify errors, not detector inputs.
"""
import hashlib
import argparse
import importlib.util
import json
from pathlib import Path
import cv2
import numpy as np
import baseline as b


def main():
    global b
    parser=argparse.ArgumentParser()
    parser.add_argument('--baseline-snapshot',type=Path,help='Exact baseline source used by partial-standard')
    args=parser.parse_args()
    if args.baseline_snapshot:
        root,data=b.ROOT,b.DATA
        spec=importlib.util.spec_from_file_location('frozen_baseline',args.baseline_snapshot)
        b=importlib.util.module_from_spec(spec);spec.loader.exec_module(b)
        b.ROOT,b.DATA=root,data
    run=b.ROOT/'tmp/blue-plate-normal-g1/partial-standard'
    out=b.ROOT/'tmp/blue-plate-normal-g1/frozen-development-rois';out.mkdir(exist_ok=True)
    samples=json.loads((run/'samples.json').read_text(encoding='utf8'))
    rows=json.loads((run/'results.json').read_text(encoding='utf8'))
    eligible=[r for r in rows if r['split']=='development']
    errors=[r for r in eligible if b.accepted(r['result'],0,0) and r['result']['raw']!=r['label']]
    controls=sorted([r for r in eligible if r['mode']=='automatic' and b.accepted(r['result'],0,0) and r['result']['raw']==r['label']],key=lambda r:hashlib.sha256(r['path'].encode()).hexdigest())[:10]
    selected={r['path'] for r in errors+controls}
    md=b.ROOT/'tools/blue_plate/char_model/candidate'
    config=json.loads((md/'interface.json').read_text(encoding='utf8'));ctx=(dict(np.load(md/'weights.npz')),config['thresholds'])
    records=[];files=[]
    for index,sample in enumerate(samples):
        if sample['path'] not in selected:continue
        assert sample['split']=='development'
        source=b.read_image(b.ROOT/sample['path']);height,width=source.shape[:2]
        scale=min(1280/width,720/height);nw,nh=round(width*scale),round(height*scale);dx,dy=(1280-nw)//2,(720-nh)//2
        image=np.zeros((720,1280,3),np.uint8);image[dy:dy+nh,dx:dx+nw]=cv2.resize(source,(nw,nh),interpolation=cv2.INTER_AREA)
        candidates=b.locate(image,'quad-color');attempts=[]
        for candidate in candidates:
            plate=b.warp(image,candidate['points']);result,mask,rects=b.recognize(plate,'global',None,None,'xor','projection-char',ctx)
            attempts.append((candidate,result,plate,mask,rects))
        attempts.sort(key=b.candidate_key)
        points=np.array([[x*nw/width+dx,y*nh/height+dy] for x,y in sample['points']])[[2,3,0,1]]
        oracle=b.warp(image,points)
        cases=[('oracle',oracle,points)]
        if attempts:cases.insert(0,('automatic',attempts[0][2],attempts[0][0]['points']))
        for mode,plate,points in cases:
            result,mask,rects=b.recognize(plate,'global',None,None,'xor','projection-char',ctx)
            expected=next(r for r in rows if r['path']==sample['path'] and r['mode']==mode)
            assert result==expected['result'],f'Replay mismatch for {sample["path"]} {mode}'
            folder=out/f'{index:03}-{mode}';folder.mkdir(exist_ok=True)
            gray=((plate[...,2].astype(np.uint16)*77+plate[...,1].astype(np.uint16)*150+plate[...,0].astype(np.uint16)*29)>>8).astype(np.uint8)
            cv2.imwrite(str(folder/'plate.png'),plate);cv2.imwrite(str(folder/'gray.png'),gray);cv2.imwrite(str(folder/'geometry-mask.png'),mask*255)
            chars,_,_=b.segment(plate,'global','projection-char')
            character_records=[]
            for pos,(char,rect) in enumerate(zip(chars,rects)):
                x,y,w,h=rect;roi=gray[max(0,y-2):min(64,y+h+2),x:x+w]
                assert np.array_equal(b.otsu32(roi),char)
                cv2.imwrite(str(folder/f'char-{pos}-gray.png'),roi)
                cv2.imwrite(str(folder/f'char-{pos}-binary.png'),char*255)
                character_records.append(dict(position=pos,truth=sample['label'][pos],rect=rect,
                    binary=(folder/f'char-{pos}-binary.png').relative_to(b.ROOT).as_posix(),
                    gray=(folder/f'char-{pos}-gray.png').relative_to(b.ROOT).as_posix(),prediction=result['scores'][pos]))
            records.append(dict(source=sample['path'],source_sha256=sample['sha256'],label=sample['label'],
                split='development',mode=mode,source_points=points.tolist(),result=result,
                accepted_wrong=b.accepted(result,0,0) and result['raw']!=sample['label'],
                characters=character_records,folder=folder.relative_to(b.ROOT).as_posix()))
            for path in sorted(folder.glob('*.png')):
                files.append(dict(path=path.relative_to(b.ROOT).as_posix(),sha256=hashlib.sha256(path.read_bytes()).hexdigest()))
    payload=dict(selection='All accepted-wrong development plates (both modes), plus 10 SHA-ordered automatically accepted-correct controls',
        purpose='failure diagnosis only; neither training nor acceptance test',heldout_consumed=0,
        source_run=run.relative_to(b.ROOT).as_posix(),source_baseline_sha256=hashlib.sha256(Path(b.__file__).read_bytes()).hexdigest(),
        model_sha256=hashlib.sha256((md/'weights.npz').read_bytes()).hexdigest(),
        normalization='char-*-binary.png is ORIGINAL binary ROI, values 0/255; threshold >0 then call predict ONCE',
        accepted_wrong_automatic=sum(r['mode']=='automatic' for r in errors),accepted_wrong_oracle=sum(r['mode']=='oracle' for r in errors),
        selected_unique_plates=len(selected),records=records,files=files)
    (out/'manifest.json').write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding='utf8')
    print({k:payload[k] for k in ['accepted_wrong_automatic','accepted_wrong_oracle','selected_unique_plates','heldout_consumed']})
    print('Frozen',len(records),'plate-mode pairs and',len(files),'PNG files')


if __name__=='__main__':main()
