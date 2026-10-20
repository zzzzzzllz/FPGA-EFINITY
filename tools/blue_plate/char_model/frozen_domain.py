"""Audit and compare a frozen development ROI batch without consuming heldout.

Keeps the approved candidate read-only. New training uses EasyPR train groups;
threshold selection uses EasyPR validation groups. No plate label trains a model.
"""
import os
os.environ.setdefault('OPENBLAS_NUM_THREADS','2')
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import cv2
import numpy as np
from sklearn.svm import LinearSVC
from threadpoolctl import threadpool_limits
from model import CLASSES, normalize, features, integer_scores, decide

ROOT=Path(__file__).resolve().parents[3]
BASE=ROOT/'tmp/blue-plate-char-model'
OUT=BASE/'frozen-domain'
SOURCE=ROOT/'tmp/blue-plate-normal-g1'
CANDIDATE=Path(__file__).resolve().parent/'candidate'


def read(path): return json.loads(path.read_text(encoding='utf8'))
def save(path,value): path.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf8')
def sha(path): return hashlib.sha256(path.read_bytes()).hexdigest()
def image(path):
    value=cv2.imdecode(np.fromfile(path,np.uint8),0)
    if value is None:raise ValueError(path)
    return value
def hashes(): return {p.name:sha(p) for p in CANDIDATE.iterdir() if p.is_file()}


def prepare():
    manifest=read(SOURCE/'frozen-development-rois/manifest.json')
    border=read(SOURCE/'border-diagnosis.json')
    assert manifest['heldout_consumed']==border['heldout_consumed']==0
    assert sha(CANDIDATE/'weights.npz')==manifest['model_sha256']
    for record in manifest['files']:
        assert sha(ROOT/record['path'])==record['sha256'],record['path']
    source_hashes={}
    for row in manifest['records']:
        assert row['split']=='development'
        source_hashes[row['source']]=sha(ROOT/row['source'])
        assert source_hashes[row['source']]==row['source_sha256']
        codes=list(map(int,Path(row['source']).stem.split('-')[4].split('_')))
        label=CLASSES[codes[0]]+CLASSES[31:55][codes[1]]+''.join(CLASSES[31:][v] for v in codes[2:])
        assert label==row['label'],(label,row['label'])
    after={(r['source'],r['mode']):r for r in border['cases']}
    weights=dict(np.load(CANDIDATE/'weights.npz'));threshold=read(CANDIDATE/'interface.json')['thresholds']
    rows=[];masks=[];after_hashes={}
    for row in manifest['records']:
        updated=after.get((row['source'],row['mode']))
        folder=ROOT/(updated['after_folder'] if updated else row['folder'])
        expected=updated['after'] if updated else row['result']
        entry=dict(key=Path(row['folder']).name,source=row['source'],label=row['label'],mode=row['mode'],
            input_version='after-border' if updated else 'original-frozen',characters=[])
        for c in row['characters']:
            pos=c['position'];path=folder/f'char-{pos}-binary.png'
            raw=(image(path)>0).astype(np.uint8);norm=normalize(raw)
            score=decide(integer_scores(features(norm),weights),pos,threshold)
            assert score==expected['scores'][pos],(entry['key'],pos,score,expected['scores'][pos])
            after_hashes[path.relative_to(ROOT).as_posix()]=sha(path)
            entry['characters'].append(dict(position=pos,truth=c['truth'],path=path.relative_to(ROOT).as_posix(),
                gray=c['gray'],raw_shape=list(raw.shape),index=len(masks)))
            masks.append(norm)
        rows.append(entry)
    np.save(OUT/'frozen-masks.npy',np.array(masks))
    save(OUT/'batch.json',rows)
    save(OUT/'input-audit.json',dict(original_png_hashes_verified=len(manifest['files']),source_hashes=source_hashes,
        candidate_hashes=hashes(),manifest_sha256=sha(SOURCE/'frozen-development-rois/manifest.json'),
        border_diagnosis_sha256=sha(SOURCE/'border-diagnosis.json'),used_roi_hashes=after_hashes,
        plate_mode_pairs=len(rows),complete_pairs=sum(len(r['characters'])==7 for r in rows),characters=len(masks),
        policy='11 after-border failure groups replace originals; remaining original-frozen groups unchanged. This is a selected development diagnosis, not a representative test.',heldout_consumed=0))
    print('verified',len(manifest['files']),'PNGs;',len(rows),'pairs;',len(masks),'characters',flush=True)


