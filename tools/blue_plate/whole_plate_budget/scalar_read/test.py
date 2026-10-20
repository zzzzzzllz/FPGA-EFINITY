"""Run new scalar-port tests on RTL or the mapped combined candidate."""
from pathlib import Path
import argparse,hashlib,json,subprocess,sys
HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[3]
OUT=ROOT/'tmp/blue-plate-whole-plate-budget/scalar-read'
SIM=ROOT/'tools/iverilog-12/app/bin';MODELS=Path('D:/Efinity/sim_models/verilog')


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--mapped',action='store_true');ap.add_argument('--bench',choices=['psum','scalar'],required=True);args=ap.parse_args()
    stage='mapped' if args.mapped else 'rtl';sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
    freeze=ROOT/'tmp/blue-plate-whole-plate-budget/requant-static/delivery-freeze.json'
    frozen=json.loads(freeze.read_text())['files_sha256']
    for n,h in frozen.items():assert sha(ROOT/n)==h,n
    inputs=json.loads((OUT/'test-inputs.json').read_text())
    for n,h in inputs['source_sha256'].items():assert sha(Path(n))==h,n
    sources=[HERE/'rtl/q31_scalar_mac8.v',HERE/'rtl/psum_scalar_mac8.v',HERE.parent/'weight_bank/rtl/weight_mac8.v',HERE.parent/'weight_bank/rtl/weight_bank8.v',HERE.parent/'mac8/rtl/mac8.v']
    if args.mapped:
        net=OUT/'synthesis/out/q31_scalar_mac8.map.v'
        sys.path.insert(0,str(HERE.parent/'partial_sum'));from lut_startup import prepare
        sources=[net,prepare(OUT,MODELS,SIM,net)]
    bench=HERE/('tb_'+args.bench+'.sv');prefix=stage+'-'+args.bench;binary=OUT/(prefix+'.vvp')
    cmd=[str(SIM/'iverilog.exe'),'-g2012','-s','tb_'+args.bench,'-y',str(MODELS),'-Y','.v','-o',str(binary),str(bench)]+[str(p) for p in sources]
    c=subprocess.run(cmd,capture_output=True,text=True);(OUT/(prefix+'-compile.log')).write_text(c.stdout+c.stderr);assert c.returncode==0,c.stderr
    vector=OUT/(stage+'-psum-vectors.txt' if args.bench=='psum' else 'real-commands.txt')
    with (OUT/(prefix+'-run.log')).open('w') as f:r=subprocess.run([str(SIM/'vvp.exe'),str(binary),'+VECTORS='+str(vector)],stdout=f,stderr=subprocess.STDOUT)
    output=(OUT/(prefix+'-run.log')).read_text();assert r.returncode==0 and 'PASS '+args.bench in output,output[-3000:]
    for n,h in frozen.items():assert sha(ROOT/n)==h,n
    paths=[Path(__file__),HERE/'prepare_tests.py',bench,vector,OUT/'test-inputs.json',freeze]+sources
    result=dict(exit_code=0,stage=stage,bench=args.bench,stdout=output,frozen_unchanged=True,files_sha256={str(p):sha(p) for p in paths})
    (OUT/(prefix+'-validation.json')).write_text(json.dumps(result,indent=2)+'\n');print(output[-1200:])


if __name__=='__main__':main()
