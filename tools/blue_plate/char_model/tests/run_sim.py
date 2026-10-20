"""Generate RTL expectations from frozen weights and run the existing Icarus."""
import hashlib
import argparse
import json
from pathlib import Path
import shutil
import subprocess
import sys
import numpy as np
HERE=Path(__file__).resolve().parent
MODEL=HERE.parent
ROOT=MODEL.parents[2]
sys.path.insert(0,str(MODEL))
from model import integer_scores,decide


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--mapped',action='store_true')
    parser.add_argument('--lut-init-fix',action='store_true',help='Use a local always_comb adaptation of vendor LUT model for Icarus startup')
    args=parser.parse_args()
    out=ROOT/'tmp/blue-plate-char-model'/('rtl-mapped' if args.mapped else 'rtl');out.mkdir(parents=True,exist_ok=True)
    candidate=MODEL/'candidate'
    config=json.loads((candidate/'interface.json').read_text(encoding='utf8'))
    weights=dict(np.load(candidate/'weights.npz'))
    vectors=json.loads((candidate/'test-vectors.json').read_text(encoding='utf8'))
    items=[]
    for v in vectors:
        if v['kind']=='tie-score-bus':
            items.append((np.zeros(320,np.int64),v['position'],True))
        else:items.append((np.array(v['features']),v['position'],False))
    rng=np.random.default_rng(701)
    for x in [np.zeros(320,int),np.full(320,32,int),np.tile([0,32],160),*rng.integers(0,33,(16,320))]:
        for position in [0,1,2]:items.append((x,position,False))
    if args.mapped:
        # RTL exhaustively covers the exported class vectors. Mapping adds a
        # small independent check of initialized physical ROM/DSP semantics.
        items=[items[i] for i in [0,31,79,89,102,105,108,111]]
    features=[];scores=[];metadata=[]
    for x,position,tie in items:
        values=np.zeros(65,np.int64) if tie else integer_scores(x,weights)
        expected=decide(values,position,config['thresholds'])
        features.extend(x.tolist());scores.extend(values.tolist())
        metadata.extend([position,expected['id'],expected['score'],expected['margin'],int(expected['accepted']),int(tie)])
    for filename,values,bits in [('features.mem',features,8),('scores.mem',scores,32),('metadata.mem',metadata,32)]:
        (out/filename).write_text(''.join(f'{int(v)&((1<<bits)-1):0{bits//4}x}\n' for v in values),encoding='ascii')
    for filename in ['w1-s10.bin','b1.mem']:shutil.copy2(candidate/filename,out/filename)
    binary=ROOT/'tools/iverilog-12/app/bin'
    design=[str(MODEL/'rtl/char_linear.v')]
    if args.mapped:
        library=list(Path('D:/Efinity/sim_models/verilog').glob('*.v'))
        if args.lut_init_fix:
            original=Path('D:/Efinity/sim_models/verilog/efx_lut4.v')
            content=original.read_text()
            old='always @(I0_net or I1_net or I2_net or I3_net) begin'
            assert content.count(old)==1
            adapted=out/'efx_lut4_icarus.v'
            adapted.write_text(content.replace(old,'always_comb begin'),encoding='utf8')
            library=[p for p in library if p.name!='efx_lut4.v']+[adapted]
        design=['-DMAPPED_NETLIST',str(ROOT/'tmp/blue-plate-char-model/synthesis/out/char_linear.map.v'),*[str(p) for p in library]]
    commands=[[str(binary/'iverilog.exe'),'-g2012','-Wall','-s','tb_char_linear','-o',str(out/'sim.vvp'),*design,str(HERE/'tb_char_linear.sv')],
              [str(binary/'vvp.exe'),str(out/'sim.vvp'),f'+count={len(items)}']]
    logs=[]
    for command in commands:
        result=subprocess.run(command,cwd=out,text=True,capture_output=True)
        logs.append(result.stdout+result.stderr)
        (out/'simulation.log').write_text('\n'.join(logs),encoding='utf8')
        if result.returncode:raise RuntimeError(logs[-1])
    sources=[MODEL/'rtl/char_linear.v',HERE/'tb_char_linear.sv',candidate/'w1-s10.bin',candidate/'b1.mem',candidate/'interface.json']
    if args.mapped:sources.append(ROOT/'tmp/blue-plate-char-model/synthesis/out/char_linear.map.v')
    report=dict(vectors=len(items),real_and_rejection=4 if args.mapped else 99,tie_injected_score_bus=0 if args.mapped else 3,extreme_and_random=4 if args.mapped else 57,
        expected_latency_cycles=41796,clock_assumption_MHz=100,
        hashes={str(p.relative_to(ROOT)).replace('\\','/'):hashlib.sha256(p.read_bytes()).hexdigest() for p in sources},
        result=logs[-1],commands=commands)
    if args.lut_init_fix:
        report['vendor_model_adaptation']=dict(source='D:/Efinity/sim_models/verilog/efx_lut4.v',
            source_sha256=hashlib.sha256(original.read_bytes()).hexdigest(),adapted_sha256=hashlib.sha256(adapted.read_bytes()).hexdigest(),
            change='Sensitivity-list always replaced by always_comb to evaluate constant-input LUTs at time zero; hardware netlist unchanged.')
    (out/'simulation.json').write_text(json.dumps(report,indent=2),encoding='utf8')
    print(logs[-1])


if __name__=='__main__':main()
