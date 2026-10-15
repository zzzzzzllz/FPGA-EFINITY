"""Compile local RTL once and compare every output pixel to frozen reference vectors."""
from pathlib import Path
work=Path(__file__).resolve().parents[4]/'tmp/tests'/Path(__file__).resolve().parents[2].name
work.mkdir(parents=True,exist_ok=True)
import json
import subprocess
import sys

root=Path(__file__).resolve().parents[1]
project=root.parent
sim=Path(__file__).resolve().parents[4]/'tools/iverilog-12/app/bin'
full='--full' in sys.argv
w,h=(1280,720) if full else (32,24)
vectors=work/('m09-full-vectors' if full else 'm09-vectors')
subprocess.run([sys.executable,str(root/'tools/canny_reference.py'),'--vectors',str(vectors),'--width',str(w),'--height',str(h)],check=True)
exe=work/'m09-local.vvp'
subprocess.run([str(sim/'iverilog.exe'),'-g2012','-s','tb_canny_local',f'-Ptb_canny_local.W={w}',f'-Ptb_canny_local.H={h}',
               '-o',str(exe),*[str(project/'rtl'/f'{n}.v') for n in ('median_pair','gaussian_pair','sobel_pair','canny_nms_pair','edge_algorithm_pair')],
               str(project/'tests'/'tb_canny_local.v')],check=True)
for case in json.loads((vectors/'manifest.json').read_text()):
    subprocess.run([str(sim/'vvp.exe'),str(exe),f'+config={case["config"]}',
                    f'+input={vectors/case["name"]}-input.hex',f'+expected={vectors/case["name"]}-class.hex'],check=True)
print(f'PASS {32*w*h} local pixels across 32 frames with backpressure and metadata')
