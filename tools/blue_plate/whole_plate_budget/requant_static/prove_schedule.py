"""Full-int8-domain constant proofs and one fixed-six-stage RNE schedule."""
from pathlib import Path
from fractions import Fraction
import hashlib,json,random
import numpy as np

HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[3]
OUT=ROOT/'tmp/blue-plate-whole-plate-budget/requant-static'
MODEL=ROOT/'tmp/blue-plate-char-segment/quantization-tap2-fork'


def rne6(p,s):
    assert -(1<<63)<=p<(1<<63) and 1<=s<=62
    initial=p;guard=sticky=0
    for k in (1,2,4,8,16,32):
        if s&k:
            sticky=int(bool(sticky or guard or (p&((1<<(k-1))-1))))
            guard=(p>>(k-1))&1;p>>=k
    answer=p+int(guard and (sticky or (p&1)))
    assert answer==round(Fraction(initial,1<<s))
    return answer


def main():
    OUT.mkdir(parents=True,exist_ok=True)
    paths=[MODEL/'integer-config.json',MODEL/'integer-parameters.npz',ROOT/'docs/validation/blue-plate/whole-plate-budget/service-cost.json',ROOT/'tmp/blue-plate-review/service-cost/review-result.json']
    paths += [ROOT/'tmp/blue-plate-review/service-research'/n for n in ('nnet_dense_compressed.h','nnet_dense_latency.h','finn-reorder.py')]
    sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest();hashes={str(p):sha(p) for p in paths}
    freeze=json.loads((MODEL/'delivery-freeze.json').read_text())['artifacts']
    for p in paths[:2]:assert sha(p)==freeze[p.relative_to(ROOT).as_posix()]
    cfg=json.loads(paths[0].read_text());weights=np.load(paths[1]);service=json.loads(paths[2].read_text());review=json.loads(paths[3].read_text())
    stages={s['name']:s for s in cfg['stages']};rows=[];proofs=[];all_channels=0
    for row in service['layers']:
        name=row['name'];fork=name=='tap2.trunk';base=cfg['fork']['stage'] if fork else name;stage=stages[base]
        w=weights[base+'.weight'].astype(np.int64).reshape(stage['shape'][0],-1);bias=weights[base+'.bias'].astype(np.int64)
        if fork:w=w[::4];bias=bias[::4]
        pos=np.maximum(w,0).sum(axis=1);neg=np.minimum(w,0).sum(axis=1)
        lo=bias-128*pos+127*neg;hi=bias+127*pos-128*neg
        assert np.all(lo<=hi) and np.all(lo>=-(1<<31)) and np.all(hi<(1<<31))
        m=weights[name+'.multiplier'];sh=weights[name+'.shift'];z=cfg['fork']['output']['zero'] if fork else stage['output']['zero']
        const=[];dynamic_shifts=0;channels=[]
        for c in range(len(lo)):
            def q(a):return max(-128,min(127,round(Fraction((max(a,0) if stage['relu'] else a)*int(m[c]),1<<int(sh[c])))+z))
            qlo,qhi=q(int(lo[c])),q(int(hi[c]));constant=qlo==qhi
            record=dict(layer=name,channel=c,bias=int(bias[c]),acc_lower=int(lo[c]),acc_upper=int(hi[c]),multiplier=int(m[c]),shift=int(sh[c]),relu=stage['relu'],zero=z,constant=constant,value=qlo if constant else None,
                packed_multiplier=((1<<31)|(qlo&255)) if constant else int(m[c]))
            assert bool(record['packed_multiplier']>>31)==constant
            if constant:assert ((record['packed_multiplier']&255)^128)-128==qlo
            channels.append(record);proofs.append(record);all_channels+=1
            if constant:const.append(c)
            else:dynamic_shifts+=int(sh[c])
        old=next(x for x in review['constant_rows'] if x['name']==name)
        assert const==[x['channel'] for x in old['proofs']]
        for r in old['proofs']:
            p=channels[r['channel']];assert (p['acc_lower'],p['acc_upper'],p['value'])==(r['acc_lower'],r['acc_upper'],r['value'])
        positions=row['positions'];nconst=len(const)*positions;ndynamic=row['outputs']-nconst
        removed=positions*sum(21+int(sh[c])+(0 if fork else 17) for c in const)
        stage_saved=positions*dynamic_shifts-6*ndynamic
        rows.append(dict(name=name,channels=len(lo),positions=positions,constant_channels=len(const),constant_outputs=nconst,dynamic_outputs=ndynamic,
            removed_old_q_and_restore_cycles=removed,constant_output_transaction_cycles=2*nconst,
            dynamic_q_transaction_cycles=27*ndynamic,dynamic_shift_cycles=6*ndynamic,
            dynamic_restore_cycles=0 if fork else 17*ndynamic,extra_shift_saving_cycles=stage_saved,
            total_saved_cycles=removed-2*nconst+stage_saved))
    # A constant primary branch must not silently supply a stale scalar to a dynamic fork.
    primary={p['channel']:p['constant'] for p in proofs if p['layer']==cfg['fork']['stage']}
    assert all(not(primary[p['channel']*4] and not p['constant']) for p in proofs if p['layer']=='tap2.trunk')
    rng=random.Random(811);tests=0
    for s in range(1,63):
        for p in [-(1<<63),-(1<<62),-5,-3,-1,0,1,3,5,(1<<62)-1,(1<<63)-1]+[rng.randrange(-(1<<63),1<<63) for _ in range(100)]:
            rne6(p,s);tests+=1
    total_const=sum(r['constant_outputs'] for r in rows);saved=sum(r['total_saved_cycles'] for r in rows)
    assert total_const==658256 and sum(r['removed_old_q_and_restore_cycles'] for r in rows)==59443864
    assert saved==82566768
    result=dict(exit_code=0,proof_domain='All independent input terms in signed int8 [-128,127], including padding; no observed ranges.',
        constant_outputs=total_const,dynamic_outputs=service['lpr']['totals']['outputs']-total_const,channels=all_channels,
        six_stage_round_checks=tests,main_review_matches=True,no_constant_primary_dynamic_fork=True,
        total_saved_cycles=saved,constant_transaction_cycles=2*total_const,
        old_lpr_core_cycles=service['lpr']['serial_core_cycles'],new_lpr_core_cycles=service['lpr']['serial_core_cycles']-saved,
        old_known_three_model_cycles=service['service']['one_roi_known_serial_cycles'],new_known_three_model_cycles=service['service']['one_roi_known_serial_cycles']-saved,
        scope='Dense MAC, dense layout, all group saves and existing per-dynamic-lane restore remain. Constant request+write handshake costs 2 clocks. No DDR or full-network latency claim.',
        rows=rows,proofs=proofs,source_sha256=hashes)
    assert hashes=={str(p):sha(p) for p in paths}
    (OUT/'proof-and-schedule.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps({k:v for k,v in result.items() if k not in ('rows','proofs','source_sha256')},indent=2))


if __name__=='__main__':main()
