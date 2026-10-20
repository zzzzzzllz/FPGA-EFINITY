"""Check eight channel-wise lanes against the actual 19 detector depthwise shapes.

Synthetic integer reference and cache/address trace only. No RTL or new model.
"""
from pathlib import Path
import hashlib,json,math,re
import numpy as np
import torch
import torch.nn.functional as F

ROOT=Path(__file__).resolve().parents[3]
OUT=ROOT/'tmp/blue-plate-whole-plate-budget'
DOC=ROOT/'docs/validation/blue-plate/whole-plate-budget'


class Cache:
    def __init__(self,arena,base,size):
        self.arena=arena;self.base=base;self.size=size
        self.tags=[-1]*256;self.data=bytearray(8192)
        self.reads=self.misses=0
    def read(self,address,n,fetch=True):
        assert self.base<=address and address+n<=self.base+self.size
        assert address//16==(address+n-1)//16
        beat=address//16;index=beat%256;tag=beat//256
        assert tag<2048  # 8MiB arena, 4KiB direct-mapped read cache.
        self.reads+=1
        if self.tags[index]!=tag:
            start=beat*16
            assert self.base<=start and start+16<=self.base+self.size
            self.tags[index]=tag;self.misses+=1
            if fetch:self.data[index*16:index*16+16]=self.arena[start:start+16]
        if fetch:return np.frombuffer(self.data,dtype=np.uint8,count=n,offset=index*16+address%16).astype(np.int64)


