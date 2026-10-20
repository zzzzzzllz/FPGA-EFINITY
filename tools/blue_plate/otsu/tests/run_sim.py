"""Cross-check Otsu RTL against independent exact rational arithmetic."""
from fractions import Fraction
import hashlib
import json
from pathlib import Path
import subprocess
import numpy as np
import cv2

ROOT=Path(__file__).resolve().parents[4]
HERE=Path(__file__).resolve().parent


def reference(hist):
    n=sum(hist)
    if n==0:return 1,0
    if n>30720:return 2,0
    moment=sum(i*c for i,c in enumerate(hist));weight=left=0;values=[]
    for t in range(31):
        weight+=hist[t];left+=t*hist[t]
        if 0<weight<n:values.append((Fraction((n*left-weight*moment)**2,weight*(n-weight)),-t))
    if not values:return 3,0
    return 0,-max(values)[1]


def main():
    out=ROOT/'tmp/blue-plate-otsu';out.mkdir(exist_ok=True)
    vectors=[dict(name='empty',hist=[0]*32)]
    for occupied in range(32):
        hist=[0]*32;hist[occupied]=30720;vectors.append(dict(name=f'constant-{occupied}',hist=hist))
    for n in [1,2,30719,30720]:
        for a,c in [(0,31),(1,30),(15,16)]:
            hist=[0]*32;hist[a]=max(1,n//2);hist[c]=n-hist[a];vectors.append(dict(name=f'two-level-{n}-{a}-{c}',hist=hist))
    for hist in [[32767]+[0]*31,[32767]*32,[960]*31+[961]]:vectors.append(dict(name='oversize',hist=hist))
    rng=np.random.default_rng(20261018)
    for i in range(120):
        n=int(rng.integers(2,30721));hist=rng.multinomial(n,rng.dirichlet(np.full(32,.4 if i%2 else 2))).tolist()
        vectors.append(dict(name=f'random-{i}',hist=hist))
    for path in sorted((ROOT/'tmp/blue-plate-normal-g1/frozen-pipeline-features').glob('error-*/plate.png')):
        plate=cv2.imread(str(path));gray=((plate[:,:,2].astype(np.uint16)*77+plate[:,:,1].astype(np.uint16)*150+plate[:,:,0].astype(np.uint16)*29)>>8).astype(np.uint8)
        vectors.append(dict(name=path.parent.name,hist=np.bincount((gray>>3).ravel(),minlength=32).tolist(),source=path.relative_to(ROOT).as_posix()))
    for v in vectors:v['status'],v['threshold']=reference(v['hist'])
    (out/'histograms.mem').write_text(''.join(f'{v:04x}\n' for item in vectors for v in item['hist']),encoding='ascii')
    (out/'expected.mem').write_text(''.join(f'{(v["status"]<<5)|v["threshold"]:02x}\n' for v in vectors),encoding='ascii')
    (out/'vectors.json').write_text(json.dumps(vectors,indent=2),encoding='utf8')
    tools=ROOT/'tools/iverilog-12/app/bin'
    rtl=HERE.parent/'rtl/otsu32.v';tb=HERE/'tb_otsu32.sv'
    commands=[[str(tools/'iverilog.exe'),'-g2012','-Wall','-s','tb_otsu32','-o',str(out/'sim.vvp'),str(rtl),str(tb)],
              [str(tools/'vvp.exe'),str(out/'sim.vvp'),f'+count={len(vectors)}']]
    logs=[]
    for command in commands:
        result=subprocess.run(command,cwd=out,text=True,capture_output=True)
        logs.append(result.stdout+result.stderr)
        (out/'simulation.log').write_text('\n'.join(logs),encoding='utf8')
        if result.returncode:raise RuntimeError(logs[-1])
    record=dict(vectors=len(vectors),jobs=len(vectors)+3,reference='Python fractions.Fraction, earliest threshold on tie',
                rtl_sha256=hashlib.sha256(rtl.read_bytes()).hexdigest(),tb_sha256=hashlib.sha256(tb.read_bytes()).hexdigest(),
                log='\n'.join(logs))
    (out/'simulation.json').write_text(json.dumps(record,indent=2),encoding='utf8')
    print(logs[-1])


if __name__=='__main__':main()
