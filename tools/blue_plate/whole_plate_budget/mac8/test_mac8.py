"""Independent Python integer oracle; each edge is checked in the vendor-model RTL."""
from pathlib import Path
import argparse,hashlib,json,random,subprocess

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[3]
OUT=ROOT/'tmp/blue-plate-whole-plate-budget/mac8'
SIM=ROOT/'tools/iverilog-12/app/bin'
MODELS=Path('D:/Efinity/sim_models/verilog')


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--mapped',action='store_true');args=ap.parse_args()
    OUT.mkdir(parents=True,exist_ok=True)
    rng=random.Random(818);state=[0]*8;lines=[];counts={'reset':0,'load':0,'stall':0,'mac_lanes':0,'overflow_lanes':0}
    pack=lambda xs,bits:sum((v&((1<<bits)-1))<<(i*bits) for i,v in enumerate(xs))
    def edge(a=None,w=None,seed=None,rst=0,ce=1,valid=1,load=0,mask=255):
        a=a if a is not None else [rng.randint(-65536,65535) for _ in range(8)]
        w=w if w is not None else [rng.randint(-128,127) for _ in range(8)]
        seed=seed if seed is not None else [rng.randint(-2**31,2**31-1) for _ in range(8)]
        assert all(-65536<=v<=65535 for v in a) and all(-128<=v<=127 for v in w)
        update=over=0
        if rst:state[:]=[0]*8;counts['reset']+=1
        elif not ce:counts['stall']+=1
        elif load:state[:]=seed;update=255;counts['load']+=1
        elif valid:
            for i in range(8):
                if mask>>i&1:
                    exact=state[i]+a[i]*w[i]
                    bad=not (-2**31<=exact<2**31)
                    state[i]=(exact+2**31)%2**32-2**31
                    update|=1<<i;over|=int(bad)<<i
                    counts['mac_lanes']+=1;counts['overflow_lanes']+=bad
        fields=[rst,ce,valid,load,mask,pack(a,17),pack(w,8),pack(seed,32),pack(state,32),update,over]
        lines.append(' '.join(format(v,'x') for v in fields))
    edge(rst=1,ce=0,load=1)
    # Every activation/weight endpoint pair, plus lane independence.
    aa=[-65536,-32768,-255,-128,-1,0,1,127,255,32767,65535]
    ww=[-128,-127,-1,0,1,127]
    for a in aa:
        for w in ww:
            edge(load=1,seed=[0]*8,valid=1,mask=0)
            edge(a=[a]*8,w=[w]*8)
    # Explicit positive and negative int32 overflow, wrapping is reported.
    edge(load=1,seed=[2**31-1,-2**31]*4)
    edge(a=[1,-1]*4,w=[1]*8)
    edge(ce=0,load=1);edge(valid=0);edge(mask=0)
    edge(rst=1,ce=0)
    # A stopped transfer cannot load or MAC; reset still clears while stopped.
    for mask in (1,2,4,8,16,32,64,128,15,85,170,255):
        edge(load=1,seed=list(range(8)))
        edge(a=aa[:8],w=[127,-128]*4,mask=mask)
        edge(ce=0);edge(valid=0);edge(mask=0)
    # Save at K=2048, overwrite the core, then reload and complete K=3328.
    splits=[]
    for lanes in (8,4):
        bias=[rng.randint(-65536,65536) for _ in range(8)]
        a=[[rng.randint(-255,255) for _ in range(8)] for _ in range(3328)]
        w=[[rng.randint(-128,127) for _ in range(8)] for _ in range(3328)]
        expected=[bias[j]+sum(a[k][j]*w[k][j] for k in range(3328)) if j<lanes else bias[j] for j in range(8)]
        edge(load=1,seed=bias)
        for k in range(3328):
            if k==2048:
                saved=state.copy();edge(load=1,seed=[0x12345678]*8);edge(ce=0,load=1)
                edge(load=1,seed=saved)
            if k%13==0:edge(ce=0)
            if k%29==0:edge(valid=0)
            edge(a=a[k],w=w[k],mask=(1<<lanes)-1)
        assert state==expected
        splits.append({'K':3328,'chunks':[2048,1280],'valid_lanes':lanes,'result':state.copy()})
    # Full unsigned-16 values fit positive signed-17 and must not become negative.
    edge(load=1,seed=[0]*8)
    for _ in range(3330):edge(a=[65535,40800,2295,255,-65536,-255,0,1],w=[127,-128,127,-128,-128,127,-1,0])
    for _ in range(2000):
        edge(rst=int(rng.randrange(71)==0),ce=int(rng.randrange(4)!=0),
             load=int(rng.randrange(23)==0),valid=int(rng.randrange(5)!=0),mask=rng.randrange(256))
    edge(rst=1,ce=0);edge(valid=0)
    vectors=OUT/'vectors.txt';vectors.write_text('\n'.join(lines)+'\n',encoding='ascii')
    rtl=OUT/'synthesis/out/mac8.map.v' if args.mapped else HERE/'rtl/mac8.v'
    stage='mapped' if args.mapped else 'rtl';binary=OUT/(stage+'.vvp')
    command=[str(SIM/'iverilog.exe'),'-g2012','-s','tb_mac8','-y',str(MODELS),'-Y','.v',
             '-o',str(binary),str(HERE/'tb_mac8.sv'),str(rtl)]
    c=subprocess.run(command,capture_output=True,text=True)
    (OUT/(stage+'-compile.log')).write_text(c.stdout+c.stderr)
    if c.returncode:raise RuntimeError(c.stdout+c.stderr)
    log=OUT/(stage+'-run.log')
    with log.open('w') as stream:
        r=subprocess.run([str(SIM/'vvp.exe'),str(binary),'+VECTORS='+str(vectors)],stdout=stream,stderr=subprocess.STDOUT,text=True)
    output=log.read_text()
    if r.returncode or 'PASS mac8' not in output:raise RuntimeError(output)
    paths=[HERE/'rtl/mac8.v',HERE/'tb_mac8.sv',Path(__file__),MODELS/'efx_dsp48.v',vectors,rtl]
    receipt={'stage':stage,'exit_code':0,'cycles':len(lines),'lane_state_checks':len(lines)*8,'coverage':counts,
        'split_checks':splits,'stdout':output,'files_sha256':{str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}}
    (OUT/(stage+'-validation.json')).write_text(json.dumps(receipt,indent=2)+'\n')
    print(json.dumps(receipt,indent=2))


if __name__=='__main__':main()