def main():
    torch.set_num_threads(1)
    files=[DOC/'detector-sharing.json',ROOT/'tmp/blue-plate-normal-g1/mature-detector/model-costs.json',OUT/'detector320.dot']
    hashes={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in files}
    plan=json.loads(files[0].read_text());graph=json.loads(files[1].read_text())['detector320']['layers']
    dot=files[2].read_text();labels={m[1]:m[2] for m in re.finditer(r'^\s*"([^"]+)" \[label="([^\n]+)" fillcolor',dot,re.M)}
    live={r['name']:r for r in plan['lifetimes']};conv={r['name']:r for r in plan['convolutions']}
    rng=np.random.default_rng(709);arena=bytearray(8*1024*1024);results=[]
    for layer in graph:
        name=layer['name'];pool=layer['type']=='Pooling'
        if not pool and (name not in conv or conv[name]['groups']==1):continue
        _,c,h,w=layer['inputs'][0];_,co,oh,ow=layer['outputs'][0]
        assert c==co and c%8==0
        label=labels[name]
        kh,kw=map(int,re.search(r'kernel_size \(HxW\): (\d+) x (\d+)',label).groups())
        sy,sx=map(int,re.search(r'stride \(HxW\): (\d+) x (\d+)',label).groups())
        py,py1,px,px1=map(int,re.search(r'pad \(HxW\): \((\d+), (\d+)\) x \((\d+), (\d+)\)',label).groups())
        if pool:assert (py,py1,px,px1)==(0,0,0,0),'Only the actual unpadded MaxPool_9 is covered'
        assert (h+py+py1-kh)//sy+1==oh and (w+px+px1-kw)//sx+1==ow
        if not pool:assert layer['blobs'][0]==[c,1,3,3]
        src=live[live[name]['parents'][0]];dst=live[name]
        assert src['size']==c*h*w and dst['size']==c*oh*ow
        assert src['base']+src['size']<=dst['base'] or dst['base']+dst['size']<=src['base']
        x=rng.integers(0,256,(h,w,c),dtype=np.uint8)
        arena[src['base']:src['base']+src['size']]=x.tobytes()
        scalar=Cache(arena,src['base'],src['size'])
        # Previous lane-one schedule: finish all spatial taps for one channel.
        for oy in range(oh):
            for ox in range(ow):
                for ch in range(c):
                    for ky in range(kh):
                        for kx in range(kw):
                            iy,ix=oy*sy+ky-py,ox*sx+kx-px
                            if 0<=iy<h and 0<=ix<w:scalar.read(src['base']+(iy*w+ix)*c+ch,1,False)
        cache=Cache(arena,src['base'],src['size'])
        weights=rng.integers(-127,128,(c,kh,kw),dtype=np.int64)
        bias=rng.integers(-32768,32768,c,dtype=np.int64);zp=int(rng.integers(1,255))
        # Same four 16-bit banks, with depth groups from the existing 16 RAM.
        banks=np.zeros((4,2048),dtype=np.uint16)
        for group in range(c//8):
            for ky in range(kh):
                for kx in range(kw):
                    address=(group*kh+ky)*kw+kx
                    for bank in range(4):
                        a,b=weights[group*8+bank*2:group*8+bank*2+2,ky,kx]
                        banks[bank,address]=(int(a)&255)|((int(b)&255)<<8)
        assert c//8*kh*kw<=2048
        inp=torch.from_numpy(x.transpose(2,0,1).copy()).double()[None]
        if pool:gold=F.max_pool2d(inp,(kh,kw),(sy,sx),(py,px)).numpy()[0].transpose(1,2,0).astype(np.int64)
        else:gold=F.conv2d(inp-zp,torch.from_numpy(weights[:,None]).double(),torch.from_numpy(bias).double(),stride=(sy,sx),padding=(py,px),groups=c).numpy()[0].transpose(1,2,0).astype(np.int64)
        raw=np.zeros((oh,ow,c),dtype=np.int64);steps=padding=0;write_beats=0
        for first in range(0,oh*ow,16):
            count=min(16,oh*ow-first);assert count*c<=4096
            for pos in range(first,first+count):
                oy,ox=divmod(pos,ow)
                for group in range(c//8):
                    ch=group*8
                    acc=np.zeros(8,dtype=np.int64) if pool else bias[ch:ch+8].copy()
                    for ky in range(kh):
                        for kx in range(kw):
                            iy,ix=oy*sy+ky-py,ox*sx+kx-px;steps+=1
                            if 0<=iy<h and 0<=ix<w:
                                address=src['base']+(iy*w+ix)*c+ch
                                assert address%16 in (0,8)
                                value=cache.read(address,8)
                            else:
                                assert not pool,'Actual unpadded pool must never request an out-of-range pixel'
                                padding+=1;value=np.full(8,zp,dtype=np.int64)
                            if pool:acc=value.copy() if ky==0 and kx==0 else np.maximum(acc,value)
                            else:
                                row=(group*kh+ky)*kw+kx
                                word=banks[:,row]
                                weight=np.empty(8,dtype=np.int64)
                                weight[::2]=word&255;weight[1::2]=word>>8
                                weight[weight>=128]-=256
                                assert np.array_equal(weight,weights[ch:ch+8,ky,kx])
                                acc+=(value-zp)*weight
                    assert np.abs(acc).max()<2**31
                    raw[oy,ox,ch:ch+8]=acc
                    result=acc if pool else np.clip(((acc+256)>>9)+128,0,255)
                    address=4096+(pos-first)*c+ch
                    assert 4096<=address and address+8<=8192
                    # Serialized output RMW in upper half; not an extra RAM port.
                    cache.data[address:address+8]=result.astype(np.uint8).tobytes()
            start=dst['base']+first*c;length=count*c
            assert length%16==0 and start+length<=dst['base']+dst['size']
            arena[start:start+length]=cache.data[4096:4096+length];write_beats+=length//16
        assert np.array_equal(raw,gold),name
        if pool:assert padding==0
        quant=gold if pool else np.clip(((gold+256)>>9)+128,0,255)
        stored=np.frombuffer(arena,dtype=np.uint8,count=dst['size'],offset=dst['base']).reshape(oh,ow,c)
        assert np.array_equal(stored,quant)
        results.append(dict(name=name,type='maxpool' if pool else 'depthwise',channels=c,
            input=[c,h,w],output=[c,oh,ow],stride=[sy,sx],padding=[py,py1,px,px1],tail_channels=c%8,
            exact_int32_elements=raw.size if not pool else 0,exact_uint8_elements=stored.size,
            scalar_cache_reads=scalar.reads,scalar_cache_misses=scalar.misses,
            vector_cache_reads=cache.reads,vector_cache_misses=cache.misses,
            vector_read_ddr_bytes=cache.misses*16,output_write_bytes=write_beats*16,
            vector_tap_steps=steps,padding_vectors=padding,
            weight_storage_bytes=0 if pool else c*kh*kw,
            weight_bank_rows=0 if pool else c//8*kh*kw,
            serial_port_and_mac_actions=2*cache.reads+2*cache.misses+steps,
            scalar_pool_compare_actions=(kh*kw-1)*raw.size if pool else 0,
            serial_pool_single_comparator_actions=(2*cache.reads+2*cache.misses+(kh*kw-1)*raw.size) if pool else 0,
            scope='Cache read actions exclude queue wait; output scalar requantization/RMW and metadata add time'))
    dw=[r for r in results if r['type']=='depthwise'];assert len(dw)==19
    pool=[r for r in results if r['type']=='maxpool'];assert len(pool)==1
    old_dw=sum(conv[r['name']]['broadcast_cycles'] for r in dw)
    new_dw=sum(r['vector_tap_steps'] for r in dw)
    new_total=plan['compute']['broadcast8_cycles']-old_dw+new_dw
    old_dw_weight_reads=sum(conv[r['name']]['weight_reads'] for r in dw)
    stats={k:sum(r[k] for r in dw) for k in ('exact_int32_elements','exact_uint8_elements','scalar_cache_reads','scalar_cache_misses','vector_cache_reads','vector_cache_misses','vector_read_ddr_bytes','output_write_bytes','weight_storage_bytes','serial_port_and_mac_actions')}
    result=dict(source_sha256=hashes,layers=results,depthwise_totals=stats,
        old_depthwise_mac_steps=old_dw,new_depthwise_mac_steps=new_dw,
        whole_detector_mac_schedule_cycles=new_total,whole_detector_mac_ms_100MHz=new_total/100000,
        old_repeated_depthwise_weight_reads=old_dw_weight_reads,
        new_resident_depthwise_weight_reads=sum(r['weight_storage_bytes'] for r in dw),
        revised_all_conv_weight_reads=plan['traffic']['tile16_weight_read_bytes']-old_dw_weight_reads+sum(r['weight_storage_bytes'] for r in dw),
        fixed_8DSP=True,extra_RAM10_for_vector_inputs=0,
        timing_scope='MAC issue and cache action counts; not RTL latency or quantized-network throughput',
        source_unchanged=all(hashlib.sha256((ROOT/p).read_bytes()).hexdigest()==h for p,h in hashes.items()))
    assert result['source_unchanged']
    for directory in (OUT,DOC):(directory/'depthwise-schedule.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf8')
    print(json.dumps({k:v for k,v in result.items() if k not in ('layers','source_sha256')},indent=2))


if __name__=='__main__':main()
