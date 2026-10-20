"""Controlled signed11 experiment using the single existing char_linear core."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
import numpy as np

HERE=Path(__file__).resolve().parent;MODEL=HERE.parents[1];ROOT=MODEL.parents[2]
BASE=ROOT/'tmp/blue-plate-char-model';OUT=BASE/'geometry11-hardware';SOURCE=BASE/'frozen-domain/geometry'
DOC=ROOT/'docs/validation/blue-plate/char-model'
sys.path.insert(0,str(MODEL))
from model import CLASSES,features,integer_scores,decide
EXPECTED='b21a547399f17ecb50264d489eec4e4563c2269babab7149dc5447f7a12f5391'
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def read(p):return json.loads(p.read_text(encoding='utf8'))
def save(p,v):p.write_text(json.dumps(v,ensure_ascii=False,indent=2),encoding='utf8')
def candidate_hashes():return {p.name:sha(p) for p in (MODEL/'candidate').iterdir() if p.is_file()}


def write_rom(folder,weights,bits=11):
    folder.mkdir(parents=True,exist_ok=True)
    w=weights['w1'].T.reshape(-1).astype(np.int64);b=weights['b1'].astype(np.int64)
    limit=1<<(bits-1);filename=f'w1-s{bits}.bin'
    assert bits in [10,11] and w.shape==(20800,) and b.shape==(65,) and w.min()>=-limit and w.max()<limit
    assert b.min()>=-2**31 and b.max()<2**31
    (folder/filename).write_text(''.join(f'{int(v)&(2*limit-1):0{bits}b}\n' for v in w),encoding='ascii')
    (folder/'b1.mem').write_text(''.join(f'{int(v)&0xffffffff:08x}\n' for v in b),encoding='ascii')
    lines=(folder/filename).read_text().splitlines();assert len(lines)==20800 and all(len(s)==bits and set(s)<=set('01') for s in lines)
    decoded=np.array([int(s,2)-(2*limit if s[0]=='1' else 0) for s in lines])
    bias=np.array([int(s,16) for s in (folder/'b1.mem').read_text().splitlines()],np.int64)
    bias[bias>=2**31]-=2**32
    assert np.array_equal(w,decoded) and np.array_equal(b,bias)
    return dict(weights_checked=len(w),biases_checked=len(b),weight_range=[int(w.min()),int(w.max())],
        outside_signed10=int(((w<-512)|(w>511)).sum()),w1_sha256=sha(folder/filename),b1_sha256=sha(folder/'b1.mem'))


def export():
    assert sha(SOURCE/'weights.npz')==EXPECTED
    config=read(SOURCE/'interface.json');assert config['classes']==list(CLASSES)
    weights=dict(np.load(SOURCE/'weights.npz'));roundtrip=write_rom(HERE,weights)
    bound=int((32*np.abs(weights['w1'].astype(np.int64)).sum(axis=0)+np.abs(weights['b1'])).max())
    assert bound==531070 and 2*bound<2**31
    core=(MODEL/'rtl/char_linear.v').read_text()
    ports=core.split(') (',1)[1].split(');',1)[0].replace('output reg','output wire')
    t=config['thresholds']
    params=dict(WEIGHT_BITS=11,WEIGHT_FILE='w1-s11.bin',BIAS_FILE='b1.mem',PROVINCE_SCORE=t['province']['score'],
        PROVINCE_MARGIN=t['province']['margin'],ALNUM_SCORE=t['alphanumeric']['score'],ALNUM_MARGIN=t['alphanumeric']['margin'])
    values=',\n        '.join(f'.{k}({json.dumps(v) if isinstance(v,str) else v})' for k,v in params.items())
    wrapper='// Generated configuration wrapper. One shared char_linear implementation.\nmodule geometry11_char_linear ('+ports+');\n    char_linear #(\n        '+values+'\n    ) core (.*);\nendmodule\n'
    (HERE/'geometry11_char_linear.v').write_text(wrapper,encoding='ascii')
    save(HERE/'interface.json',dict(status='experimental geometry11 hardware verification; default candidate unchanged',
        source_weights_sha256=EXPECTED,thresholds=t,classes=list(CLASSES),parameters=params,roundtrip=roundtrip,
        absolute_accumulator_bound=bound,rom_layout='class-major: address=class_id*320+feature_id; two-complement signed11 binary weights, signed32 hex bias',
        score_bits=32,feature_count=320,candidate_hashes=candidate_hashes()))
    print('Exact signed11 ROM roundtrip:',roundtrip,flush=True)


def cases():
    batch=read(BASE/'frozen-domain/batch.json');masks=np.load(BASE/'frozen-domain/frozen-masks.npy')
    audit=read(BASE/'frozen-domain/input-audit.json')
    assert all(sha(ROOT/p)==h for p,h in audit['used_roi_hashes'].items())
    items=[]
    for row in batch:
        for c in row['characters']:
            items.append(dict(x=features(masks[c['index']]),position=c['position'],tie=False,kind='real-frozen-roi',key=row['key'],truth=c['truth']))
    rng=np.random.default_rng(701)
    for x in [np.zeros(320,int),np.full(320,32,int),np.tile([0,32],160),*rng.integers(0,33,(16,320))]:
        for position in [0,1,2]:items.append(dict(x=x,position=position,tie=False,kind='extreme-random'))
    weights=dict(np.load(SOURCE/'weights.npz'))
    for feature in np.unique(np.where(weights['w1']<-512)[0]):
        x=np.zeros(320,int);x[feature]=32
        items.append(dict(x=x,position=2,tie=False,kind='geometry-outside-signed10',feature=int(feature)))
    for position in [0,1,2]:items.append(dict(x=np.zeros(320,int),position=position,tie=True,kind='tie-score-bus'))
    return items


def simulate(boundary=False,mapped=False,bits=11):
    config=read(HERE/'interface.json');assert candidate_hashes()==config['candidate_hashes']
    assert sha(SOURCE/'weights.npz')==EXPECTED
    weights=dict(np.load(SOURCE/'weights.npz'));items=cases()
    kind=('boundary' if bits==11 else 'boundary10') if boundary else ('mapped' if mapped else 'rtl')
    out=OUT/kind;out.mkdir(parents=True,exist_ok=True)
    if boundary:
        limit=1<<(bits-1)
        edges=np.array([-limit,-limit//2-1,-limit//2,-1,0,limit//2-1,limit//2,limit-1],np.int16)
        weights=dict(w1=np.zeros((320,65),np.int16),b1=np.arange(-32,33,dtype=np.int32)*17)
        for c in range(65):weights['w1'][:8,c]=np.roll(edges,c%8)
        weights['w1'][:,0]=limit-1;weights['w1'][:,1]=-limit
        inputs=[np.zeros(320,int),np.full(320,32,int),np.tile([0,32],160)]
        for i in range(8):x=np.zeros(320,int);x[i]=32;inputs.append(x)
        items=[dict(x=x,position=pos,tie=False,kind='synthetic-width-boundary') for x in inputs for pos in [0,1,2]]
        for pos in [0,1,2]:items.append(dict(x=np.zeros(320,int),position=pos,tie=True,kind='tie-score-bus'))
    if mapped:
        selected=[0,7,14]
        selected += [i for i,v in enumerate(items) if v.get('key') in ['115-automatic','050-oracle'] and v['truth'] in ['Y','V']]
        selected += [259,262,265]
        selected += [i for i,v in enumerate(items) if v['kind']=='geometry-outside-signed10']
        items=[items[i] for i in dict.fromkeys(selected)]
    roundtrip=write_rom(out,weights,bits)
    assert len(items)*320<=131072 and len(items)*6<=2048
    xs=[];ss=[];meta=[];records=[]
    for v in items:
        scores=np.zeros(65,np.int64) if v['tie'] else integer_scores(v['x'],weights)
        assert scores.min()>=-2**31 and scores.max()<2**31
        expected=decide(scores,v['position'],config['thresholds'])
        xs.extend(v['x']);ss.extend(scores);meta.extend([v['position'],expected['id'],expected['score'],expected['margin'],int(expected['accepted']),int(v['tie'])])
        records.append({**{k:value for k,value in v.items() if k!='x'},'expected':expected})
    for name,values,value_bits in [('features.mem',xs,8),('scores.mem',ss,32),('metadata.mem',meta,32)]:
        (out/name).write_text(''.join(f'{int(v)&((1<<value_bits)-1):0{value_bits//4}x}\n' for v in values),encoding='ascii')
    binary=ROOT/'tools/iverilog-12/app/bin'
    args=[str(binary/'iverilog.exe'),'-g2012','-Wall','-s','tb_char_linear','-o',str(out/'sim.vvp')]
    sources=[MODEL/'rtl/char_linear.v',MODEL/'tests/tb_char_linear.sv']
    if mapped:
        netlist=OUT/'synthesis/out/geometry11_char_linear.map.v'
        original=Path('D:/Efinity/sim_models/verilog/efx_lut4.v');text=original.read_text();old='always @(I0_net or I1_net or I2_net or I3_net) begin';assert text.count(old)==1
        adapted=out/'efx_lut4_icarus.v';adapted.write_text(text.replace(old,'always_comb begin'),encoding='utf8')
        library=[p for p in original.parent.glob('*.v') if p.name!=original.name]+[adapted]
        args+=['-DMAPPED_NETLIST','-DCHAR_DUT=geometry11_char_linear',str(netlist),*[str(p) for p in library],str(sources[1])]
        monitor=out/'mapped_progress.sv'
        monitor.write_text('''`timescale 1ns/1ps
module mapped_progress;
integer cycles=0;
always @(posedge tb_char_linear.clk) begin
    cycles=cycles+1;
    if(cycles%10000==0) $display("progress cycles=%0d vector=%0d scores=%0d",cycles,tb_char_linear.vector_index,tb_char_linear.score_count);
end
endmodule
''',encoding='ascii')
        args[1:1]=['-s','mapped_progress']
        args.append(str(monitor))
    else:
        parameters={**config['parameters'],'WEIGHT_BITS':bits,'WEIGHT_FILE':f'w1-s{bits}.bin'}
        args += [f'-Ptb_char_linear.{k}={json.dumps(v) if isinstance(v,str) else v}' for k,v in parameters.items()]
        args += [str(p) for p in sources]
    before={str(p.relative_to(ROOT)):sha(p) for p in sources}
    logs=[];started=time.monotonic()
    for index,cmd in enumerate([args,[str(binary/'vvp.exe'),'-i',str(out/'sim.vvp'),f'+count={len(items)}']]):
        live=out/f'command-{index}.log'
        with live.open('w',encoding='utf8') as stream:
            r=subprocess.run(cmd,cwd=out,stdout=stream,stderr=subprocess.STDOUT,text=True,timeout=1800 if mapped else 300)
        logs.append(live.read_text(encoding='utf8'))
        (out/'simulation.log').write_text('\n'.join(logs),encoding='utf8')
        if r.returncode:raise RuntimeError(logs[-1])
    assert before=={str(p.relative_to(ROOT)):sha(p) for p in sources}
    assert candidate_hashes()==config['candidate_hashes']
    report=dict(kind=kind,elapsed_seconds=round(time.monotonic()-started,3),weight_bits=bits,vectors=len(items),expected_score_comparisons=(len(items)+2)*65,latency_cycles=41796,rom_roundtrip=roundtrip,
        source_hashes=before,weights_sha256=EXPECTED if not boundary else 'synthetic boundary fixture; not a model',records=records,result=logs[-1],heldout_consumed=0)
    if mapped:report['mapped_netlist_sha256']=sha(netlist);report['vendor_lut_adaptation']=dict(original_sha256=sha(original),adapted_sha256=sha(adapted),change='Same previously independently verified Icarus time-zero always_comb adaptation; no installed model or mapped netlist changes')
    save(out/'simulation.json',report);print(logs[-1],flush=True)


def prepare():
    out=OUT/'synthesis';out.mkdir(parents=True,exist_ok=True)
    for p in [MODEL/'rtl/char_linear.v',HERE/'geometry11_char_linear.v',HERE/'w1-s11.bin',HERE/'b1.mem']:shutil.copy2(p,out/p.name)
    ET.register_namespace('efx','http://www.efinixinc.com/enf_proj');ns={'e':'http://www.efinixinc.com/enf_proj'}
    tree=ET.parse(BASE/'synthesis/char_linear.xml');root=tree.getroot();root.set('name','geometry11_char_linear');root.set('description','Independent geometry signed11 experiment')
    design=root.find('e:design_info',ns);design.find('e:top_module',ns).set('name','geometry11_char_linear')
    ET.SubElement(design,'{'+ns['e']+'}design_file',dict(name='geometry11_char_linear.v',version='default',library='default'))
    root.find('e:constraint_info/e:sdc_file',ns).set('name','geometry11_char_linear.sdc')
    tree.write(out/'geometry11_char_linear.xml',encoding='utf8',xml_declaration=True)
    (out/'geometry11_char_linear.sdc').write_text('create_clock -name clk -period 10.000 [get_ports {clk}]\n',encoding='ascii')
    save(out/'source-hashes.json',{p.name:sha(p) for p in out.iterdir() if p.suffix in ['.v','.mem','.bin','.xml','.sdc']})
    print(out)


def guards():
    out=OUT/'guard';out.mkdir(parents=True,exist_ok=True)
    for name in ['w1-s11.bin','b1.mem']:shutil.copy2(HERE/name,out/name)
    tb=out/'width_guard.sv';tb.write_text('module width_guard #(parameter WIDTH=9); char_linear #(.WEIGHT_BITS(WIDTH),.WEIGHT_FILE("w1-s11.bin")) dut(); initial #1 $finish; endmodule\n',encoding='ascii')
    binary=ROOT/'tools/iverilog-12/app/bin';results={}
    for width in [9,12]:
        subprocess.run([str(binary/'iverilog.exe'),'-g2012','-s','width_guard',f'-Pwidth_guard.WIDTH={width}','-o',str(out/'guard.vvp'),str(MODEL/'rtl/char_linear.v'),str(tb)],cwd=out,check=True,capture_output=True)
        r=subprocess.run([str(binary/'vvp.exe'),str(out/'guard.vvp')],cwd=out,capture_output=True,text=True)
        assert r.returncode!=0 and 'WEIGHT_BITS must be 10 or 11' in r.stdout,(width,r.stdout,r.stderr)
        results[str(width)]=dict(rejected=True,log=r.stdout+r.stderr)
    save(out/'verification.json',results);print('Unsupported widths 9 and 12 rejected explicitly.')


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('action',choices=['export','sim','boundary','boundary10','prepare','mapped','guards']);a=p.parse_args()
    OUT.mkdir(parents=True,exist_ok=True)
    if a.action=='export':export()
    elif a.action=='prepare':prepare()
    elif a.action=='guards':guards()
    else:simulate(boundary=a.action in ['boundary','boundary10'],mapped=a.action=='mapped',bits=10 if a.action=='boundary10' else 11)
