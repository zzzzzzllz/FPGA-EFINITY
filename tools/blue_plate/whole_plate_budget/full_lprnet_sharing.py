"""Read-only full pretrained LPRNet audit for the existing shared 8-lane budget.

Checks float64 branch reordering, buffer lifetimes and a synthetic K-split sum.
Does not quantize weights, export a model, read images or implement RTL.
"""
from pathlib import Path
import hashlib,importlib.util,json,math
import numpy as np
import torch
import torch.nn.functional as F

ROOT=Path(__file__).resolve().parents[3]
OUT=ROOT/'tmp/blue-plate-whole-plate-budget'
DOC=ROOT/'docs/validation/blue-plate/whole-plate-budget'
SOURCE=ROOT/'tmp/blue-plate-review/mature-research/lprnet/model/LPRNet.py'
WEIGHTS=SOURCE.parents[1]/'weights/Final_LPRNet_model.pth'


def align(n):return (n+15)//16*16


def main():
    torch.set_num_threads(1);torch.manual_seed(719)
    paths=[SOURCE,WEIGHTS,DOC/'costs.json',DOC/'detector-sharing.json',
           ROOT/'docs/design/blue-plate-color-candidate.md',Path('D:/Efinity/sim_models/verilog/efx_dsp48.v')]
    hashes={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    assert hashes[str(SOURCE)]=='94a49696268ff942d92d58285ddeacab9b2ef35a4102bd73862518729e0dfc14'
    assert hashes[str(WEIGHTS)]=='d1ca22ca7a251a90702a166c8ad8ce7f05acb39f5ef8055139a33d462716d1ad'
    spec=importlib.util.spec_from_file_location('full_pretrained_lprnet',SOURCE)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    net=module.build_lprnet(7,False,68,0)
    net.load_state_dict(torch.load(WEIGHTS,map_location='cpu',weights_only=True));net=net.double().eval()
    original=json.loads((DOC/'costs.json').read_text())['lprnet']
    conv=[];lives=[];pool_checks=[];seen=[]
    slots=[0,262144];current={'base':0,'size':24*align(94*3)}
    peak=0
    for r in original['layers']:
        name=r['name']
        if name=='container.0':continue
        cin,ih,iw=r['input'][1:];co,oh,ow=r['output'][1:]
        assert current['size']==ih*align(iw*cin)
        dest={'base':slots[1-slots.index(current['base'])],'size':oh*align(ow*co)}
        assert dest['size']<=262144 and current['size']<=262144
        assert min(16,oh*ow)*co<=4096
        peak=max(peak,current['size']+dest['size'])
        lives.append(dict(name=name,input=current.copy(),output=dest.copy(),
             phase='Complete producer and its context projection before next main operation'))
        current=dest
        if r['type']=='Conv2d':
            assert co<=512  # Four 512x20 banks carry 72-bit per-output metadata.
            groups=math.ceil(co/8);k=r['K'];s=oh*ow
            chunks=[min(2048,k-start) for start in range(0,k,2048)]
            assert sum(chunks)==k and max(chunks)*8<=16384
            assert net.get_submodule(name).weight.numel()==r['weights']
            conv.append(dict(name=name,input=r['input'][1:],output=r['output'][1:],K=k,
                output_groups=groups,tail_lanes=(8-co%8)%8,K_chunks=chunks,
                largest_weight_chunk_bytes=max(chunks)*8,
                cache_words=max(chunks),macs=r['macs'],mac_steps=s*groups*k,
                weight_storage=groups*sum(align(chunk*8) for chunk in chunks),
                weight_read_bytes=math.ceil(s/16)*groups*sum(align(chunk*8) for chunk in chunks),
                partial_sum_transition_words=2*s*groups*8*(len(chunks)-1),
                bias_scale_shift_storage=align(co*9),output_elements=co*s))
    assert len(conv)==15 and max(r['K'] for r in conv)==3328
    contexts=[];max_error=0.;min_energy=float('inf')
    # Existing trained weights only. Batch=1 preserves source global mean semantics.
    for trial in range(2):
        x=torch.randn(1,3,24,94,dtype=torch.float64)
        with torch.inference_mode():
            gold=net(x);z=x;offset=0
            projected=net.container[0].bias[None,:,None].expand(1,68,18).clone()
            for i,layer in enumerate(net.backbone):
                before=z;z=layer(z)
                if isinstance(layer,torch.nn.MaxPool3d):
                    equivalent=F.max_pool2d(before[:,::layer.stride[0]],(3,3),layer.stride[1:])
                    assert torch.equal(z,equivalent)
                    if trial==0:pool_checks.append(dict(layer=i,channel_stride=layer.stride[0],shape=list(z.shape)))
                if i not in (2,6,13,22):continue
                kernel=(5,5) if i in (2,6) else ((4,10) if i==13 else (1,1))
                stride=(5,5) if i in (2,6) else ((4,2) if i==13 else (1,1))
                f=F.avg_pool2d(z,kernel,stride) if i!=22 else z
                energy=f.square().mean();assert torch.isfinite(energy) and energy>0
                min_energy=min(min_energy,float(energy))
                c=f.shape[1];weight=net.container[0].weight[:,offset:offset+c]
                projected+=F.conv2d(f.mean(2,keepdim=True),weight,bias=None).squeeze(2)/energy
                offset+=c
                if trial==0:
                    window=math.prod(kernel);m=f.numel()
                    contexts.append(dict(tap=i,channels=c,pooled_shape=list(f.shape),
                        window=window,height_entries=c*18,height_uint16_bytes=c*18*2,
                        height_uint16_RAM=math.ceil(c*18/512),
                        max_uint8_window_sum=255*window,max_uint8_height_window_sum=4*255*window,
                        max_uint8_window_square_sum=m*(255*window)**2,
                        max_weight127_projection_sum=c*4*255*window*127,
                        projection_mac_steps=18*9*c,
                        weight_read_bytes=2*9*align(c*8),weight_storage=9*align(c*8),
                        consume='pool, energy and height sum; project and release before next tap',
                        float32_height_RAM=2*math.ceil(c*18/512)))
            assert offset==516 and torch.isfinite(projected).all()
            error=float((gold-projected).abs().max());max_error=max(max_error,error);assert error<1e-9
    # Unscaled arithmetic fixture for the sole oversized K; not model quantization.
    rng=np.random.default_rng(719);split_checks=[]
    for positions in (16,8):
        for lanes in (8,4):
            a=rng.integers(-255,256,(positions,3328),dtype=np.int64)
            w=rng.integers(-127,128,(lanes,3328),dtype=np.int64)
            bias=rng.integers(-65536,65536,lanes,dtype=np.int64)
            gold=a@w.T+bias
            accum=np.repeat(bias[None],positions,axis=0)
            ps=bytearray(512*4)
            for start,end in ((0,2048),(2048,3328)):
                bank=np.zeros((4,2048),dtype=np.uint16)
                padded=np.zeros((8,end-start),dtype=np.int64);padded[:lanes]=w[:,start:end]
                for pair in range(4):
                    bank[pair,:end-start]=(padded[2*pair]&255)|((padded[2*pair+1]&255)<<8)
                restored=np.zeros_like(padded)
                restored[::2]=bank[:,:end-start]&255;restored[1::2]=bank[:,:end-start]>>8
                restored[restored>=128]-=256
                assert np.array_equal(restored,padded)
                if start:
                    accum=np.frombuffer(ps,dtype=np.int32,count=positions*8).reshape(positions,8)[:,:lanes].astype(np.int64)
                accum+=a[:,start:end]@restored[:lanes].T
                assert np.abs(accum).max()<2**31
                if end<3328:
                    stored=np.zeros((positions,8),dtype=np.int32);stored[:,:lanes]=accum
                    assert stored.nbytes<=512
                    ps[:stored.nbytes]=stored.tobytes()
            assert np.array_equal(accum,gold)
            split_checks.append(dict(spatial_positions=positions,valid_lanes=lanes,
                                     chunks=[2048,1280],exact_outputs=gold.size,psum_bytes=positions*8*4))
    metadata=sum(r['bias_scale_shift_storage'] for r in conv)+align(68*9)
    storage=sum(r['weight_storage'] for r in conv)+sum(r['weight_storage'] for r in contexts)
    steps=sum(r['mac_steps'] for r in conv)+sum(r['projection_mac_steps'] for r in contexts)
    weight_reads=sum(r['weight_read_bytes'] for r in conv)+sum(r['weight_read_bytes'] for r in contexts)
    ownership={'weights':list(range(16)),'parameters':list(range(16,20)),
        'io':list(range(20,27)),'tags':[27],'partial_sum':[28,29],
        'spare':[30,31],'height':list(range(32,41)),'logits':list(range(41,47)),
        'tables':[47,48],'resize':[49],'control':[50]}
    assert sorted(b for v in ownership.values() for b in v)==list(range(51))
    assert max(c['max_uint8_height_window_sum'] for c in contexts)<2**16
    assert max(c['max_weight127_projection_sum'] for c in contexts)<2**31
    detector=json.loads((DOC/'detector-sharing.json').read_text())
    new_ddr=detector['arena']['all_with_constants_descriptors_weights_rawcopy_bytes']-16384+storage+metadata
    assert new_ddr<=8*1024*1024
    pool_taps=sum(math.prod(r['output'])*9 for r in original['layers'] if r['type']=='MaxPool3d')
    context_taps=sum(math.prod(c['pooled_shape'])*c['window'] for c in contexts)
    backbone_taps=sum(r['mac_steps'] for r in conv)
    writes=sum(r['output']['size'] for r in lives)
    result=dict(source_sha256=hashes,source_unchanged=all(hashlib.sha256(p.read_bytes()).hexdigest()==hashes[str(p)] for p in paths),
        scope='Existing pretrained float64 random-input algebra check plus unscaled K-split arithmetic fixture; no image evaluation, quantization, export, RTL or synthesis',
        shape=[1,3,24,94],output=[1,68,18],layers=conv,contexts=contexts,lifetimes=lives,
        pool_channel_decimation_checks=pool_checks,float64_trials=2,float64_reorder_max_error=max_error,
        minimum_observed_energy=min_energy,K_split_checks=split_checks,phase_bank_ownership=ownership,
        memory=dict(shared_RAM=51,partial_sum_RAM_from_existing_spare=2,remaining_work_spare=2,
            height_RAM=9,logit_RAM=6,max_feature_bytes=max(max(r['input']['size'],r['output']['size']) for r in lives),
            live_feature_peak_bytes=peak,feature_slots=[{'base':0,'capacity':262144},{'base':262144,'capacity':262144}],
            padded_int8_weight_storage=storage,metadata_storage=metadata,
            full_shared_ddr_reservation=new_ddr,
            width_scope='Capacity analysis assumes W8/A8 backbone, uint16 window-height sums, int32 partial sums/logits; not a validated quantized model'),
        timing=dict(original_model_macs=144411264,height_commuted_macs=144411264-2526336*3//4,
            mac_steps=steps,mac_ms_100MHz=steps/100000,
            inter_chunk_psum_word_actions=sum(r['partial_sum_transition_words'] for r in conv),
            serial_backbone_requant_outputs=sum(r['output_elements'] for r in conv),
            weight_read_bytes=weight_reads,metadata_read_bytes=metadata,
            source_pool_compare_count=original['serial_nonconv']['maxpool_comparisons'],
            source_context_average_adds=original['serial_nonconv']['context_average_additions'],
            detector_plus_one_mac_ms=229.776+steps/100000,
            detector_plus_two_mac_ms=229.776+2*steps/100000,
            scope='Only MAC issue loops; cache, metadata, scalar normalization, quantization, CTC, DMA and geometry not included'),
        traffic=dict(backbone_scalar_input_taps=backbone_taps,pool_scalar_input_taps=pool_taps,
            context_scalar_input_taps=context_taps,feature_write_bytes=writes,
            one_16byte_read_per_scalar_contiguous_write_ceiling=(backbone_taps+pool_taps+context_taps)*16+weight_reads+metadata+writes,
            scope='No cache-miss measurement for full LPRNet. Conservative no-retry read-beat ceiling; excludes input resize, descriptors, scalar lookup tables, CTC and external protocol overhead.'),
        color_scope='Read fixed color candidate handoff; native crop versus 224x64 remains main experiment; no 304x101 hardware buffer')
    assert result['source_unchanged']
    for folder in (OUT,DOC):(folder/'full-lprnet-sharing.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf8')
    print(json.dumps({k:v for k,v in result.items() if k not in ('layers','contexts','lifetimes','source_sha256','phase_bank_ownership')},indent=2))


if __name__=='__main__':main()
