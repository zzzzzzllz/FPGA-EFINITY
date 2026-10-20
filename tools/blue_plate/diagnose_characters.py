"""Compare template and released EasyPR ANN on identical character crops.

Feature construction follows EasyPR charFeatures / preprocessChar (Apache-2.0).
This is an offline floating-point diagnostic, not the deployed FPGA classifier.
"""
import json
from pathlib import Path
import cv2
import numpy as np
import baseline as b


def ann_feature(mask, size):
    h,w=mask.shape
    side=max(h,w)
    square=np.zeros((side,side),np.uint8)
    square[(side-h)//2:(side-h)//2+h,(side-w)//2:(side-w)//2+w]=mask*255
    square=cv2.resize(square,(20,20),interpolation=cv2.INTER_LINEAR)
    yy,xx=np.where(square>20)
    if not len(xx):
        raise ValueError('Blank character')
    tight=square[yy.min():yy.max()+1,xx.min():xx.max()+1]
    centered=np.zeros((20,20),np.uint8)
    h,w=tight.shape
    centered[(20-h)//2:(20-h)//2+h,(20-w)//2:(20-w)//2+w]=tight
    low=cv2.resize(centered,(size,size),interpolation=cv2.INTER_LINEAR)
    vertical=(low>20).sum(axis=0).astype(np.float32)
    horizontal=(low>20).sum(axis=1).astype(np.float32)
    if vertical.max():vertical/=vertical.max()
    if horizontal.max():horizontal/=horizontal.max()
    return np.concatenate([vertical,horizontal,low.ravel()]).astype(np.float32).reshape(1,-1)


def load_models():
    models=[cv2.ml.ANN_MLP_load(str(b.DATA/'easypr/model'/p)) for p in ['ann.xml','ann_chinese.xml']]
    order='川鄂赣甘贵桂黑沪冀津京吉辽鲁蒙闽宁青琼陕苏晋皖湘新豫渝粤云藏浙'
    return models,'0123456789'+b.LETTERS+order,order


def predict(mask,position,models,allchars,chinese):
    chinese_mode=position==0
    model=models[int(chinese_mode)]
    feature=ann_feature(mask,20 if chinese_mode else 10)
    scores=model.predict(feature)[1].ravel()
    labels=chinese if chinese_mode else allchars
    allowed=b.PROVINCES if chinese_mode else b.LETTERS if position==1 else b.ADS
    ranking=sorted(((float(scores[i]),c) for i,c in enumerate(labels) if c in allowed),reverse=True)
    return dict(char=ranking[0][1],score=ranking[0][0],margin=ranking[0][0]-ranking[1][0])


def main():
    out=b.DATA/'character-diagnostic';out.mkdir(exist_ok=True)
    models,allchars,chinese=load_models()
    classes,templates,_,_=b.make_templates('xor',12)
    samples=b.load_samples()
    rows=[];annotations=[];strips=[]
    # These five development crops are individually visually checked. They are
    # a failure diagnostic, not a random test or an estimate of full accuracy.
    selected=[3,6,7,8,9]
    for index in selected:
        sample=samples[index]
        assert sample['split']=='development'
        plate=b.warp(b.read_image(b.ROOT/sample['path']),np.array(sample['points'])[[2,3,0,1]])
        chars,mask,rects=b.segment(plate,'global','projection')
        assert len(chars)==7
        annotations.append(dict(path=sample['path'],label=sample['label'],rects=rects,
            coordinate_system='224x64 oracle-rectified plate',selection='clear development images; visually audited'))
        row=dict(path=sample['path'],label=sample['label'],xor=[],ann=[])
        for position,char in enumerate(chars):
            row['xor'].append(b.classify(char,position,classes,templates,'xor'))
            row['ann'].append(predict(char,position,models,allchars,chinese))
        rows.append(row)
        strip=np.hstack([cv2.resize(c*255,(48,64),interpolation=cv2.INTER_NEAREST) for c in chars])
        strips.append(strip)
    cv2.imwrite(str(out/'checked-characters.png'),np.vstack(strips))
    summaries={}
    for method in ['xor','ann']:
        summaries[method]=dict(characters=35,correct=sum(s['char']==truth for row in rows for s,truth in zip(row[method],row['label'])),
            provinces_correct=sum(row[method][0]['char']==row['label'][0] for row in rows),
            full_correct=sum(''.join(s['char'] for s in row[method])==row['label'] for row in rows))
    (out/'manual-audit.json').write_text(json.dumps(annotations,ensure_ascii=False,indent=2),encoding='utf8')
    (out/'results.json').write_text(json.dumps(rows,ensure_ascii=False,indent=2),encoding='utf8')
    (out/'summary.json').write_text(json.dumps(summaries,indent=2),encoding='utf8')
    print(json.dumps(summaries))


if __name__=='__main__':main()
