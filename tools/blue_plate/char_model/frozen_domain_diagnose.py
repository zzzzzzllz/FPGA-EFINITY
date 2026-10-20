"""Inspect full input shape, feature contribution, and training-only neighbors."""
import json
from pathlib import Path
import cv2
import numpy as np
from model import CLASSES,features,integer_scores,allowed_ids
from frozen_domain import ROOT,BASE,OUT,CANDIDATE,read,save,image


def tile(im,text):
    if im.ndim==2:im=cv2.cvtColor(im,cv2.COLOR_GRAY2BGR)
    out=np.zeros((114,96,3),np.uint8)
    h,w=im.shape[:2];s=min(88/h,88/w)
    im=cv2.resize(im,(max(1,round(w*s)),max(1,round(h*s))),interpolation=cv2.INTER_NEAREST)
    h,w=im.shape[:2];out[22+(88-h)//2:22+(88-h)//2+h,(96-w)//2:(96-w)//2+w]=im
    cv2.putText(out,text,(2,13),0,.36,(255,255,255),1)
    return out


def shape(mask):
    yy,xx=np.where(mask);tight=mask[yy.min():yy.max()+1,xx.min():xx.max()+1]
    return dict(height=int(tight.shape[0]),width=int(tight.shape[1]),density=float(tight.mean()),foreground=int(mask.sum()))


def main():
    batch=read(OUT/'batch.json');masks=np.load(OUT/'frozen-masks.npy')
    data=np.load(BASE/'dataset.npz');ids=np.flatnonzero(data['split']=='train')
    tm=data['masks'][ids];ty=data['y'][ids]
    train_features=np.array([features(m) for m in tm],np.int32)
    provenance=read(BASE/'manifest.json')
    weights=dict(np.load(CANDIDATE/'weights.npz'))
    selected=[('115-automatic',4),('050-oracle',6)]
    result=[];strips=[]
    for key,pos in selected:
        row=next(r for r in batch if r['key']==key);c=row['characters'][pos]
        norm=masks[c['index']];x=features(norm);score=integer_scores(x,weights)
        allowed=allowed_ids(pos);ranked=allowed[np.argsort(-score[allowed],kind='stable')]
        truth=CLASSES.index(c['truth']);pred=int(ranked[0])
        diff=(weights['w1'][:,truth].astype(np.int64)-weights['w1'][:,pred])*x
        contrib=dict(grid_top_half=int(diff[:128].sum()),grid_bottom_half=int(diff[128:256].sum()),
            column_projection=int(diff[256:288].sum()),row_projection=int(diff[288:].sum()),
            bias=int(weights['b1'][truth]-weights['b1'][pred]),total=int(score[truth]-score[pred]))
        assert sum(v for k,v in contrib.items() if k!='total')==contrib['total']
        neighbors=[];distribution={}
        for label in [truth,pred]:
            pool=np.flatnonzero(ty==label)
            distances=np.abs(train_features[pool]-x).sum(axis=1)
            picks=pool[np.argsort(distances,kind='stable')[:4]]
            neighbors.extend(dict(id=int(ids[i]),char=CLASSES[label],distance=int(np.abs(train_features[i]-x).sum()),
                path=provenance[int(ids[i])]['path'],file_sha256=provenance[int(ids[i])]['file_sha256'],shape=shape(tm[i])) for i in picks)
            props=[shape(tm[i]) for i in pool]
            distribution[CLASSES[label]]=dict(count=len(pool),density_quantiles=np.quantile([v['density'] for v in props],[.1,.5,.9]).tolist(),
                aspect_quantiles=np.quantile([v['width']/v['height'] for v in props],[.1,.5,.9]).tolist())
        raw=image(ROOT/c['path']);gray=image(ROOT/c['gray'])
        tiles=[tile(gray,'gray'),tile(raw,'binary'),tile(norm*255,'canonical')]
        # 16x16 sums retain four intensity levels. Row/column projection is in JSON.
        grid=x[:256].reshape(16,16).astype(np.uint8)*7
        tiles.append(tile(grid,'grid 0..32'))
        for n in neighbors:
            tiles.append(tile(data['masks'][n['id']]*255,f"{n['char']} d{n['distance']}"))
        strips.append(np.hstack(tiles))
        result.append(dict(key=key,position=pos,label=row['label'],truth=c['truth'],prediction=CLASSES[pred],
            raw_shape=shape(raw>0),normalized_shape=shape(norm),top_scores=[dict(char=CLASSES[int(i)],score=int(score[i])) for i in ranked[:8]],
            true_minus_predicted_feature_contribution=contrib,train_distributions=distribution,neighbors=neighbors,
            input_column_sums=x[256:288].tolist(),input_row_sums=x[288:].tolist()))
    cv2.imwrite(str(OUT/'confusion-neighbors.png'),np.vstack(strips))
    save(OUT/'confusion-analysis.json',result)
    print(json.dumps([{k:v for k,v in r.items() if k not in ['neighbors','input_column_sums','input_row_sums']} for r in result],ensure_ascii=False,indent=2))


if __name__=='__main__':main()
