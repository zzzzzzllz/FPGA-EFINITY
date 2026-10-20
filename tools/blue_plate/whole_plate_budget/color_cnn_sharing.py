"""Actual color ONNX shape/cost/ownership audit; no image evaluation or RTL."""
from pathlib import Path
from collections import defaultdict
import hashlib,json,math,re,sys
import cv2
import numpy as np

ROOT=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(ROOT/'tools/blue_plate'))
from compare_hyperlpr import model_cost
OUT=ROOT/'tmp/blue-plate-whole-plate-budget'
DOC=ROOT/'docs/validation/blue-plate/whole-plate-budget'
MODEL=ROOT/'tmp/blue-plate-normal-g1/mature-detector/litemodel_cls_96x_r1.onnx'


def align(n):return (n+15)//16*16


def main():
    cv2.setNumThreads(1)
    sources=[MODEL,ROOT/'tools/blue_plate/hyperlpr_reference.py',
        ROOT/'tmp/blue-plate-review/mature-research/hyperlpr/Prj-Python/hyperlpr3/inference/classification.py',
        DOC/'full-lprnet-sharing.json',ROOT/'tools/blue_plate/compare_hyperlpr.py',
        ROOT/'tmp/blue-plate-normal-g1/mature-detector/model-costs.json']
    hashes={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in sources}
    original_cost_keys=list(json.loads(sources[-1].read_text()))
    assert hashes[str(MODEL)]=='fe123688d3bf08b9ef029fcd57f3ac4644ac2e5ef8b9e7a676aacd5fad152142'
    net=cv2.dnn.readNetFromONNX(str(MODEL));net.enableFusion(False)
    net.setInput(np.zeros((1,3,96,96),np.float32));y=net.forward()
    assert y.shape==(1,3) and np.isfinite(y).all()
    costs=model_cost(net,(1,3,96,96));rows=costs['layers'];dot=net.dump()
    (OUT/'color-model.dot').write_text(dot);net.dumpToPbtxt(str(OUT/'color-model.pbtxt'))
    for folder in (OUT,DOC):(folder/'color-model-cost.json').write_text(json.dumps(costs,indent=2)+'\n')
    labels={m[1]:m[2] for m in re.finditer(r'^\s*"([^"]+)" \[label="([^\n]+)" fillcolor',dot,re.M)}
    edges=re.findall(r'"([^"\n]+)" -> "([^"\n]+)"',dot)
    parents=defaultdict(list);children=defaultdict(list)
    for a,b in edges:parents[b].append(a);children[a].append(b)
    index={r['name']:i for i,r in enumerate(rows)}
    assert all(index[a]<index[b] for a,b in edges)
    def width(r):
        if r['name'] in ('onnx_node!AveragePool_99','onnx_node!Reshape_100'):return 2
        return 4 if r['name'] in ('onnx_node!Gemm_103','onnx_node!Softmax_104','output') else 1
    # A fixed per-node region is simpler than online allocation and fits the
    # detector's already reserved temporary arena. Last-use times are still checked.
    allocations={};offset=0;peak=0;life=[]
    for i,r in enumerate(rows):
        size=align(math.prod(r['outputs'][0])*width(r));name=r['name']
        for p in parents[name]:assert p in allocations
        last=max([index[c] for c in children[name]] or [len(rows)])
        allocations[name]=(offset,size,last);offset+=size
        assert offset<=1536000
        active=[(a,n) for a,n,end in allocations.values() if end>=i]
        peak=max(peak,sum(n for a,n in active))
        assert all(a+n<=b for (a,n),(b,m) in zip(active,active[1:]))
        life.append(dict(name=name,base=offset-size,bytes=size,element_bytes=width(r),last_consumer=last))
    schedule=[];raw_weights=raw_bias=steps=macs=packed_storage=weight_reads=meta_storage=meta_reads=0
    dw_checks=[]
    for r in rows:
        if r['type'] not in ('Convolution','Gemm'):continue
        name=r['name'];co=r['blobs'][0][0];k=math.prod(r['blobs'][0][1:])
        positions=math.prod(r['outputs'][0][2:]) if r['type']=='Convolution' else r['outputs'][0][0]
        group=r['inputs'][0][1]//r['blobs'][0][1] if r['type']=='Convolution' else 1
        dw=group>1
        if dw:assert group==co and r['blobs'][0][1]==1
        groups=math.ceil(co/8)
        layer_steps=positions*groups*k
        spatial_tile=min(16,4096//(co*width(r)),positions)
        assert spatial_tile>=1 and spatial_tile*co*width(r)<=4096
        assert k*8<=16384
        meta=align(co*9)
        metadata_chunks=[min(512,co-b) for b in range(0,co,512)]
        assert max(metadata_chunks)<=512
        if dw:
            packed=align(groups*k*8);reads=packed
        else:
            packed=groups*align(k*8);reads=math.ceil(positions/spatial_tile)*packed
        meta_loads=math.ceil(positions/spatial_tile) if co>512 else 1
        record=dict(name=name,type=r['type'],depthwise=dw,K=k,channels=co,positions=positions,
            spatial_tile=spatial_tile,tail_lanes=(8-co%8)%8,metadata_chunks=metadata_chunks,
            weight_group_bytes=k*8,macs=math.prod(r['blobs'][0])*positions,mac_steps=layer_steps,
            packed_weight_bytes=packed,weight_read_bytes=reads,metadata_read_bytes=meta*meta_loads)
        schedule.append(record)
        raw_weights+=math.prod(r['blobs'][0]);raw_bias+=math.prod(r['blobs'][1])
        macs+=record['macs'];steps+=layer_steps;packed_storage+=packed;weight_reads+=reads
        meta_storage+=meta;meta_reads+=meta*meta_loads
        if dw:
            _,cin,ih,iw=r['inputs'][0];_,_,oh,ow=r['outputs'][0]
            sy,sx=map(int,re.search(r'stride \(HxW\): (\d+) x (\d+)',labels[name]).groups())
            py,py1,px,px1=map(int,re.search(r'pad \(HxW\): \((\d+), (\d+)\) x \((\d+), (\d+)\)',labels[name]).groups())
            kh,kw=r['blobs'][0][2:];base,size,_=allocations[parents[name][0]]
            requests=cross=beats=padding=0
            for oy in range(oh):
                for ox in range(ow):
                    for ch in range(0,cin,8):
                        count=min(8,cin-ch)
                        for ky in range(kh):
                            for kx in range(kw):
                                iy,ix=oy*sy+ky-py,ox*sx+kx-px
                                if not (0<=iy<ih and 0<=ix<iw):padding+=1;continue
                                start=base+(iy*iw+ix)*cin+ch;end=start+count
                                assert base<=start<end<=base+size
                                touched=(end-1)//16-start//16+1
                                assert touched<=2
                                requests+=1;beats+=touched;cross+=touched-1
            dw_checks.append(dict(name=name,channels=cin,tail_valid_channels=cin%8,
                vector_requests=requests,cross_word_vectors=cross,cache_word_reads=beats,padding_vectors=padding))
    assert costs['convolution_macs']==5215968 and macs==5380192
    nonmac_reads=0;output_writes=0
    for r in rows:
        name=r['name'];count=math.prod(r['outputs'][0]);op=r['type']
        if not op:continue
        output_writes+=align(count*width(r))
        if op in ('Convolution','Gemm'):continue
        if op=='Pooling':nonmac_reads+=count*9
        elif op=='NaryEltwise':nonmac_reads+=count*len(r['inputs'])
        else:nonmac_reads+=count
    # All ordinary MAC inputs miss; depthwise coalescing explicitly includes
    # two-word gathers. This is not a measured cache miss trace.
    conv_read_steps=sum(r['mac_steps'] for r in schedule if not r['depthwise'])
    conv_read_steps+=sum(r['cache_word_reads'] for r in dw_checks)
    descriptors=len(rows)*256
    read_upper=16*(conv_read_steps+nonmac_reads)+weight_reads+meta_reads+descriptors+16
    lower=sum(sum(allocations[p][1] for p in parents[r['name']])+allocations[r['name']][1] for r in rows if r['type'])+packed_storage+meta_storage+16+descriptors
    lpr=json.loads((DOC/'full-lprnet-sharing.json').read_text())
    added=packed_storage+meta_storage+16+descriptors+43008+6912
    total=lpr['memory']['full_shared_ddr_reservation']+added
    assert total<8*1024*1024
    result=dict(source_sha256=hashes,source_unchanged=all(hashlib.sha256(p.read_bytes()).hexdigest()==hashes[str(p)] for p in sources),
        original_model_cost_keys=original_cost_keys,
        classifier_in_original_model_cost_file='classifier' in original_cost_keys,shape=[1,3,96,96],output=[1,3],layer_types=costs['layer_types'],
        schedule=schedule,depthwise_address_checks=dw_checks,lifetimes=life,
        macs=dict(convolution=costs['convolution_macs'],Gemm=macs-costs['convolution_macs'],total=macs,
            shared8_mac_steps=steps,shared8_mac_ms_100MHz=steps/100000,
            detector_lpr_color_one_roi_mac_ms=229.776+lpr['timing']['mac_ms_100MHz']+steps/100000,
            detector_lpr_color_two_roi_mac_ms=229.776+2*(lpr['timing']['mac_ms_100MHz']+steps/100000)),
        memory=dict(raw_W8=raw_weights,raw_bias32=raw_bias*4,packed_weights=packed_storage,metadata=meta_storage,
            PReLU_parameter_reserve=16,descriptors=descriptors,all_features_reserved_bytes=offset,live_peak_bytes=peak,
            max_single_feature_bytes=max(r['bytes'] for r in life),extra_ROI_and_pending_LPR_bytes=49920,
            full_three_model_ddr_reservation=total,shared_RAM_target=51,
            width_scope='Capacity assumption: W8/A8, uint16 pool sums, requantized signed A8 FC1/PReLU, int32 final scores; no quantization implemented'),
        traffic=dict(weight_reads=weight_reads,metadata_reads=meta_reads,ideal_materialized_edge_reference=lower,
            cache_miss_read_ceiling=read_upper,contiguous_feature_writes=output_writes,
            read_ceiling_plus_contiguous_writes=read_upper+output_writes,
            scope='No retries; includes descriptors and scalar PReLU reserve; excludes resize, ROI copy, nonlinear LUT traffic and external bus overhead'),
        scope='Actual frozen ONNX, zero synthetic forward, shape and range/packing audit only; no dataset evaluation, quantization, RTL or synthesis')
    assert result['source_unchanged']
    for folder in (DOC,OUT):(folder/'color-cnn-sharing.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf8')
    print(json.dumps({k:v for k,v in result.items() if k not in ('source_sha256','schedule','depthwise_address_checks','lifetimes')},indent=2))


if __name__=='__main__':main()
