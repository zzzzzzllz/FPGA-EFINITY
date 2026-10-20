"""Integer sampling research on the unchanged full-frame candidate pipeline.

Default mode isolates sampling with OpenCV coefficient solving. --integer-solver
also uses integer corner-to-matrix arithmetic; neither mode is an RTL solver.
"""
import hashlib
import argparse
import json
from pathlib import Path
import cv2
import numpy as np
import baseline as b


def inverse_matrix(points):
    forward=cv2.getPerspectiveTransform(np.float32(points),np.float32([[0,0],[223,0],[223,63],[0,63]]))
    ok,matrix=cv2.invert(forward)
    if not ok or abs(matrix[2,2])<1e-12:raise ValueError('Degenerate perspective matrix')
    return matrix/matrix[2,2]


def rounded_ratio(numerator,denominator):
    if denominator<0:numerator,denominator=-numerator,-denominator
    q,r=divmod(numerator,denominator)
    return q+int(2*r>denominator or (2*r==denominator and q%2!=0))


def integer_matrix(points,fraction_bits=32):
    # Unit-square projective map, then u=x/223 and v=y/63.
    # Corner input is signed Q16. All coefficient solving uses Python integers;
    # RTL must implement these bounded wide products/divisions, not float setup.
    p=[[int(round(float(v)*65536)) for v in row] for row in points]
    x0,y0=p[0];x1,y1=p[1];x2,y2=p[2];x3,y3=p[3]
    dx1,dx2,dx3=x1-x2,x3-x2,x0-x1+x2-x3
    dy1,dy2,dy3=y1-y2,y3-y2,y0-y1+y2-y3
    det=dx1*dy2-dx2*dy1
    if det==0:raise ValueError('Degenerate quadrilateral')
    gn=dx3*dy2-dx2*dy3;hn=dx1*dy3-dx3*dy1
    scale=1<<fraction_bits
    rows=[]
    for a0,a1,a3 in [(x0,x1,x3),(y0,y1,y3)]:
        a=(a1-a0)*det+gn*a1;b=(a3-a0)*det+hn*a3;c=a0*det
        rows.append([rounded_ratio(a*scale,223*det*65536),rounded_ratio(b*scale,63*det*65536),rounded_ratio(c*scale,det*65536)])
    rows.append([rounded_ratio(gn*scale,223*det),rounded_ratio(hn*scale,63*det),scale])
    return np.array(rows,dtype=np.int64)


