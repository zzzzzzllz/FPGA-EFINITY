"""Check RAM addressing and stalled synchronous-read/MAC alignment against integers."""
from pathlib import Path
import argparse,hashlib,json,random,subprocess

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[3]
OUT=ROOT/'tmp/blue-plate-whole-plate-budget/weight-bank'
SIM=ROOT/'tools/iverilog-12/app/bin'
MODELS=Path('D:/Efinity/sim_models/verilog')
MAC=HERE.parent/'mac8/rtl/mac8.v'


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--mapped',action='store_true');args=ap.parse_args()
    OUT.mkdir(parents=True,exist_ok=True)
    assert hashlib.sha256(MAC.read_bytes()).hexdigest()=='f3490692d9bd2160144da3c92693bb8b65f0cbe0a9d435dc4321514cd2c7ffee'
    mem=[None]*2048;state=[0]*8;pending=False;word=0;aq=[0]*8;mq=0;lines=[]
    counts=dict(writes=0,reads=0,mac_lanes=0,errors=0,stalls=0,resets=0,loads=0,overflow_lanes=0)
    read_addresses=set();rng=random.Random(1648)
    pack=lambda xs,bits:sum((v&((1<<bits)-1))<<(i*bits) for i,v in enumerate(xs))
    weights=lambda k:[((k*17+j*29)%256)-128 for j in range(8)]
    acts=lambda k:[((k*23+j*53)%511)-255 for j in range(8)]
    def edge(rst=0,ce=1,wr=0,wa=0,wd=0,issue=0,ra=0,a=None,mask=255,load=0,seed=None):
        nonlocal pending,word,aq,mq
        a=a if a is not None else [rng.randint(-255,255) for _ in range(8)]
        seed=seed if seed is not None else [rng.randint(-65536,65536) for _ in range(8)]
        error=bool(ce and not rst and ((wr and issue) or (load and (wr or issue)) or ((wr or load) and pending)))
        updated=over=0
        if rst:
            state[:]=[0]*8;pending=False;word=0;counts['resets']+=1
        elif not ce:counts['stalls']+=1
        else:
            if load and not error:state[:]=seed;updated=255;counts['loads']+=1
            elif pending:
                for j in range(8):
                    if mq>>j&1:
                        w=(word>>(8*j))&255;w=w-256 if w>=128 else w
                        exact=state[j]+aq[j]*w
                        bad=not (-2**31<=exact<2**31)
                        state[j]=(exact+2**31)%2**32-2**31
                        updated|=1<<j;over|=int(bad)<<j
                        counts['mac_lanes']+=1;counts['overflow_lanes']+=bad
            pending=bool(issue and not error)
            if pending:
                assert mem[ra] is not None,'Read before load'
                word=mem[ra];aq=a.copy();mq=mask;counts['reads']+=1;read_addresses.add(ra)
            if wr and not error:mem[wa]=wd;counts['writes']+=1
            counts['errors']+=error
        fields=[rst,ce,wr,wa,wd,issue,ra,pack(a,17),mask,load,pack(seed,32),word,int(pending),int(error),pack(state,32),updated,over]
        lines.append(' '.join(format(v,'x') for v in fields))
    edge(rst=1,ce=0)
    # Load every depth/width bank and read every address, including all boundaries.
    for k in range(2048):edge(wr=1,wa=k,wd=pack(weights(k),8))
    edge(load=1,seed=[0]*8)
    for k in range(2048):
        if k%31==0:edge(ce=0,issue=1,ra=(k+13)%2048)
        edge(issue=1,ra=k,a=acts(k),mask=(255 if k%3 else 15))
    edge()
    assert not pending and len(read_addresses)==2048
    for addr in (0,511,512,1023,1024,1535,1536,2047):
        edge(issue=1,ra=addr,a=[-255,255,-128,127,0,1,-1,255],mask=85)
        edge(ce=0,wr=1,wa=addr,wd=0);edge(ce=0,load=1)
        edge()
    # Invalid new commands are rejected; a previously issued read still retires.
    edge(wr=1,wa=511,wd=0,issue=1,ra=511)
    edge(issue=1,ra=511)
    edge(load=1,seed=[777]*8)
    edge(issue=1,ra=1024)
    edge(wr=1,wa=1024,wd=0)
    edge(load=1,wr=1,wa=1536,wd=0)
    edge(load=1,issue=1,ra=0)
    edge(issue=1,ra=1024);edge(rst=1,ce=0);edge()
    # Reset clears pending/output only; loaded RAM contents survive.
    edge(issue=1,ra=2047);edge()
    splits=[]
    for valid_lanes in (8,4):
        bias=[1000-j*777 for j in range(8)]
        edge(load=1,seed=bias)
        for start,count in ((0,2048),(2048,1280)):
            if start:saved=state.copy();edge(load=1,seed=[12345678]*8)
            for k in range(count):edge(wr=1,wa=k,wd=pack(weights(start+k),8))
            if start:edge(load=1,seed=saved)
            for k in range(count):
                if k%17==0:edge(ce=0,issue=1,ra=k)
                if k%43==0:edge()
                edge(issue=1,ra=k,a=acts(start+k),mask=(1<<valid_lanes)-1)
            edge()
            assert not pending
        expected=[bias[j]+sum(acts(k)[j]*weights(k)[j] for k in range(3328)) if j<valid_lanes else bias[j] for j in range(8)]
        assert state==expected
        splits.append(dict(K=3328,chunks=[2048,1280],valid_lanes=valid_lanes,result=state.copy()))
    # Overflow remains explicit through the weight-read pipeline.
    edge(wr=1,wa=0,wd=pack([127,-128]*4,8));edge(load=1,seed=[2**31-1,-2**31]*4)
    edge(issue=1,ra=0,a=[65535]*8);edge();edge(rst=1)
    vectors=OUT/'vectors.txt';vectors.write_text('\n'.join(lines)+'\n',encoding='ascii')
    stage='mapped' if args.mapped else 'rtl';binary=OUT/(stage+'.vvp')
    sources=[OUT/'synthesis/out/weight_mac8.map.v'] if args.mapped else [HERE/'rtl/weight_bank8.v',HERE/'rtl/weight_mac8.v',MAC]
    command=[str(SIM/'iverilog.exe'),'-g2012','-s','tb_weight_mac8','-y',str(MODELS),'-Y','.v','-o',str(binary),str(HERE/'tb_weight_mac8.sv')]+[str(s) for s in sources]
    c=subprocess.run(command,capture_output=True,text=True);(OUT/(stage+'-compile.log')).write_text(c.stdout+c.stderr)
    if c.returncode:raise RuntimeError(c.stdout+c.stderr)
    log=OUT/(stage+'-run.log')
    with log.open('w') as stream:r=subprocess.run([str(SIM/'vvp.exe'),str(binary),'+VECTORS='+str(vectors)],stdout=stream,stderr=subprocess.STDOUT,text=True)
    output=log.read_text()
    if r.returncode or 'PASS weight_mac8' not in output:raise RuntimeError(output)
    paths=[HERE/'rtl/weight_bank8.v',HERE/'rtl/weight_mac8.v',MAC,HERE/'tb_weight_mac8.sv',Path(__file__),MODELS/'efx_ram10.v',MODELS/'efx_dsp48.v',vectors]+sources
    receipt=dict(exit_code=0,stage=stage,cycles=len(lines),lane_state_checks=len(lines)*8,coverage=counts,
        all_addresses_read=len(read_addresses),split_checks=splits,stdout=output,
        files_sha256={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths})
    (OUT/(stage+'-validation.json')).write_text(json.dumps(receipt,indent=2)+'\n')
    print(json.dumps(receipt,indent=2))


if __name__=='__main__':main()
