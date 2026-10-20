"""C8-native memory schedule audit; synthetic bytes, no trained weights or RTL.

Execute existing layer geometry through a scalar-address DDR cache model and
compare integer convolution/pooling against PyTorch. Quantization below is a
test fixture, not an exported model. Context projection is checked in float64.
"""
from pathlib import Path
import hashlib
import importlib.util
import json
import math
import numpy as np
import torch
import torch.nn.functional as F

ROOT = Path(__file__).resolve().parents[3]
SOURCE = ROOT/'tools/blue_plate/char_segment/lprnet_cost.py'
OUT = ROOT/'tmp/blue-plate-whole-plate-budget'
DOC = ROOT/'docs/validation/blue-plate/whole-plate-budget'


def aligned(n):
    return (n+15)//16*16


class Memory:
    """Two 64KiB DDR slots, and one 512x128 RAM split into two halves.

    All actions are sequential: tag read, optional fill, data read; output
    read/modify/write; flush after row. Thus no same-address RAM collision.
    Seven 512x20 banks hold data; one 512x16 RAM holds tags and validity.
    """
    def __init__(self):
        self.ddr = bytearray(131072)
        self.data = bytearray(8192)
        self.tags = [-1]*256
        self.active = None
        self.counts = dict(reads=0,misses=0,read_bytes=0,write_bytes=0,
                           output_rmw_beats=0,row_clear_beats=0,max_write_row=0)
        self.rows = []

    def descriptor(self,slot,c,h,w):
        pitch=aligned(c*w)
        assert h*pitch<=65536
        return dict(base=slot*65536,c=c,h=h,w=w,pitch=pitch,size=h*pitch)

    def begin(self,d):
        self.active=d
        self.tags=[-1]*256
        self.start=self.counts.copy()

    def address(self,y,x,c):
        d=self.active
        assert 0<=y<d['h'] and 0<=x<d['w'] and 0<=c<d['c']
        return d['base']+y*d['pitch']+x*d['c']+c

    def get(self,y,x,c):
        address=self.address(y,x,c)
        beat=address//16;index=beat%256;tag=beat//256
        assert 0<=tag<32  # Entire private arena is 128 KiB.
        self.counts['reads']+=1
        if self.tags[index]!=tag:
            start=beat*16
            d=self.active
            assert d['base']<=start and start+16<=d['base']+d['size']
            self.data[index*16:index*16+16]=self.ddr[start:start+16]
            self.tags[index]=tag
            self.counts['misses']+=1
            self.counts['read_bytes']+=16
        return self.data[index*16+address%16]

    def row(self,d,y,values):
        assert d['base']!=self.active['base']
        flat=values.astype(np.uint8).tobytes()
        assert len(flat)==d['w']*d['c'] and d['pitch']<=4096
        # Data RAM write half is addresses 256..511; read half is 0..255.
        self.data[4096:4096+d['pitch']]=bytes(d['pitch'])
        self.data[4096:4096+len(flat)]=flat
        for x in range(d['w']):
            for c in range(0,d['c'],8):
                start=x*d['c']+c
                last=start+min(8,d['c']-c)-1
                self.counts['output_rmw_beats']+=2*(last//16-start//16+1)
        self.counts['row_clear_beats']+=d['pitch']//16
        self.counts['max_write_row']=max(self.counts['max_write_row'],d['pitch'])
        start=d['base']+y*d['pitch']
        assert start+d['pitch']<=d['base']+d['size']
        self.ddr[start:start+d['pitch']]=self.data[4096:4096+d['pitch']]
        self.counts['write_bytes']+=d['pitch']

    def finish(self,name,src,dst=None):
        self.rows.append(dict(name=name,input=src,output=dst,
             counts={k:self.counts[k]-self.start[k] for k in self.start if k!='max_write_row'},
             barrier='All output writes complete before next consumer; invalidate read tags on begin'))


def nchw(x):
    return torch.from_numpy(x.transpose(2,0,1).copy()).double()[None]


def run():
    torch.set_num_threads(1);torch.manual_seed(701)
    tracked=[SOURCE,ROOT/'docs/validation/blue-plate/char-segment/lightweight-model-contract.md',
             ROOT/'docs/validation/blue-plate/char-segment/lprnet-cost.json']
    hashes={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in tracked}
    spec=importlib.util.spec_from_file_location('existing_student',SOURCE)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    net=module.Candidate(8,native=True).eval()
    original=module.profile(net,torch.randn(1,1,48,160))
    assert original['conv_macs']==3980560 and original['trainable_parameters']==13736
    rng=np.random.default_rng(701)
    memory=Memory();x=rng.integers(0,256,(48,160,1),dtype=np.uint8)
    current=memory.descriptor(0,1,48,160)
    memory.ddr[:7680]=x.tobytes()
    contexts=[];checks=[];lifetimes=[];conv_cycles=0;pool_comparisons=0
    weights=rng.integers(-2,3,(66,122),dtype=np.int64)
    container_weights=weights.copy()
    container_bias=rng.integers(-100,100,66).astype(np.float64)
    projected=np.repeat(container_bias[:,None],35,axis=1)
    projection_events=[];context_offset=0
    context_specs={2:((11,22),(11,4)),6:((5,20),(5,4)),13:((4,9),(2,2)),22:None}

    def context(tap):
        nonlocal current,x,context_offset
        memory.begin(current)
        c=current['c'];h,w=4,35
        f=np.zeros((h,w,c),dtype=np.uint8)
        spec=context_specs[tap]
        kh,kw=spec[0] if spec else (1,1)
        sy,sx=spec[1] if spec else (1,1)
        for oy in range(h):
            for ox in range(w):
                for ch in range(c):
                    total=sum(memory.get(oy*sy+ky,ox*sx+kx,ch) for ky in range(kh) for kx in range(kw))
                    f[oy,ox,ch]=(total+(kh*kw)//2)//(kh*kw)
        gold=F.avg_pool2d(nchw(x),(kh,kw),(sy,sx)) if spec else nchw(x)
        # Positive half-up average is a fixture, not the future QAT rounding contract.
        expected=torch.floor(gold+0.5).numpy()[0].transpose(1,2,0).astype(np.uint8)
        assert np.array_equal(f,expected)
        height=f.astype(np.uint16).sum(0,dtype=np.uint16)
        energy=int(np.square(f.astype(np.uint64)).sum())
        assert int(height.max())<=1020 and energy<=c*140*255**2
        assert height.nbytes<=4620
        # Reuse the same five 512x16 banks for every branch's height sums.
        height_store=bytearray(512*2*5)
        height_store[:height.nbytes]=height.tobytes()
        restored=np.frombuffer(height_store,dtype=np.uint16,count=height.size).reshape(height.shape)
        assert np.array_equal(restored,height)
        contribution=container_weights[:,context_offset:context_offset+c]@restored.T.astype(np.int64)
        assert np.abs(contribution).max()<2**31
        # Address proof for a serialized read/modify/write of ten 512x16 banks.
        # This does not certify quantized gain arithmetic or final integer bounds.
        for t in range(35):
            for cls in range(66):
                address=(t*66+cls)*4
                assert address+4<=512*4*5
        energy_mean=max(energy/f.size,1e-6)
        projected[:]+=contribution/(4*energy_mean)
        projection_events.append(dict(tap=tap,height_elements=height.size,logit_updates=2310,
             max_height_address_exclusive=height.nbytes,max_logit_address_exclusive=9240,
             next_action='release height-sum buffer before next backbone operation'))
        context_offset+=c
        contexts.append(dict(tap=tap,channels=c,pooled_bytes=f.size,height_sum_bytes=height.nbytes,
                             square_sum=energy,height=height,f=f))
        memory.finish('context_'+str(tap),current)
        lifetimes.append(dict(producer='backbone.'+str(tap),buffer=current['base'],
                              context_consumed='immediately before the next backbone operation',
                              retained_after_context='height sums until this branch projection; scalar energy',
                              full_tap_retained=False))

    for record in original['layers']:
        name=record['name']
        if name=='container':
            continue
        layer=net.get_submodule(name)
        memory.begin(current);src=current
        out_c,oh,ow=record['output'][1:]
        dest=memory.descriptor(1-src['base']//65536,out_c,oh,ow)
        out=np.zeros((oh,ow,out_c),dtype=np.uint8)
        if isinstance(layer,torch.nn.Conv2d):
            kh,kw=layer.kernel_size;py,px=layer.padding
            weights=rng.integers(-2,3,(out_c,src['c'],kh,kw),dtype=np.int64)
            biases=rng.integers(-255,256,out_c,dtype=np.int64)
            for oy in range(oh):
                for ox in range(ow):
                    for first in range(0,out_c,8):
                        last=min(first+8,out_c)
                        acc=biases[first:last].copy()
                        for ky in range(kh):
                            for kx in range(kw):
                                iy,ix=oy+ky-py,ox+kx-px
                                for ch in range(src['c']):
                                    conv_cycles+=1
                                    if 0<=iy<src['h'] and 0<=ix<src['w']:
                                        a=memory.get(iy,ix,ch)
                                        acc+=a*weights[first:last,ch,ky,kx]
                        assert np.abs(acc).max()<2**31
                        out[oy,ox,first:last]=np.clip((acc+16)>>5,0,255)
                memory.row(dest,oy,out[oy])
            gold=F.conv2d(nchw(x),torch.from_numpy(weights).double(),torch.from_numpy(biases).double(),padding=(py,px))
            expected=torch.clamp(torch.floor((gold+16)/32),0,255).numpy()[0].transpose(1,2,0).astype(np.uint8)
        else:
            assert isinstance(layer,module.ChannelSpatialPool)
            sy,sx=layer.ss
            for oy in range(oh):
                for ox in range(ow):
                    for ch in range(out_c):
                        out[oy,ox,ch]=max(memory.get(oy*sy+ky,ox*sx+kx,ch*layer.cs) for ky in range(3) for kx in range(3))
                        pool_comparisons+=8
                memory.row(dest,oy,out[oy])
            expected=layer(nchw(x)).numpy()[0].transpose(1,2,0).astype(np.uint8)
        assert np.array_equal(out,expected),name
        checks.append(dict(layer=name,exact_uint8_elements=out.size))
        memory.finish(name,src,dest)
        x=out;current=dest
        tap={'backbone.0':2,'backbone.4.ops.6':6,'backbone.11.ops.6':13,'backbone.20':22}.get(name)
        if tap is not None:context(tap)

    # Check only the linear reordering, not an integer reciprocal approximation.
    full=[]
    branch_cycles=0
    for ctx in contexts:
        f=ctx['f'].astype(np.float64);energy=max(float(np.square(f).mean()),1e-6)
        full.append(f/energy);c=ctx['channels']
        branch_cycles+=35*math.ceil(66/8)*c
    merged=np.concatenate(full,axis=2)
    gold=np.einsum('oc,hwc->ohw',container_weights,merged).mean(1)+container_bias[:,None]
    error=float(np.abs(gold-projected).max());assert error<1e-10
    assert conv_cycles+branch_cycles==453362
    # Explicit ownership/port trace for the shared RAM: no simultaneous actions.
    phases=[{'phase':'input tag','read':'tag[index]','write':None},
            {'phase':'miss fill','read':None,'write':'data[index] then tag[index]'},
            {'phase':'input sample','read':'data[index]','write':None},
            {'phase':'output RMW read','read':'data[256+row_word]','write':None},
            {'phase':'output RMW write','read':None,'write':'data[256+row_word]'},
            {'phase':'row flush','read':'data[256+row_word]','write':None}]
    resources={'weights':16,'bias_multiplier_shift_72bit':4,'shared_128bit_io':7,
               'cache_tags':1,'height_sum_uint16':5,'logits_int32':10,
               'ctc_lut_target':2,'resize_target':1,'control_target':1}
    serial_actions={'tag_and_data_reads':2*memory.counts['reads'],
        'cache_data_and_tag_fills':2*memory.counts['misses'],
        'output_rmw':memory.counts['output_rmw_beats'],'output_clear':memory.counts['row_clear_beats'],
        'mac_steps':conv_cycles+branch_cycles,'maxpool_compares':pool_comparisons,
        'average_pool_adds':1120*241+2240*99+4480*35,
        'context_squares':17080,'context_sum_adds':17080-4,
        'context_height_adds':17080*3//4,'logit_read_write':4*2310*2}
    # Float memory and Python arrays are the independent oracle, not hardware storage.
    result=dict(candidate='Candidate(8,native=True)',source_sha256=hashes,
        descriptors={'scratch_offset_A':[0,65536],'scratch_offset_B':[65536,131072],
                     'scope':'Relative offsets only; DDR physical base must be reserved disjoint from video slots'},
        resources=resources,allocated_RAM10=sum(resources.values()),
        optional_work_margin_RAM10=4,allocated_with_work_margin_RAM10=sum(resources.values())+4,
        retained_with_gray_RAM10=145,total_with_gray_and_margin_RAM10=145+sum(resources.values())+4,
        scope='Memory/address scheduling proof on synthetic bytes; no trained quantization, reciprocal, RTL, Fmax, XLR or AXI timing proof',
        activation_fixture='uint8; integer weights [-2,2]; bias [-255,255]; positive half-up shift 5 then ReLU/clamp; BN assumed folded',
        quantized_model_equivalence=False,arithmetic_checks=checks,context_checks=[{k:v for k,v in c.items() if k not in ('f','height')} for c in contexts],
        context_projection_float64_error=error,mac_schedule_cycles=conv_cycles+branch_cycles,
        serial_action_scenario=serial_actions,
        serial_action_scenario_ms_100MHz=sum(serial_actions.values())/100000,
        timing_scope='One cycle per listed serial action scenario; excludes DDR stalls, cache request control, pool division, energy reciprocal, gain multiplication, CTC and resize; not RTL timing',
        pool_comparisons=pool_comparisons,traffic=memory.counts,operations=memory.rows,
        tap_lifetimes=lifetimes,context_projection_events=projection_events,port_phases=phases,
        caveat='Context heights/projected values are consumed branch-by-branch in hardware; Python retains oracle copies only.')
    assert all(hashlib.sha256((ROOT/p).read_bytes()).hexdigest()==h for p,h in hashes.items())
    result['source_unchanged']=True
    for directory in (OUT,DOC):
        directory.mkdir(parents=True,exist_ok=True)
        (directory/'student-schedule.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf8')
    print(json.dumps({k:v for k,v in result.items() if k not in ('operations','arithmetic_checks','source_sha256','port_phases','tap_lifetimes')},indent=2))


if __name__=='__main__':run()
