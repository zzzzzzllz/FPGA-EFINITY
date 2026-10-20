"""Compare every emitted coordinate with an independent Fraction oracle."""
from fractions import Fraction
import hashlib
import json
from pathlib import Path
import subprocess
import numpy as np

ROOT=Path(__file__).resolve().parents[4]
HERE=Path(__file__).resolve().parent


def main():
    out=ROOT/'tmp/blue-plate-geometry/coords';out.mkdir(parents=True,exist_ok=True)
    frozen=ROOT/'tmp/blue-plate-normal-g1/integer-geometry-solver'
    manifest=json.loads((frozen/'candidates.json').read_text(encoding='utf8'))
    matrices=np.load(frozen/'candidate-plates.npz')['inverse_q32']
    samples=[]
    for number in [36,114,126,127,149,476]:
        index=next(i for i,e in enumerate(manifest) if e['sample_index']==number)
        samples.append(dict(name=f'real-{number}',matrix=matrices[index].tolist(),status=0))
    scale=1<<32
    for name,matrix in [
        ('identity',[[scale,0,0],[0,scale,0],[0,0,scale]]),
        ('negative-half-ties',[[scale//32,0,-scale//64],[0,scale//32,scale//64],[0,0,scale]])]:
        samples.append(dict(name=name,matrix=matrix,status=0))
    samples.extend([dict(name='zero-denominator',matrix=[[scale,0,0],[0,scale,0],[0,0,0]],status=1),
                    dict(name='overflow',matrix=[[0,0,(1<<47)-1],[0,scale,0],[0,0,1]],status=2)])
    coefficients=[];expected=[]
    for sample in samples:
        m=sample['matrix'];coefficients.extend(v for row in m for v in row)
        for y in range(64):
            for x in range(224):
                if sample['status']:pair=0
                else:
                    den=m[2][0]*x+m[2][1]*y+m[2][2]
                    sx=round(Fraction(32*(m[0][0]*x+m[0][1]*y+m[0][2]),den))
                    sy=round(Fraction(32*(m[1][0]*x+m[1][1]*y+m[1][2]),den))
                    pair=((sx&0xffffffff)<<32)|(sy&0xffffffff)
                expected.append(pair)
    for filename,data,bits in [('coefficients',coefficients,48),('expected',expected,64),('statuses',[s['status'] for s in samples],2)]:
        (out/f'{filename}.mem').write_text(''.join(f'{int(v)&((1<<bits)-1):x}\n' for v in data),encoding='ascii')
    (out/'vectors.json').write_text(json.dumps(samples,indent=2),encoding='utf8')
    tools=ROOT/'tools/iverilog-12/app/bin';sources=[HERE.parent/'rtl/perspective_coords.v',HERE/'tb_perspective_coords.sv']
    commands=[[str(tools/'iverilog.exe'),'-g2012','-Wall','-s','tb_perspective_coords','-o',str(out/'sim.vvp'),*map(str,sources)],
              [str(tools/'vvp.exe'),str(out/'sim.vvp'),f'+count={len(samples)}']]
    logs=[]
    for command in commands:
        result=subprocess.run(command,cwd=out,text=True,capture_output=True);logs.append(result.stdout+result.stderr)
        (out/'simulation.log').write_text('\n'.join(logs),encoding='utf8')
        if result.returncode:raise RuntimeError(logs[-1])
    (out/'simulation.json').write_text(json.dumps(dict(vectors=len(samples),heldout_consumed=0,oracle='fractions.Fraction and Python nearest-even round',
        log=logs[-1],hashes={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sources}),indent=2),encoding='utf8')
    print(logs[-1])


if __name__=='__main__':main()
