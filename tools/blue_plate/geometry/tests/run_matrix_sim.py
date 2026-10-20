"""Check all frozen Q16 real quadrilaterals against their audited Q32 matrices."""
from fractions import Fraction
import hashlib
import json
from pathlib import Path
import subprocess
import numpy as np

ROOT=Path(__file__).resolve().parents[4];HERE=Path(__file__).resolve().parent


def solve(points):
    # Eight-equation exact Gaussian elimination, independent of RTL's closed form.
    equations=[]
    for (u,v),(x,y) in zip([(0,0),(223,0),(223,63),(0,63)],points):
        x,y=Fraction(x,65536),Fraction(y,65536)
        equations.extend([[u,v,1,0,0,0,-u*x,-v*x,x],[0,0,0,u,v,1,-u*y,-v*y,y]])
    a=[[Fraction(v) for v in row] for row in equations]
    for col in range(8):
        pivot=next((r for r in range(col,8) if a[r][col]),None)
        if pivot is None:return None
        a[col],a[pivot]=a[pivot],a[col];divisor=a[col][col];a[col]=[v/divisor for v in a[col]]
        for row in range(8):
            if row!=col:
                factor=a[row][col];a[row]=[v-factor*w for v,w in zip(a[row],a[col])]
    return [round(a[i][-1]*(1<<32)) for i in range(8)]+[1<<32]


def main():
    out=ROOT/'tmp/blue-plate-geometry/matrix';out.mkdir(parents=True,exist_ok=True)
    frozen=ROOT/'tmp/blue-plate-normal-g1/integer-geometry-solver'
    entries=json.loads((frozen/'candidates.json').read_text(encoding='utf8'))
    matrices=np.load(frozen/'candidate-plates.npz')['inverse_q32']
    vectors=[]
    for i,entry in enumerate(entries):
        points=[[round(v*65536) for v in p] for p in entry['points']]
        expected=solve(points);assert expected==matrices[i].ravel().tolist()
        vectors.append(dict(name=f'real-{i}',points=points,expected=expected,status=0))
    q=65536
    extras=[('identity',[[0,0],[223*q,0],[223*q,63*q],[0,63*q]]),
            ('negative',[[0,0],[-223*q,0],[-223*q,-63*q],[0,-63*q]]),
            ('maximum',[[2048*q,2048*q],[-2048*q,2048*q],[-2048*q,-2048*q],[2048*q,-2048*q]]),
            ('degenerate',[[0,0]]*4),('out-of-range',[[2048*q+1,0],[223*q,0],[223*q,63*q],[0,63*q]]),
            ('overflow',[[50*q,50*q],[100*q+100000,100*q+99999],[100*q,100*q],[100*q+100001,100*q+100000]])]
    for name,points in extras:
        expected=solve(points);status=0
        if any(abs(v)>2048*q for point in points for v in point):status=1
        elif expected is None:status=2
        elif any(v<-(1<<47) or v>=(1<<47) for v in expected):status=3
        vectors.append(dict(name=name,points=points,expected=expected or [0]*9,status=status))
    for name,data,bits in [('corners',[v for item in vectors for point in item['points'] for v in point],32),
                           ('coefficients',[v for item in vectors for v in item['expected']],48),('statuses',[item['status'] for item in vectors],2)]:
        (out/f'{name}.mem').write_text(''.join(f'{v&((1<<bits)-1):x}\n' for v in data),encoding='ascii')
    (out/'vectors.json').write_text(json.dumps(vectors,indent=2),encoding='utf8')
    sources=[HERE.parent/'rtl/perspective_matrix.v',HERE/'tb_perspective_matrix.sv'];tools=ROOT/'tools/iverilog-12/app/bin'
    commands=[[str(tools/'iverilog.exe'),'-g2012','-Wall','-s','tb_perspective_matrix','-o',str(out/'sim.vvp'),*map(str,sources)],
              [str(tools/'vvp.exe'),str(out/'sim.vvp'),f'+count={len(vectors)}']]
    logs=[]
    for cmd in commands:
        result=subprocess.run(cmd,cwd=out,text=True,capture_output=True);logs.append(result.stdout+result.stderr)
        (out/'simulation.log').write_text('\n'.join(logs),encoding='utf8')
        if result.returncode:raise RuntimeError(logs[-1])
    (out/'simulation.json').write_text(json.dumps(dict(real_candidates=len(entries),vectors=len(vectors),oracle='Fraction eight-equation Gaussian elimination',heldout_consumed=0,log=logs[-1],
        hashes={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sources}),indent=2),encoding='utf8')
    print(logs[-1])


if __name__=='__main__':main()
