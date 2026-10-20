"""Denoise payload must remain original gray / selected median, including in Canny mode."""
from pathlib import Path
work=Path(__file__).resolve().parents[4]/'tmp/tests'/Path(__file__).resolve().parents[2].name
work.mkdir(parents=True,exist_ok=True)
import subprocess
import numpy as np
from canny_reference import images,classify,hysteresis

root=Path(__file__).resolve().parents[1]
project=root.parent
sim=Path(__file__).resolve().parents[4]/'tools/iverilog-12/app/bin'
vectors=work/'m09-denoise'
vectors.mkdir(exist_ok=True)
exe=work/'m09-denoise.vvp'
subprocess.run([str(sim/'iverilog.exe'),'-g2012','-s','tb_canny_local','-o',str(exe),
               *[str(project/'rtl'/f'{n}.v') for n in ('median_pair','gaussian_pair','sobel_pair','canny_nms_pair','edge_algorithm_pair')],
               str(project/'tests'/'tb_canny_local.v')],check=True)
for case,gray in enumerate(images(32,24)):
    for med in (0,1):
        for canny in (0,1):
            state,filtered,*_=classify(gray,32,1,med,canny)
            # Matching gray RGB makes the RGB->Y reference exact, not an unrelated payload.
            rgb=gray.astype(np.uint32)*0x010101
            raw=(gray.astype(np.uint32)<<24)|rgb
            raw_edge=classify(gray,32,1,False,False)[0]==2
            denoised=(gray.astype(np.uint32)<<16)|(filtered.astype(np.uint32)<<8)|(raw_edge.astype(np.uint32)*255)
            expected=(state.astype(np.uint32)<<30)|denoised
            config=0x5020|(med<<11)|(canny<<13)
            for suffix,data in [('input',raw),('class',expected)]:
                (vectors/f'{suffix}.hex').write_text(''.join(f'{int(v):08x}\n' for v in data.flat))
            subprocess.run([str(sim/'vvp.exe'),str(exe),f'+config={config}',
                            f'+input={vectors/"input.hex"}',f'+expected={vectors/"class.hex"}'],check=True)
print('PASS 32 denoise payload frames: median on/off, Sobel/Canny, stalls and metadata')
