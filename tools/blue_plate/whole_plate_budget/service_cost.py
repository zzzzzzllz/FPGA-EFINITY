"""Read-only service ledger: frozen integer parameters, actual RTL, existing maps."""
from pathlib import Path
import csv,hashlib,json,math,re
import numpy as np

ROOT=Path(__file__).resolve().parents[3]
DOC=ROOT/'docs/validation/blue-plate/whole-plate-budget'
OUT=ROOT/'tmp/blue-plate-whole-plate-budget/service-cost'
MODEL=ROOT/'tmp/blue-plate-char-segment/quantization-tap2-fork'
sources={}
def read(p):
    p=Path(p);p=p if p.is_absolute() else ROOT/p
    data=p.read_bytes();sources[str(p.relative_to(ROOT))]=hashlib.sha256(data).hexdigest()
    return data
def js(p):return json.loads(read(p))
def ms(n):return n/100000
def align(n):return (n+15)//16*16
def resources(p):
    s=read(p).decode().split('Resource Summary (begin)',1)[1].split('Resource Summary (end)',1)[0]
    return {k:int(v) for k,v in re.findall(r'^(EFX_\w+)\s*:\s*(\d+)',s,re.M)}


def main():
    OUT.mkdir(parents=True,exist_ok=True)
    freeze=js(MODEL/'delivery-freeze.json')['artifacts']
    config=js(MODEL/'integer-config.json');read(MODEL/'integer-parameters.npz')
    for p in ('integer-config.json','integer-parameters.npz'):
        key=str((MODEL/p).relative_to(ROOT)).replace('\\','/')
        assert sources[str((MODEL/p).relative_to(ROOT))]==freeze[key]
    params=np.load(MODEL/'integer-parameters.npz')
    costs=js(DOC/'costs.json');full=js(DOC/'full-lprnet-sharing.json')
    detector=js(DOC/'detector-sharing.json');dw=js(DOC/'depthwise-schedule.json')
    color=js(DOC/'color-cnn-sharing.json');lane=js(DOC/'lane16-comparison.json')['summary']['8']
    deployment=js('tmp/blue-plate-char-segment/integer-deployment-audit/report.json')['cost']
    rq=js(DOC/'requant-validation.json')
    for p in ['tools/blue_plate/whole_plate_budget/requant/rtl/q31_psum_mac8.v',
              'tools/blue_plate/whole_plate_budget/partial_sum/rtl/psum_weight_mac8.v']:
        read(p)
    assert sources['tools\\blue_plate\\whole_plate_budget\\requant\\rtl\\q31_psum_mac8.v']==rq['files_sha256']['tools\\blue_plate\\whole_plate_budget\\requant\\rtl\\q31_psum_mac8.v']
    read('docs/validation/blue-plate/char-segment/integer-deployment-addendum.md')
    read('tools/blue_plate/char_segment/integer_lprnet.py');read('tools/blue_plate/char_segment/integer_lprnet_fork.py')
    rows=[];shapes={r['name']:r for r in costs['lprnet']['layers']}
    for stage in config['stages']:
        if stage['kind']!='conv':continue
        name=stage['name'];r=shapes[name];co,h,w=r['output'][1:];positions=h*w;groups=math.ceil(co/8)
        shifts=params[name+'.shift'];assert len(shifts)==co and np.all((shifts>=1)&(shifts<=62))
        assert list(params[name+'.weight'].shape)==stage['shape']
        outputs=co*positions;group_jobs=groups*positions;k=stage['mac_terms'];chunks=math.ceil(k/2048)
        spatial=12 if name==config['fork']['stage'] else 16;tiles=math.ceil(positions/spatial)
        weighted_shifts=int(shifts.sum())*positions
        weight_bytes=tiles*groups*sum(align(min(2048,k-start)*8) for start in range(0,k,2048))
        ci,ih,iw=r['input'][1:];kh,kw=stage['kernel'];ph,pw=stage['padding']
        valid_xy=sum(0<=y+ky-ph<ih and 0<=x+kx-pw<iw for y in range(h) for x in range(w) for ky in range(kh) for kx in range(kw))
        rows.append(dict(name=name,positions=positions,channels=co,K=k,groups=groups,spatial_tile=spatial,
            outputs=outputs,shift_min=int(shifts.min()),shift_max=int(shifts.max()),shift_cycles=weighted_shifts,
            mac_cycles=group_jobs*k,q_internal_cycles=19*outputs+weighted_shifts,q_handshake_cycles=2*outputs,
            save_cycles=9*group_jobs,restore_cycles=17*outputs,bias_load_cycles=group_jobs,
            conv_drain_cycles=group_jobs*chunks,k_split_save_restore_cycles=26*group_jobs*(chunks-1),
            weight_bank_load_cycles=tiles*groups*k,weight_ddr_bytes=weight_bytes,
            input_word_reads=valid_xy*ci*groups,parameter_row_reads=outputs,
            feature_write_bytes=0 if name=='container.0' else h*align(w*co)))
    shifts=params['tap2.trunk.shift'];n=64*792
    rows.append(dict(name='tap2.trunk',positions=792,channels=64,K=0,groups=0,spatial_tile=12,
        outputs=n,shift_min=int(shifts.min()),shift_max=int(shifts.max()),shift_cycles=int(shifts.sum())*792,
        mac_cycles=0,q_internal_cycles=19*n+int(shifts.sum())*792,q_handshake_cycles=2*n,
        save_cycles=0,restore_cycles=0,bias_load_cycles=0,conv_drain_cycles=0,k_split_save_restore_cycles=0,
        weight_bank_load_cycles=0,weight_ddr_bytes=0,input_word_reads=0,parameter_row_reads=n,feature_write_bytes=n))
    fields=['outputs','shift_cycles','mac_cycles','q_internal_cycles','q_handshake_cycles','save_cycles','restore_cycles',
            'bias_load_cycles','conv_drain_cycles','k_split_save_restore_cycles','weight_bank_load_cycles',
            'weight_ddr_bytes','input_word_reads','parameter_row_reads','feature_write_bytes']
    totals={k:sum(r[k] for r in rows) for k in fields}
    assert totals['mac_cycles']==deployment['full_original_order_lane_cycles']==18189792
    assert totals['weight_ddr_bytes']==deployment['total_weight_reads_with_fork_bytes']==9561760
    assert totals['outputs']==1376576 and totals['shift_cycles']==63771888
    cycle_fields=fields[2:11];core=sum(totals[k] for k in cycle_fields)
    # The documented baseline restores each valid original lane; fork reuses the scalar.
    lpr=dict(totals=totals,serial_core_cycles=core,serial_core_ms=ms(core),
        scope='Exact zero-stall counts for the documented serial schedule at assumed 100MHz, not measured whole-network latency.',
        first_lane_restore_elision_sensitivity_cycles=17*sum(r['positions']*r['groups'] for r in rows))
    pools=[r for r in costs['lprnet']['layers'] if r['type']=='MaxPool3d']
    pool_outputs=sum(math.prod(r['output']) for r in pools)
    context=[]
    for i,t in config['taps'].items():
        c=shapes[t['stage']]['output'][1];n=c*4*18;area=t['area'];vmax=255*area
        context.append(dict(branch=int(i),outputs=n,window_area=area,window_reads_two_pass=2*n*area,
            window_adds_two_pass=2*n*(area-1),energy_squares=n,energy_reduction_adds=n-1,
            gain_divisions=1,gain_numerator_bits=(t['constant_q30']*n).bit_length(),
            energy_max_bits=(n*vmax*vmax).bit_length(),normalization_wide_products=n,
            gain_7bit_partial_products_if_fixed_8_limbs=8*n))
    assert sum(r['window_adds_two_pass'] for r in context)==deployment['context_two_pass_window_additions']
    nonconv=dict(maxpool_outputs=pool_outputs,maxpool_scalar_reads=9*pool_outputs,maxpool_comparisons=8*pool_outputs,
        context=context,projection_requant_outputs=4896,height_center_subtractions=4896,height_sum_additions=3672,
        status='Operation counts exact; no RTL cycle schedule for pool/energy/gain/division/height/CTC. Do not add one operation as one clock.')
    others={}
    for name,schedule in [('detector',detector['convolutions']),('color',color['schedule'])]:
        channels='output_channels' if name=='detector' else 'channels'
        count=sum(r['positions']*r[channels] for r in schedule)
        groups=sum(r['positions']*math.ceil(r[channels]/8) for r in schedule)
        others[name]=dict(conv_or_gemm_outputs=count,group_jobs=groups,mac_cycles=lane[name]['mac_steps'],
            weight_ddr_bytes=lane[name]['weight_reads'],metadata_ddr_bytes=lane[name]['metadata_reads'],
            conditional_q_cycles_shift_1=count*22,conditional_q_cycles_shift_62=count*83,
            conditional_save_restore_cycles=groups*9+count*17,
            status='MAC/shape counts exact for existing graph schedule; no frozen detector/color Q31 parameters. 22..83 is only a conditional per-output Q31 transaction envelope, not a validated quantized implementation.')
    lower=core+sum(v['mac_cycles'] for v in others.values())
    input_extra=2*totals['input_word_reads']+sum(lane[n]['serial_hit_mac_actions']-lane[n]['mac_steps'] for n in others)
    service=dict(one_roi_known_serial_cycles=lower,one_roi_known_serial_ms=ms(lower),
        excludes='detector/color requantization and nonlinear ops; LPR nonconv; cache lookup/data stages; DDR waits, resizing, geometry, NMS, confidence, publication.',
        serial_cache_hit_extra_cycles=input_extra,serial_cache_hit_scenario_ms=ms(lower+input_extra),
        cache_scope='Two serial tag/data actions per LPR valid input word; existing detector/color all-hit schedules. Conditional architecture scenario, not universal hardware lower bound.')
    service['conditional_all_outputs_use_Q31_ms_range']=[ms(lower+sum(v[k]+v['conditional_save_restore_cycles'] for v in others.values())) for k in ('conditional_q_cycles_shift_1','conditional_q_cycles_shift_62')]
    # No-retry payload scenario, not measured misses or wall-time upper bound.
    context_reads=sum(r['window_reads_two_pass'] for r in context)
    lpr_writes=totals['feature_write_bytes']+sum(r['output'][2]*align(r['output'][3]*r['output'][1]) for r in pools)+37184
    lpr_reads=16*(totals['input_word_reads']+9*pool_outputs+context_reads)
    lpr_payload=lpr_reads+lpr_writes+totals['weight_ddr_bytes']+full['memory']['metadata_storage']+576
    detector_payload=detector['traffic']['schedule_with_read_misses_and_contiguous_writes']-detector['traffic']['tile16_weight_read_bytes']+others['detector']['weight_ddr_bytes']
    color_payload=color['traffic']['read_ceiling_plus_contiguous_writes']
    traffic=dict(lpr=dict(mac_input_word_requests=totals['input_word_reads'],maxpool_scalar_reads=9*pool_outputs,
        context_scalar_reads=context_reads,contiguous_feature_writes=lpr_writes,weight_reads=totals['weight_ddr_bytes'],
        parameter_ddr_reads=full['memory']['metadata_storage']+576,all_scalar_input_miss_payload=lpr_payload),
        detector_payload_scenario=detector_payload,color_payload_scenario=color_payload,
        three_model_payload_scenario=lpr_payload+detector_payload+color_payload,
        raw_private_copy_read_plus_write=1280*720*3*2,detector_input_write=320*320*3,
        calibrated_rgb_roi_write=224*64*3,lpr_input_write=24*94*3,color_input_write=96*96*3,
        geometry_neighbor_sample_requests=224*64*4,nms=detector['nms'],
        base_video_bytes_per_second=497664000,nominal_bus_bytes_per_second=1600000000,
        hypothetical_residual_nominal_bytes_per_second=1600000000-497664000,
        guaranteed_inference_bandwidth=None,finite_worst_case_latency=None,
        scope='Payload-only no-retry scenario, 16B per scalar miss and contiguous writes; excludes descriptors, LUT/CTC/NMS/ROI and bus overhead. It is neither measured typical traffic nor a guaranteed end-to-end upper bound.')
    traffic['payload_time_ms_at_hypothetical_residual']=traffic['three_model_payload_scenario']/traffic['hypothetical_residual_nominal_bytes_per_second']*1000
    traffic['weight_reads_three_models']=totals['weight_ddr_bytes']+sum(v['weight_ddr_bytes'] for v in others.values())
    traffic['metadata_reads_three_models']=full['memory']['metadata_storage']+576+sum(v['metadata_ddr_bytes'] for v in others.values())
    reports={'reader':'docs/validation/blue-plate/frame-reader/evidence/frame_reader.map.rpt',
       'geometry_color':'tmp/blue-plate-geometry/color-output/synthesis/out/perspective_quad.map.rpt',
       'display':'docs/validation/blue-plate/plate-display/plate_display.map.rpt',
       'shared_q31':'tmp/blue-plate-whole-plate-budget/requant/synthesis/out/q31_psum_mac8.map.rpt'}
    maps={n:resources(p) for n,p in reports.items()}
    video_place=read('docs/validation/blue-plate/video-base/evidence/live-place.rpt').decode()
    base_xlr=int(re.search(r'XLRs:\s*(\d+)\s*/',video_place)[1]);assert base_xlr==24090
    comb=sum(r['EFX_LUT4']+r['EFX_ADD']+r.get('EFX_SRL8',0) for r in maps.values());ff=sum(r['EFX_FF'] for r in maps.values())
    envelopes={'ideal_cross_module_ff_pack':base_xlr+max(comb,ff),
        'ideal_module_local_ff_pack':base_xlr+sum(max(r['EFX_LUT4']+r['EFX_ADD']+r.get('EFX_SRL8',0),r['EFX_FF']) for r in maps.values()),
        'no_ff_pack':base_xlr+comb+ff}
    resource=dict(budget=dict(XLR=49248,RAM10=204,physical_DSP=128),video_placed_XLR=base_xlr,maps=maps,
        added_comb_slots=comb,added_FF=ff,conditional_XLR=envelopes,remaining_XLR={k:49248-v for k,v in envelopes.items()},
        mapped_RAM10=106+sum(r.get('EFX_RAM10',0) for r in maps.values()),external_gray_allocation=14,
        engine_target_RAM10=51,engine_mapped_RAM10=18,engine_unmapped_RAM10=33,full_target_RAM10=196,
        full_target_DSP=85+sum(r.get('EFX_DSP48',0)+r.get('EFX_DSP24',0) for r in maps.values()),
        scope='Packing envelope for unchanged mapped primitives outside the already placed video base. Not PNR bounds; excludes unmapped engine/control/integration logic. Do not add old MAC/bank/psum again.')
    assert resource['mapped_RAM10']==149 and resource['full_target_DSP']==97
    confirm=read('tools/blue_plate/plate_display/plate_confirm.v').decode();ttl=int(re.search(r'parameter TTL_MS=(\d+)',confirm)[1]);assert ttl==500
    read('tools/blue_plate/plate_display/plate_display_state.v')
    log=read('tmp/blue-plate-normal-g1/mature-detector/display-service-time/run.log').decode();assert 'PASS 10 service-time scenarios' in log
    read('tools/blue_plate/tests/tb_display_service_time.sv');read('coding/edge-quality-30fps/rtl/frame_store_dma.v')
    reader=js('docs/validation/blue-plate/frame-reader/evidence/handoff.json')
    read('tmp/blue-plate-char-segment/quantization-research/cmsis-nn-support.h')
    read('tmp/blue-plate-char-segment/quantization-research/tflite-quantization-util.cc')
    improvement=dict(candidate='Replace serial SHIFT loop with one bounded-latency full-width arithmetic shift + guard/sticky RNE stage; retain all other stages and exact arithmetic.',
        conditional_saved_cycles=totals['shift_cycles']-totals['outputs'],
        lpr_serial_core_ms_if_one_cycle_RNE=ms(core-totals['shift_cycles']+totals['outputs']),
        one_roi_known_ms_if_one_cycle_RNE=ms(lower-totals['shift_cycles']+totals['outputs']),
        status='Comparison only; no implementation/map/timing claim. Extra barrel-shift/reduction LUTs unknown; CMSIS rounding mode is not copied. Even this isolated ideal change does not meet TTL.')
    result=dict(lpr=lpr,layers=rows,other_models=others,nonconv=nonconv,service=service,traffic=traffic,resources=resource,
        memory=dict(arena_bytes=deployment['arena_bytes'],arena_capacity=8*1024*1024,
        arena_remaining=8*1024*1024-deployment['arena_bytes'],context_A8_bytes=deployment['extra_context_ddr_bytes']),
        display=dict(TTL_ms=ttl,required_observations=3,steady_condition='L < 500 and L + P < 500, plus ordered/config/legal/same-box packets',
        serial_condition='L=P implies L<250 ms (strict)',current_q31_only_ms=ms(totals['q_internal_cycles']),
        current_result='Fails freshness even before other work: LPR Q31 internal time alone exceeds 500ms.',
        existing_probe_verified=True,full_scan_test_cycles=reader['full_scan_cycles'],front_end_scope='Existing injected-stall scan fixture, not hardware or a lower bound; not added to the core lower subtotal.'),
        improvement=improvement,source_sha256=sources,source_unchanged=True)
    for p,h in sources.items():assert hashlib.sha256((ROOT/p).read_bytes()).hexdigest()==h,p
    for folder in (OUT,DOC):
        (folder/'service-cost.json').write_text(json.dumps(result,indent=2)+'\n')
        with (folder/'service-cost-layers.csv').open('w',newline='') as f:
            writer=csv.DictWriter(f,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)
    print(json.dumps({k:result[k] for k in ('service','resources','improvement')},indent=2))


if __name__=='__main__':main()
