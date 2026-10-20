"""Test whether plate-wide bbox clipping loses weak character strokes.

All candidate ROIs and their original selection rule stay fixed. Padding is
uniform for every character and image; labels are used only for reporting.
"""
import hashlib
import json
from pathlib import Path
import numpy as np
import baseline as b
from char_model import model


def main():
    root=b.ROOT/'tmp/blue-plate-normal-g1';frozen=root/'integer-geometry'
    out=root/'character-crop-study';out.mkdir(exist_ok=True)
    plates=np.load(frozen/'candidate-plates.npz')['rgb_bgr']
    manifest=json.loads((frozen/'candidates.json').read_text(encoding='utf8'))
    previous=[r for r in json.loads((root/'full-dual-local-geometry/results.json').read_text(encoding='utf8')) if r['mode']=='automatic']
    directory=b.ROOT/'tmp/blue-plate-char-model/frozen-domain/geometry'
    cfg=json.loads((directory/'interface.json').read_text(encoding='utf8'));weights=dict(np.load(directory/'weights.npz'))
    variants={'baseline':(0,2),'x1':(1,2),'x2':(2,2),'y4':(0,4),'x2y4':(2,4)}
    attempts={name:{} for name in variants}
    for entry,plate in zip(manifest,plates):
        chars,mask,rects=b.segment(plate,'global','projection-char')
        gray=((plate[:,:,2].astype(np.uint16)*77+plate[:,:,1].astype(np.uint16)*150+plate[:,:,0].astype(np.uint16)*29)>>8).astype(np.uint8)
        for name,(px,py) in variants.items():
            result=dict(status='segmentation',raw='',scores=[])
            if len(chars)==7:
                altered=chars if name=='baseline' else [b.otsu32(gray[max(0,y-py):min(64,y+h+py),max(0,x-px):min(224,x+w+px)]) for x,y,w,h in rects]
                if all(c is not None and np.count_nonzero(c)>=4 for c in altered):
                    decisions=[model.decide(model.integer_scores(model.features(model.normalize(c)),weights),i,cfg['thresholds']) for i,c in enumerate(altered)]
                    result=dict(status='scored',raw=''.join(d['char'] for d in decisions),scores=decisions)
            attempts[name].setdefault(entry['path'],[]).append((entry['candidate'],result))
    report={}
    for name,lookup in attempts.items():
        rows=[];transitions=[]
        for old in previous:
            row=old.copy();candidates=lookup.get(old['path'],[])
            if candidates:
                candidates.sort(key=b.candidate_key);row['result']=candidates[0][1]
            if name=='baseline':assert row['result']==old['result']
            if row['result']!=old['result']:
                transitions.append(dict(path=row['path'],label=row['label'],split=row['split'],before=old['result'],after=row['result']))
            rows.append(row)
        report[name]=dict(metrics={split:b.summarize([r for r in rows if r['split']==split],0,0) for split in ['development','validation']},changed=len(transitions))
        (out/f'{name}-transitions.json').write_text(json.dumps(transitions,ensure_ascii=False,indent=2),encoding='utf8')
        (out/f'{name}-results.json').write_text(json.dumps(rows,ensure_ascii=False,indent=2),encoding='utf8')
    payload=dict(heldout_consumed=0,candidates=len(plates),variants=report,
        source_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        frozen_roi_sha256=hashlib.sha256((frozen/'candidate-plates.npz').read_bytes()).hexdigest())
    (out/'report.json').write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding='utf8')
    for name,item in report.items():print(name,[(split,*(m[k] for k in ['correct','wrong_number','reject'])) for split,m in item['metrics'].items()])


if __name__=='__main__':main()
