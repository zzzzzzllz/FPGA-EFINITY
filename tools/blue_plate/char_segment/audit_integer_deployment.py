"""Read-only deployment arithmetic/cost checks; no CTC replacement or network RTL."""
from fractions import Fraction
import math

import numpy as np
import torch

from experiment import ROOT, read_json, write_json, sha
from integer_lprnet_fork import ForkLPR, FORK
from fixed_lprnet import STRICT_THRESHOLD

MODEL = ROOT/'tmp/blue-plate-char-segment/quantization-tap2-fork'
VAL = ROOT/'tmp/blue-plate-char-segment/quantization-fork-validation'
OUT = ROOT/'tmp/blue-plate-char-segment/integer-deployment-audit'


def wide_multiply(a, m):
    assert -(1 << 31) <= a < 1 << 31 and 0 <= m < 1 << 31
    limbs_a = (a & 65535, a >> 16)
    pieces = [(x, (m >> (7*j)) & 127, 16*i+7*j) for i,x in enumerate(limbs_a) for j in range(5)]
    result = 0
    # Each batch starts with a load of zero; current MAC registers are intentionally overwritten.
    for start in (0, 8):
        lanes = [0]*8
        for lane, (x, y, shift) in enumerate(pieces[start:start+8]):
            assert -(1 << 16) <= x < 1 << 16 and 0 <= y <= 127
            lanes[lane] += x*y
            assert -(1 << 31) <= lanes[lane] < 1 << 31
            result += lanes[lane] << shift
            assert -(1 << 63) <= result < 1 << 63
    return result


