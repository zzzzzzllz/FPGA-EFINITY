"""Deterministic development / held-out synthetic samples, not camera accuracy."""
from pathlib import Path
work=Path(__file__).resolve().parents[4]/'tmp/tests'/Path(__file__).resolve().parents[2].name
work.mkdir(parents=True,exist_ok=True)
import json
import numpy as np
from canny_reference import classify, hysteresis
from shape_reference import recognize


def sample(kind, seed, w=1280, h=720):
    rng = np.random.default_rng(seed)
    y,x = np.indices((h,w))
    radius = int(rng.integers(50,175))
    cx,cy = int(rng.integers(300,w-300)),int(rng.integers(230,h-230))
    angle = rng.uniform(0,np.pi)
    u = (x-cx)*np.cos(angle)+(y-cy)*np.sin(angle)
    v = -(x-cx)*np.sin(angle)+(y-cy)*np.cos(angle)
    if kind=='circle': mask = (x-cx)**2+(y-cy)**2<=radius**2
    elif kind=='rectangle': mask = (abs(u)<=radius)&(abs(v)<=radius*.7)
    elif kind=='ellipse': mask = ((x-cx)/(radius*1.4))**2+((y-cy)/(radius*.7))**2<=1
    elif kind=='triangle': mask = (v>=-radius)&(v<=radius)&(abs(u)<(v+radius)/2)
    elif kind=='open':
        mask = ((abs(u-radius)<3)&(abs(v)<radius))|((abs(v-radius)<3)&(abs(u)<radius))
    else: raise ValueError(kind)
    return np.where(mask,32,224).astype(np.uint8)


def run():
    root = Path(__file__).resolve().parents[1]
    records = []
    for split,first in [('development',10000),('held-out',20000)]:
        for canny in (False,True):
            for kind in ('circle','rectangle','ellipse','triangle','open'):
                correct = 0
                details = []
                for i in range(20):
                    gray = sample(kind,first+i)
                    state,*_ = classify(gray,32,1,True,canny)
                    edge = hysteresis(state)[0] if canny else state==2
                    original = edge.copy()
                    result = recognize(edge)
                    assert np.array_equal(edge,original), 'recognizer changed input'
                    expected = {'circle':1,'rectangle':2}.get(kind,0)
                    kinds = [t['kind'] for t in result['targets']]
                    passed = kinds==([expected] if expected else [])
                    correct += passed
                    if not passed: details.append(dict(seed=first+i,found=result))
                record = dict(split=split,algorithm='canny' if canny else 'sobel',kind=kind,correct=correct,total=20,failures=details)
                records.append(record)
                print(f'{split} {record["algorithm"]} {kind}: {correct}/20',flush=True)
    output = work/'edge-m10-reference.json'
    output.write_text(json.dumps(dict(source='synthetic; camera acceptance is separate',records=records),indent=2),encoding='utf-8')
    assert all(r['correct']>=19 for r in records), output


if __name__=='__main__': run()
