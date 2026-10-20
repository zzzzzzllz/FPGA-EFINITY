"""Reuse frozen full-K vectors; add scalar reads and real two-consumer records."""
from pathlib import Path
import hashlib,json
import numpy as np

HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[3]
OUT=ROOT/'tmp/blue-plate-whole-plate-budget/scalar-read'


def main():
    OUT.mkdir(parents=True,exist_ok=True)
    pack=lambda xs,n:sum((int(x)&((1<<n)-1))<<(i*n) for i,x in enumerate(xs))
    hashes={}
    def track(p):hashes[str(p)]=hashlib.sha256(p.read_bytes()).hexdigest();return p
    inserted={}
    for stage in ('rtl','mapped'):
        source=track(ROOT/'tmp/blue-plate-whole-plate-budget/partial-sum'/(stage+'-vectors.txt'))
        rows=[];last=None;groups=0
        def edge(acc,save=0,sread=0,ready=0,lane=0,busy=0,done=0,valid=0,value=0):
            fields=[0,1,0,0,0,0,0,0,255,0,0,save,0,63,acc,0,0,busy,done,0,0,sread,ready,lane,valid,value&0xffffffff]
            rows.append(' '.join(format(x,'x') for x in fields))
        for line in source.read_text().splitlines():
            f=[int(x,16) for x in line.split()]
            if f[9] and f[10]==pack([0x12345678]*8,32):
                assert last and not last[17] and not last[20]
                acc=last[14];edge(acc,save=1,busy=1)
                for j in range(8):edge(acc,busy=int(j<7),done=int(j==7))
                for lane in range(8):
                    edge(acc,sread=1,lane=lane,busy=1)
                    edge(acc,busy=1,valid=1,value=acc>>(lane*32))
                    edge(acc,ready=1)
                groups+=1
            rows.append(line+' 0 0 0 0 0');last=f
        (OUT/(stage+'-psum-vectors.txt')).write_text('\n'.join(rows)+'\n')
        inserted[stage]=dict(original_cycles=len(source.read_text().splitlines()),cycles=len(rows),saved_groups=groups,scalar_reads=groups*8)
    model=ROOT/'tmp/blue-plate-char-segment/quantization-tap2-fork'
    cfg=json.loads(track(model/'integer-config.json').read_text());params=np.load(track(model/'integer-parameters.npz'))
    source=ROOT/'tmp/blue-plate-char-segment/integer-deployment-audit'
    records=json.loads(track(source/'output-channel-mac-vectors.json').read_text())['records']
    vectors=np.load(track(source/'output-channel-mac-vectors.npz'))
    import sys
    sys.path.insert(0,str(HERE.parent/'requant'));from golden import requant
    stages={s['name']:s for s in cfg['stages']};lines=[];qcount=forkcount=0
    def emit(op,*fields):lines.append(' '.join(format(int(x),'x') for x in (op,*fields)))
    for r in records:
        prefix=f"v{r['index']:02d}.";name=r['layer'];stage=stages[name]
        w=vectors[prefix+'weight'];a=vectors[prefix+'activation'];seed=vectors[prefix+'seed'];sums=vectors[prefix+'psum_after']
        for k in range(r['k']):emit(1,k,pack(w[k],8))
        emit(2,pack(seed,32))
        for k in range(r['k']):emit(3,k,pack(a[k],17),(1<<r['active_output_lanes'])-1)
        emit(4,pack(sums[-1],32));emit(5,r['index'])
        for lane in range(r['active_output_lanes']):
            c=r['first_output_channel']+lane;acc=int(sums[-1,lane])
            outputs=[(6,name,c,stage['output']['zero'])]
            if name==cfg['fork']['stage'] and c%4==0:outputs.append((7,'tap2.trunk',c//4,cfg['fork']['output']['zero']));forkcount+=1
            for op,key,ch,zero in outputs:
                m=int(params[key+'.multiplier'][ch]);shift=int(params[key+'.shift'][ch]);relu=int(stage['relu'])
                product=(max(acc,0) if relu else acc)*m
                emit(op,r['index'],lane,acc&0xffffffff,m,shift,relu,zero&255,requant(acc,m,shift,relu,zero)&255,product&((1<<64)-1));qcount+=1
    (OUT/'real-commands.txt').write_text('\n'.join(lines)+'\n')
    (OUT/'test-inputs.json').write_text(json.dumps(dict(inserted=inserted,real_q_outputs=qcount,real_fork_outputs=forkcount,real_mac_steps=sum(r['k'] for r in records),source_sha256=hashes),indent=2)+'\n')
    print(inserted,'real outputs',qcount,'forks',forkcount)


if __name__=='__main__':main()
