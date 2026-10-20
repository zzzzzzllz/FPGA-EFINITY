"""Full-K RTL coverage plus bounded mapped coverage of the new serial storage."""
from pathlib import Path
import argparse,hashlib,json,subprocess
from lut_startup import prepare

HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[3]
OUT=ROOT/'tmp/blue-plate-whole-plate-budget/partial-sum'
SIM=ROOT/'tools/iverilog-12/app/bin';MODELS=Path('D:/Efinity/sim_models/verilog')
FROZEN=[HERE.parent/'mac8/rtl/mac8.v',HERE.parent/'weight_bank/rtl/weight_bank8.v',HERE.parent/'weight_bank/rtl/weight_mac8.v']


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--mapped',action='store_true');args=ap.parse_args()
    OUT.mkdir(parents=True,exist_ok=True);stage='mapped' if args.mapped else 'rtl'
    hashes={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in FROZEN}
    assert list(hashes.values())==['f3490692d9bd2160144da3c92693bb8b65f0cbe0a9d435dc4321514cd2c7ffee','58efc434e8750c1951e6143e27206ba7b11938b0115241014ecc1c635c096f86','73835aa728ec3922ada18bf06242ed28f427df2a1ef67be19c6fd0b376a13294']
    mem=[None]*2048;psmem=[None]*512;acc=[0]*8;state='IDLE';index=slotq=ramword=0;done=False
    pending=False;word=0;aq=[0]*8;mq=0;lines=[];addresses=set();cases=[]
    counts=dict(save_done=0,restore_done=0,errors=0,stalls=0,resets=0,mac_lanes=0,psum_writes=0,psum_reads=0)
    pack=lambda xs,bits:sum((v&((1<<bits)-1))<<(j*bits) for j,v in enumerate(xs))
    def edge(rst=0,ce=1,wr=0,wa=0,wd=0,issue=0,ra=0,a=None,mask=255,load=0,seed=None,save=0,restore=0,slot=0):
        nonlocal state,index,slotq,ramword,done,pending,word,aq,mq
        a=[1]*8 if a is None else a;seed=[0]*8 if seed is None else seed
        oldstate=state;oldindex=index;oldslot=slotq
        normal=bool(wr or issue or load);anycmd=normal or save or restore
        partialbad=bool((save and restore) or normal or pending)
        localerror=bool(ce and not rst and (anycmd if state!='IDLE' else ((save or restore) and partialbad)))
        forward=state=='IDLE' and not save and not restore
        cce=bool(ce and state in ('IDLE','CAPTURE'))
        cw=wr and forward;ci=issue and forward;cl=state=='CAPTURE' or (load and forward)
        coreerror=bool(cce and not rst and ((cw and ci) or (cl and (cw or ci)) or ((cw or cl) and pending)))
        error=localerror or coreerror;upd=over=0
        if rst:
            state='IDLE';index=slotq=ramword=0;done=False;pending=False;acc[:]=[0]*8;counts['resets']+=1
        else:
            if not ce:counts['stalls']+=1
            if cce:
                if cl and not coreerror:
                    if oldstate=='CAPTURE':acc[oldindex]=ramword
                    else:acc[:]=seed
                    upd=255
                elif pending:
                    for j in range(8):
                        if mq>>j&1:
                            w=(word>>(8*j))&255;w=w-256 if w>=128 else w
                            exact=acc[j]+aq[j]*w
                            over|=int(not -2**31<=exact<2**31)<<j
                            acc[j]=(exact+2**31)%2**32-2**31;upd|=1<<j;counts['mac_lanes']+=1
                pending=bool(ci and not coreerror)
                if pending:
                    assert mem[ra] is not None
                    word=mem[ra];aq=a.copy();mq=mask
                if cw and not coreerror:mem[wa]=wd
            if ce:
                done=False
                if oldstate=='IDLE':
                    if (save or restore) and not partialbad:
                        slotq=slot;index=0;state='SAVE' if save else 'READ'
                elif oldstate=='SAVE':
                    address=oldslot*8+oldindex;psmem[address]=acc[oldindex];addresses.add(address);counts['psum_writes']+=1
                    if oldindex==7:state='IDLE';done=True;counts['save_done']+=1
                    else:index+=1
                elif oldstate=='READ':
                    address=oldslot*8+oldindex;assert psmem[address] is not None
                    ramword=psmem[address];state='CAPTURE';counts['psum_reads']+=1
                else:
                    if oldindex==7:state='IDLE';done=True;counts['restore_done']+=1
                    else:index+=1;state='READ'
            counts['errors']+=error
        fields=[rst,ce,wr,wa,wd,issue,ra,pack(a,17),mask,load,pack(seed,32),save,restore,slot,
            pack(acc,32),upd,over,int(state!='IDLE'),int(done),int(error),int(pending)]
        lines.append(' '.join(format(v,'x') for v in fields))
    def transfer(kind,slot,stall=True):
        assert state=='IDLE' and not pending
        edge(**{kind:1},slot=slot);ticks=0
        while state!='IDLE':
            if stall and ticks%3==0:edge(ce=0,load=1)
            edge();ticks+=1
        assert done and ticks==(8 if kind=='save' else 16)
        edge(ce=0);assert done
        edge();assert not done
    edge(rst=1,ce=0)
    # All 512 physical addresses, with nontrivial signed 32-bit values.
    for s in range(64):
        edge(load=1,seed=[((s*7919+j*1234567)&0x7fffffff)*(-1 if j%2 else 1) for j in range(8)])
        transfer('save',s)
    for s in reversed(range(64)):
        edge(load=1,seed=[-777]*8);transfer('restore',s)
        assert acc==psmem[s*8:s*8+8]
    # Rejected undrained and simultaneous commands; pending work still retires.
    edge(wr=1,wa=2047,wd=pack([-128,127]*4,8));edge(issue=1,ra=2047)
    edge(save=1,slot=63);edge(save=1,restore=1);edge(save=1,load=1)
    edge(save=1,slot=62);edge(issue=1,ra=2047);edge(wr=1,wa=0,wd=0);edge(restore=1,slot=0)
    while state!='IDLE':edge()
    edge(restore=1,slot=63);edge();edge(rst=1,ce=0);edge()
    transfer('restore',63);assert acc==psmem[504:512]
    edge(save=1,slot=61);edge();edge(rst=1,ce=0)
    # Redo an interrupted save before using that slot.
    edge(load=1,seed=[1234]*8);transfer('save',61);transfer('restore',61)
    chunks=(7,5) if args.mapped else (2048,1280)
    total=sum(chunks)
    for positions,lanes in ((16,8),(16,4),(8,8),(8,4)):
        w=lambda k:[((k*17+j*29+positions*3)%256)-128 for j in range(8)]
        a=lambda p,k:((p*73+k*23)%511)-255
        bias=lambda p:[1000+p*113-j*777 for j in range(8)]
        offset=0
        for segment,length in enumerate(chunks):
            for k in range(length):edge(wr=1,wa=k,wd=pack(w(offset+k),8))
            order=range(positions) if segment==0 else reversed(range(positions))
            for p in order:
                if segment==0:edge(load=1,seed=bias(p))
                else:transfer('restore',p)
                for k in range(length):
                    if k%257==0:edge(ce=0,issue=1,ra=k)
                    if k%509==0:edge()
                    edge(issue=1,ra=k,a=[a(p,offset+k)]*8,mask=(1<<lanes)-1)
                edge();assert not pending
                if segment==0:transfer('save',p)
                else:
                    expected=[bias(p)[j]+sum(a(p,k)*w(k)[j] for k in range(total)) if j<lanes else bias(p)[j] for j in range(8)]
                    assert acc==expected
                edge(load=1,seed=[0x12345678]*8)
            offset+=length
        cases.append(dict(positions=positions,valid_lanes=lanes,K=total,chunks=list(chunks),exact_outputs=positions*8))
    edge(rst=1)
    vectors=OUT/(stage+'-vectors.txt');vectors.write_text('\n'.join(lines)+'\n',encoding='ascii')
    sources=[OUT/'synthesis/out/psum_weight_mac8.map.v'] if args.mapped else [HERE/'rtl/psum_weight_mac8.v']+FROZEN
    if args.mapped:sources.append(prepare(OUT,MODELS,SIM,sources[0]))
    binary=OUT/(stage+'.vvp');cmd=[str(SIM/'iverilog.exe'),'-g2012','-s','tb_psum','-y',str(MODELS),'-Y','.v','-o',str(binary),str(HERE/'tb_psum.sv')]+[str(p) for p in sources]
    c=subprocess.run(cmd,capture_output=True,text=True);(OUT/(stage+'-compile.log')).write_text(c.stdout+c.stderr)
    if c.returncode:raise RuntimeError(c.stdout+c.stderr)
    log=OUT/(stage+'-run.log')
    with log.open('w') as f:r=subprocess.run([str(SIM/'vvp.exe'),str(binary),'+VECTORS='+str(vectors)],stdout=f,stderr=subprocess.STDOUT,text=True)
    output=log.read_text()
    if r.returncode or 'PASS psum' not in output:raise RuntimeError(output[-3000:])
    assert hashes=={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in FROZEN}
    paths=[HERE/'rtl/psum_weight_mac8.v',HERE/'tb_psum.sv',Path(__file__),vectors,MODELS/'efx_ram10.v',MODELS/'efx_dsp48.v']+FROZEN+sources
    result=dict(exit_code=0,stage=stage,cycles=len(lines),lane_state_checks=len(lines)*8,coverage=counts,
        physical_addresses_saved=len(addresses),cases=cases,frozen_sources_unchanged=True,
        scope='Bounded protocol/serial-port mapped test; K=12' if args.mapped else 'All four spatial/tail cases use full K=3328',
        files_sha256={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths},stdout=output)
    (OUT/(stage+'-validation.json')).write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps({k:v for k,v in result.items() if k not in ('files_sha256','stdout')},indent=2))


if __name__=='__main__':main()
