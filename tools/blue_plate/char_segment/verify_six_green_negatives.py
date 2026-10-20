"""Independent saved-input/Q8 and Decimal CTC checks; no neural inference."""
from decimal import Decimal, localcontext
from fractions import Fraction
import hashlib
import json
from pathlib import Path

import cv2
import numpy as np

ROOT=Path(__file__).resolve().parents[3]
DATA=ROOT/'tmp/blue-plate-char-segment'
OUT=DATA/'six-green-negatives'


def read(p):
    return json.loads(p.read_text(encoding='utf-8'))


def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def digest(a):
    return hashlib.sha256(np.ascontiguousarray(a).tobytes()).hexdigest()


def scalar_resize(image):
    def position(i,src,dst):
        u=max(Fraction(0),min(Fraction(src-1),Fraction((2*i+1)*src-dst,2*dst)))
        lo=int(u)
        fraction=int((u-lo)*256+Fraction(1,2))
        lo+=fraction//256
        return lo,min(lo+1,src-1),fraction%256
    result=np.empty((24,94,3),np.uint8)
    ys=[position(i,64,24) for i in range(24)]
    xs=[position(i,224,94) for i in range(94)]
    for y,(y0,y1,fy) in enumerate(ys):
        for x,(x0,x1,fx) in enumerate(xs):
            for c in range(3):
                v=int(image[y0,x0,c])*(256-fx)*(256-fy)+int(image[y0,x1,c])*fx*(256-fy)
                v+=int(image[y1,x0,c])*(256-fx)*fy+int(image[y1,x1,c])*fx*fy
                result[y,x,c]=(v+32768)//65536
    return result


def decimal_ctc(q,target,scale):
    extended=[67]
    for c in target:extended.extend([c,67])
    prior=[Decimal(0)]*len(extended)
    prior[0]=Decimal(1)
    for col in q.T:
        top=int(col.max())
        exp=[(Decimal(int(v)-top)*scale).exp() for v in col]
        total=sum(exp)
        emissions=[v/total for v in exp]
        current=[]
        for i,c in enumerate(extended):
            value=prior[i]
            if i:value+=prior[i-1]
            if i>=2 and c!=67 and c!=extended[i-2]:value+=prior[i-2]
            current.append(value*emissions[c])
        prior=current
    return sum(prior[-2:] if target else prior[-1:])


def main():
    frozen=read(OUT/'input-freeze.json')
    assert frozen['samples']==[217,271,341,376,381,466]
    for mapping in ('source_hashes','artifacts'):
        assert all(sha(ROOT/p)==h for p,h in frozen[mapping].items())
    assert read(OUT/'inference-start.json')['input_freeze_sha256']==sha(OUT/'input-freeze.json')
    records=read(OUT/'reconstruction-records.json')
    results=read(OUT/'results.json')
    lut=read(DATA/'ctc-q30/lut.json')
    classes=read(DATA/'pretrained-new-rois/config.json')['classes']
    checks=[]
    with np.load(OUT/'inputs.npz',allow_pickle=False) as inputs, np.load(OUT/'integer-logits.npz',allow_pickle=False) as logits:
        assert logits['logits'].shape==(6,68,18) and logits['logits'].dtype==np.int16
        for i,(row,result) in enumerate(zip(records,results)):
            sample=row['sample_index']
            assert sample==result['sample_index']==frozen['samples'][i]
            for meta in row['arrays'].values():
                a=inputs[meta['key']]
                assert list(a.shape)==meta['shape'] and a.dtype.str==meta['dtype'] and digest(a)==meta['sha256_c_order_bytes']
            a=lambda suffix:inputs[f'sample{sample}.{suffix}']
            hsv=cv2.cvtColor(a('native'),cv2.COLOR_BGR2HSV)
            hsv[...,0][hsv[...,1]>60]=60
            np.testing.assert_array_equal(cv2.cvtColor(hsv,cv2.COLOR_HSV2BGR),a('green'))
            h,s,_=cv2.split(cv2.cvtColor(a('green'),cv2.COLOR_BGR2HSV))
            blue=int(((h>100)&(h<140)&(s>95)&(s<255)).sum())
            yellow=int(((h>15)&(h<40)&(s>95)&(s<255)).sum())
            old=row['historical_hs_evidence']
            assert blue==old['counts']['blue_hs'] and yellow==old['counts']['yellow_hs'] and h.size==old['area']
            gh,gw=a('green').shape[:2]
            expected_matrix=[[round(Fraction((gw-1)*2**32,223)),0,0],
                             [0,round(Fraction((gh-1)*2**32,63)),0],[0,0,2**32]]
            assert row['patch_inverse_q32']==expected_matrix
            np.testing.assert_array_equal(scalar_resize(a('fixed_bgr')),a('q8_bgr'))
            q=logits['logits'][i]
            assert digest(q)==result['logits']['sha256_c_order_bytes']
            path=[max(range(68),key=lambda c:int(q[c,t])) for t in range(18)]
            target=[c for j,c in enumerate(path) if c!=67 and (j==0 or c!=path[j-1])]
            assert path==result['greedy_path'] and target==result['decoded_ids']
            assert ''.join(classes[c] for c in target)==result['code']
            legal=len(target)==7 and target[0]<31 and 41<=target[1]<=64 and all(31<=c<=64 for c in target[2:])
            assert legal==result['legal']
            with localcontext() as ctx:
                ctx.prec=180
                scale=Decimal(lut['scale_numerator'])/Decimal(lut['scale_denominator'])
                probability=decimal_ctc(q,target,scale)
                lo,hi=result['bounds_q30']
                assert Decimal(lo)/(2**30)<=probability<=Decimal(hi)/(2**30)
                threshold=(Decimal(lut['tau_numerator'])/Decimal(lut['tau_denominator']))**7
                raw='accept' if probability>=threshold else 'reject'
                assert raw==result['raw_interval_status']
                checks.append(dict(sample_index=sample,decimal_probability=str(probability),
                    q30_contains_decimal=True,raw_threshold_agrees=True,scalar_q8_exact=True,
                    reconstructed_hs_exact=True,edited_fullframe_acceptance=None))
    assert len(checks)==6
    output=dict(pass_all=True,decimal_precision=180,checks=checks,network_forwards=0,
                source_image_reads=0,all_frozen_sources_and_inputs_unchanged=True)
    (OUT/'verification.json').write_text(json.dumps(output,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print('Verified six frozen inputs, scalar Q8 interpolation, saved logits and 180-digit Decimal CTC intervals; zero network calls.')


if __name__=='__main__':main()
