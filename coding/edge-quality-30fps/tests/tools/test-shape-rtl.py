"""Run the real shared cache and shape RTL against the integer reference."""
from pathlib import Path
import json
import runpy
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor,as_completed
import numpy as np
from canny_reference import classify,hysteresis
from shape_reference import recognize

root=Path(__file__).resolve().parents[1]
project=root.parent
sim=Path(__file__).resolve().parents[4]/'tools/iverilog-12/app/bin'
import os
os.chdir(root)
vectors=Path('tmp/m10-vectors')
vectors.mkdir(exist_ok=True,parents=True)
sample=runpy.run_path(str(root/'tools/test-shape-reference.py'))['sample']
validation='--validation' in sys.argv
stress='--stress' in sys.argv
exe=vectors/('shape-validation.vvp' if validation else 'shape-stress.vvp' if stress else 'shape-basic.vvp')
subprocess.run([str(sim/'iverilog.exe'),'-g2012','-s','tb_shape_recognizer','-o',str(exe),
               str(project/'rtl/shape_recognizer.v'),str(project/'rtl/canny_hysteresis.v'),str(project/'tests'/'tb_shape_recognizer.v')],check=True)
cases=[]
for canny in (False,True):
    for kind in ('circle','rectangle','ellipse','triangle','open'):
        for seed in (range(20000,20020) if validation else [10003]):
            gray=sample(kind,seed)
            state,*_=classify(gray,32,1,True,canny)
            edge=hysteresis(state)[0] if canny else state==2
            cases.append((f'{kind}-{int(canny)}-{seed}',edge))
cases.append(('blank',np.zeros((720,1280),dtype=bool)))
if stress:
    cases=[]
    def rect(edge,x,y,w,h):
        edge[y:y+h+1,x]=1;edge[y:y+h+1,x+w]=1
        edge[y,x:x+w+1]=1;edge[y+h,x:x+w+1]=1
    for number in (4,5):
        edge=np.zeros((720,1280),dtype=bool)
        for i in range(number): rect(edge,30+i*230,200,90,100)
        cases.append((f'{number}-targets',edge))
    for size in (63,64,400,401):
        edge=np.zeros((720,1280),dtype=bool);rect(edge,100,100,size,size)
        cases.append((f'limit-{size}',edge))
    edge=np.zeros((720,1280),dtype=bool);rect(edge,15,100,100,100)
    cases.append(('margin-reject',edge))
    edge=np.zeros((720,1280),dtype=bool)
    for i in range(12):
        y=100+i*10;edge[y,100:1101]=1
        if i<11: edge[y:y+11,1100 if i%2==0 else 100]=1
    cases.append(('long-open-contour',edge))
    edge=np.zeros((720,1280),dtype=bool)
    for x in (62,63,64,125,126,127,128,189,190,191,192):
        edge[40+x:43+x, x:x+70]=1
    cases.append(('run-word-boundaries',edge))
    edge=np.zeros((720,1280),dtype=bool)
    edge[50,0:1280]=1;edge[51:80:2,63:1217]=1
    edge[50:80,64]=1;edge[50:80,1215]=1
    edge[80:130,600]=1
    for i in range(64): edge[150+i,62+i]=1
    cases.append(('run-merge-split-diagonal',edge))
    rng=np.random.default_rng(1042)
    edge=np.zeros((720,1280),dtype=bool)
    edge[20:148,20:276]=rng.random((128,256))<0.22
    cases.append(('run-noise-components',edge))
    # More than 4096 runs in one component must cross the local queue prefix
    # into DDR and still preserve exact connectivity and classification.
    edge=np.zeros((720,1280),dtype=bool)
    edge[100:230:2,100:230]=1
    edge[101:230:2,100:230:2]=1
    cases.append(('run-queue-spill',edge))
def run_case(case):
    name,edge=case
    expected=recognize(edge)
    words=[]
    for group in edge.reshape(-1,64):
        words.append(sum(int(bit)*2<<(2*i) for i,bit in enumerate(group)))
    source=vectors/f'{name}.hex'
    source.write_text(''.join(f'{word:032x}\n' for word in words))
    packed=[len(expected['targets']),sum(t['kind']<<(2*i) for i,t in enumerate(expected['targets'])),int(expected['overflow'])]
    for t in expected['targets']:
        x0,y0,x1,y1=t['box'];packed.extend([x0<<16|y0,x1<<16|y1])
    packed += [0]*(11-len(packed))
    packed.append(len(expected['candidates']))
    want=vectors/f'{name}-expected.hex'
    want.write_text(''.join(f'{value:08x}\n' for value in packed))
    result=subprocess.run([str(sim/'vvp.exe'),str(exe),f'+input={source}',f'+expected={want}',
                           *(['+spill=1'] if name=='run-queue-spill' else [])],capture_output=True,text=True)
    print(name+'\n'+result.stdout+result.stderr,flush=True)
    result.check_returncode()
    return name
if len(sys.argv)>1 and not validation and not stress:
    cases=[case for case in cases if sys.argv[1] in case[0]]
with ThreadPoolExecutor(max_workers=2) as pool:
    for future in as_completed([pool.submit(run_case,case) for case in cases]): future.result()
print(f'PASS {len(cases)} M10 shared-cache RTL vectors')
if stress:
    for transfer in (1,2):
        subprocess.run([str(sim/'vvp.exe'),str(exe),f'+input={vectors}/4-targets.hex',
                        f'+expected={vectors}/4-targets-expected.hex',f'+error_at={transfer}'],check=True)