def sample_integer(image,points,fraction_bits=32,integer_solver=False):
    quantized=integer_matrix(points,fraction_bits) if integer_solver else np.rint(inverse_matrix(points)*(1<<fraction_bits)).astype(np.int64)
    yy,xx=np.indices((64,224),dtype=np.int64)
    denominator=quantized[2,0]*xx+quantized[2,1]*yy+quantized[2,2]
    if np.any(denominator<=0):raise ValueError('Nonpositive perspective denominator')
    coordinates=[]
    for row in range(2):
        numerator=(quantized[row,0]*xx+quantized[row,1]*yy+quantized[row,2])*32
        quotient,remainder=np.divmod(numerator,denominator)
        quotient+=((remainder*2>denominator)|((remainder*2==denominator)&((quotient&1)!=0)))
        coordinates.append(quotient)
    sx,sy=coordinates;ix,iy=sx>>5,sy>>5;fx,fy=sx&31,sy&31
    accum=np.zeros((64,224,3),np.int64)
    for dx,dy,weight in [(0,0,(32-fx)*(32-fy)),(1,0,fx*(32-fy)),(0,1,(32-fx)*fy),(1,1,fx*fy)]:
        x,y=ix+dx,iy+dy;valid=(x>=0)&(x<image.shape[1])&(y>=0)&(y<image.shape[0])
        accum[valid]+=image[y[valid],x[valid]].astype(np.int64)*weight[valid,None]
    return ((accum+512)>>10).astype(np.uint8),quantized


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--integer-solver',action='store_true');args=parser.parse_args()
    root=b.ROOT/'tmp/blue-plate-normal-g1';out=root/('integer-geometry-solver' if args.integer_solver else 'integer-geometry');out.mkdir(exist_ok=True)
    previous=root/'full-dual-local-geometry'
    samples=json.loads((previous/'samples.json').read_text(encoding='utf8'))
    expected={(r['path'],r['mode']):r for r in json.loads((previous/'results.json').read_text(encoding='utf8'))}
    model=b.ROOT/'tmp/blue-plate-char-model/frozen-domain/geometry'
    config=json.loads((model/'interface.json').read_text(encoding='utf8'))
    context=(dict(np.load(model/'weights.npz')),config['thresholds'])
    rows={bits:[] for bits in ([32] if args.integer_solver else [24,32])};stats={bits:dict(rgb_values=0,different_rgb_values=0,max_error=0,changed_results=0) for bits in rows}
    manifest=[];plates=[];matrices=[]
    for index,sample in enumerate(samples):
        if sample['split']=='heldout':continue
        original=b.read_image(b.ROOT/sample['path']);h,w=original.shape[:2]
        scale=min(1280/w,720/h);nw,nh=round(w*scale),round(h*scale);dx,dy=(1280-nw)//2,(720-nh)//2
        image=np.zeros((720,1280,3),np.uint8);image[dy:dy+nh,dx:dx+nw]=cv2.resize(original,(nw,nh),interpolation=cv2.INTER_AREA)
        candidates=b.locate(image,'dual-local','none',context)
        attempts={bits:[] for bits in [0,*rows]}
        for c in candidates:
            reference=b.warp(image,c['points']);result,mask,rects=b.recognize(reference,'global',None,None,'xor','projection-char',context)
            attempts[0].append((c,result,reference,mask,rects))
            entry=dict(sample_index=index,path=sample['path'],split=sample['split'],points=np.asarray(c['points']).tolist(),kind='automatic',candidate=c)
            entry['candidate']={k:np.asarray(v).tolist() if isinstance(v,np.ndarray) else v for k,v in c.items()}
            entry['plate_index']=len(plates);manifest.append(entry);plates.append(reference)
            for bits in rows:
                plate,matrix=sample_integer(image,c['points'],bits,args.integer_solver)
                delta=np.abs(plate.astype(np.int16)-reference.astype(np.int16))
                stats[bits]['rgb_values']+=plate.size;stats[bits]['different_rgb_values']+=int(np.count_nonzero(delta))
                stats[bits]['max_error']=max(stats[bits]['max_error'],int(delta.max()))
                result,mask,rects=b.recognize(plate,'global',None,None,'xor','projection-char',context)
                attempts[bits].append((c,result,plate,mask,rects))
                if bits==32:matrices.append(matrix)
        for values in attempts.values():values.sort(key=b.candidate_key)
        no_candidate=dict(status='no_candidate',raw='',scores=[])
        assert (attempts[0][0][1] if attempts[0] else no_candidate)==expected[sample['path'],'automatic']['result']
        for bits in rows:
            old=expected[sample['path'],'automatic'];result=attempts[bits][0][1] if attempts[bits] else no_candidate
            row=old.copy();row['result']=result
            if attempts[bits]:row['iou']=b.iou(attempts[bits][0][0]['box'],[sample['box'][0]*nw/w+dx,sample['box'][1]*nh/h+dy,sample['box'][2]*nw/w+dx,sample['box'][3]*nh/h+dy])
            rows[bits].append(row);stats[bits]['changed_results']+=result!=old['result']
        if index%25==0:print('processed source index',index,flush=True)
    np.savez_compressed(out/'candidate-plates.npz',rgb_bgr=np.array(plates),inverse_q32=np.array(matrices))
    (out/'candidates.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf8')
    for bits,data in rows.items():
        (out/f'q{bits}-results.json').write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf8')
        stats[bits]['metrics']={split:b.summarize([r for r in data if r['split']==split],0,0) for split in ['development','validation']}
    report=dict(heldout_consumed=0,opencv_version=cv2.__version__,candidate_count=len(plates),sampling=stats,
        matrix_solver='Q16 corners, exact integer square-to-quad coefficients, Q32 rounding' if args.integer_solver else 'OpenCV getPerspectiveTransform + invert; not yet an integer or RTL solver',
        source_sha256={str(p.relative_to(b.ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in [Path(__file__),Path(b.__file__),Path(b.__file__).parent/'mser_locator.py',model/'weights.npz']})
    (out/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
    print(json.dumps(stats,ensure_ascii=False),flush=True)


if __name__=='__main__':main()
