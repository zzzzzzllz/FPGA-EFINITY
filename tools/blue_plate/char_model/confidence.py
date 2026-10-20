"""Validation-only operating-point sweep; external development ROIs are read-only."""
import json
from pathlib import Path
import numpy as np
from model import features, integer_scores, decide
ROOT=Path(__file__).resolve().parents[3]
OUT=ROOT/'tmp/blue-plate-char-model'


def main():
    data=np.load(OUT/'dataset.npz'); y=data['y']; split=data['split']
    roi_records=json.loads((OUT/'roi-records.json').read_text(encoding='utf8'))['records']
    roi_masks=np.load(OUT/'roi-masks.npy').reshape(-1,7,32,32)
    results={}
    for name in ['linear0.1','mlp64','mlp128']:
        folder=OUT/name; pred=np.load(folder/'predictions.npz')
        config=json.loads((folder/'interface.json').read_text(encoding='utf8'))
        weights=dict(np.load(folder/'weights.npz'))
        audited={r['index'] for r in json.loads((folder/'roi-diagnostic.json').read_text(encoding='utf8'))['rows']}
        policies={'validation_1pct':config['thresholds']}
        strict={}
        for group_name,group in [('province',y<31),('alphanumeric',y>=31)]:
            use=(split=='validation')&group
            correct=pred['prediction'][use]==y[use]
            top,margin=pred['score'][use],pred['margin'][use]
            best=None
            # For each score threshold, reject every observed validation error
            # by setting gap above the largest remaining erroneous gap.
            for score in np.unique(top):
                bad=(~correct)&(top>=score)
                gap=0 if not bad.any() else int(margin[bad].max())+1
                count=int((correct&(top>=score)&(margin>=gap)).sum())
                choice=(-count,int(score),gap)
                if best is None or choice<best: best=choice
            strict[group_name]=dict(score=best[1],margin=best[2])
        policies['validation_zero_errors']=strict
        results[name]={}
        for policy,thresholds in policies.items():
            accepted=np.zeros(len(y),bool)
            for group_name,group in [('province',y<31),('alphanumeric',y>=31)]:
                t=thresholds[group_name]
                accepted[group]=(pred['score'][group]>=t['score'])&(pred['margin'][group]>=t['margin'])
            summary={'thresholds':thresholds}
            for name_split in ['validation','test']:
                use=split==name_split; ok=accepted&use; correct=pred['prediction']==y
                summary[name_split]=dict(total=int(use.sum()),correct=int((ok&correct).sum()),wrong=int((ok&~correct).sum()),reject=int((use&~accepted).sum()))
            rows=[]
            for r,masks in zip(roi_records,roi_masks):
                if r['index'] not in audited:continue
                decisions=[decide(integer_scores(features(mask),weights),position,thresholds) for position,mask in enumerate(masks)]
                text=''.join(d['char'] for d in decisions)
                rows.append(dict(index=r['index'],correct=text==r['label'],accepted=all(d['accepted'] for d in decisions)))
            summary['development_roi']=dict(plates=len(rows),correct=sum(r['correct'] and r['accepted'] for r in rows),wrong=sum(not r['correct'] and r['accepted'] for r in rows),reject=sum(not r['accepted'] for r in rows))
            results[name][policy]=summary
    (OUT/'confidence.json').write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf8')
    print(json.dumps(results,indent=2))


if __name__=='__main__': main()
