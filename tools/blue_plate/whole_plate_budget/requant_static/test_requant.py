from pathlib import Path
import argparse,hashlib,json,random,re,subprocess,sys
HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE.parent/'requant'))
from golden import ROOT,real_cases,requant
OUT=ROOT/'tmp/blue-plate-whole-plate-budget/requant-static'

SIM=ROOT/'tools/iverilog-12/app/bin';MODELS=Path('D:/Efinity/sim_models/verilog')
FROZEN=[HERE.parent/'mac8/rtl/mac8.v',HERE.parent/'weight_bank/rtl/weight_bank8.v',HERE.parent/'weight_bank/rtl/weight_mac8.v',HERE.parent/'partial_sum/rtl/psum_weight_mac8.v']


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--mapped',action='store_true');args=ap.parse_args()
    OUT.mkdir(exist_ok=True,parents=True);stage='mapped' if args.mapped else 'rtl'
    hashes={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in FROZEN}
    assert list(hashes.values())==['f3490692d9bd2160144da3c92693bb8b65f0cbe0a9d435dc4321514cd2c7ffee','58efc434e8750c1951e6143e27206ba7b11938b0115241014ecc1c635c096f86','73835aa728ec3922ada18bf06242ed28f427df2a1ef67be19c6fd0b376a13294','9201a4f73f20331dbbc847fe34e8e9238a539e590999af2c8b13b290ff251a4e']
    cases=real_cases()
    def add(a,m,s,relu=False,z=0):cases.append(dict(args=[a,m,s,relu,z],expected=requant(a,m,s,relu,z),reuse=False))
    for a in (-(1<<31),-65536,-3,-1,0,1,3,65535,(1<<31)-1):
        for s in ((1,31,62) if args.mapped else (1,7,16,31,32,61,62)):
            add(a,(1<<31)-1,s,z=-128 if a&1 else 63)
    # Ties above and below even/odd signed quotients; both saturation boundaries.
    for a in (-257,-255,-253,-5,-3,-1,1,3,5,251,253,255,257):add(a,1,1)
    for s in range(1,63):add(1<<min(s-1,30),1<<max(0,s-31),s) if s<62 else add(-(1<<31),1<<30,s)
    rng=random.Random(1501)
    for _ in range(16 if args.mapped else 400):add(rng.randrange(-(1<<31),1<<31),rng.randrange(1,1<<31),rng.randrange(1,63),bool(rng.randrange(2)),rng.randrange(-128,128))
    proof=json.loads((OUT/'proof-and-schedule.json').read_text())
    lookup={(p['layer'],p['channel']):p for p in proof['proofs']}
    records=json.loads((ROOT/'tmp/blue-plate-char-segment/integer-deployment-audit/output-channel-mac-vectors.json').read_text())['records']
    for c in cases:
        match=re.search(r'(output|fork) v(\d+) lane(\d+)',c.get('source',''))
        c['constant']=False
        if match:
            kind,record,lane=match.groups();r=records[int(record)];ch=r['first_output_channel']+int(lane)
            p=lookup[('tap2.trunk',ch//4)] if kind=='fork' else lookup[(r['layer'],ch)]
            c['constant']=p['constant']
            if p['constant']:assert c['expected']==p['value']
    # Constant output must preserve the un-clamped original across a later reuse.
    cases += [dict(args=[-(1<<31),(1<<31)-1,31,True,17],expected=17,reuse=False,constant=False),
              dict(args=[123,0,0,False,0],expected=127,reuse=True,constant=True),
              dict(args=[-(1<<31),1,31,False,0],expected=-1,reuse=True,constant=False)]
    constants=[p for p in proof['proofs'] if p['constant']]
    chosen=constants[::max(1,len(constants)//24)] if args.mapped else constants
    for p in chosen:
        for a in (p['acc_lower'],p['acc_upper']):
            cases.append(dict(args=[a,0,0,False,0],expected=p['value'],reuse=True,constant=True))
    lines=[]
    for c in cases:
        a,m,s,relu,z=c['args'];p=(max(a,0) if relu else a)*m
        fields=[int(c.get('constant',False)),c['expected']&255,int(c['reuse']),a&0xffffffff,m,s,int(relu),z&255,c['expected']&255,p&((1<<64)-1)]
        lines.append(' '.join(format(x,'x') for x in fields))
    vectors=OUT/(stage+'-vectors.txt');vectors.write_text('\n'.join(lines)+'\n')
    sources=[HERE/'rtl/q31_static_mac8.v']+FROZEN
    if args.mapped:
        sys.path.insert(0,str(HERE.parent/'partial_sum'));from lut_startup import prepare
        net=OUT/'synthesis/out/q31_static_mac8.map.v';sources=[net,prepare(OUT,MODELS,SIM,net)]
    binary=OUT/(stage+'.vvp');cmd=[str(SIM/'iverilog.exe'),'-g2012','-s','tb_requant','-y',str(MODELS),'-Y','.v']
    if args.mapped:cmd+=['-DMAPPED']
    cmd+=['-o',str(binary),str(HERE/'tb_requant.sv')]+[str(p) for p in sources]
    c=subprocess.run(cmd,capture_output=True,text=True);(OUT/(stage+'-compile.log')).write_text(c.stdout+c.stderr)
    assert c.returncode==0,c.stderr
    with (OUT/(stage+'-run.log')).open('w') as f:r=subprocess.run([str(SIM/'vvp.exe'),str(binary),'+VECTORS='+str(vectors)],stdout=f,stderr=subprocess.STDOUT)
    output=(OUT/(stage+'-run.log')).read_text();assert r.returncode==0 and 'PASS requant' in output,output
    assert hashes=={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in FROZEN}
    paths=[Path(__file__),HERE.parent/'requant/golden.py',HERE/'prove_schedule.py',OUT/'proof-and-schedule.json',HERE/'tb_requant.sv',vectors]+sources+FROZEN
    result=dict(exit_code=0,stage=stage,cases=len(cases),real_cases=100,latency='25 enabled edges after dynamic accept; constant result valid at acceptance; output held until CE and ready',frozen_sources_unchanged=True,stdout=output,files_sha256={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths})
    (OUT/(stage+'-validation.json')).write_text(json.dumps(result,indent=2)+'\n');print(output)


if __name__=='__main__':main()
