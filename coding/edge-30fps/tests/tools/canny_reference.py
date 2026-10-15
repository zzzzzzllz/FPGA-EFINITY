"""M09 integer reference and deterministic RTL vectors; no OpenCV defaults."""
from collections import deque
from pathlib import Path
import argparse
import json
import numpy as np


def windows(a):
    p = np.pad(a.astype(np.int32), 1, mode='edge')
    h, w = a.shape
    return [p[y:y+h, x:x+w] for y in range(3) for x in range(3)]


def classify(gray, threshold=32, ratio=1, median=True, canny=True):
    if not 0 <= threshold <= 2040 or (canny and threshold == 0):
        raise ValueError('threshold outside algorithm range')
    if ratio not in (0, 1, 2):
        raise ValueError('ratio must be 0, 1 or 2')
    filtered = np.median(windows(gray), axis=0).astype(np.int32) if median else gray.astype(np.int32)
    smooth = sum(k*v for k, v in zip((1,2,1,2,4,2,1,2,1), windows(filtered)))
    smooth = (smooth+8) >> 4 if canny else filtered
    a,b,c,d,e,f,g,h,i = windows(smooth)
    gx, gy = c+2*f+i-a-2*d-g, g+2*h+i-a-2*b-c
    ax, ay = abs(gx), abs(gy)
    mag = ax+ay
    direction = np.where(ay*256 <= ax*106, 0,
                         np.where(ay*106 >= ax*256, 1, np.where((gx < 0) == (gy < 0), 2, 3)))
    a,b,c,d,e,f,g,h,i = windows(mag)
    before = np.choose(direction, [d,b,a,c])
    after = np.choose(direction, [f,h,i,g])
    nms = np.where((mag > before) & (mag >= after), mag, 0) if canny else mag.copy()
    nms[[0,-1],:] = 0
    nms[:,[0,-1]] = 0
    low = threshold*(ratio+1)//4
    state = np.where(nms > threshold, 2, np.where((nms > low) & canny, 1, 0)).astype(np.uint8)
    return state, filtered, smooth, mag, direction, nms


def hysteresis(state):
    accepted = state == 2
    h,w = state.shape
    queue = deque(map(tuple, np.argwhere(accepted)))
    total, highwater = len(queue), len(queue)
    while queue:
        y,x = queue.popleft()
        for yy in range(max(0,y-1), min(h,y+2)):
            for xx in range(max(0,x-1), min(w,x+2)):
                if state[yy,xx] == 1 and not accepted[yy,xx]:
                    accepted[yy,xx] = True
                    queue.append((yy,xx))
                    total += 1
        highwater = max(highwater, len(queue))
    assert total <= h*w
    return accepted, total, highwater


def connectivity_oracle(state):
    # Independent component traversal starts at every candidate, including weak-only components.
    h,w = state.shape
    seen = set()
    result = np.zeros_like(state, dtype=bool)
    for y,x in np.argwhere(state != 0):
        if (y,x) in seen:
            continue
        component, stack, strong = [], [(y,x)], False
        seen.add((y,x))
        while stack:
            yy,xx = stack.pop()
            component.append((yy,xx))
            strong |= state[yy,xx] == 2
            for dy,dx in ((-1,-1),(-1,0),(-1,1),(0,-1),(0,1),(1,-1),(1,0),(1,1)):
                p = yy+dy,xx+dx
                if 0 <= p[0] < h and 0 <= p[1] < w and state[p] and p not in seen:
                    seen.add(p)
                    stack.append(p)
        if strong:
            for p in component:
                result[p] = True
    return result


def images(w,h):
    y,x = np.indices((h,w))
    rng = np.random.default_rng(901)
    return [np.full((h,w), 73, np.uint8), np.uint8(x>=w//2)*192,
            np.uint8(y>=h//2)*128, np.uint8(x*h >= y*w)*255,
            np.uint8((x>w//4)&(x<3*w//4)&(y>h//4)&(y<3*h//4))*224,
            rng.integers(0,256,(h,w),dtype=np.uint8),
            np.uint8((x%8)*32), np.uint8((x+y)%2)*255]


def selftest():
    for a in images(32,24):
        for med in (False,True):
            for threshold in (1,32,64,255,1020,2040):
                for ratio in range(3):
                    state,*_ = classify(a,threshold,ratio,med)
                    got,n,_ = hysteresis(state)
                    assert np.array_equal(got, connectivity_oracle(state))
                    assert n == int(got.sum())
    chain = np.zeros((65,65),np.uint8)
    for y in range(1,64,2):
        chain[y,1:64] = 1
        if y<63:
            chain[y+1,63 if y%4==1 else 1] = 1
    chain[1,1] = 2
    got,total,_ = hysteresis(chain)
    assert total == np.count_nonzero(chain) and total > 2000
    chain[1,1] = 1
    assert not hysteresis(chain)[0].any()
    diagonal = np.eye(65,dtype=np.uint8)
    diagonal[0,0] = 2
    assert hysteresis(diagonal)[1] == 65
    dense = np.full((720,1280),2,np.uint8)
    assert hysteresis(dense)[1:] == (921600,921600)
    print('PASS reference: 576 local cases, long winding chain, no seed, corner contact, dense 720p')


def vectors(out,w,h,camera_rgby=False):
    out.mkdir(parents=True,exist_ok=True)
    manifest = []
    for case,a in enumerate(images(w,h)):
        for med in (0,1):
            for algorithm in (0,1):
                ratio = case%3
                threshold = (1,32,64,255,96,160,32,2040)[case]
                state,filtered,*_ = classify(a,threshold,ratio,med,algorithm)
                edge,total,highwater = hysteresis(state)
                # RGB carries a varying payload independent of the Y input, exposing misalignment.
                y,x = np.indices(a.shape)
                rgb = ((x*13+case)&255).astype(np.uint32)<<16 | ((y*17+case)&255).astype(np.uint32)<<8 | ((x+y*3)&255).astype(np.uint32)
                if camera_rgby:
                    # Vary RGB spatially while preserving the exact input Y.
                    limit=np.minimum(np.minimum(a,255-a)//8,3).astype(np.int32)
                    delta=np.clip((x*3+y*5)%7-3,-limit,limit)
                    r=a.astype(np.int32)+3*delta;g=a;b=a.astype(np.int32)-8*delta
                    assert np.array_equal((77*r+150*g.astype(np.int32)+29*b+128)>>8,a)
                    rgb=(r.astype(np.uint32)<<16)|(g.astype(np.uint32)<<8)|b.astype(np.uint32)
                raw = (a.astype(np.uint32)<<24)|rgb
                local = (state.astype(np.uint32)<<30)|rgb
                expected = (edge.astype(np.uint32)<<31)|rgb
                name = f'{case}-{med}-{algorithm}'
                for suffix,data in [('input',raw),('class',local),('final',expected)]:
                    (out/f'{name}-{suffix}.hex').write_text(''.join(f'{int(v):08x}\n' for v in data.flat))
                manifest.append(dict(name=name,config=(ratio<<14)|(algorithm<<13)|(med<<11)|threshold,
                                     enqueued=total,highwater=highwater))
    (out/'manifest.json').write_text(json.dumps(manifest,indent=2))
    print(f'Wrote {len(manifest)} vectors, {w}x{h}')


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('--vectors',type=Path)
    p.add_argument('--width',type=int,default=32)
    p.add_argument('--height',type=int,default=24)
    p.add_argument('--camera-rgby',action='store_true')
    args = p.parse_args()
    if args.vectors:
        vectors(args.vectors,args.width,args.height,args.camera_rgby)
    else:
        selftest()
