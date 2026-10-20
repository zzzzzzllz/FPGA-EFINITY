"""Actual reader/geometry/Q8 connection with a provisional-write sink model."""
import hashlib
import json
from pathlib import Path
import shutil
import subprocess

import numpy as np
from run_sim import reference

ROOT=Path(__file__).resolve().parents[4]
HERE=Path(__file__).resolve().parent
OUT=ROOT/'tmp/blue-plate-ocr-input/integration'
def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()

def main():
    OUT.mkdir(parents=True,exist_ok=True)
    fixture=ROOT/'tmp/blue-plate-geometry/color-output/dev-125-roi-72'
    copies=[(fixture/'frame.mem','frame.mem'),(fixture/'corners.mem','corners.mem'),
            (ROOT/'tmp/blue-plate-ocr-input/dev-125/expected.mem','expected.mem')]
    for source,name in copies:shutil.copy2(source,OUT/name)
    y,x=np.indices((64,224))
    synthetic=np.stack(((x+y)%256,y,x),2).astype(np.uint8)
    (OUT/'synthetic.mem').write_text(''.join(bytes(p).hex()+'\n' for p in reference(synthetic).reshape(-1,3)))
    sources=[ROOT/'tools/blue_plate/frame_reader/rtl/frame_reader.v']
    sources += [ROOT/'tools/blue_plate/geometry/rtl'/f'{n}.v' for n in ['perspective_matrix','perspective_quad','perspective_roi','perspective_coords','perspective_fetch']]
    sources += [ROOT/'tools/blue_plate/otsu/rtl'/f'{n}.v' for n in ['otsu32','roi_otsu32']]
    sources += [HERE.parent/'rtl'/f'{n}.v' for n in ['ocr_resize_q8','geometry_ocr_input']]
    sources += [HERE/'tb_geometry_ocr_input.sv']
    evidence=sources+[Path(__file__),HERE/'run_sim.py',*[p for p,_ in copies]]
    hashes={p.relative_to(ROOT).as_posix():sha(p) for p in evidence}
    bins=ROOT/'tools/iverilog-12/app/bin'
    commands=[[str(bins/'iverilog.exe'),'-g2012','-Wall','-s','tb','-y','D:/Efinity/sim_models/verilog','-Y','.v',
        '-o',str(OUT/'sim.vvp'),*map(str,sources)],
        [str(bins/'vvp.exe'),str(OUT/'sim.vvp')]]
    for name,command in zip(['compile','simulation'],commands):
        with (OUT/f'{name}.log').open('w') as output:
            run=subprocess.Popen(command,cwd=OUT,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True)
            for line in run.stdout:
                output.write(line);output.flush();print(line,end='',flush=True)
            run.wait()
        log=(OUT/f'{name}.log').read_text()
        if run.returncode:raise RuntimeError(f'{name} failed')
    assert 'PASS linked geometry/Q8' in log
    for p,h in hashes.items():assert sha(ROOT/p)==h,p
    result=dict(pass_=True,jobs=8,source_sha_selected_real_roi=dict(sample_index=125,roi_index=72),
        full_frames=2,early_failures=6,real_ddr_writer=False,calibration_read=0,heldout_read=0,
        commands=commands,log=log,source_hashes=hashes,
        vendor_ram_sha256=sha(Path('D:/Efinity/sim_models/verilog/efx_ram10.v')))
    (OUT/'report.json').write_text(json.dumps(result,indent=2),encoding='utf8')

if __name__=='__main__':main()