def main():
    if OUT.exists():
        raise FileExistsError(f'Preserve audit: {OUT}')
    OUT.mkdir()
    torch.set_num_threads(4)
    model_freeze = read_json(MODEL/'delivery-freeze.json')['artifacts']
    validation_freeze = read_json(VAL/'frozen.json')['artifacts']
    assert all(sha(ROOT/n) == h for n,h in model_freeze.items())
    assert all(sha(VAL/n) == h for n,h in validation_freeze.items())
    config = read_json(MODEL/'integer-config.json')
    arrays = dict(np.load(MODEL/'integer-parameters.npz'))
    image = np.load(ROOT/'tmp/blue-plate-char-segment/pretrained-new-rois/q8_bgr-inputs.npz')['bgr'][0]
    logits, trace, _, fork = ForkLPR(config, arrays)(image, capture_vectors=True)
    head_input = trace['concat'][0].numpy()[0].transpose(1,2,0).reshape(72,516).astype(np.int64)
    head_weight = arrays['container.0.weight'].reshape(68,516).astype(np.int64)
    head_acc = head_input@head_weight.T+arrays['container.0.bias']
    expected = np.empty((72,68), np.int8)
    for c in range(68):
        m, shift = int(arrays['container.0.multiplier'][c]), int(arrays['container.0.shift'][c])
        expected[:,c] = [max(-128,min(127,round(Fraction(int(v)*m,1 << shift))+63)) for v in head_acc[:,c]]
    expected = expected.reshape(4,18,68).transpose(2,0,1)[None]
    assert np.array_equal(expected, trace['container.0'][0].numpy())
    assert np.array_equal((expected.astype(np.int64)-63).sum(axis=2),logits.numpy())
    rng = np.random.default_rng(701)
    cases = [(a,m) for a in [-(1<<31),-(1<<31)+1,-65536,-1,0,65535,(1<<31)-1]
             for m in [0,1,127,128,65535,1<<30,(1<<31)-1]]
    cases += [(int(a),int(m)) for a,m in zip(rng.integers(-(1<<31),1<<31,1000),rng.integers(0,1<<31,1000))]
    assert all(wide_multiply(a,m)==a*m for a,m in cases)
    vectors, records = {}, []
    for name, x, weight, positions, groups in [
        (FORK, fork['input'][0].transpose(1,2,0).reshape(792,64), arrays[FORK+'.weight'].reshape(256,64), [0,791], [0,248]),
        ('container.0', head_input, head_weight, [0,71], [0,64])]:
        for pos in positions:
            for group in groups:
                index=len(records); k=x.shape[1]; count=min(8,weight.shape[0]-group)
                activation=np.repeat(x[pos,:,None],8,axis=1).astype(np.int32)
                weights=np.zeros((k,8),np.int8); weights[:,:count]=weight[group:group+count].T
                mask=np.array([1]*count+[0]*(8-count),np.uint8)
                seed=np.zeros(8,np.int64);seed[:count]=arrays[name+'.bias'][group:group+count]
                partial=seed.copy(); history=[]
                for a,w in zip(activation,weights):
                    partial += a.astype(np.int64)*w.astype(np.int64)*mask
                    assert np.all(np.abs(partial)<1<<31)
                    history.append(partial.copy())
                target=seed[:count]+weight[group:group+count].astype(np.int64)@x[pos].astype(np.int64)
                assert np.array_equal(target,partial[:count])
                prefix=f'v{index:02d}.'
                for key,value in dict(activation=activation,weight=weights,lane_mask=mask,seed=seed.astype(np.int32),
                                      psum_after=np.array(history,np.int32)).items():vectors[prefix+key]=value
                records.append(dict(index=index,layer=name,position=pos,first_output_channel=group,
                    k=k,cycles=k,active_output_lanes=count,original_int32_saved_bytes=32,
                    trunk_lanes=[0,4] if name==FORK else []))
    np.savez_compressed(OUT/'output-channel-mac-vectors.npz',**vectors)
    write_json(OUT/'output-channel-mac-vectors.json',dict(source_roi=0,semantics='one K term per cycle; 8 independent output-channel sums; input broadcast',records=records))
    # Preserve four A8 context branches in DDR, with the existing 16-byte row alignment.
    regions=[]; end=0
    for i,c in enumerate((64,128,256,68)):
        pitch=(18*c+15)//16*16; size=4*pitch
        data=trace[f'context.{i}.normalized'][0].numpy()[0].transpose(1,2,0)
        store=np.zeros((4,pitch),np.int8);store[:,:18*c]=data.reshape(4,-1)
        assert np.array_equal(store[:,:18*c].reshape(4,18,c),data)
        regions.append(dict(branch=i,channels=c,offset=end,row_pitch=pitch,bytes=size));end+=size
    assert end==37184 and 7015168+end<8*1024*1024
    head_mac=72*68*516; old_head_mac=18*68*516
    head_cycles=72*9*516; old_head_cycles=18*9*516
    cost=dict(original_order_head_macs=head_mac,height_swapped_head_macs=old_head_mac,
        extra_head_macs=head_mac-old_head_mac,original_order_head_lane_cycles=head_cycles,
        extra_head_lane_cycles=head_cycles-old_head_cycles,full_original_order_macs=144411264,
        full_original_order_lane_cycles=18189792,mac_only_ms_at_100mhz=181.89792,
        head_requantizations=4896,old_height_swapped_requantizations=1224,
        context_regions=regions,extra_context_ddr_bytes=end,arena_bytes=7015168+end,
        head_weight_reads_bytes=5*9*516*8,head_extra_weight_reads_bytes=(5-2)*9*516*8,
        total_weight_reads_with_fork_bytes=9188160+262144+(5-2)*9*516*8,
        context_two_pass_window_additions=2*1050624,ram_banks=51,
        saved_accumulator_slot_bytes=32,saved_accumulator_bank_reuse='existing 2 RAM partial-sum bank; after all K segments complete',
        head_centered_height_sum_bytes=2448,head_output_block_bytes=16*68,head_full_int32_ddr_buffer_bytes=0,
        hardware_map_pass=False,full_integer_confidence_pass=False)
    # Independent frozen validation selection/count, without another network inference.
    roi=read_json(VAL/'roi-records.json');frames=read_json(VAL/'frame-records.json')
    for mode in ['ocr_only','combined']:
        count=dict(correct=0,wrong=0,rejected=0,total=84)
        for frame in frames:
            legal=[r for r in roi if r['sample_index']==frame['sample_index'] and r['legal'] and (mode=='ocr_only' or r['combined_pass'])]
            legal.sort(key=lambda r:(-r['score'],r['roi_index']))
            best=legal[0] if legal else None
            accepted=best is not None and best['score']>=STRICT_THRESHOLD
            code=best['code'] if accepted else None
            status='rejected' if code is None else 'correct' if code==frame['label'] else 'wrong'
            assert code==frame['methods'][mode+'_strict']['code']
            count[status]+=1
        assert count==read_json(VAL/'results.json')['summary'][mode+'_strict']
    margins=[abs(r['score']**7-STRICT_THRESHOLD**7) for r in roi if r['legal']]
    result=dict(cost=cost,checks=dict(full_head_numpy_fraction_outputs=4896,height_sum_exact=True,
        signed32_times_q31_cases=len(cases),wide_product_uses_signed17_by_signed8=True,
        output_channel_vectors=len(records),output_channel_cycles=sum(r['cycles'] for r in records),
        context_ddr_regions_roundtrip=True,validation_selection_independently_recounted=True),
        confidence_proposal=dict(fraction_bits=30,tail_start=math.ceil(30*math.log(2)/config['logit_scale']),
            probability_threshold=STRICT_THRESHOLD**7,validation_min_probability_threshold_distance=min(margins),
            evaluated=False),
        source_hashes={str(p.relative_to(ROOT)).replace('\\','/'):sha(p) for p in [
            ROOT/'tools/blue_plate/whole_plate_budget/mac8/rtl/mac8.v',
            ROOT/'tools/blue_plate/whole_plate_budget/partial_sum/rtl/psum_weight_mac8.v',
            ROOT/'tmp/blue-plate-char-segment/fit-gate/research/LossCTC.cu',
            ROOT/'tmp/blue-plate-char-segment/integer-deployment-research/tflite-softmax.h']})
    assert all(sha(ROOT/n)==h for n,h in model_freeze.items())
    assert all(sha(VAL/n)==h for n,h in validation_freeze.items())
    write_json(OUT/'report.json',result)
    print(result)


if __name__=='__main__':main()
