"""Scalar Q31 contract, checked against frozen arrays without model inference."""
from pathlib import Path
from fractions import Fraction
import hashlib,json,random
import numpy as np

HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[3]
OUT=ROOT/'tmp/blue-plate-whole-plate-budget/requant'
MODEL=ROOT/'tmp/blue-plate-char-segment/quantization-tap2-fork'
VECTORS=ROOT/'tmp/blue-plate-char-segment/integer-deployment-audit'


def segmented(a,m):
    assert -(1<<31)<=a<1<<31 and 0<m<1<<31
    terms=[(a&65535 if i==0 else a>>16)*((m>>(7*j))&127) for i in range(2) for j in range(5)]
    shifts=[16*i+7*j for i in range(2) for j in range(5)]
    total=0
    for p,s in zip(terms,shifts):
        assert -(1<<31)<=p<1<<31
        total+=p<<s
        assert -(1<<63)<=total<1<<63
    assert total==a*m
    return total


def requant(a,m,s,relu,z):
    assert 1<=s<=62 and -128<=z<=127
    p=segmented(max(a,0) if relu else a,m);sticky=0
    for k in range(s):
        guard=p&1;p>>=1
        if k==s-1:p+=guard and (sticky or (p&1))
        else:sticky|=guard
    value=max(-128,min(127,p+z))
    assert value==max(-128,min(127,round(Fraction((max(a,0) if relu else a)*m,1<<s))+z))
    return value


def real_cases():
    config=json.loads((MODEL/'integer-config.json').read_text());params=np.load(MODEL/'integer-parameters.npz')
    stages={s['name']:s for s in config['stages']};records=json.loads((VECTORS/'output-channel-mac-vectors.json').read_text())['records']
    vectors=np.load(VECTORS/'output-channel-mac-vectors.npz');fork=np.load(MODEL/'fork-vectors.npz')
    result=[]
    for r in records:
        name=r['layer'];stage=stages[name];acc=vectors[f"v{r['index']:02d}.psum_after"][-1]
        for lane in range(r['active_output_lanes']):
            c=r['first_output_channel']+lane;a=int(acc[lane]);p=r['position']
            args=[a,int(params[name+'.multiplier'][c]),int(params[name+'.shift'][c]),bool(stage['relu']),stage['output']['zero']]
            q=requant(*args)
            if name=='backbone.11.block.6':assert q==int(fork['context'][0,c,p//44,p%44])
            result.append(dict(args=args,expected=q,source=f"output v{r['index']:02d} lane{lane}",reuse=False))
            if name=='backbone.11.block.6' and c%4==0:
                assert a==int(fork['accumulator'][0,c//4,p//44,p%44])
                args=[a,int(params['tap2.trunk.multiplier'][c//4]),int(params['tap2.trunk.shift'][c//4]),True,config['fork']['output']['zero']]
                q=requant(*args);assert q==int(fork['trunk'][0,c//4,p//44,p%44])
                result.append(dict(args=args,expected=q,source=f"fork v{r['index']:02d} lane{lane}",reuse=True))
    old=ROOT/'tmp/blue-plate-char-segment/quantization-w8a8/real-mac-vectors.json'
    for r in json.loads(old.read_text())['records']:
        args=[r['accumulator'],r['multiplier'],r['right_shift'],r['relu'],r['output_zero']]
        assert requant(*args)==r['requantized']
        result.append(dict(args=args,expected=r['requantized'],source='old scalar '+str(r['index']),reuse=False))
    return result


def main():
    OUT.mkdir(parents=True,exist_ok=True)
    freeze=json.loads((MODEL/'delivery-freeze.json').read_text())['artifacts']
    for n,h in freeze.items():assert hashlib.sha256((ROOT/n).read_bytes()).hexdigest()==h,n
    real=real_cases();rng=random.Random(2718);tests=[]
    for a in (-(1<<31),-(1<<31)+1,-65536,-3,-1,0,1,3,65535,(1<<31)-1):
        for m in (1,127,128,65535,1<<30,(1<<31)-1):
            for s in (1,7,16,31,32,61,62):tests.append([a,m,s,False,-128 if a&1 else 63])
    tests += [[rng.randrange(-(1<<31),1<<31),rng.randrange(1,1<<31),rng.randrange(1,63),bool(rng.randrange(2)),rng.randrange(-128,128)] for _ in range(1200)]
    for args in tests:requant(*args)
    # Both signs, odd/even quotients, and exact half ties at every supported shift.
    for s in range(1,63):
        for sign in (-1,1):
            a=sign*(1<<min(s-1,30));m=1<<max(0,s-31)
            if m<1<<31:requant(a,m,s,False,0)
    paths=[Path(__file__),MODEL/'integer-config.json',MODEL/'integer-parameters.npz',MODEL/'fork-vectors.npz',VECTORS/'output-channel-mac-vectors.npz',VECTORS/'output-channel-mac-vectors.json',ROOT/'docs/validation/blue-plate/char-segment/integer-deployment-addendum.md']
    result=dict(exit_code=0,real_scalar_outputs=len(real),synthetic_cases=len(tests),real=real,
        source_sha256={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths})
    (OUT/'golden-validation.json').write_text(json.dumps(result,indent=2)+'\n')
    print('PASS Q31 golden:',len(real),'real outputs;',len(tests),'synthetic plus shift ties')


if __name__=='__main__':main()
