"""Verify RGB pairs through the real histogram and exact threshold RTL."""
import hashlib
import argparse
import json
from pathlib import Path
import subprocess
import cv2
import numpy as np
from run_sim import reference

ROOT=Path(__file__).resolve().parents[4]
HERE=Path(__file__).resolve().parent


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--mapped',action='store_true')
    parser.add_argument('--lut-init-fix',action='store_true');args=parser.parse_args()
    out=ROOT/'tmp/blue-plate-otsu'/('roi-mapped' if args.mapped else 'roi');out.mkdir(parents=True,exist_ok=True)
    rng=np.random.default_rng(20261019)
    cases=[]
    def add(name,rgb,width,declared=None):
        rgb=np.asarray(rgb,dtype=np.uint8).reshape(-1,3)
        hist=np.bincount(((rgb.astype(np.uint32)@np.array([77,150,29]))>>11),minlength=32).tolist()
        status,threshold=reference(hist)
        n=len(rgb) if declared is None else declared
        if n>30720:status,threshold=2,0
        cases.append(dict(name=name,rgb=rgb,width=width,size=n,hist=hist,status=status,threshold=threshold))
    add('empty',[],1)
    add('too-large',[],1,30721)
    add('max-declared',[],1,65535)
    for gray in range(0,256,8):add(f'constant-{gray}',np.full((30720 if gray in [0,248] else 65,3),gray),5)
    for width in [1,2,3,31,32,223,224,319,320]:
        n=width*min(96,30720//width)
        add(f'random-width-{width}',rng.integers(0,256,(n,3)),width)
    add('gray-ramp',np.repeat(np.arange(256,dtype=np.uint8),3).reshape(-1,3),16)
    add('alternating-extremes',np.tile([[0,0,0],[255,255,255]],(15360,1)),320)
    add('same-bin-pairs',np.tile([[8,8,8],[15,15,15],[248,248,248],[255,255,255]],(7680,1)),320)
    for path in sorted((ROOT/'tmp/blue-plate-normal-g1/frozen-pipeline-features').glob('error-*/plate.png')):
        bgr=cv2.imread(str(path));add(path.parent.name,bgr[:,:,::-1],bgr.shape[1])
        cases[-1]['source']=path.relative_to(ROOT).as_posix()
        cases[-1]['source_sha256']=hashlib.sha256(path.read_bytes()).hexdigest()
    if args.mapped:
        names=['empty','too-large','error-036','constant-8','gray-ramp','random-width-3','random-width-1']
        cases=[next(c for c in cases if c['name']==name) for name in names]
    beats=[];starts=[];lengths=[]
    for c in cases:
        starts.append(len(beats))
        rgb=c.pop('rgb');width=c['width']
        for row in range(0,len(rgb),width):
            for x in range(row,min(row+width,len(rgb)),2):
                dual=x+1<min(row+width,len(rgb));last=x+(2 if dual else 1)==len(rgb)
                a=int(rgb[x]@np.array([65536,256,1],dtype=np.uint32))
                b=int(rgb[x+1]@np.array([65536,256,1],dtype=np.uint32)) if dual else 0xabcdef
                beats.append((int(last)<<50)|((3 if dual else 1)<<48)|(a<<24)|b)
        lengths.append(len(beats)-starts[-1])
    arrays={'beats':beats,'starts':starts,'lengths':lengths,'sizes':[c['size'] for c in cases],
            'expected':[(c['status']<<5)|c['threshold'] for c in cases],
            'histograms':[v for c in cases for v in c['hist']]}
    for name,values in arrays.items():(out/f'{name}.mem').write_text(''.join(f'{v:x}\n' for v in values),encoding='ascii')
    (out/'vectors.json').write_text(json.dumps(cases,indent=2),encoding='utf8')
    bin_dir=ROOT/'tools/iverilog-12/app/bin'
    sources=[HERE.parent/'rtl/otsu32.v',HERE.parent/'rtl/roi_otsu32.v',HERE/'tb_roi_otsu32.sv']
    design=list(map(str,sources))
    adaptation=None
    if args.mapped:
        netlist=ROOT/'tmp/blue-plate-otsu/synthesis-roi/out/roi_otsu32.map.v'
        library=list(Path('D:/Efinity/sim_models/verilog').glob('*.v'))
        if args.lut_init_fix:
            original=Path('D:/Efinity/sim_models/verilog/efx_lut4.v')
            content=original.read_text();old='always @(I0_net or I1_net or I2_net or I3_net) begin'
            assert content.count(old)==1
            adapted=out/'efx_lut4_icarus.v';adapted.write_text(content.replace(old,'always_comb begin'),encoding='utf8')
            library=[p for p in library if p.name!='efx_lut4.v']+[adapted]
            adaptation=dict(source=str(original),source_sha256=hashlib.sha256(original.read_bytes()).hexdigest(),
                adapted_sha256=hashlib.sha256(adapted.read_bytes()).hexdigest(),
                change='Local LUT sensitivity-list always -> always_comb for constant initialization in Icarus; vendor installation and netlist unchanged')
        design=['-DMAPPED_NETLIST',str(netlist),*map(str,library),str(sources[-1])]
        sources.append(netlist)
    commands=[[str(bin_dir/'iverilog.exe'),'-g2012','-Wall','-s','tb_roi_otsu32','-o',str(out/'sim.vvp'),*design],
              [str(bin_dir/'vvp.exe'),str(out/'sim.vvp'),f'+count={len(cases)}',f'+beats={len(beats)}']]
    logs=[]
    for command in commands:
        p=subprocess.run(command,cwd=out,text=True,capture_output=True);logs.append(p.stdout+p.stderr)
        (out/'simulation.log').write_text('\n'.join(logs),encoding='utf8')
        if p.returncode:raise RuntimeError(logs[-1])
    report=dict(cases=len(cases),beats=len(beats),real_rois=sum('source' in c for c in cases),heldout_consumed=0,log='\n'.join(logs),
                source_sha256={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sources})
    if adaptation:report['vendor_model_adaptation']=adaptation
    (out/'simulation.json').write_text(json.dumps(report,indent=2),encoding='utf8')
    print(logs[-1])


if __name__=='__main__':main()
