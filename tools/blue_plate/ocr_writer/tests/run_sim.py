"""Check the fixed HWC writer against one frozen development ROI and AXI handshakes."""
import hashlib
import json
from pathlib import Path
import subprocess

import numpy as np

ROOT=Path(__file__).resolve().parents[4]
HERE=Path(__file__).resolve().parent
OUT=ROOT/'tmp/blue-plate-ocr-writer'
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()

def main():
    OUT.mkdir(parents=True,exist_ok=True)
    freeze=OUT/'frozen-input-sources.json'
    frozen_sources=json.loads(freeze.read_text())
    for name,h in frozen_sources.items():assert sha(ROOT/name)==h,name
    manifest=ROOT/'tmp/blue-plate-char-segment/experiment/dev-manifest.json'
    records=json.loads(manifest.read_text(encoding='utf8'))['records']
    selected=sorted(records,key=lambda r:(r['source_sha256'],r['roi_index']))[0]
    assert selected['original_split']=='development' and selected['roi_index']==72
    q8=ROOT/'tmp/blue-plate-char-segment/pretrained-new-rois/q8_bgr-inputs.npz'
    assert sha(q8)=='fee23d53600eac35346687e6682abcc6885a47c552c25cd4a457992614ab3ce3'
    image=np.load(q8)['bgr'][selected['roi_index']]
    assert image.shape==(24,94,3) and image.dtype==np.uint8
    signed=(image.astype(np.int16)-128).astype(np.int8)
    (OUT/'input.mem').write_text(''.join(bytes(p).hex()+'\n' for p in image.reshape(-1,3)))
    (OUT/'expected-bytes.mem').write_text(''.join(f'{b:02x}\n' for b in signed.tobytes()))
    deployment=ROOT/'tmp/blue-plate-char-segment/deployment-roi0/manifest.json'
    memory=json.loads(deployment.read_text(encoding='utf8'))['memory']
    assert memory['feature_slot_bytes']==262144 and memory['feature_slot_count']==2
    assert memory['feature_layout']=='HWC, channel contiguous, packed rows' and memory['physical_addresses'] is None
    rtl=HERE.parent/'rtl/ocr_hwc_writer.v';bench=HERE/'tb_ocr_hwc_writer.sv'
    evidence=[rtl,bench,Path(__file__),HERE/'prepare_synthesis.py',freeze,manifest,q8,deployment,
        ROOT/'coding/edge-quality-30fps/rtl/frame_store_dma.v',ROOT/'coding/edge-quality-30fps/rtl/ti60f225_oob_top.v',
        ROOT/'coding/edge-quality-30fps/rtl/ddr3_controller/ddr3_top.v',ROOT/'coding/edge-quality-30fps/rtl/ddr3_controller/axi4_bus_ctl/axi4_bus_ctl.v']
    hashes={p.relative_to(ROOT).as_posix():sha(p) for p in evidence}
    bins=ROOT/'tools/iverilog-12/app/bin'
    commands=[[str(bins/'iverilog.exe'),'-g2012','-Wall','-s','tb','-o',str(OUT/'sim.vvp'),str(rtl),str(bench)],
              [str(bins/'vvp.exe'),str(OUT/'sim.vvp')]]
    for name,command in zip(['compile','simulation'],commands):
        with (OUT/f'{name}.log').open('w') as output:
            run=subprocess.Popen(command,cwd=OUT,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True)
            for line in run.stdout:output.write(line);output.flush();print(line,end='',flush=True)
            run.wait()
        if run.returncode:raise RuntimeError(f'{name} failed')
    log=(OUT/'simulation.log').read_text()
    assert 'PASS OCR HWC writer tests=20' in log
    for name,h in {**hashes,**frozen_sources}.items():assert sha(ROOT/name)==h,name
    report=dict(pass_=True,tests=20,sample_index=selected['sample_index'],roi_index=selected['roi_index'],
        bytes_per_complete_roi=6768,beats_per_complete_roi=423,source_sha256=selected['source_sha256'],
        input_bgr_sha256=hashlib.sha256(image.tobytes()).hexdigest(),hwc_int8_sha256=hashlib.sha256(signed.tobytes()).hexdigest(),
        actual_controller_simulated=False,board_test=False,physical_addresses_assigned=False,
        calibration_read=0,heldout_read=0,commands=commands,log=log,source_hashes=hashes)
    (OUT/'report.json').write_text(json.dumps(report,indent=2),encoding='utf8')

if __name__=='__main__':main()
