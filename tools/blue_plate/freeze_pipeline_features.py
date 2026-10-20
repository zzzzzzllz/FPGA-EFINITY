"""Freeze actual pipeline features, then compare existing classifiers read-only."""
import hashlib
import json
from pathlib import Path
import cv2
import numpy as np
import baseline as b
from char_model import model


def main():
    root=b.ROOT/'tmp/blue-plate-normal-g1'
    out=root/'frozen-pipeline-features';out.mkdir(exist_ok=True)
    run=root/'full-dual-local-geometry'
    samples=json.loads((run/'samples.json').read_text(encoding='utf8'))
    expected={(r['path'],r['mode']):r for r in json.loads((run/'results.json').read_text(encoding='utf8'))}
    geometry=b.ROOT/'tmp/blue-plate-char-model/frozen-domain/geometry'
    config=json.loads((geometry/'interface.json').read_text(encoding='utf8'))
    context=(dict(np.load(geometry/'weights.npz')),config['thresholds'])
    features=[];records=[]
    for index,sample in enumerate(samples):
        if sample['split']=='heldout':continue
        original=b.read_image(b.ROOT/sample['path']);h,w=original.shape[:2]
        scale=min(1280/w,720/h);nw,nh=round(w*scale),round(h*scale);dx,dy=(1280-nw)//2,(720-nh)//2
        image=np.zeros((720,1280,3),np.uint8);image[dy:dy+nh,dx:dx+nw]=cv2.resize(original,(nw,nh),interpolation=cv2.INTER_AREA)
        attempts=[]
        for candidate in b.locate(image,'dual-local','none',context):
            plate=b.warp(image,candidate['points']);result,mask,rects=b.recognize(plate,'global',None,None,'xor','projection-char',context)
            attempts.append((candidate,result,plate,mask,rects))
        attempts.sort(key=b.candidate_key)
        gt=np.float32([[x*nw/w+dx,y*nh/h+dy] for x,y in sample['points']])[[2,3,0,1]]
        cases=[('oracle',b.warp(image,gt))]
        if attempts:cases.insert(0,('automatic',attempts[0][2]))
        else:records.append(dict(**expected[sample['path'],'automatic'],feature_start=None))
        for mode,plate in cases:
            result,mask,rects=b.recognize(plate,'global',None,None,'xor','projection-char',context)
            exp=expected[sample['path'],mode];assert result==exp['result'],f'Replay changed: {index}/{mode}'
            start=None
            if result['status']=='scored':
                chars,_,_=b.segment(plate,'global','projection-char');start=len(features)
                features.extend(model.features(model.normalize(char)) for char in chars)
                if mode=='automatic' and b.accepted(result,0,0) and result['raw']!=sample['label']:
                    folder=out/f'error-{index:03}';folder.mkdir(exist_ok=True)
                    cv2.imwrite(str(folder/'plate.png'),plate)
                    for pos,char in enumerate(chars):cv2.imwrite(str(folder/f'char-{pos}-binary.png'),char*255)
                    (folder/'record.json').write_text(json.dumps(dict(source=sample['path'],label=sample['label'],result=result,rects=rects),ensure_ascii=False,indent=2),encoding='utf8')
            records.append(dict(**exp,feature_start=start))
    x=np.array(features,dtype=np.uint8);np.savez_compressed(out/'features.npz',features=x)
    (out/'records.json').write_text(json.dumps(records,ensure_ascii=False,indent=2),encoding='utf8')
    variants={'geometry':geometry,'mlp64':b.ROOT/'tmp/blue-plate-char-model/mlp64','mlp128':b.ROOT/'tmp/blue-plate-char-model/mlp128'}
    comparison={}
    for name,directory in variants.items():
        cfg=json.loads((directory/'interface.json').read_text(encoding='utf8'));weights=dict(np.load(directory/'weights.npz'))
        scores=model.integer_scores(x,weights);rows=[]
        for row in records:
            row=row.copy();start=row.pop('feature_start')
            if start is not None:
                decisions=[model.decide(scores[start+i],i,cfg['thresholds']) for i in range(7)]
                row['result']=dict(status='scored',raw=''.join(d['char'] for d in decisions),scores=decisions)
            rows.append(row)
        if name=='geometry':assert all(r['result']==expected[r['path'],r['mode']]['result'] for r in rows)
        comparison[name]=dict(weights_sha256=hashlib.sha256((directory/'weights.npz').read_bytes()).hexdigest(),
            metrics={mode:{split:b.summarize([r for r in rows if r['mode']==mode and r['split']==split],0,0)
                           for split in ['development','validation']} for mode in ['automatic','oracle']})
        (out/(name+'-results.json')).write_text(json.dumps(rows,ensure_ascii=False,indent=2),encoding='utf8')
    payload=dict(purpose='Fixed observed ROI/features; no training, no detector reselection',heldout_consumed=0,
        pipeline_replay_rows=len(records),character_vectors=len(x),
        baseline_sha256=hashlib.sha256(Path(b.__file__).read_bytes()).hexdigest(),
        auxiliary_sha256=hashlib.sha256((Path(b.__file__).parent/'mser_locator.py').read_bytes()).hexdigest(),
        features_sha256=hashlib.sha256((out/'features.npz').read_bytes()).hexdigest(),comparison=comparison)
    (out/'comparison.json').write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding='utf8')
    for name,item in comparison.items():
        print(name,[(mode,split,*(item['metrics'][mode][split][k] for k in ['correct','wrong_number','reject']))
                    for mode in ['automatic','oracle'] for split in ['development','validation']])


if __name__=='__main__':main()
