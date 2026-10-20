"""Read-only frozen-network K-tile and working-bank study; no inference or RTL builds."""
from pathlib import Path
import csv,hashlib,json,math
import numpy as np

ROOT=Path(__file__).resolve().parents[3]
DOC=ROOT/'docs/validation/blue-plate/whole-plate-budget'
OUT=ROOT/'tmp/blue-plate-whole-plate-budget/ram-tiles'
sources={}


def read(p):
    p=Path(p);p=p if p.is_absolute() else ROOT/p
    b=p.read_bytes();sources[str(p.relative_to(ROOT))]=hashlib.sha256(b).hexdigest();return b


def js(p):return json.loads(read(p))
def align(n):return (n+15)//16*16
def chunks(k,depth):return [min(depth,k-i) for i in range(0,k,depth)]


def main():
    OUT.mkdir(parents=True,exist_ok=True)
    research=js(OUT/'research/sources.json')
    for r in research['sources']:
        b=read(OUT/'research'/r['path'])
        assert hashlib.sha1(b'blob '+str(len(b)).encode()+b'\0'+b).hexdigest()==r['git_blob_sha']
    service=js(DOC/'service-cost.json');scalar=js(DOC/'scalar-read-validation.json')
    proof=js('tmp/blue-plate-whole-plate-budget/requant-static/proof-and-schedule.json')
    config=js('tmp/blue-plate-char-segment/quantization-tap2-fork/integer-config.json')
    parameters=ROOT/'tmp/blue-plate-char-segment/quantization-tap2-fork/integer-parameters.npz';read(parameters)
    params=np.load(parameters)
    stages={s['name']:s for s in config['stages'] if s['kind']=='conv'}
    layers=[r for r in service['layers'] if r['K']]
    detailed=[];totals={};rng=np.random.default_rng(20261019);checks=[]
    for depth in (2048,512,256):
        rows=[]
        for r in layers:
            name=r['name'];k=r['K'];n=r['positions'];groups=r['groups'];tile=r['spatial_tile'];tiles=math.ceil(n/tile)
            split=chunks(k,depth);jobs=n*groups;transitions=jobs*(len(split)-1)
            row=dict(depth=depth,name=name,K=k,positions=n,groups=groups,spatial_tile=tile,K_chunks=split,
                     MAC_cycles=jobs*k,weight_bank_write_cycles=tiles*groups*k,
                     weight_payload_bytes=tiles*groups*sum(align(c*8) for c in split),
                     logical_weight_blocks=tiles*groups*len(split),
                     size_only_burst_lower_bound_32beat=tiles*groups*sum(math.ceil(c*8/512) for c in split),
                     size_only_burst_lower_bound_256beat=tiles*groups*sum(math.ceil(c*8/4096) for c in split),
                     activation_scalar_requests=r['input_word_reads'],
                     intermediate_save_restore_pairs=transitions,partial_sum_word_actions=transitions*16,
                     partial_sum_internal_bytes=transitions*64,partial_sum_DDR_bytes=0,
                     extra_vs_2048_boundary_cycles=27*jobs*(len(split)-math.ceil(k/2048)),
                     final_Q_scratch_collides=split[-1]>depth-2,
                     primary_convolution_outputs=r['outputs'])
            rows.append(row);detailed.append(row)
        fields=('MAC_cycles','weight_bank_write_cycles','weight_payload_bytes','logical_weight_blocks','size_only_burst_lower_bound_32beat',
                'size_only_burst_lower_bound_256beat','activation_scalar_requests','intermediate_save_restore_pairs','partial_sum_word_actions',
                'partial_sum_internal_bytes','partial_sum_DDR_bytes','extra_vs_2048_boundary_cycles','primary_convolution_outputs')
        total={f:sum(r[f] for r in rows) for f in fields}
        total.update(weight_RAM_target=16 if depth==2048 else 4,psum_RAM=2,
                     known_core_cycles=scalar['service']['new_lpr_core_cycles']+total['extra_vs_2048_boundary_cycles'],
                     Q_scratch_addresses=[depth-2,depth-1],
                     conflicting_layers=[r['name'] for r in rows if r['final_Q_scratch_collides']])
        total['known_core_ms']=total['known_core_cycles']/100000
        total['remaining_500ms_source_age_ms']=500-total['known_core_ms']
        totals[str(depth)]=total
        assert total['MAC_cycles']==18189792 and total['weight_payload_bytes']==9561760 and total['activation_scalar_requests']==18034656
    assert totals['512']['extra_vs_2048_boundary_cycles']==104976
    assert totals['256']['extra_vs_2048_boundary_cycles']==227448
    assert not totals['512']['conflicting_layers']
    # Preserve each lane's exact K order using frozen weights and synthetic int8 input only.
    for r in layers:
        k=r['K'];name=r['name'];co=stages[name]['shape'][0]
        positions=r['spatial_tile'];a=rng.integers(-128,128,(positions,k),dtype=np.int64)
        w=params[name+'.weight'].reshape(co,k).astype(np.int64)
        for first in sorted({0,(math.ceil(co/8)-1)*8}):
            valid=min(8,co-first);seed=params[name+'.bias'][first:first+valid].astype(np.int64)
            products=a[:,:,None]*w[first:first+valid].T[None,:,:]
            full=products.cumsum(axis=1)+seed
            assert full.min()>=-(1<<31) and full.max()<(1<<31)
            for depth in (512,256):
                partial=np.broadcast_to(seed,(positions,valid)).copy();offset=0
                for count in chunks(k,depth):
                    partial+=products[:,offset:offset+count].sum(axis=1);offset+=count
                    assert np.array_equal(partial,full[:,offset-1,:])
                assert np.array_equal(partial,full[:,-1,:])
                checks.append(dict(layer=name,depth=depth,first_channel=first,positions=positions,lanes=valid,
                                   checkpoints=len(chunks(k,depth)),exact_outputs=partial.size))
    source_paths=['tools/blue_plate/whole_plate_budget/weight_bank/rtl/weight_bank8.v',
                  'tools/blue_plate/whole_plate_budget/weight_bank/rtl/weight_mac8.v',
                  'tools/blue_plate/whole_plate_budget/scalar_read/rtl/psum_scalar_mac8.v',
                  'tools/blue_plate/whole_plate_budget/scalar_read/rtl/q31_scalar_mac8.v',
                  'tools/blue_plate/whole_plate_budget/student_schedule.py',
                  'tools/blue_plate/whole_plate_budget/full_lprnet_sharing.py',
                  'tools/blue_plate/frame_reader/rtl/frame_reader.v',
                  'tmp/blue-plate-frame-reader/synthesis/out/frame_reader.map.v',
                  'tools/blue_plate/ocr_input/rtl/geometry_ocr_input.v',
                  'tools/blue_plate/char_segment/integer_lprnet.py',
                  'tools/blue_plate/char_segment/integer_lprnet_fork.py',
                  'tools/blue_plate/char_segment/ctc_interval.py',
                  'docs/validation/blue-plate/char-segment/ctc-q30-plan.md']
    for p in source_paths:read(p)
    lut=js('tmp/blue-plate-char-segment/ctc-q30/lut.json')
    assert len(lut['lower'])==71 and lut['fraction_bits']==30
    banks=dict(weights=4,partial_sum=2,parameters=4,shared_IO=7,tags=1,CTC=2,resize=1,control_reserve=1)
    fused=dict(weights=4,partial_sum_parameters_CTC=2,shared_IO=7,tags=1,resize=1,control_reserve=1)
    assert sum(banks.values())==22 and sum(fused.values())==16
    # Explicit disjoint words: 16 spatial positions * 8 lanes, plus ten 3-word parameter records.
    work_words=dict(psum=list(range(128)),parameters=list(range(128,158)))
    assert len(set().union(*(set(v) for v in work_words.values())))==158
    ctc_words=dict(exp=71,dp_previous_current_bounds=60,emission_bounds_all_classes=136,column_maxima=18,target=7)
    assert sum(ctc_words.values())==292<=512
    metadata_payload=metadata_records=0
    for r in layers:
        block_bytes=records=0
        for first in range(0,r['channels'],8):
            count=min(8,r['channels']-first)
            block_bytes+=align(first*9%16+count*9);records+=count
            if r['name']=='backbone.11.block.6':
                block_bytes+=align((first//4)*9%16+2*9);records+=2
        tiles=math.ceil(r['positions']/r['spatial_tile'])
        metadata_payload+=tiles*block_bytes;metadata_records+=tiles*records
    assert metadata_payload==943904 and metadata_records==91848
    head=4*align(18*68);logits=18*align(68*2)
    spill=dict(head_A8_bytes=head,logits_int16_bytes=logits,contiguous_extra_payload=head*2+logits*3,
               scalar_read_miss_extra_payload=(4*68*18+2*68*18)*16+head+logits,
               CTC_LUT_load_bytes=align(71*4),context_A8_existing_bytes=37184,
               complete_DDR_service_ms=None)
    physical_base=188+2+9
    scenarios=dict(weight512_with_existing_modules=dict(RAM=213,deficit=9),
                   corrected_22bank_separate_reader=dict(RAM=physical_base+7+22,deficit=physical_base+7+22-204),
                   corrected_22bank_shared_reader=dict(RAM=physical_base+22,deficit=physical_base+22-204),
                   fused_16bank_shared_reader=dict(RAM=physical_base+16,deficit=physical_base+16-204))
    frozen_counts={}
    for name in ('requant-static','scalar-read','font-compact'):
        d=js(ROOT/f'tmp/blue-plate-whole-plate-budget/{name}/delivery-freeze.json')['files_sha256']
        for p,h in d.items():
            p=Path(p);p=p if p.is_absolute() else ROOT/p
            assert hashlib.sha256(p.read_bytes()).hexdigest()==h,p
        frozen_counts[name]=len(d)
    result=dict(status='Research and software arithmetic/address checks only; no new RTL or map',
                recommended_depth=512,totals=totals,layers=detailed,split_checks=checks,
                Q31_counts_unchanged=dict(total_outputs=1376576,constant=proof['constant_outputs'],dynamic=proof['dynamic_outputs'],
                                         primary_scalar_reads=scalar['service']['dynamic_primary_outputs']),
                corrected_bank_plan=banks,fused_conditional_bank_plan=fused,work_word_ranges=work_words,
                later_CTC_words=ctc_words,DDR_spill_scenarios=spill,resource_scenarios=scenarios,
                fused_parameter_cost=dict(group_metadata_payload=metadata_payload,extra_vs_layer_resident=metadata_payload-14784,
                                          parameter_records=metadata_records,word32_local_load_writes=metadata_records*3,
                                          scope='Each spatial tile/output group loads its records; 9-byte records in aligned per-layer arrays, fork rows separate; no retention across tiles'),
                integrated_XLR=None,finite_WCET=None,locator_cost=None,
                research=research,prior_frozen_file_counts=frozen_counts,source_sha256=sources.copy())
    result['sources_unchanged']=all(hashlib.sha256((ROOT/p).read_bytes()).hexdigest()==h for p,h in sources.items())
    assert result['sources_unchanged']
    with (DOC/'ram-tile-layers.csv').open('w',newline='',encoding='utf-8') as f:
        writer=csv.DictWriter(f,fieldnames=list(detailed[0]));writer.writeheader();writer.writerows(detailed)
    for folder in (DOC,OUT):(folder/'ram-tile-audit.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(dict(totals=totals,scenarios=scenarios,spill=spill,checked_outputs=sum(c['exact_outputs'] for c in checks),
                         frozen=frozen_counts),indent=2))


if __name__=='__main__':main()
