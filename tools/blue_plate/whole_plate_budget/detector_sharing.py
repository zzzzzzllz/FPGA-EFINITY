"""Read actual detector graph; audit shared storage lifetimes and traffic bounds.

No training, real-image inference, quantization export, RTL or synthesis.
The INT8 backbone / INT32 decoded-head widths below are explicit assumptions.
"""
from collections import Counter,defaultdict
from pathlib import Path
import hashlib,json,math,re
import cv2
import numpy as np

ROOT=Path(__file__).resolve().parents[3]
OUT=ROOT/'tmp/blue-plate-whole-plate-budget'
DOC=ROOT/'docs/validation/blue-plate/whole-plate-budget'
MODEL=ROOT/'tmp/blue-plate-normal-g1/mature-detector/y5fu_320x_sim.onnx'
COST=ROOT/'tmp/blue-plate-normal-g1/mature-detector/model-costs.json'


def align(n):return (n+15)//16*16


def main():
    cv2.setNumThreads(1)
    sources=[MODEL,COST,ROOT/'tmp/blue-plate-review/mature-research/hyperlpr/Prj-Python/hyperlpr3/inference/multitask_detect.py']
    hashes={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sources}
    original=json.loads(COST.read_text())['detector320']
    rows=original['layers'];byname={r['name']:r for r in rows}
    net=cv2.dnn.readNetFromONNX(str(MODEL));net.enableFusion(False)
    net.setInput(np.zeros((1,3,320,320),np.float32));prediction=net.forward()
    assert prediction.shape==(1,6300,15) and np.isfinite(prediction).all()
    dot=net.dump();(OUT/'detector320.dot').write_text(dot)
    net.dumpToPbtxt(str(OUT/'detector320.pbtxt'))
    ids,inputs,outputs=net.getLayersShapes((1,3,320,320))
    for lid,inp,out in zip(ids,inputs,outputs):
        layer=net.getLayer(int(lid));r=byname[layer.name]
        assert r['outputs']==[a.tolist() for a in out]
        assert r['inputs']==[a.tolist() for a in inp]
    edges=re.findall(r'"([^"\n]+)" -> "([^"\n]+)"',dot)
    parents=defaultdict(list);children=defaultdict(list)
    for src,dst in edges:
        assert src in byname and dst in byname,(src,dst)
        parents[dst].append(src);children[src].append(dst)
    assert set(a for e in edges for a in e)==set(byname)
    index={r['name']:i for i,r in enumerate(rows)}
    assert all(index[a]<index[b] for a,b in edges)
    # Materialize every node, including transforms; no unproved alias/fusion savings.
    def width(r):
        suffix=re.search(r'_(\d+)$',r['name'])
        return 4 if r['type']=='Const' or r['name']=='output' or (suffix and int(suffix[1])>=501 and r['type']!='Convolution') else 1
    sizes={r['name']:align(math.prod(r['outputs'][0])*width(r)) for r in rows}
    arena=8*1024*1024;free=[(0,arena)];live={};lifetimes=[];peak=high=0;peak_names=[]
    remaining=Counter(src for src,dst in edges)
    for i,r in enumerate(rows):
        name=r['name'];size=sizes[name]
        for parent in parents[name]:assert parent in live,(name,parent)
        place=next((j for j,(base,length) in enumerate(free) if length>=size),None)
        assert place is not None,'8MiB arena exhausted'
        base,length=free.pop(place)
        if length>size:free.append((base+size,length-size));free.sort()
        for other,(addr,count) in live.items():assert base+size<=addr or addr+count<=base,(name,other)
        live[name]=(base,size);high=max(high,base+size)
        total=sum(n for _,n in live.values())
        if total>peak:peak=total;peak_names=list(live)
        last=max([index[c] for c in children[name]] or [len(rows)])
        lifetimes.append(dict(name=name,type=r['type'],element_bytes=width(r),base=base,size=size,
                              producer=i,last_consumer=last,parents=parents[name]))
        for parent in parents[name]:
            remaining[parent]-=1
            if remaining[parent]==0:free.append(live.pop(parent))
        free.sort();merged=[]
        for start,length in free:
            if merged and merged[-1][0]+merged[-1][1]==start:merged[-1]=(merged[-1][0],merged[-1][1]+length)
            else:merged.append((start,length))
        free=merged
    assert list(live)==['output']
    conv=[];node_traffic=[];metadata=weight_reads=conv_reads=conv_cycles=0
    for r in rows:
        name=r['name'];op=r['type'];count=math.prod(r['outputs'][0]);reads=0
        if op=='Convolution':
            co,ci,kh,kw=r['blobs'][0];cin=r['inputs'][0][1];group=cin//ci
            assert cin%ci==0 and co%group==0
            k=ci*kh*kw;positions=math.prod(r['outputs'][0][2:]);groups=group*math.ceil((co//group)/8)
            cycles=positions*groups*k
            packed=groups*k*8
            # Cache one output-channel group at a time, all K, across 16 positions.
            load=math.ceil(positions/16)*groups*align(k*8)
            assert k<=2048 and k*8<=16384
            assert min(16,positions)*co<=4096
            conv.append(dict(name=name,groups=group,K=k,output_channels=co,positions=positions,
                macs=r['macs'],broadcast_cycles=cycles,weight_tile_bytes=k*8,
                padded_weights=packed,weight_reads=load,
                whole_row_bytes=r['outputs'][0][3]*co))
            conv_reads+=cycles;conv_cycles+=cycles;weight_reads+=load;metadata+=align(co*9)
            reads=cycles
        elif op in ('','Const'):
            continue
        elif op=='Pooling':reads=count*4
        elif op in ('Concat','Reshape','Permute','Slice','Resize','Sigmoid','Identity'):reads=count
        elif op=='NaryEltwise':reads=count*len(r['inputs'])
        else:raise ValueError(op)
        # One 16B beat per scalar read/output is a pessimistic traffic ceiling,
        # assuming no retries, not a bound on arbitration delay.
        output_bytes=count*width(r)
        node_traffic.append(dict(name=name,logical_scalar_reads=reads,output_elements=count,
            no_cache_read_bytes=16*reads,contiguous_write_bytes=align(output_bytes),
            one_beat_per_output_scalar_bytes=16*count))
    assert sum(r['macs'] for r in conv)==183417600
    ordinary=[r for r in rows if r['type'] not in ('','Const')]
    # Read each graph edge once, respecting width assumptions, plus materialized output.
    ideal=sum(sum(sizes[p] for p in parents[r['name']])+sizes[r['name']] for r in ordinary)
    weights=sum(math.prod(r['blobs'][0]) for r in rows if r['type']=='Convolution')
    metadata_once=sum(align(r['blobs'][0][0]*9) for r in rows if r['type']=='Convolution')
    contiguous=sum(r['contiguous_write_bytes'] for r in node_traffic)
    read_ceiling=sum(r['no_cache_read_bytes'] for r in node_traffic)
    write_ceiling=sum(r['one_beat_per_output_scalar_bytes'] for r in node_traffic)
    constants=sum(sizes[r['name']] for r in rows if r['type']=='Const')
    descriptors=256*len(rows)
    packed_storage=sum(r['groups']*math.ceil((r['output_channels']//r['groups'])/8)*align(r['K']*8) for r in conv)
    count=6300;pairs=count*(count-1)//2
    nms=dict(candidates=count,record_bytes=64,records_ddr=count*64,
        sort_pair_bytes=8,sort_buffers_ddr=2*count*8,suppressed_bitmap_bytes=(count+7)//8,
        all_survive_pairs=pairs,merge_sort_passes=math.ceil(math.log2(count)),
        merge_sort_traffic=2*count*8*math.ceil(math.log2(count)),
        pairwise_16byte_bbox_plus_16byte_index_traffic=32*pairs,
        selected_record_traffic=count*64,
        note='Full unbounded-candidate source semantics; no hidden top-K or two-ROI cap. IoU arithmetic and quantization not implemented.')
    det_reserved=align(high)+align(nms['records_ddr'])+align(nms['sort_buffers_ddr'])
    raw_copy=1280*720*3
    all_reserved=det_reserved+packed_storage+metadata_once+constants+descriptors+raw_copy+16384
    assert all_reserved<=arena
    phases={
        'preprocess':{'io':list(range(20,27)),'tags':[27],'two_RGB_rows':list(range(32,40)),
                      'control':[50]},
        'detect':{'weights':list(range(16)),'parameters':list(range(16,20)),
                  'io':list(range(20,27)),'tags':[27],'tables':[47,48],'descriptor':[50]},
        'postprocess':{'io':list(range(20,27)),'tags':[27],'suppression_bitmap':[28],'control':[50]},
        'rectify_resize':{'io':list(range(20,27)),'resize':[49],'control':[50]},
        'recognize':{'weights':list(range(16)),'parameters':list(range(16,20)),
                     'io':list(range(20,27)),'tags':[27],'height':list(range(32,37)),
                     'logits':list(range(37,47)),'tables':[47,48],'descriptor':[50]},
        'ctc':{'logits':list(range(37,47)),'tables':[47,48],'control':[50]}}
    for phase,owners in phases.items():
        slots=[b for group in owners.values() for b in group]
        assert len(set(slots))==len(slots) and all(0<=b<51 for b in slots),phase
    assert 2*1280*3<=8*512*2
    result=dict(source_sha256=hashes,opencv_version=cv2.__version__,synthetic_output=list(prediction.shape),
        layer_count=len(rows),layer_types=original['layer_types'],graph_edges=len(edges),
        width_assumption='INT8 materialized core; INT32 constants and post-head decode. Not a quantized model export.',
        arena=dict(bytes=arena,live_peak_bytes=peak,first_fit_high_water_bytes=high,peak_nodes=peak_names,
                   detector_and_postprocess_reserved_bytes=det_reserved,
                   all_with_constants_descriptors_weights_rawcopy_bytes=all_reserved,
                   raw_copy_bytes=raw_copy,descriptor_bytes=descriptors,
                   note='Relative private DDR offsets, not assigned physical addresses; no in-place reuse or graph fusion'),
        lifetimes=lifetimes,convolutions=conv,phase_bank_ownership=phases,
        compute=dict(macs=sum(r['macs'] for r in conv),broadcast8_cycles=conv_cycles,
                     broadcast8_ms_100MHz=conv_cycles/100000,
                     depthwise_convs=sum(r['groups']>1 for r in conv),
                     max_row_bytes=max(r['whole_row_bytes'] for r in conv),
                     max_any_core_row_bytes=max(r['outputs'][0][1]*r['outputs'][0][3] for r in rows if len(r['outputs'][0])==4),
                     max_K=max(r['K'] for r in conv),max_weight_tile_bytes=max(r['weight_tile_bytes'] for r in conv)),
        traffic=dict(weights_int8=weights,metadata_int32_bias_multiplier_int8_shift=metadata_once,
                     constants_materialization_read_and_write=2*constants,descriptor_reads=descriptors,
                     padded_weight_storage=packed_storage,
                     ideal_one_read_per_edge_plus_output=ideal+weights+metadata_once+2*constants+descriptors,
                     tile16_weight_read_bytes=weight_reads,tile_metadata_bytes=metadata,
                     scalar_read_16byte_beat_ceiling=read_ceiling,
                     contiguous_output_bytes=contiguous,
                     schedule_with_read_misses_and_contiguous_writes=read_ceiling+contiguous+weight_reads+metadata+2*constants+descriptors,
                     all_scalar_beats_ceiling=read_ceiling+write_ceiling+weight_reads+metadata+2*constants+descriptors,
                     note='No retries; per-scalar read ceiling includes padding taps conservatively. No finite wall-time bound without DDR service guarantee.'),
        nms=nms,source_unchanged=all(hashlib.sha256((ROOT/p).read_bytes()).hexdigest()==h for p,h in hashes.items()))
    assert result['source_unchanged']
    for directory in (OUT,DOC):
        (directory/'detector-sharing.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf8')
    print(json.dumps({k:v for k,v in result.items() if k not in ('lifetimes','convolutions','source_sha256')},indent=2))


if __name__=='__main__':main()
