"""Use a real 720p source frame as DDR bytes; check every interpolated RGB."""
from fractions import Fraction
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import cv2
import numpy as np

ROOT=Path(__file__).resolve().parents[4];HERE=Path(__file__).resolve().parent


def threshold(hist):
    n=sum(hist);m=sum(i*v for i,v in enumerate(hist));w=s=0;values=[]
    for t in range(31):
        w+=hist[t];s+=t*hist[t]
        if 0<w<n:values.append((Fraction((n*s-w*m)**2,w*(n-w)),-t))
    return -max(values)[1] if values else (3<<5)


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--coordinates',action='store_true');parser.add_argument('--integrated',action='store_true');parser.add_argument('--quad',action='store_true');parser.add_argument('--border-grid',action='store_true');args=parser.parse_args()
    if args.border_grid and (args.coordinates or args.integrated or args.quad):parser.error('border-grid tests supplied coordinates; use it without coordinate/quad flags')
    if args.quad:args.integrated=True
    if args.integrated:args.coordinates=True
    out=ROOT/'tmp/blue-plate-geometry'/('fetch-border' if args.border_grid else 'quad' if args.quad else 'roi' if args.integrated else 'coords-fetch' if args.coordinates else 'fetch');out.mkdir(parents=True,exist_ok=True)
    frozen=ROOT/'tmp/blue-plate-normal-g1/integer-geometry-solver'
    manifest=json.loads((frozen/'candidates.json').read_text(encoding='utf8'))
    index=next(i for i,e in enumerate(manifest) if e['sample_index']==36);entry=manifest[index]
    source=ROOT/entry['path'];original=cv2.imread(str(source));h,w=original.shape[:2]
    scale=min(1280/w,720/h);nw,nh=round(w*scale),round(h*scale);dx,dy=(1280-nw)//2,(720-nh)//2
    image=np.zeros((720,1280,3),np.uint8);image[dy:dy+nh,dx:dx+nw]=cv2.resize(original,(nw,nh),interpolation=cv2.INTER_AREA)[:,:,::-1]
    if args.border_grid:
        yy,xx=np.indices((720,1280));image=np.stack([(7*xx+13*yy+10)&255,(11*xx+3*yy+30)&255,(xx^(17*yy)^130)&255],axis=2).astype(np.uint8)
    matrix=np.load(frozen/'candidate-plates.npz')['inverse_q32'][index].tolist()
    (out/'corners.mem').write_text(''.join(f'{round(v*65536)&0xffffffff:x}\n' for point in entry['points'] for v in point),encoding='ascii')
    (out/'coefficients.mem').write_text(''.join(f'{v&((1<<48)-1):x}\n' for row in matrix for v in row),encoding='ascii')
    coords=[]
    for y in range(64):
        for x in range(224):
            den=matrix[2][0]*x+matrix[2][1]*y+matrix[2][2]
            coords.append([round(Fraction(32*(matrix[r][0]*x+matrix[r][1]*y+matrix[r][2]),den)) for r in range(2)])
    edges=[(x,y) for x in [-65,-32,-1,0,1,1279*32,1279*32+31,1280*32] for y in [-33,-1,0,719*32+31,720*32]]
    if args.border_grid:
        anchors=[(-1,-1),(1279,-1),(-1,719),(1279,719),(600,-1),(600,719),(-1,300),(1279,300),(100,100),(600,350)]
        coords=[(x*32+fx,y*32+fy) for x,y in anchors for fy in range(32) for fx in range(32)]
        edges=[(x*32,y*32) for x in [-3,-2,1280,1281] for y in [0,719]]
    groups=[coords,edges];expected=[];thresholds=[]
    for group in groups:
        hist=[0]*32
        for sx,sy in group:
            ix,fx=divmod(sx,32);iy,fy=divmod(sy,32);rgb=[0,0,0]
            for ax,ay,weight in [(0,0,(32-fx)*(32-fy)),(1,0,fx*(32-fy)),(0,1,(32-fx)*fy),(1,1,fx*fy)]:
                if 0<=ix+ax<1280 and 0<=iy+ay<720:
                    for c in range(3):rgb[c]+=int(image[iy+ay,ix+ax,c])*weight
            rgb=[(v+512)//1024 for v in rgb];hist[(77*rgb[0]+150*rgb[1]+29*rgb[2])//2048]+=1
            expected.append((rgb[0]<<16)|(rgb[1]<<8)|rgb[2])
        thresholds.append(threshold(hist))
    raw=image.tobytes();(out/'frame.mem').write_text(''.join(raw[i:i+16].hex()+'\n' for i in range(0,len(raw),16)),encoding='ascii')
    coords=coords+edges
    for name,values in [('coordinates',[((x&0xffffffff)<<32)|(y&0xffffffff) for x,y in coords]),('pixels',expected),('lengths',[len(g) for g in groups]),('thresholds',thresholds)]:
        (out/f'{name}.mem').write_text(''.join(f'{v:x}\n' for v in values),encoding='ascii')
    sources=[ROOT/'tools/blue_plate/frame_reader/rtl/frame_reader.v',HERE.parent/'rtl/perspective_fetch.v',ROOT/'tools/blue_plate/otsu/rtl/otsu32.v',ROOT/'tools/blue_plate/otsu/rtl/roi_otsu32.v',HERE/'tb_fetch_otsu.sv']
    if args.coordinates:sources.append(HERE.parent/'rtl/perspective_coords.v')
    if args.integrated:sources.append(HERE.parent/'rtl/perspective_roi.v')
    if args.quad:sources.extend([HERE.parent/'rtl/perspective_quad.v',HERE.parent/'rtl/perspective_matrix.v'])
    tools=ROOT/'tools/iverilog-12/app/bin'
    defines=(['-DGENERATED_COORDS'] if args.coordinates else [])+(['-DINTEGRATED_ROI'] if args.integrated else [])+(['-DQUAD_SOLVER'] if args.quad else [])
    commands=[[str(tools/'iverilog.exe'),'-g2012','-Wall',*defines,'-s','tb_fetch_otsu','-o',str(out/'sim.vvp'),*map(str,sources)],
              [str(tools/'vvp.exe'),str(out/'sim.vvp')]]
    logs=[]
    for cmd in commands:
        result=subprocess.run(cmd,cwd=out,text=True,capture_output=True);logs.append(result.stdout+result.stderr)
        (out/'simulation.log').write_text('\n'.join(logs),encoding='utf8')
        if result.returncode:raise RuntimeError(logs[-1])
    (out/'simulation.json').write_text(json.dumps(dict(source='nonblack RGB coordinate formula' if args.border_grid else entry['path'],source_sha256=hashlib.sha256(image.tobytes() if args.border_grid else source.read_bytes()).hexdigest(),heldout_consumed=0,
        real_roi_pixels=0 if args.border_grid else len(groups[0]),border_pixels=len(coords) if args.border_grid else 0 if args.coordinates else len(edges),coordinates_rtl=args.coordinates,matrix_rtl=args.quad,log=logs[-1],source_hashes={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sources}),indent=2),encoding='utf8')
    print(logs[-1])


if __name__=='__main__':main()
