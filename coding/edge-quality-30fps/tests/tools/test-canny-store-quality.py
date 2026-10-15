"""Actual CDC FIFOs, shared AXI, local pipeline and complete hysteresis, every pixel."""
from pathlib import Path
work=Path(__file__).resolve().parents[4]/'tmp/tests'/Path(__file__).resolve().parents[2].name
work.mkdir(parents=True,exist_ok=True)
import subprocess
import json
import sys
import numpy as np
from canny_reference import classify,hysteresis
from shape_reference import recognize

root=Path(__file__).resolve().parents[1]
project=root.parent
sim=Path(__file__).resolve().parents[4]/'tools/iverilog-12/app/bin'
full='--full' in sys.argv
medium='--medium' in sys.argv
shape='--shape' in sys.argv
target='--target' in sys.argv
if target and not (full and shape): raise ValueError('--target requires --full --shape')
if shape and not (medium or full): raise ValueError('Recognition requires --medium or --full')
exe=work/('quality-store-full.vvp' if full else 'm09-store-medium.vvp' if medium else 'm09-store.vvp')
files=['frame_store','frame_store_control','frame_store_dma','frame_pair_fifo','frame_mailbox',
       'frame_buffer_V4/DC_FIFO','median_pair','gaussian_pair','sobel_pair','canny_nms_pair','edge_algorithm_pair','canny_hysteresis','shape_recognizer']
subprocess.run([str(sim/'iverilog.exe'),'-g2012','-s','tb_canny_store','-o',str(exe),
               *(['-DFULL_SMOKE'] if full else ['-DMEDIUM_SMOKE'] if medium else []),
               *[str(project/'rtl'/f'{name}.v') for name in files],str(project/'tests'/'tb_canny_store.v')],check=True)
import os
os.chdir(root)
vectors=Path('quality-store-full-vectors' if full else 'm10-store-medium-vectors' if medium else 'm10-store-vectors')
width,height=(1280,720) if full else (128,256) if medium else (32,24)
if target:
    vectors.mkdir(parents=True,exist_ok=True)
    y,x=np.indices((height,width));gray=np.full((height,width),235,np.uint8)
    gray[(x-350)**2+(y-300)**2<=90**2]=25
    gray[220:401,740:941]=25
    state,*_=classify(gray,24,1,False,True);edge=hysteresis(state)[0]
    rgb=gray.astype(np.uint32)*0x010101
    for suffix,data in [('input',(gray.astype(np.uint32)<<24)|rgb),('final',(edge.astype(np.uint32)<<31)|rgb)]:
        (vectors/f'targets-{suffix}.hex').write_text(''.join(f'{int(v):08x}\n' for v in data.flat))
    assert sorted(t['kind'] for t in recognize(edge)['targets'])==[1,2]
    cases=[dict(name='targets',config=0x6018)]
else:
    subprocess.run([sys.executable,str(root/'tools/canny_reference.py'),'--vectors',str(vectors),'--width',str(width),'--height',str(height),'--camera-rgby'],check=True)
    cases=json.loads((vectors/'manifest.json').read_text())
    if full: cases=[case for case in cases if case['config']==0x6820]
    elif medium: cases=[case for case in cases if case['name'] in ('1-1-1','5-1-1')]
assert cases
for case in cases:
    if shape:
        values=np.loadtxt(vectors/f'{case["name"]}-final.hex',dtype=np.uint32,converters=lambda v:int(v,16))
        result=recognize((values>>31).reshape(height,width)!=0)
        boxes=sum((t['box'][0]|t['box'][1]<<11|t['box'][2]<<22|t['box'][3]<<33)<<(44*i) for i,t in enumerate(result['targets']))
        kinds=sum(t['kind']<<(2*i) for i,t in enumerate(result['targets']))
        packed=(1<<188)|(int(result['overflow'])<<187)|(len(result['targets'])<<184)|(kinds<<176)|boxes
        shapes_path=vectors/f'{case["name"]}-shapes.hex';shapes_path.write_text(f'{packed:048x}\n')
    subprocess.run([str(sim/'vvp.exe'),'-i',str(exe),*(['+recognition=1',f'+shapes={shapes_path}'] if shape else []),f'+config={case["config"]}',
                    f'+input={vectors/case["name"]}-input.hex',f'+expected={vectors/case["name"]}-final.hex'],check=True)
if not full:
    subprocess.run([str(sim/'vvp.exe'),'-i',str(exe),'+config=26656','+state_error=1',
                    f'+input={vectors}/1-1-1-input.hex',f'+expected={vectors}/1-1-1-final.hex'],check=True)
if not full and not medium:
    subprocess.run([str(sim/'vvp.exe'),'-i',str(exe),'+config=26656','+reuse_slots=1',
                    f'+input={vectors}/1-1-1-input.hex',f'+expected={vectors}/1-1-1-final.hex'],check=True)
    subprocess.run([str(sim/'vvp.exe'),'-i',str(exe),'+config=26656','+reference_test=1',
                    f'+input={vectors}/1-1-1-input.hex',f'+expected={vectors}/1-1-1-final.hex'],check=True)
print(f'PASS {len(cases)} frame-store cases: final pixels, frame metadata, publication gate, AXI stalls')