def calibrate(scores,y):
    thresholds={}
    for name,ids in [('province',np.arange(31)),('alphanumeric',np.arange(31,65))]:
        use=y<31 if name=='province' else y>=31
        s=scores[use][:,ids];truth=y[use]
        order=np.argsort(-s,axis=1,kind='stable');pred=ids[order[:,0]]
        top=s[np.arange(len(s)),order[:,0]];gap=top-s[np.arange(len(s)),order[:,1]]
        choices=[]
        for score in np.unique(np.quantile(top,np.linspace(0,.9,19)).astype(int)):
            for margin in np.unique(np.quantile(gap,np.linspace(0,.95,39)).astype(int)):
                ok=(top>=score)&(gap>=margin)
                wrong=int((ok&(pred!=truth)).sum());correct=int((ok&(pred==truth)).sum())
                feasible=wrong<=int(ok.sum()*.01)
                choices.append(((not feasible,-correct if feasible else wrong,wrong),int(score),int(margin)))
        _,score,margin=min(choices);thresholds[name]=dict(score=score,margin=margin)
    return thresholds


def check_quant(w,b):
    wq=np.rint(w*256);bq=np.rint(b*8192)
    if not np.isfinite(wq).all() or wq.min() < -32768 or wq.max()>32767:raise OverflowError('w')
    if not np.isfinite(bq).all() or bq.min() < -2**31 or bq.max()>=2**31:raise OverflowError('b')
    return dict(w1=wq.astype(np.int16),b1=bq.astype(np.int32))


def compare(name,weights,threshold,masks):
    batch=read(OUT/'batch.json');output=[];flat=[]
    scores=integer_scores(np.array([features(m) for m in masks]),weights)
    for row in batch:
        ds=[]
        for c in row['characters']:
            d=decide(scores[c['index']],c['position'],threshold)
            ds.append(d);flat.append(dict(key=row['key'],position=c['position'],truth=c['truth'],**d))
        raw=''.join(d['char'] for d in ds)
        accepted=len(ds)==7 and all(d['accepted'] for d in ds)
        output.append(dict(key=row['key'],label=row['label'],mode=row['mode'],raw=raw,accepted=accepted,correct=raw==row['label'],scores=ds))
    summary={}
    for mode in ['all','automatic','oracle']:
        selected=[r for r in output if mode=='all' or r['mode']==mode]
        summary[mode]=dict(pairs=len(selected),raw_correct=sum(r['correct'] for r in selected),
            accepted_correct=sum(r['correct'] and r['accepted'] for r in selected),
            accepted_wrong=sum(not r['correct'] and r['accepted'] for r in selected),rejected=sum(not r['accepted'] for r in selected))
    summary['characters']=dict(total=len(flat),raw_correct=sum(r['truth']==r['char'] for r in flat),
        accepted_wrong=sum(r['truth']!=r['char'] and r['accepted'] for r in flat),rejected=sum(not r['accepted'] for r in flat))
    result=dict(name=name,thresholds=threshold,summary=summary,rows=output,characters=flat)
    save(OUT/(name+'-batch.json'),result)
    print(name,summary,flush=True)
    return result


def stats(scores,y,thresholds):
    decisions=[decide(s,0 if truth<31 else 2,thresholds) for s,truth in zip(scores,y)]
    correct=np.array([d['id']==t for d,t in zip(decisions,y)]);accepted=np.array([d['accepted'] for d in decisions])
    return dict(total=len(y),raw_correct=int(correct.sum()),correct=int((correct&accepted).sum()),
        wrong=int((~correct&accepted).sum()),reject=int((~accepted).sum()))


