"""Frozen 307-dev comparison plus bounded RGB-stream RTL and lifecycle tests."""
import argparse
import ast
from fractions import Fraction
import hashlib
import json
from pathlib import Path
import re
import subprocess

import numpy as np

ROOT=Path(__file__).resolve().parents[4]
HERE=Path(__file__).resolve().parent
OUT=ROOT/'tmp/blue-plate-ocr-input'
RTL=HERE.parent/'rtl/ocr_resize_q8.v'
MODELS=Path('D:/Efinity/sim_models/verilog')


def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def axis(src,dst):
    result=[]
    for i in range(dst):
        coord=min(max(Fraction((2*i+1)*src-dst,2*dst),0),src-1)
        lo=int(coord);f=int((coord-lo)*256+Fraction(1,2));lo+=f//256
        result.append((lo,min(lo+1,src-1),f%256))
    return result


def reference(image):
    # Keep the horizontal intermediate exact, then use one final half-up rounding.
    xs,ys=axis(224,94),axis(64,24)
    x0,x1,fx=np.array(xs).T
    result=[]
    for y0,y1,fy in ys:
        top=image[y0,x0].astype(np.int64)*(256-fx[:,None])+image[y0,x1].astype(np.int64)*fx[:,None]
        bottom=image[y1,x0].astype(np.int64)*(256-fx[:,None])+image[y1,x1].astype(np.int64)*fx[:,None]
        result.append((top*(256-fy)+bottom*fy+32768)>>16)
    return np.array(result,dtype=np.uint8)


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--mapped',action='store_true')
    parser.add_argument('--lut-init-fix',action='store_true');args=parser.parse_args()
    OUT.mkdir(exist_ok=True)
    source=ROOT/'tools/blue_plate/char_segment/experiment.py'
    contract=ROOT/'tools/blue_plate/char_segment/fixed_lprnet.py'
    manifest_path=ROOT/'tmp/blue-plate-char-segment/experiment/dev-manifest.json'
    inputs=manifest_path.with_name('dev-inputs.npz')
    frozen_q8=ROOT/'tmp/blue-plate-char-segment/pretrained-new-rois/q8_bgr-inputs.npz'
    q8_config=frozen_q8.with_name('config.json')
    manifest=json.loads(manifest_path.read_text(encoding='utf8'))
    assert sha(inputs)==manifest['inputs_sha256']
    # Use the later frozen LPR input experiment, not the earlier ROI extraction revision.
    frozen_hashes=json.loads(q8_config.read_text(encoding='utf8'))['input_hashes']
    assert sha(source)==frozen_hashes['tools/blue_plate/char_segment/experiment.py']
    assert sha(manifest_path)==frozen_hashes['tmp/blue-plate-char-segment/experiment/dev-manifest.json']
    assert sha(frozen_q8)=='fee23d53600eac35346687e6682abcc6885a47c552c25cd4a457992614ab3ce3'
    records=manifest['records'];images=np.load(inputs)['bgr'];gold=np.load(frozen_q8)['bgr']
    assert len(records)==len(images)==len(gold)==307
    assert all(r['original_split']=='development' for r in records)
    tree=ast.parse(source.read_text(encoding='utf8'))
    scope={'np':np}
    exec(compile(ast.Module(body=[n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name in ['axis_lut','resize_q8']],type_ignores=[]),str(source),'exec'),scope)
    for axis_name,src,dst in [('x',224,94),('y',64,24)]:
        table=[int(v,16) for v in re.findall(r'\d+:axis_'+axis_name+r"=\d+'h([0-9a-f]+);",RTL.read_text())]
        points=axis(src,dst)
        assert table==[(lo<<8)|f for lo,hi,f in points]
        assert all(hi==lo+1 for lo,hi,f in points)
        assert all(points[i+1][0]>points[i][1] for i in range(dst-1))
    hashes={str(p.relative_to(ROOT)):sha(p) for p in [source,contract,manifest_path,inputs,frozen_q8,q8_config,RTL,HERE/'tb_ocr_resize_q8.sv',Path(__file__)]}
    for record,image,expected in zip(records,images,gold):
        assert hashlib.sha256(image.tobytes()).hexdigest()==record['roi_bgr_sha256']
        assert np.array_equal(reference(image),expected)
        assert np.array_equal(scope['resize_q8'](image,24,94),expected)
    selected=sorted(records,key=lambda r:(r['source_sha256'],r['roi_index']))[:4]
    cases=[]
    for r in selected:cases.append((f"dev-{r['sample_index']}",images[r['roi_index']],gold[r['roi_index']]))
    yy,xx=np.indices((64,224))
    synthetic=np.stack(((xx*37+yy*13)%256,((xx^yy)&1)*255,(xx*7+yy*71)%256),2).astype(np.uint8)
    cases.append(('boundary-pattern',synthetic,reference(synthetic)))
    stage='mapped' if args.mapped else 'rtl'
    binaries=OUT/f'{stage}.vvp'
    sources=[OUT/'synthesis/out/ocr_resize_q8.map.v'] if args.mapped else [RTL]
    adaptation=None
    if args.mapped:
        for p in [*sources,OUT/'synthesis/out/ocr_resize_q8.map.rpt',OUT/'synthesis/source-hashes.json']:
            hashes[str(p.relative_to(ROOT))]=sha(p)
        assert json.loads((OUT/'synthesis/source-hashes.json').read_text())['ocr_resize_q8.v']==sha(RTL)
        resource=(OUT/'synthesis/out/ocr_resize_q8.map.rpt').read_text()
        assert re.search(r'EFX_RAM10\s*:\s*1\s',resource) and 'No DSP in design' in resource
        if args.lut_init_fix:
            original=MODELS/'efx_lut4.v';content=original.read_text()
            old='always @(I0_net or I1_net or I2_net or I3_net) begin'
            assert content.count(old)==1
            adapted=OUT/'efx_lut4_icarus.v'
            adapted.write_text(content.replace(old,'always_comb begin'))
            sources.append(adapted)
            adaptation=dict(source=str(original),source_sha256=sha(original),adapted_sha256=sha(adapted),
                change='Local LUT always -> always_comb for constant initialization in Icarus; vendor installation and netlist unchanged')
    bins=ROOT/'tools/iverilog-12/app/bin'
    compile_cmd=[str(bins/'iverilog.exe'),'-g2012','-Wall','-s','tb','-y',str(MODELS),'-Y','.v','-o',str(binaries),str(HERE/'tb_ocr_resize_q8.sv'),*map(str,sources)]
    c=subprocess.run(compile_cmd,capture_output=True,text=True)
    (OUT/f'{stage}-compile.log').write_text(c.stdout+c.stderr)
    if c.returncode:raise RuntimeError(c.stdout+c.stderr)
    runs=[]
    for name,image,expected in cases:
        case=OUT/name;case.mkdir(exist_ok=True)
        (case/'input.mem').write_text(''.join(bytes(p[::-1]).hex()+'\n' for p in image.reshape(-1,3)))
        # Output word and memory byte stream both put B before G before R.
        (case/'expected.mem').write_text(''.join(bytes(p).hex()+'\n' for p in expected.reshape(-1,3)))
        modes=range(8) if name=='boundary-pattern' and not args.mapped else [0]
        for mode in modes:
            command=[str(bins/'vvp.exe'),str(binaries),f'+MODE={mode}']
            run=subprocess.run(command,cwd=case,capture_output=True,text=True)
            log=run.stdout+run.stderr;(case/f'{stage}-{mode}.log').write_text(log)
            if run.returncode or 'PASS Q8 input' not in log:raise RuntimeError(log)
            runs.append(dict(case=name,mode=mode,command=command,log=log))
            print(name,mode,log.strip(),flush=True)
    for p,h in hashes.items():assert sha(ROOT/p)==h
    report=dict(pass_=True,stage=stage,dev_rois=307,exact_q8_bytes=int(gold.size),calibration_read=0,heldout_read=0,
                compile_command=compile_cmd,runs=runs,source_hashes=hashes,
                vendor_ram_sha256=sha(MODELS/'efx_ram10.v'),vendor_model_adaptation=adaptation)
    (OUT/f'{stage}-report.json').write_text(json.dumps(report,indent=2),encoding='utf8')


if __name__=='__main__':main()
