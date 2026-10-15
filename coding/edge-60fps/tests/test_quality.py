"""Independent array reference and RTL comparison; no FPGA connection."""
import argparse
import json
from pathlib import Path
import subprocess
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
WORK = ROOT.parents[1] / 'tmp/tests/edge-60fps/test-work'
REPORT = WORK.parent/'reports'
REPORT.mkdir(parents=True, exist_ok=True)
WORK.mkdir(parents=True, exist_ok=True)
GAINS = np.array([704, 512, 758], dtype=np.int64)

def pair_demosaic(raw, phase, average):
    h, w = raw.shape
    out = np.zeros((h, w, 3), dtype=np.int64)
    out[0] = raw[0, :, None]
    for y in range(1, h):
        tile = raw[y-1:y+1].reshape(2, w//2, 2)
        samples = {}
        for dy in range(2):
            for dx in range(2):
                code = ((((y-1+dy) % 2)*2+dx) ^ phase)
                samples[code] = tile[dy, :, dx]
        out[y, :, 0] = np.repeat(samples[3], 2)
        out[y, :, 2] = np.repeat(samples[0], 2)
        if average:
            out[y, :, 1] = np.repeat((samples[1]+samples[2])//2, 2)
        else:
            code = ((y % 2)*2 + np.arange(w) % 2) ^ phase
            out[y, :, 1] = np.where((code == 1) | (code == 2), raw[y], raw[y-1])
    return out

def demosaic(raw, phase, average=True):
    # Independent masked convolution: channel kernels from Colour Science.
    h,w=raw.shape
    yy,xx=np.indices(raw.shape)
    code=((yy%2)*2+xx%2)^phase
    kernels=[np.array([[1,2,1],[2,4,2],[1,2,1]]),
             np.array([[0,1,0],[1,4,1],[0,1,0]]),
             np.array([[1,2,1],[2,4,2],[1,2,1]])]
    masks=[code==3,(code==1)|(code==2),code==0]
    result=[]
    for mask,kernel in zip(masks,kernels):
        padded=np.pad(raw*mask,1,mode='reflect')
        total=sum(int(kernel[y,x])*padded[y:y+h,x:x+w] for y in range(3) for x in range(3))
        channel=(total+2)//4
        assert np.array_equal(channel[mask],raw[mask]), 'Measured CFA samples must survive'
        result.append(channel)
    return np.stack(result,axis=-1)

def area(rgb):
    rgb = rgb.copy()
    # Integrate the source footprint [0,1.5], [1.5,3] on each axis.
    vertical = np.stack(((2*rgb[0::3]+rgb[1::3]+1)//3,
                         (rgb[1::3]+2*rgb[2::3]+1)//3), axis=1)
    vertical = vertical.reshape(-1, rgb.shape[1], 3)
    horizontal = np.stack(((2*vertical[:,0::3]+vertical[:,1::3]+1)//3,
                           (vertical[:,1::3]+2*vertical[:,2::3]+1)//3), axis=2)
    return horizontal.reshape(vertical.shape[0], -1, 3)

def gain(rgb):
    return np.minimum(255, rgb*GAINS//1024)

def old_output(raw, phase):
    rgb = gain(pair_demosaic(raw, phase, False))
    ys = np.arange(raw.shape[0]*2//3)*3//2
    xs = np.arange(raw.shape[1]*2//3)*3//2
    return rgb[ys[:,None], xs]

def write_hex(path, data, width):
    with path.open('w', encoding='ascii') as out:
        out.writelines(f'{int(value):0{width}x}\n' for value in data.ravel())

def vectors(w, h, phase, detail=False):
    rng = np.random.default_rng(601013+phase)
    raw = rng.integers(0, 1024, (h, w), dtype=np.int64)
    raw[:h//3] //= 4
    if detail:
        yy,xx=np.indices((h,w))
        raw=100+4*xx+2*yy
        # Diagonal thin bars below the ramp exercise odd/even pixel locations.
        raw[h//2:]=np.where((xx[h//2:]+yy[h//2:])%7==0,700,80)
    # The second frame is black: stale line RAM and FIFO contents must not leak.
    return [raw, np.zeros_like(raw)]

def run_case(sim, w, h, phase, burst, chain=False, detail=False):
    raw_frames = vectors(w, h, phase, detail)
    outputs = [gain(area(demosaic(raw, phase, True))) for raw in raw_frames]
    raw = np.concatenate(raw_frames).reshape(-1, 4)
    write_hex(WORK/'raw.hex', (raw << np.arange(0,40,10)).sum(axis=1), 10)
    rgb = np.concatenate(outputs)
    write_hex(WORK/'expected.hex', (rgb[:,:,0]<<16)+(rgb[:,:,1]<<8)+rgb[:,:,2], 8)
    sums = np.array([demosaic(raw, phase, True).sum(axis=(0,1)) for raw in raw_frames])
    write_hex(WORK/'stats.hex', sums, 8)
    line = 1449 if w==1920 else 220
    budget = 1666667 if w==1920 else 6000
    flags = [f'-Ptb_quality.{key}={value}' for key,value in
             dict(W=w,H=h,PHASE=phase,BURST=burst,LINE_CYCLES=line,FRAME_CYCLES=budget).items()]
    sources = ['tests/tb_quality.v','rtl/raw_demosaic4.v','rtl/raw_1080_to_720.v',
               'rtl/frame_buffer_V4/DC_FIFO.v','rtl/frame_buffer_V4/vid_par2ser.v']
    top='tb_quality_chain' if chain else 'tb_quality'
    if chain:
        # Leave the top's unused camera instance unbound. Feed its actual
        # adapter from one tested camera instance, avoiding duplicate work.
        renamed=(ROOT/'rtl/raw_1080_to_720.v').read_text().replace('module raw_full_view ', 'module quality_input ',1)
        (WORK/'quality_input.v').write_text(renamed,encoding='utf-8')
        sources[2]=str(WORK/'quality_input.v')
        sources += ['tests/tb_quality_chain.v','rtl/ti60f225_oob_top.v',
                    'rtl/rgb_to_gray.v','rtl/sobel_pair.v']
        flags += ['-i','-Irtl','-DQUALITY_DUT=quality_input']
    executable=WORK/(top+'.vvp')
    subprocess.run([str(sim/'iverilog.exe'),'-g2012','-s',top,*flags,
                    '-o',str(executable),*sources],cwd=ROOT,check=True)
    log = REPORT/('sim-top-chain-final.log' if chain else f'sim-{w}x{h}-p{phase}-b{burst}{"-detail" if detail else ""}.log')
    log.parent.mkdir(exist_ok=True)
    command=[str(sim/'vvp.exe'),'-i',str(executable)]
    with log.open('w',encoding='utf-8') as output:
        process=subprocess.Popen(command,cwd=WORK.parent,text=True,stdout=subprocess.PIPE,stderr=subprocess.STDOUT)
        for line in process.stdout:
            print(line,end='',flush=True)
            output.write(line)
            output.flush()
        if process.wait():
            raise subprocess.CalledProcessError(process.returncode,command)
    return str(log)

def noise_comparison():
    h,w=540,960
    y,x=np.indices((h,w))
    code=(y%2)*2+x%2
    level=np.choose(code,[238,352,352,256])
    noise=np.random.default_rng(60).normal(0,20,(h,w)).round().astype(np.int64)
    raw=np.clip(level+noise,0,1023)
    old=old_output(raw,0)[4:-4,4:-4]
    new=gain(area(demosaic(raw,0,True)))[4:-4,4:-4]
    old_std=old.std(axis=(0,1));new_std=new.std(axis=(0,1))
    result={'type':'synthetic flat RAW10 field with independent Gaussian noise, sigma=20 DN',
            'old_rgb_std_8bit':old_std.tolist(),'new_rgb_std_8bit':new_std.tolist(),
            'std_reduction_percent':((1-new_std/old_std)*100).tolist(),
            'old_rgb_mean':old.mean(axis=(0,1)).tolist(),'new_rgb_mean':new.mean(axis=(0,1)).tolist()}
    assert np.max(np.abs(new.mean(axis=(0,1))-old.mean(axis=(0,1))))<1
    return result

def detail_regression():
    y,x=np.indices((48,96))
    raw=100+4*x+2*y
    evidence=[]
    for phase in range(4):
        new=demosaic(raw,phase)
        old=pair_demosaic(raw,phase,True)
        assert np.array_equal(new[2:-2,2:-2],np.repeat(raw[2:-2,2:-2,None],3,axis=2))
        old_duplicates=np.mean(np.all(old[2:-2,2:-2:2]==old[2:-2,3:-2:2],axis=-1))
        new_duplicates=np.mean(np.all(new[2:-2,2:-2:2]==new[2:-2,3:-2:2],axis=-1))
        assert old_duplicates==1 and new_duplicates==0
        evidence.append({'phase':phase,'pair_repeat_fraction_before':float(old_duplicates),
                         'pair_repeat_fraction_after':float(new_duplicates)})
    return evidence

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--full',action='store_true')
    parser.add_argument('--exposure',action='store_true',help='Sensor ROM and startup readback test')
    parser.add_argument('--detail',action='store_true',help='RTL ramp and diagonal thin-line regression')
    parser.add_argument('--chain',action='store_true',help='Full-size test through the actual gray/Sobel top adapter')
    parser.add_argument('--sim-bin',type=Path,default=ROOT.parents[1]/'tools/iverilog-12/app/bin')
    args=parser.parse_args()
    if args.exposure:
        executable=WORK/'exposure.vvp'
        sources=['tests/tb_exposure.v','rtl/cam_i2c_ctrl/i2c/i2c_master_reg_rom.v',
                 'rtl/cam_i2c_ctrl/i2c/i2c_master_ctrl_top.v',
                 'rtl/cam_i2c_ctrl/i2c/i2c_master_reg_set.v']
        subprocess.run([str(args.sim_bin/'iverilog.exe'),'-g2012','-i','-s','tb_exposure',
                        '-o',str(executable),*sources],cwd=ROOT,check=True)
        output=subprocess.check_output([str(args.sim_bin/'vvp.exe'),str(executable)],cwd=ROOT,text=True)
        (REPORT/'exposure-simulation.log').write_text(output,encoding='utf-8')
        print(output,end='')
        raise SystemExit(0)
    logs=[]
    if args.chain:
        logs.append(run_case(args.sim_bin,1920,1080,0,1,chain=True))
    elif args.full:
        for burst in (0,1):logs.append(run_case(args.sim_bin,1920,1080,0,burst))
    else:
        for phase in range(4):
            for burst in (0,1):logs.append(run_case(args.sim_bin,48,18,phase,burst,detail=args.detail))
    result={'detail_regression':detail_regression(),'simulation_logs':logs,'synthetic_noise_comparison':noise_comparison(),
            'hardware_tested':False}
    target=REPORT/('verification-chain.json' if args.chain else 'verification-full.json' if args.full else 'verification-detail.json' if args.detail else 'verification-small.json')
    target.write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(result,indent=2),flush=True)
