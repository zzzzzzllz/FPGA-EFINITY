"""Freeze raw development ROIs and exact one-pass Python reference outputs."""
import hashlib
import json
import sys
from pathlib import Path
import cv2
import numpy as np

ROOT=Path(__file__).resolve().parents[4]
MODEL=ROOT/'tools/blue_plate/char_model'
OUT=ROOT/'tmp/blue-plate-char-preprocess'
sys.path.insert(0,str(MODEL))
from model import normalize,features,integer_scores,decide

def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()

def prepare():
    vectors=OUT/'vectors';vectors.mkdir(parents=True,exist_ok=True)
    batch_dir=ROOT/'tmp/blue-plate-char-model/frozen-domain'
    batch=json.loads((batch_dir/'batch.json').read_text(encoding='utf8'))
    audit=json.loads((batch_dir/'input-audit.json').read_text(encoding='utf8'))
    config=json.loads((MODEL/'candidate/interface.json').read_text(encoding='utf8'))
    weights=dict(np.load(MODEL/'candidate/weights.npz'))
    inputs={str(p.relative_to(ROOT)).replace('\\','/'):sha(p) for p in
            [MODEL/'model.py',MODEL/'candidate/interface.json',MODEL/'candidate/weights.npz',
             MODEL/'rtl/char_linear.v',MODEL/'candidate/w1-s10.bin',MODEL/'candidate/b1.mem',
             batch_dir/'batch.json',batch_dir/'input-audit.json']}
    cases=[]
    def add(name,mask,position=2,error=0,width=None,height=None,count=None,last=1,path=None):
        mask=np.asarray(mask,dtype=np.uint8)
        hh,ww=mask.shape
        cases.append(dict(name=name,mask=mask,position=position,error=error,width=ww if width is None else width,
                          height=hh if height is None else height,count=mask.size if count is None else count,last=last,path=path))
    for row in batch:
        for c in row['characters']:
            path=ROOT/c['path'];digest=sha(path)
            assert digest==audit['used_roi_hashes'][c['path']],path
            inputs[c['path']]=digest
            raw=(cv2.imdecode(np.fromfile(path,np.uint8),0)>0).astype(np.uint8)
            add(row['key']+'/'+str(c['position']),raw,c['position'],path=c['path'])
    real_count=len(cases)
    rng=np.random.default_rng(701)
    for h,w in [(96,320),(96,1),(1,320),(4,1),(1,4),(32,32),(29,28),(28,29),(57,33),(96,5),(3,320)]:
        add(f'filled-{w}x{h}',np.ones((h,w),np.uint8))
        if h*w>=4:
            sparse=np.zeros((h,w),np.uint8);ids=np.unique([0,w-1,(h-1)*w,h*w-1])
            sparse.flat[ids]=1
            if sparse.sum()>=4:add(f'corners-{w}x{h}',sparse)
    for i in range(24):
        h,w=int(rng.integers(4,97)),int(rng.integers(4,321))
        add('random-'+str(i),(rng.random((h,w))<.17).astype(np.uint8))
    add('blank',np.zeros((8,9),np.uint8),error=2)
    sparse=np.zeros((8,9),np.uint8);sparse.flat[:3]=1
    add('three-foreground',sparse,error=2)
    for w,h in [(0,10),(10,0),(321,1),(1,97),(511,127)]:
        add(f'invalid-{w}x{h}',np.zeros((1,1),np.uint8),error=1,width=w,height=h,count=0)
    add('early-last',np.ones((8,8),np.uint8),error=3,count=7)
    add('missing-last',np.ones((8,8),np.uint8),error=3,last=0)
    rows=[];canonical_changes=0
    with (OUT/'cases.txt').open('w') as index:
        for i,c in enumerate(cases):
            raw=c.pop('mask');count=c['count']
            (vectors/f'raw-{i}.mem').write_text(''.join(f'{int(v)}\n' for v in raw.ravel()[:count]),encoding='ascii')
            result=dict(id=0,score=0,margin=0,accepted=False)
            if not c['error']:
                norm=normalize(raw);feat=features(norm);scores=integer_scores(feat,weights)
                result=decide(scores,c['position'],config['thresholds'])
                (vectors/f'norm-{i}.mem').write_text(''.join(f'{int(v)}\n' for v in norm.ravel()),encoding='ascii')
                (vectors/f'features-{i}.mem').write_text(''.join(f'{int(v):02x}\n' for v in feat),encoding='ascii')
                (vectors/f'scores-{i}.mem').write_text(''.join(f'{int(v)&0xffffffff:08x}\n' for v in scores),encoding='ascii')
                try: canonical_changes+=int(not np.array_equal(norm,normalize(norm)))
                except ValueError: canonical_changes+=1
                c['normalized_foreground']=int(norm.sum())
            fields=[i,c['width'],c['height'],count,c['error'],c['last'],c['position'],result['id'],result['score'],result['margin'],int(result['accepted'])]
            index.write(' '.join(map(str,fields))+'\n');rows.append(dict(index=i,**c))
    manifest=dict(cases=rows,real_raw_rois=real_count,reference_non_idempotent_cases=canonical_changes,
                  source_sha256=inputs,interface=config['normalization'],heldout_consumed=0)
    (OUT/'vectors.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
    print(f'{len(cases)} cases; {real_count} frozen raw development ROIs; {canonical_changes} non-idempotent cases',flush=True)
    return manifest

def prepare_empty():
    """Supplemental IDs leave the running 310-case vectors unchanged."""
    vectors=OUT/'vectors';vectors.mkdir(parents=True,exist_ok=True)
    raw=np.zeros((96,320),np.uint8)
    for y,x in [(0,319),(95,0),(95,319),(94,318)]:raw[y,x]=1
    norm=normalize(raw);feat=features(norm)
    assert raw.sum()==4 and norm.sum()==0 and feat.sum()==0
    config=json.loads((MODEL/'candidate/interface.json').read_text(encoding='utf8'))
    weights=dict(np.load(MODEL/'candidate/weights.npz'));scores=integer_scores(feat,weights)
    base=json.loads((OUT/'vectors.json').read_text(encoding='utf8'))
    records=[]
    with (OUT/'cases-empty.txt').open('w') as stream:
        for position in [0,1,2]:
            i=310+position;decision=decide(scores,position,config['thresholds'])
            for kind,data,fmt in [('raw',raw.ravel(),'b'),('norm',norm.ravel(),'b'),('features',feat,'02x'),('scores',scores,'08x')]:
                (vectors/f'{kind}-{i}.mem').write_text(''.join(format(int(v)&0xffffffff,fmt)+'\n' for v in data),encoding='ascii')
            fields=[i,320,96,30720,0,1,position,decision['id'],decision['score'],decision['margin'],int(decision['accepted'])]
            stream.write(' '.join(map(str,fields))+'\n')
            records.append(dict(index=i,name='sampled-empty-position-'+str(position),width=320,height=96,
                                raw_foreground=4,normalized_foreground=0,error=0,position=position,decision=decision))
    manifest=dict(cases=records,source_sha256=base['source_sha256'],real_raw_rois=0,heldout_consumed=0)
    (OUT/'empty-vectors.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
    return manifest

if __name__=='__main__': prepare()
