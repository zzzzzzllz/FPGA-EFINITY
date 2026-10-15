"""Check DDR traversal against independent component connectivity under memory stalls."""
from pathlib import Path
work=Path(__file__).resolve().parents[4]/'tmp/tests'/Path(__file__).resolve().parents[2].name
work.mkdir(parents=True,exist_ok=True)
import json
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
import numpy as np
from canny_reference import hysteresis, connectivity_oracle

root=Path(__file__).resolve().parents[1]
project=root.parent
sim=Path(__file__).resolve().parents[4]/'tools/iverilog-12/app/bin'
full='--full' in sys.argv
medium='--medium' in sys.argv
cache_stress='--cache-stress' in sys.argv
reuse='--reuse' in sys.argv
w,h=(128,720) if cache_stress else (1280,720) if full else (128,256) if medium else (32,24)
vectors=work/('m10-cache-stress-vectors' if cache_stress else 'm09-full-vectors' if full else 'm09-medium-vectors' if medium else 'm09-vectors')
vectors.mkdir(parents=True,exist_ok=True)
cases=[]
if not full and not medium and not cache_stress:
    cases=[c for c in json.loads((vectors/'manifest.json').read_text()) if c['config']&8192]
if reuse:
    cases=[dict(name=name,config=0x6820) for name in ('winding','no-seed','corner','dense','weak-dense','random')]
else:
    for name in ('winding','no-seed','corner','dense','weak-dense','random'):
        state=np.zeros((h,w),np.uint8)
        if name in ('winding','no-seed'):
            for y in range(1,h-1,2):
                state[y,1:w-1]=1
                if y<h-2: state[y+1,w-2 if y%4==1 else 1]=1
            if name=='winding': state[1,1]=2
        elif name=='corner':
            np.fill_diagonal(state,1);state[0,0]=2
        elif name=='dense': state[:]=2
        elif name=='weak-dense': state[:]=1;state[h//2,w//2]=2
        else: state=np.random.default_rng(902).choice([0,1,2],(h,w),p=[.5,.45,.05]).astype(np.uint8)
        edge,total,highwater=hysteresis(state)
        if not full: assert np.array_equal(edge,connectivity_oracle(state))
        payload=np.arange(w*h,dtype=np.uint32).reshape(h,w)&0xffffff
        for suffix,data in [('class',(state.astype(np.uint32)<<30)|payload),('final',(edge.astype(np.uint32)<<31)|payload)]:
            (vectors/f'{name}-{suffix}.hex').write_text(''.join(f'{int(v):08x}\n' for v in data.flat))
        cases.append(dict(name=name,config=0x6820,enqueued=total,highwater=highwater))
exe=work/('m10-hysteresis-cache-stress.vvp' if cache_stress else 'm09-hysteresis-cache64-full.vvp' if full else 'm09-hysteresis-medium.vvp' if medium else 'm09-hysteresis.vvp')
subprocess.run([str(sim/'iverilog.exe'),'-g2012','-s','tb_canny_hysteresis',f'-Ptb_canny_hysteresis.W={w}',f'-Ptb_canny_hysteresis.H={h}',
               f'-Ptb_canny_hysteresis.BURST={128 if full or medium or cache_stress else 16}',
               '-o',str(exe),str(project/'rtl/canny_hysteresis.v'),str(project/'tests'/'tb_canny_hysteresis.v')],check=True)
def run_case(case):
    result=subprocess.run([str(sim/'vvp.exe'),'-i',str(exe),f'+config={case["config"]}',
                    f'+input={vectors/case["name"]}-class.hex',f'+expected={vectors/case["name"]}-final.hex'],
                    capture_output=True,text=True)
    print(case['name']+'\n'+result.stdout+result.stderr,flush=True)
    result.check_returncode()
with ThreadPoolExecutor(max_workers=2 if full else 1) as pool:
    for future in as_completed([pool.submit(run_case,case) for case in cases]):
        future.result()
print(f'PASS {len(cases)} complete DDR hysteresis cases, {w}x{h}')