def train(variants=False,regularized=False):
    audit=read(OUT/'input-audit.json');assert hashes()==audit['candidate_hashes']
    masks=np.load(OUT/'frozen-masks.npy')
    compare('frozen-linear',dict(np.load(CANDIDATE/'weights.npz')),read(CANDIDATE/'interface.json')['thresholds'],masks)
    for name in ['mlp64','mlp128']:
        compare(name,dict(np.load(BASE/name/'weights.npz')),read(BASE/name/'interface.json')['thresholds'],masks)
    # Only the train and validation slices are used; no test scores are computed.
    data=np.load(BASE/'dataset.npz');splits=data['split'];y=data['y']
    train_idx=np.flatnonzero(splits=='train');val_idx=np.flatnonzero(splits=='validation')
    training=data['masks'][train_idx];validation=data['masks'][val_idx]
    xtrain=np.array([features(m) for m in training],np.float32)
    xval=np.array([features(m) for m in validation],np.float32)
    results={}
    recipes=['geometry-regularized'] if regularized else (['balanced','geometry'] if variants else ['stroke-cross','stroke-horizontal'])
    for name in recipes:
        matrices=[xtrain];labels=[y[train_idx]];counts={}
        geometry=name.startswith('geometry')
        operations=[] if name=='balanced' else (['shear-left','shear-right','narrow','wide'] if geometry else ['dilate','erode'])
        kernel=cv2.getStructuringElement(cv2.MORPH_CROSS,(3,3)) if name=='stroke-cross' else np.ones((1,3),np.uint8)
        for operation in operations:
            augmented=[];targets=[]
            for m,label in zip(training,y[train_idx]):
                if geometry:
                    scale={'narrow':.85,'wide':1.15}.get(operation,1.)
                    shear={'shear-left':-.2,'shear-right':.2}.get(operation,0.)
                    # Larger canvas preserves the transformed foreground before tight normalization.
                    matrix=np.float32([[scale,shear,16+15.5*(1-scale-shear)],[0,1,16]])
                    transformed=cv2.warpAffine(m,matrix,(64,64),flags=cv2.INTER_NEAREST)
                else:
                    transformed=getattr(cv2,operation)(m,kernel)
                if transformed.sum()<4:continue
                augmented.append(features(normalize(transformed)));targets.append(label)
            matrices.append(np.array(augmented,np.float32));labels.append(np.array(targets));counts[operation]=len(targets)
        x=np.concatenate(matrices);targets=np.concatenate(labels)
        regularization=.01 if regularized else .1
        svm=LinearSVC(C=regularization,class_weight='balanced' if name=='balanced' else None,dual=False,max_iter=5000,random_state=701).fit(x/32,targets)
        weights=check_quant(svm.coef_.T,svm.intercept_)
        val_scores=integer_scores(xval,weights);thresholds=calibrate(val_scores,y[val_idx])
        folder=OUT/name;folder.mkdir(exist_ok=True)
        np.savez(folder/'weights.npz',**weights)
        config=dict(model_type='linear',classes=list(CLASSES),thresholds=thresholds,augmentation=counts,
            training_original=len(training),validation=len(validation),heldout_scored=0,C=regularization,class_weight='balanced' if name=='balanced' else None,
            weight_range=[int(weights['w1'].min()),int(weights['w1'].max())],
            bias_range=[int(weights['b1'].min()),int(weights['b1'].max())],
            absolute_accumulator_bound=int((32*np.abs(weights['w1'].astype(np.int64)).sum(axis=0)+np.abs(weights['b1'])).max()),
            preprocessing='unchanged raw ROI normalize once; unchanged 320 integer features',status='experimental; approved candidate untouched')
        save(folder/'interface.json',config)
        result=compare(name,weights,thresholds,masks)
        results[name]=dict(validation=stats(val_scores,y[val_idx],thresholds),batch=result['summary'],configuration=config)
    filename='regularized-comparison.json' if regularized else ('variant-comparison.json' if variants else 'training-comparison.json')
    save(OUT/filename,results)
    assert hashes()==audit['candidate_hashes']
    print(json.dumps(results,ensure_ascii=False),flush=True)


def main():
    p=argparse.ArgumentParser();p.add_argument('action',choices=['prepare','train','variants','regularized']);args=p.parse_args()
    OUT.mkdir(parents=True,exist_ok=True)
    with threadpool_limits(limits=2):
        if args.action=='prepare':prepare()
        else:train(variants=args.action=='variants',regularized=args.action=='regularized')


if __name__=='__main__':main()
