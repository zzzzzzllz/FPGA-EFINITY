"""Record every frozen-batch change and validation outcome; never score test data."""
import csv
import hashlib
import sklearn
import numpy as np
from frozen_domain import BASE,OUT,CANDIDATE,read,save,hashes,features,integer_scores,stats,decide,CLASSES,sha


def main():
    baseline=read(OUT/'frozen-linear-batch.json')
    original={r['key']:r for r in baseline['rows']}
    data=np.load(BASE/'dataset.npz');indices=np.flatnonzero(data['split']=='validation')
    x=np.array([features(m) for m in data['masks'][indices]]);y=data['y'][indices]
    rows=[];results={};class_rows=[]
    provenance=read(BASE/'manifest.json')
    names=['frozen-linear','mlp64','mlp128','stroke-cross','stroke-horizontal','balanced','geometry','geometry-regularized']
    for name in names:
        result=read(OUT/(name+'-batch.json'))
        folder=CANDIDATE if name=='frozen-linear' else ((BASE/name) if name.startswith('mlp') else OUT/name)
        weights=dict(np.load(folder/'weights.npz'))
        scores=integer_scores(x,weights)
        decisions=[decide(s,0 if truth<31 else 2,result['thresholds']) for s,truth in zip(scores,y)]
        predicted=np.array([d['id'] for d in decisions]);accepted=np.array([d['accepted'] for d in decisions])
        wrong=accepted&(predicted!=y)
        if name=='frozen-linear':base_wrong=wrong.copy();base_decisions=decisions
        validation_changes=[]
        for i in np.flatnonzero(wrong!=base_wrong):
            dataset_id=int(indices[i])
            validation_changes.append(dict(dataset_id=dataset_id,truth=CLASSES[y[i]],
                change='new_accepted_error' if wrong[i] else 'removed_accepted_error',
                before=base_decisions[i],after=decisions[i],
                path=provenance[dataset_id]['path'],file_sha256=provenance[dataset_id]['file_sha256']))
        for class_id,char in enumerate(CLASSES):
            use=y==class_id
            class_rows.append(dict(model=name,char=char,total=int(use.sum()),raw_correct=int((use&(predicted==y)).sum()),
                accepted_correct=int((use&accepted&(predicted==y)).sum()),accepted_wrong=int((use&wrong).sum()),
                rejected=int((use&~accepted).sum())))
        result['validation']=stats(scores,y,result['thresholds'])
        changes=[]
        for row in result['rows']:
            prev=original[row['key']]
            values=dict(model=name,key=row['key'],label=row['label'],mode=row['mode'],
                before=prev['raw'],before_accepted=prev['accepted'],after=row['raw'],after_accepted=row['accepted'])
            rows.append(values)
            if (prev['raw'],prev['accepted'])!=(row['raw'],row['accepted']):changes.append(values)
        results[name]=dict(summary=result['summary'],validation=result['validation'],validation_error_changes=validation_changes,changes=changes,
            targets=[c for c in result['characters'] if (c['key'],c['position']) in [('115-automatic',4),('050-oracle',6)]])
    with (OUT/'all-pair-results.csv').open('w',encoding='utf-8-sig',newline='') as f:
        writer=csv.DictWriter(f,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)
    with (OUT/'validation-by-class.csv').open('w',encoding='utf-8-sig',newline='') as f:
        writer=csv.DictWriter(f,fieldnames=list(class_rows[0]));writer.writeheader();writer.writerows(class_rows)
    assert hashes()==read(OUT/'input-audit.json')['candidate_hashes']
    save(OUT/'comparison-summary.json',dict(heldout_scored=0,candidate_unchanged=True,models=results))
    corpus_masks=data['masks'];corpus_labels=data['y'];corpus_splits=data['split']
    fingerprints={split:hashlib.sha256(b''.join(corpus_masks[i].tobytes()+bytes([int(corpus_labels[i])]) for i in np.flatnonzero(corpus_splits==split))).hexdigest()
        for split in ['train','validation']}
    candidates={}
    for name,c in [('geometry',.1),('geometry-regularized',.01)]:
        folder=OUT/name;w=dict(np.load(folder/'weights.npz'))
        bound=int((32*np.abs(w['w1'].astype(np.int64)).sum(axis=0)+np.abs(w['b1'])).max())
        bits=next(n for n in range(2,33) if w['w1'].min()>=-2**(n-1) and w['w1'].max()<2**(n-1))
        candidates[name]=dict(C=c,weights_sha256=sha(folder/'weights.npz'),interface_sha256=sha(folder/'interface.json'),
            signed_weight_bits=bits,absolute_accumulator_bound=bound,thresholds=read(folder/'interface.json')['thresholds'])
    save(OUT/'experiment-freeze.json',dict(status='Fixed experiments for full development comparison; approved candidate stays frozen',
        candidates=candidates,sklearn=sklearn.__version__,training_slices_sha256=fingerprints,
        trainer_sha256=sha(CANDIDATE.parent/'frozen_domain.py'),model_interface_sha256=sha(CANDIDATE.parent/'model.py'),
        feature_count=320,classes=CLASSES,weight_fraction_bits=8,bias_fraction_bits=13,
        LinearSVC=dict(dual=False,max_iter=5000,random_state=701,class_weight=None),
        augmentation=dict(original=True,shear=[-.2,.2],horizontal_scale=[.85,1.15],canvas=[64,64],interpolation='nearest',renormalize_transformed=True),
        threshold_policy='Original validation-only 1% accepted error budget per province/alphanumeric group',heldout_scored=0))
    for name,result in results.items():print(name,result['summary']['all'],result['validation'],flush=True)


if __name__=='__main__':main()
